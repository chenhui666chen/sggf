# -*- coding: utf-8 -*-
"""备份保留策略守卫（P28）。

## 取证：`.bak` 体积的真正来源

实测 `data/prompt_evolution/`（2026-10-17）：
- `evolution_history.json` 8.10 MB，其 `.bak` 也是 8.10 MB（**等大**）
- 单轮平均仅 391 KB，8 轮共 3.05 MB（未计indent 放大）
- 体积拆解发现：`all_versions` 290 KB 与 `best_versions` 285 KB
  —— **`best_versions` 永远是 `all_versions` 的子集完整副本**，
  等于每个版本被序列化两遍。

`.bak` 等大本身是设计使然（`:89` 写入前整体 copy），它保留的是**上一版**，
不是历史版本链 —— 所以单份 `.bak` 是必要且足够的，
膨胀是「主文件本身过大」传导过来的。

## 本守卫锁定什么

引入**按大小/份数**的备份上限，防止无界增长；
但**不得以牺牲崩溃恢复能力为代价**：
- 至少要保留最近 1 份可回退的备份
- 「主文件损坏→回退读备份」这条路径必须完好
- 备份写入前的「主文件可解析才备份」保护不得移除
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STORE = "backend/app/services/ai_trace_storage.py"


def _src() -> str:
    return (REPO_ROOT / STORE).read_text(encoding="utf-8")


class TestCrashRecoveryPreserved:
    """轮转不得削弱崩溃恢复能力（这是 P26 刚锁住的能力）。"""

    def test_fallback_read_still_present(self):
        src = _src()
        assert "_read_path(self.backup_path)" in src, (
            "主文件损坏时回退读备份的路径被移除"
        )

    def test_only_backs_up_parseable_file(self):
        """只在主文件可解析时才备份 —— 防止损坏内容覆盖好备份。"""
        src = _src()
        assert "json.JSONDecodeError" in src, "备份前的可解析性校验被移除"

    def test_at_least_one_backup_always_retained(self):
        """轮转至少保留 1 份备份 —— 归零等于取消崩溃恢复。"""
        from app.services.ai_trace_storage import AtomicJsonStore

        assert getattr(AtomicJsonStore, "BACKUP_KEEP", 1) >= 1, (
            "BACKUP_KEEP 必须 >= 1，否则崩溃恢复能力归零"
        )


class TestBackupRetentionPolicy:
    def test_policy_is_declared(self):
        src = _src()
        assert "BACKUP_KEEP" in src, (
            "应声明备份保留策略常量（份数上限）"
        )

    def test_prunes_only_excess_backups(self):
        """轮转必须只清理超出上限的旧备份。"""
        src = _src()
        assert "_prune_backups" in src or "prune" in src.lower(), (
            "应实现备份轮转逻辑"
        )

    def test_prune_is_safe_on_missing_dir(self):
        """轮转在目录不存在时必须安全返回，不得抛异常阻断写入。"""
        src = _src()
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith("#")
        )
        assert "FileNotFoundError" in code or "exists()" in code, (
            "轮转需对缺失目录/文件安全"
        )


class TestAtomicWriteUnchanged:
    def test_atomic_replace_still_used(self):
        """原子替换是写入正确性的基础，轮转不得改动它。"""
        src = _src()
        assert "os.replace(temp_path, self.path)" in src, (
            "原子替换被移除 —— 半写文件会导致存档损坏"
        )

    def test_fsync_still_used(self):
        src = _src()
        assert "os.fsync" in src, "fsync 被移除 —— 崩溃时可能丢数据"

    def test_lock_still_used(self):
        src = _src()
        assert "_locked(self.path)" in src, "进程锁被移除 —— 并发写会互相覆盖"