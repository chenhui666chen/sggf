# -*- coding: utf-8 -*-
"""JSON 存储备份的崩溃恢复能力守卫（P26）。

## 取证修正：`.bak` 不是垃圾，删除是错的

盘点时我把 `data/prompt_evolution/` 下7 个 `.bak` 记为「只增不减的垃圾」。
深挖 `ai_trace_storage.py` 后**证伪**了这个判断：

    class AtomicJsonStore:
        \"\"\"带进程锁、原子替换和上一版本备份的 JSON 存储。\"\"\"

- `:74-75` 读取时若主文件 JSON 损坏 → **回退读 `.bak`**
- `:89` 写入时先把当前主文件 copy 成 `.bak`

也就是说 `.bak` 是**崩溃恢复机制的一部分**。删掉它等于放弃
「存档写坏了一半还能读回上一版」的能力 —— 而这个存档正是 P17~P20
反复取证依赖的进化历史。**删除是错的。**

实现本身还很讲究：`:88-92` 只在主文件**能成功解析**时才 copy，
不会用损坏内容覆盖掉好的备份。

## 但确实有个真问题

备份**永不轮转、也无大小上限**：
`evolution_history.json.bak` 已达 8.5MB，与主文件几乎等大。
随进化轮次累积，这些文件会无界增长。

本守卫锁定「崩溃恢复能力不得被破坏」，避免后人顺手把它们当垃圾清理。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STORE = "backend/app/services/ai_trace_storage.py"


def _src() -> str:
    return (REPO_ROOT / STORE).read_text(encoding="utf-8")


class TestBackupIsCrashRecoveryNotGarbage:
    def test_read_falls_back_to_backup(self):
        """主文件损坏时必须能回退读备份 —— 这是 .bak 存在的全部理由。"""
        src = _src()
        assert "backup_path" in src, "备份路径机制被移除"
        # 回退读取路径：read()捕获解析异常后读 backup
        assert "_read_path(self.backup_path)" in src, (
            "主文件损坏时的备份回退读取被移除 —— "
            "这是崩溃恢复能力，.bak 不是可清理的垃圾"
        )

    def test_backup_written_before_overwrite(self):
        """覆盖前必须先备份。"""
        src = _src()
        assert "shutil.copy2(self.path, self.backup_path)" in src, (
            "写入前的备份步骤被移除"
        )

    def test_only_backs_up_parseable_file(self):
        """只在主文件可解析时才备份 —— 防止损坏内容覆盖好的备份。"""
        src = _src()
        assert "try:" in src and "json.JSONDecodeError" in src, (
            "备份前的可解析性校验被移除"
        )

    def test_store_still_documents_its_purpose(self):
        src = _src()
        assert "上一版本备份" in src, (
            "AtomicJsonStore 的 docstring 应说明它带备份能力，"
            "避免后人把 .bak 当临时文件清理"
        )


class TestStoreIsImportable:
    def test_class_exists_with_backup_attribute(self):
        from app.services.ai_trace_storage import AtomicJsonStore

        assert hasattr(AtomicJsonStore, "_write_unlocked"), (
            "AtomicJsonStore 结构被破坏"
        )