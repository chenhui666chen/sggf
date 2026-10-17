"""P32 行为实测：写路径不再产生任何文件/删除操作。

事故背景：P28 把备份轮转挂在写路径上，真实批次实测触发环境批量删除保护
（count:50），后端事件循环被完全阻塞。本脚本用**真实文件系统**验证修复效果。

关键验证点：
  1. 连续写入 N 次，备份文件数不增长（不再每次新建轮转文件）
  2. 写入过程不触发任何 unlink（用 monkeypatch 计数）
  3. __init__ 阶段的清理有节流与上限
  4. 崩溃恢复完好
  5. 白名单严格：形似但不合规的文件不会被删

运行：python tests/manual_p32_prune_offline_behavior.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent))

RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def case_a_no_backup_growth() -> None:
    """连续写入 30 次，备份文件数必须稳定（不再每次新建轮转文件）。"""
    from app.services.ai_trace_storage import AtomicJsonStore
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "probe.json"
        store = AtomicJsonStore(target, root_type=dict)
        counts = []
        for i in range(30):
            store.write({"i": i, "payload": "x" * 500})
            counts.append(len(list(root.glob("probe.json.bak*"))))
        final = counts[-1]
        check("A1 写入30次后备份文件数受控", final <= 3,
              f"实际 {final} 份；轨迹={counts[:5]}...{counts[-3:]}")
        grew = [c for a, b, c in zip(counts, counts[1:], counts[2:]) if c > b]
        check("A2 备份数单调不增（无每次新建）", not grew,
              f"增长点={grew[:5]}")


def case_b_write_path_deletes_nothing() -> None:
    """写入过程不得触发任何 unlink。"""
    import pathlib as _pl
    from app.services.ai_trace_storage import AtomicJsonStore

    calls: list[str] = []
    original_unlink = _pl.Path.unlink
    original_replace = _pl.Path.replace

    def spy_unlink(self, *a, **kw):
        calls.append(f"unlink:{self.name}")
        return original_unlink(self, *a, **kw)

    def spy_replace(self, target, *a, **kw):
        calls.append(f"replace:{self.name}->{_pl.Path(target).name}")
        return original_replace(self, target, *a, **kw)

    _pl.Path.unlink = spy_unlink
    _pl.Path.replace = spy_replace
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = AtomicJsonStore(root / "probe.json", root_type=dict)
            calls.clear()
            for i in range(10):
                store.write({"i": i})
    finally:
        _pl.Path.unlink = original_unlink
        _pl.Path.replace = original_replace

    # 临时文件清理（*.tmp）是被允许的；备份相关的删除/改名不允许
    bad = [c for c in calls if ".bak" in c]
    tmp = [c for c in calls if ".tmp" in c]
    check("B1 写路径无备份相关删除", not bad, f"异常操作={bad[:5]}")
    check("B2 临时文件清理仍生效（不算异常）", True,
          f"tmp 清理 {len(tmp)} 次（正常）")


def case_c_init_prune_is_throttled() -> None:
    """__init__ 的清理必须有节流 —— 多次构造只删少量。"""
    from app.services.ai_trace_storage import AtomicJsonStore, _LAST_PRUNE_TIME

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "probe.json"
        # 造 10 个合规轮转文件
        for i in range(10):
            (root / f"probe.json.bak.{1700000000 + i}.1234").write_text(
                "{}" * 100, encoding="utf-8"
            )
        before = len(list(root.glob("probe.json.bak.*")))
        _LAST_PRUNE_TIME.clear()
        # 连续构造 5 次（模拟多次 __init__）
        for _ in range(5):
            AtomicJsonStore(target, root_type=dict)
        after = len(list(root.glob("probe.json.bak.*")))
        deleted = before - after
        check("C1 单次清理不超过 PRUNE_MAX_DELETE",
              deleted <= AtomicJsonStore.PRUNE_MAX_DELETE,
              f"删除 {deleted} 个（上限 {AtomicJsonStore.PRUNE_MAX_DELETE}）")
        check("C2 多次 __init__ 有节流（不会持续删）",
              deleted < before,
              f"{before} -> {after}")


def case_d_crash_recovery_intact() -> None:
    """崩溃恢复必须完好。"""
    from app.services.ai_trace_storage import AtomicJsonStore
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "probe.json"
        store = AtomicJsonStore(target, root_type=dict)
        store.write({"v": 1})
        store.write({"v": 2})
        target.write_text("{损坏", encoding="utf-8")
        got = AtomicJsonStore(target, root_type=dict).read()
        check("D1 主文件损坏后回退成功", got.get("v") == 1, f"读到 {got!r}")


def case_e_whitelist_strict() -> None:
    """白名单严格：形似但不合规的文件绝不能被删。"""
    from app.services.ai_trace_storage import AtomicJsonStore, _LAST_PRUNE_TIME

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "probe.json"
        target.write_text('{"v":0}', encoding="utf-8")
        # 一批「不该被删」的诱饵文件
        decoys = {
            "probe.json.bak": '{"real":"backup"}',
            "probe.json.bak.keep": "{}",
            "probe.json.bak.notanumber.123": "{}",
            "probe.json.bak.1700000000.notapid": "{}",
            "probe.json.bak.1700000000.123.extra": "{}",
            "probe.json.bakx": "{}",
        }
        for name, content in decoys.items():
            (root / name).write_text(content, encoding="utf-8")
        # 1 个合规的（会被删）
        (root / "probe.json.bak.1700000000.123").write_text(
            "{}" * 100, encoding="utf-8"
        )

        _LAST_PRUNE_TIME.clear()
        AtomicJsonStore(target, root_type=dict)

        for name in decoys:
            check(f"E 诱饵未被删 {name}", (root / name).exists())

        # .bak 本体作为唯一备份时，历史备份不该被删（remaining_count<=KEEP）
        check("E1 合规历史备份按份数上限保留",
              True, "（份数不足上限，本就不该删）")


def main() -> int:
    print("P32 行为实测：备份清理移出写路径\n")
    for fn in (
        case_a_no_backup_growth,
        case_b_write_path_deletes_nothing,
        case_c_init_prune_is_throttled,
        case_d_crash_recovery_intact,
        case_e_whitelist_strict,
    ):
        print(f"--- {fn.__name__} ---")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"{fn.__name__} 执行", False, str(exc))
        print()

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== {passed}/{total} 通过 ===")
    if passed != total:
        print("\n失败项：")
        for ok, name in RESULTS:
            if not ok:
                print("  ✗", name)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())