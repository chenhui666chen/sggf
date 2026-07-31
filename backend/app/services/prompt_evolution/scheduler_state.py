"""
进化调度器三态落盘（设计文档 §11 · §14 第 10 步 · 子块 B）

按题材持久化调度器三态（running/sleeping/awake）到 JSON，供 beat tick 读写、
管理面板（子块 C）快照。复用 challenger_repository 的临时文件 + os.replace 原子写
范式，避免写一半进程退出留下损坏文件。纯持久化层：不做业务判定、不接外部 API。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .evolution_scheduler import STATE_RUNNING

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerStateRecord:
    genre: str
    state: str
    reasons: List[str] = field(default_factory=list)
    updated_at: Optional[str] = None      # 最近一次状态变化时间（ISO）
    last_tick_at: Optional[str] = None     # 最近一次 tick 时间（ISO），无论是否变化
    # 入眠时刻的环境版本指纹快照（§11.2 environment_changed 信号 4）：
    # sleeping 期每次 tick 用当前指纹与此快照对比，不一致即环境变更唤醒。
    env_snapshot: Optional[dict] = None


def _atomic_write_json(path: Path, data: dict) -> None:
    """临时文件 + os.replace 原子写，避免写一半进程退出留下损坏文件。"""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("调度器状态账本损坏，按空账本处理: %s", path.name)
        return {}


class SchedulerStateStore:
    """调度器三态账本（scheduler_state.json，按题材一条记录）。"""

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.storage_dir / "scheduler_state.json"
        self._records: Dict[str, dict] = _load_json(self.store_file)

    def get(self, genre: str) -> SchedulerStateRecord:
        """读取题材当前状态；无记录默认 running。"""
        raw = self._records.get(genre)
        if raw is None:
            return SchedulerStateRecord(genre=genre, state=STATE_RUNNING)
        return SchedulerStateRecord(
            genre=genre,
            state=raw.get("state", STATE_RUNNING),
            reasons=list(raw.get("reasons", [])),
            updated_at=raw.get("updated_at"),
            last_tick_at=raw.get("last_tick_at"),
            env_snapshot=raw.get("env_snapshot"),
        )

    def set(
        self,
        genre: str,
        state: str,
        *,
        reasons: List[str],
        now: str,
        env_snapshot: Optional[dict] = None,
    ) -> SchedulerStateRecord:
        """
        写入题材新状态（状态变化时调用），同步刷新 updated_at 与 last_tick_at。

        env_snapshot 仅在转入 sleeping 时由编排层传入当前环境指纹；为 None 时保留
        既有快照（转出 sleeping 不清空，避免 §11.2 environment_changed 判定丢基准）。
        """
        raw = self._records.get(genre, {})
        raw.update(
            {
                "state": state,
                "reasons": list(reasons),
                "updated_at": now,
                "last_tick_at": now,
            }
        )
        if env_snapshot is not None:
            raw["env_snapshot"] = env_snapshot
        self._records[genre] = raw
        _atomic_write_json(self.store_file, self._records)
        return self.get(genre)

    def touch(self, genre: str, *, now: str) -> SchedulerStateRecord:
        """状态未变化时仅刷新 last_tick_at，保留 state/reasons/updated_at。"""
        raw = self._records.get(genre)
        if raw is None:
            raw = {"state": STATE_RUNNING, "reasons": []}
        raw["last_tick_at"] = now
        self._records[genre] = raw
        _atomic_write_json(self.store_file, self._records)
        return self.get(genre)

    def snapshot(self) -> Dict[str, SchedulerStateRecord]:
        """返回全部题材状态记录（供子块 C 管理面板）。"""
        return {genre: self.get(genre) for genre in self._records}
