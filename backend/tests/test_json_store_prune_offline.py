# -*- coding: utf-8 -*-
"""P32：备份轮转必须移出写入热路径（P28 修复引入的副作用）。

## 事故取证（2026-10-17 11:00 真实批次）

P28 为「备份无界增长」引入的轮转，实测把后端**整体卡死**：

```
[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
  {"count":50,"threshold":50,"scope":"turn","targets":[...],"targetCount":1}
[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
  {"count":64,"threshold":50,"scope":"turn","targets":[...],"targetCount":1}
2026-10-17 10:48:58 - 进化队列已由管理员停止
```

之后 `/docs` 连续 15 秒无响应（HTTP=000），状态接口超时，
后端进程活着但事件循环被完全阻塞。

## 两个叠加的根因

回源码核实（`ai_trace_storage.py:142-155`）：

1. **每次写入都删文件** —— `_prune_backups()` 挂在写路径上，
   于是「每次只删 1 个」也会累积到 50 次触发环境的批量删除保护。
   ⚠️ 关键取证：`targetCount:1` 说明单次删的**文件数**是 1，
   但 `count:50` 是**本轮累计删除次数** ⇒ 保护机制数的是累计次数，
   「小批量高频」照样撞线。

2. **每次写入都新建备份文件** —— 写入前先
   `os.replace(self.backup_path, rotated)` 把旧 `.bak` 改名成
   `.bak.<时间戳>.<pid>`。`evolution_history.json` 在一轮进化里
   要写几十次 ⇒ 几十个轮转文件 ⇒ 几十次删除。
   **这才是撞线的真正源头**，删文件只是它的后果。

## 本守卫锁定什么

- 写路径**不得**调用任何删除/清理逻辑
- 写路径**不得**为每次写入新建备份文件（`.bak` 保持单份）
- 清理只允许在**存储初始化**时做一次，且必须低频 + 有上限
- 清理必须**白名单式**：只删 `自己命名的` `.bak.<数字>.<数字>` 形态文件
- 崩溃恢复能力（单份 `.bak`）不得削弱
"""
from __future__ import annotations

import inspect
import tempfile
from pathlib import Path


def _store_cls():
    from app.services.ai_trace_storage import AtomicJsonStore
    return AtomicJsonStore


def _strip_comments(src: str) -> str:
    """去掉整行注释与行尾注释。

    🔧 必需：我在 P32 的注释里写了「原实现调用了 _prune_backups」这样的历史说明，
    而源码文本断言会把注释里的字样也算命中 —— 第一版守卫因此恒定失败。
    **断言代码行为时必须排除注释**，否则修复说明本身就会被判成违规。
    """
    import re
    out = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # 去掉行尾注释（不处理字符串内的 #，本文件无此场景）
        line = re.sub(r"(?<!['\"])#.*$", "", line)
        out.append(line)
    return "\n".join(out)


class TestWritePathIsDeleteFree:
    """写路径不得触发任何删除 —— 这是本次卡死的直接原因。"""

    def test_write_does_not_call_prune(self):
        from app.services.ai_trace_storage import AtomicJsonStore
        code = _strip_comments(
            inspect.getsource(AtomicJsonStore._write_unlocked)
        )
        assert "_prune_backups" not in code, (
            "写路径仍调用 _prune_backups —— 每次写入都删文件，"
            "会撞环境的批量删除保护（实测 count:50 触发，后端整体卡死）"
        )

    def test_write_does_not_unlink_any_file(self):
        from app.services.ai_trace_storage import AtomicJsonStore
        src = inspect.getsource(AtomicJsonStore._write_unlocked)
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith("#")
        )
        # unlink 只允许出现在 finally 里清理自己的临时文件
        for line in code.splitlines():
            if "unlink" not in line:
                continue
            assert "temp_path" in line, (
                f"写路径出现非临时文件的删除：{line.strip()} —— "
                f"只允许清理自己的 .tmp 临时文件"
            )

    def test_write_does_not_rotate_backup_every_time(self):
        """每次写入新建一个 .bak.<ts>.<pid> 是撞线的真正源头。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        src = inspect.getsource(AtomicJsonStore._write_unlocked)
        assert "rotated" not in src, (
            "写路径仍在为每次写入新建轮转备份文件 —— "
            "一轮进化写几十次就产生几十个备份与几十次删除，"
            "实测撞 count:50 阈值导致后端事件循环卡死"
        )

    def test_single_backup_is_overwritten_in_place(self):
        """`.bak` 保持单份、被就地覆盖 —— 这正是崩溃恢复所需的形态。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        src = inspect.getsource(AtomicJsonStore._write_unlocked)
        assert "shutil.copy2(self.path, self.backup_path)" in src, (
            "就地覆盖单份 .bak 的写法被移除 —— 崩溃恢复依赖它"
        )


