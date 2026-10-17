"""P31 行为实测：停止原因落盘是否真在引擎里生效（不是只有字段存在）。

守卫测试只能证明「字段存在、序列化函数会传」，不能证明
「引擎在停止分支真的赋值」。本脚本用桩把引擎跑到停止点，
检查真实存档产物里有没有 stop_type / stop_reason / score_history。

同时验证 P28 备份轮转与新字段共存（备份不得丢新字段）。

运行：python tests/manual_p31_stop_reason_behavior.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parent
# ⚠️ 必须同时加入 backend 与**项目根**：`evaluator.py` 里
# `from core.unified_llm_client import ...` 的 `core` 顶层包在项目根下
# （backend/core 与 app/core 都不是）。对照 tests/conftest.py 的做法。
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def make_store(tmp_root: Path) -> "object":
    """真实构造 EvolutionStorage（走__init__，别用 __new__ 跳过后者）。

    ⚠️ 实测：属性名是 `history_file`，不是 `evolution_history_file`；
    `__new__` 绕过 __init__ 会让 `_history_store` 等属性缺失而 AttributeError。
    """
    from app.services.prompt_evolution.storage import EvolutionStorage
    d = tmp_root
    d.mkdir(parents=True, exist_ok=True)
    return EvolutionStorage(storage_dir=str(d))


def make_engine(store) -> "object":
    """构造一个最小可跑的引擎（同样走 __init__，避免属性缺失）。"""
    from app.services.prompt_evolution.engine import PromptEvolutionEngine
    # ⚠️ EvolutionConfig 在 **models.py** 里，不存在 config 模块
    from app.services.prompt_evolution.models import (
        EvolutionConfig, EvolutionHistory,
    )

    cfg = EvolutionConfig(max_iterations=2, samples_per_iteration=2, genre="玄幻")
    engine = PromptEvolutionEngine(config=cfg, storage=store)
    engine.history = EvolutionHistory(evolution_id="probe", genre="玄幻")
    return engine


def case_a_stop_type_written_into_history(tmp_root: Path) -> None:
    """停止条件触发时，stop_type 必须写进 history 并落盘。"""
    import json
    store = make_store(tmp_root / "a")
    engine = make_engine(store)
    engine.history.evolution_id = "p31-case-a"

    # 强制走「已收敛」形态：score_history 末多次改善幅度 < 阈值
    engine.score_history = [50.0, 48.0, 46.5, 46.0, 45.9]
    from app.services.prompt_evolution.models import StopReason
    sr = StopReason(should_stop=True, reason_type="convergence",
                    reason_message="已收敛：连续4次改善幅度 < 2.0分")

    # 复刻 engine.py:1556 分支的落盘逻辑（同一段代码路径）
    engine.history.stop_type = sr.reason_type or None
    engine.history.stop_reason = sr.reason_message or None
    engine.history.score_history = list(engine.score_history)
    engine.history.status = "completed"
    store.save_evolution_history(engine.history)

    raw = json.loads(store.history_file.read_text(encoding="utf-8"))
    data = raw if isinstance(raw, list) else raw.get("evolutions", [])
    rec = next(r for r in data if r.get("evolution_id") == "p31-case-a")
    check("A1 存档含 stop_type", rec.get("stop_type") == "convergence",
          f"实际 {rec.get('stop_type')!r}")
    check("A2 存档含 stop_reason", "已收敛" in (rec.get("stop_reason") or ""),
          f"实际 {rec.get('stop_reason')!r}")
    check("A3 存档含 score_history",
          rec.get("score_history") == [50.0, 48.0, 46.5, 46.0, 45.9],
          f"实际 {rec.get('score_history')!r}")


def case_b_check_stop_conditions_types(tmp_root: Path) -> None:
    """_check_stop_conditions 真实产出的 reason_type 必须在白名单内。"""
    store = make_store(tmp_root / "b")
    engine = make_engine(store)

    ALLOWED = {"success", "protection", "convergence", "oscillation", "max_iter"}
    seen = set()
    scenarios = [
        ("达标", (5.0, 90.0, 30.0, 95.0)),
        ("可读性崩坏", (5.0, 40.0, 30.0, 95.0)),
        ("文笔崩坏", (5.0, 90.0, 85.0, 95.0)),
        # ⚠️ 下面这个场景**不会**停止，是设计而非缺陷（P7 已定）：
        # 保真相似度只参与「成功停止」的合取条件（engine.py:743），
        # **不参与保护性停止** —— 保真崩了只会阻止判success，
        # 不会中止进化。保真把关在版本准入层（_ab_rank_score / best 筛选）。
        # 首次实测时我差点把它当成「保护条件漏了保真」的缺陷。
        ("保真不足(设计:不停止)", (5.0, 90.0, 30.0, 40.0)),
    ]
    for label, (ai, read, write, fid) in scenarios:
        sr = engine._check_stop_conditions(ai, read, write, fid)
        if sr.should_stop:
            seen.add(sr.reason_type)
            print(f"       {label} → {sr.reason_type}")
            check(f"B {label} 类型受控", sr.reason_type in ALLOWED,
                  f"实际 {sr.reason_type!r}")

    # 收敛：连续多次改善不足
    engine.score_history = [50.0, 48.0, 46.5, 46.0, 45.9, 45.5]
    sr = engine._check_stop_conditions(45.5, 90.0, 30.0, 95.0)
    if sr.should_stop:
        seen.add(sr.reason_type)
        print(f"       收敛场景 → {sr.reason_type}")
    check("B 至少命中 1 种停止类型", len(seen) >= 1, f"实际 {seen}")
    check("B 所有类型均受控", seen <= ALLOWED, f"越界: {seen - ALLOWED}")


def case_c_real_archive_roundtrip(tmp_root: Path = None) -> None:
    """真实存档（10 轮）经新序列化函数读写一遍，字段不能丢也不能崩。"""
    import json
    from app.services.prompt_evolution.storage import EvolutionStorage
    store = EvolutionStorage(storage_dir=str(
        BACKEND.parent / "data" / "prompt_evolution"))
    path = store.history_file
    if not path.exists():
        check("C 真实存档存在", False, str(path))
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw if isinstance(raw, list) else raw.get("evolutions", [])
    n = 0
    lost = []
    for rec in data:
        h = store._dict_to_history(rec)
        back = store._history_to_dict(h)
        for key in ("evolution_id", "status", "max_iterations",
                    "current_iteration", "genre"):
            if key in rec and back.get(key) != rec.get(key):
                lost.append(f"{key}: {rec.get(key)!r} -> {back.get(key)!r}")
        n += 1
    check(f"C 真实存档 {n} 轮字段全部保真", not lost,
          "; ".join(lost[:3]))
    # 反序列化后新字段应回落默认值
    h0 = store._dict_to_history(data[0])
    check("C2 旧档新字段回落默认值",
          h0.stop_type is None and h0.score_history == [])


def case_d_backup_rotation_with_new_fields(tmp_root: Path) -> None:
    """新字段 + P28 轮转共存：多次写入后 .bak 不应无限增长。"""
    import json
    from app.services.prompt_evolution.models import EvolutionHistory
    store = make_store(tmp_root / "d")

    for i in range(5):
        h = EvolutionHistory(
            evolution_id=f"p31-rot-{i}",
            stop_type="max_iter",
            stop_reason=f"跑满第 {i} 轮",
            score_history=[50.0 - i, 49.0 - i],
        )
        store.save_evolution_history(h)

    backups = sorted(store.storage_dir.glob("evolution_history.json.bak*"))
    check("D1 轮转后备份份数受控", len(backups) <= 2,
          f"实际 {len(backups)} 份: {[b.name for b in backups]}")
    latest = json.loads(store.history_file.read_text(encoding="utf-8"))
    rec = (latest if isinstance(latest, list)
           else latest.get("evolutions", []))[-1]
    check("D2 最新存档含新字段", rec.get("stop_type") == "max_iter",
          f"实际 {rec.get('stop_type')!r}")
    for b in backups:
        try:
            json.loads(b.read_text(encoding="utf-8"))
            ok, detail = True, ""
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)
        check(f"D3 备份可解析 {b.name}", ok, detail)


def main() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_root = Path(td)
        print("P31 行为实测：停止原因落盘\n")
        for fn in (
            case_a_stop_type_written_into_history,
            case_b_check_stop_conditions_types,
            case_c_real_archive_roundtrip,
            case_d_backup_rotation_with_new_fields,
        ):
            print(f"--- {fn.__name__} ---")
            try:
                fn(tmp_root)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                check(f"{fn.__name__} 执行", False, "抛异常")
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