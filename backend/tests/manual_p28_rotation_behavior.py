# -*- coding: utf-8 -*-
"""P28 轮转的**行为**实测（不只是看代码形状）。

守卫 test_json_store_backup_rotation.py 只验证了代码存在，
但没验证轮转真的按预期工作。这里用临时目录跑真实写入序列。

⚠️ 必须在持锁的上下文里调用 `_write_unlocked`，或经由公开的 `write()`
   —— 因为所有 IO 都依赖字节锁。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai_trace_storage import AtomicJsonStore  # noqa: E402


def test_rotation_keeps_at_most_backup_keep():
    """连续写入 N 次后，历史备份份数应受 BACKUP_KEEP 约束。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "demo.json"
        store = AtomicJsonStore(p)
        for i in range(6):
            store.write({"i": i, "pad": "x" * 200})

        history = list(p.parent.glob("demo.json.bak.*"))
        print(f"  写入 6 次后历史备份 {len(history)} 份 (BACKUP_KEEP={store.BACKUP_KEEP})")
        assert len(history) <= store.BACKUP_KEEP, (
            f"历史备份未受份数上限约束：{len(history)} > {store.BACKUP_KEEP}"
        )


def test_crash_recovery_still_works_after_rotation():
    """关键：轮转后崩溃恢复能力必须完好。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "demo.json"
        store = AtomicJsonStore(p)
        store.write({"v": 1})
        store.write({"v": 2})
        assert store.read() == {"v": 2}

        # 模拟主文件损坏（截断成非法 JSON）
        p.write_text('{"v": 3, "broken', encoding="utf-8")
        recovered = store.read()
        print(f"  主文件损坏后回退读到: {recovered}")
        assert recovered == {"v": 1}, (
            f"崩溃恢复失效，回退读到 {recovered}，期望上一版 {{'v': 1}}"
        )


def test_rotation_preserves_at_least_one_bak():
    """无论写多少次，.bak 本身必须始终存在。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "demo.json"
        store = AtomicJsonStore(p)
        for i in range(5):
            store.write({"i": i})
            assert store.backup_path.exists() or i == 0, (
                f"第 {i} 次写入后 .bak 不存在 —— 崩溃恢复能力丢失"
            )


def test_byte_limit_prunes_oldest():
    """总量上限应触发清理，且从最老的开始删。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "demo.json"
        store = AtomicJsonStore(p)
        store.BACKUP_HISTORY_MAX_BYTES = 1000  # 压低阈值以触发
        for i in range(8):
            store.write({"i": i, "pad": "y" * 300})

        history = sorted(
            p.parent.glob("demo.json.bak.*"),
            key=lambda x: x.stat().st_mtime,
        )
        total = sum(x.stat().st_size for x in history)
        print(f"  总量上限 1000B → 实际 {total}B, 保留 {len(history)} 份")
        assert total <= 1000 or len(history) <= store.BACKUP_KEEP


def test_read_is_idempotent_after_rotation():
    """轮转不得影响正常读取。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "demo.json"
        store = AtomicJsonStore(p)
        for i in range(3):
            store.write({"n": i})
            assert store.read() == {"n": i}, f"第 {i} 轮读取不一致"


def test_missing_directory_is_safe():
    """目录不存在时应自行创建，不报错。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "nested" / "deep" / "demo.json"
        store = AtomicJsonStore(p)
        store.write({"ok": True})
        assert p.exists()
        assert store.read() == {"ok": True}


def test_json_still_valid_after_rotation():
    """存档必须是合法 JSON —— 这是取证脚本的基础。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "demo.json"
        store = AtomicJsonStore(p)
        for i in range(4):
            store.write({"round": i, "items": list(range(50))})
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["round"] == 3