class TestCleanupIsInitOnlyAndBounded:
    """清理只允许在初始化时做一次，且必须有上限。"""

    def test_prune_is_not_called_from_write_path(self):
        from app.services.ai_trace_storage import AtomicJsonStore
        write_code = _strip_comments(
            inspect.getsource(AtomicJsonStore._write_unlocked)
        )
        assert "_prune_backups" not in write_code
        # 清理方法体须保留（供 __init__ 调用），只是不得挂在写路径上
        assert "_prune_backups" in inspect.getsource(AtomicJsonStore)
        assert "_prune_backups" in _strip_comments(
            inspect.getsource(AtomicJsonStore.__init__)
        ), (
            "__init__ 里没有调用 _prune_backups —— "
            "历史遗留备份将永远不被清理"
        )

    def test_prune_has_hard_cap_on_deletions(self):
        """单次清理必须有删除数量上限 —— 避免一次撞穿保护阈值。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        src = inspect.getsource(AtomicJsonStore._prune_backups)
        assert "MAX_DELETE" in src or "max_delete" in src, (
            "清理逻辑须声明单次删除上限（PRUNE_MAX_DELETE），"
            "否则历史遗留几百个备份会被一次性删除，必然撞保护阈值"
        )

    def test_prune_has_time_throttle(self):
        """清理必须按时间节流，跨进程累积也要限速。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        src = inspect.getsource(AtomicJsonStore._prune_backups)
        assert "PRUNE_INTERVAL" in src or "prune_interval" in src, (
            "清理须按时间间隔节流（PRUNE_INTERVAL），"
            "否则多个进程/多次初始化会连续触发删除"
        )


class TestCleanupWhitelistIsStrict:
    """清理必须只删自己命名的文件，绝不碰用户数据。"""

    def test_only_deletes_self_named_rotated_pattern(self):
        from app.services.ai_trace_storage import AtomicJsonStore
        # 形态校验逻辑放在 _is_own_rotated_backup 里（两处一起看）
        src = _strip_comments(inspect.getsource(AtomicJsonStore))
        assert "isdigit" in src, (
            "清理必须严格校验文件名形态（.bak.<数字>.<数字>），"
            "不能靠 glob 命中就删 —— glob 误伤会删掉用户数据"
        )
        # 且 _prune_backups 必须真的调用了这个校验（而不是形同虚设）
        prune_code = _strip_comments(
            inspect.getsource(AtomicJsonStore._prune_backups)
        )
        assert "_is_own_rotated_backup" in prune_code, (
            "_prune_backups 没有调用白名单校验 —— "
            "形态校验写了却不使用，等于没有"
        )

    def test_never_deletes_the_plain_backup(self):
        """.bak 本体是崩溃恢复的唯一依据，任何情况下都不得删除。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        src = _strip_comments(inspect.getsource(AtomicJsonStore._prune_backups))
        assert "backup_path" not in src, (
            "_prune_backups 里出现了 backup_path —— "
            "`.bak` 本体是崩溃恢复的唯一依据，绝不能被清理逻辑碰到"
        )

    def test_prune_never_raises(self):
        """清理失败不得阻断写入 —— 源码必须兜住异常。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        src = inspect.getsource(AtomicJsonStore._prune_backups)
        assert "except" in src, "清理必须兜住异常，不得让写入路径崩"


class TestNoAccumulationRegression:
    """行为实测：连续写入多轮，备份文件数必须受控（不再无界增长）。"""

    def test_repeated_writes_do_not_multiply_backups(self):
        cls = _store_cls()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = cls(root / "probe.json", root_type=dict)
            for i in range(20):
                store.write({"i": i, "payload": "x" * 1000})
            backups = sorted(root.glob("probe.json.bak*"))
            # 稳态：`.bak` 一份 + 至多少量历史备份（受上限约束）
            assert len(backups) <= 3, (
                f"写入 20 次后备份文件有 {len(backups)} 份："
                f"{[b.name for b in backups]} —— "
                f"应稳定在 .bak 一份（+至多上限内的历史备份）"
            )

    def test_crash_recovery_still_works(self):
        """清理逻辑不得破坏「主文件损坏→回退读 .bak」。

        ⚠️ 必须写**两次**：第一次写入时主文件尚不存在，
        按设计没有「上一版」可备份，`.bak` 不会产生 ——
        这是正确行为（备份的是上一版，而非当前内容）。
        第一版守卫只写一次就断言 `.bak`，恒定失败。
        """
        cls = _store_cls()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "probe.json"
            store = cls(target, root_type=dict)
            store.write({"v": 1})
            store.write({"v": 2})          # 第二次才有上一版可备份
            assert (root / "probe.json.bak").exists(), (
                "写入两次后仍无 .bak —— 崩溃恢复能力被破坏"
            )
            # 触发一次清理（若实现保留手动入口），确认它不碰 .bak
            prune = getattr(store, "_prune_backups", None)
            if callable(prune):
                prune()
            assert (root / "probe.json.bak").exists(), (
                "清理后 .bak 消失 —— 崩溃恢复的唯一依据被误删"
            )
            # 破坏主文件后应回退读到上一版（v=1）
            target.write_text("{坏掉的 json", encoding="utf-8")
            fallback = cls(target, root_type=dict).read()
            assert fallback.get("v") == 1, (
                f"崩溃恢复失效：主文件损坏后回退读到 {fallback!r}（应为 v=1）"
            )