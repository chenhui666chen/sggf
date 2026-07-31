# -*- coding: utf-8 -*-
"""
哨兵巡检探针（设计文档 §11.2 sentinel_degraded 信号 5 · §14 第 10 步子块 B）

定时用固定哨兵语料（holdout 留出子集按 sample_id 排序取前 N，恒定语料）对当前冠军
做新鲜 AI 检测：同一冠军 + 同一 policy 的首次探测建基线；后续探测
last_score - baseline_score > wake_ai_score_rise（复用 §11.2 现有唤醒阈值口径，
不新增阈值）即置退化标志，供休眠期 tick 只读消费唤醒。冠军或 policy 变更时基线
重置（新冠军与旧基线不可比）。

哨兵与 holdout 复评（holdout_probe）不同：不能按 champion_hash 跳过重测——哨兵
目的正是对同一冠军重复探测检测器/环境漂移；成本控制在任务层（只探 sleeping 题材，
低频 beat）。读取降级：无缓存 / 损坏 / policy 不一致 / 超龄（TTL）/ 时间戳缺失
一律 False（不误唤醒，安全侧）。持久化复用临时文件 + os.replace 原子写范式。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .evolution_scheduler import DEFAULT_WAKE_AI_SCORE_RISE
from .holdout_probe import champion_prompt_hash, is_record_stale

logger = logging.getLogger(__name__)

SENTINEL_STATE_FILENAME = "sentinel_state.json"

# 哨兵语料条数（结构参数非质量阈值）：留出集中按 sample_id 排序取前此数，
# 恒定语料保证跨次探测可比。
SENTINEL_SAMPLE_COUNT = 5

# 缓存新鲜度上限：2× 12h beat 巡检周期（结构参数）。超龄说明巡检任务停摆，
# 旧退化标志不再可信，消费侧按无缓存降级。
SENTINEL_STATE_MAX_AGE_HOURS = 24


def is_sentinel_record_consumable(
    record: Optional[dict], *, policy: str, now=None
) -> bool:
    """
    哨兵缓存记录可消费判定——is_degraded / describe_signal 统一口径（防漂移）：
    policy 一致 + degraded 为严格 bool（合法 JSON 但类型损坏如 "false" 字符串
    经真值转换会误唤醒，必须拒绝）+ 时间戳新鲜。
    """
    if not record or record.get("policy") != policy:
        return False
    if not isinstance(record.get("degraded"), bool):
        return False
    return not is_record_stale(record.get("checked_at"), SENTINEL_STATE_MAX_AGE_HOURS, now)


def select_sentinel_samples(sample_manager, genre: str) -> List:
    """哨兵语料：该题材留出样本按 sample_id 排序取前 SENTINEL_SAMPLE_COUNT（确定性）。"""
    holdout = sample_manager.get_samples_by_genre(genre, holdout=True)
    return sorted(holdout, key=lambda s: s.sample_id)[:SENTINEL_SAMPLE_COUNT]


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
        logger.warning("哨兵状态缓存损坏，按空缓存处理: %s", path.name)
        return {}


class SentinelStateStore:
    """哨兵巡检状态缓存（sentinel_state.json，按题材一条记录）。"""

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.storage_dir / SENTINEL_STATE_FILENAME
        self._records = _load_json(self.store_file)

    def get_record(self, genre: str) -> Optional[dict]:
        """读取题材缓存记录原样返回；无记录返回 None。"""
        raw = self._records.get(genre)
        return dict(raw) if isinstance(raw, dict) else None

    def set_record(self, genre: str, record: dict) -> None:
        """写入题材缓存记录（原子写）。"""
        self._records[genre] = dict(record)
        _atomic_write_json(self.store_file, self._records)

    def is_degraded(self, genre: str, *, policy: str, now: Optional[datetime] = None) -> bool:
        """
        tick 消费口径：返回缓存退化标志；无缓存 / policy 不一致（§8.1 不跨评审
        策略版本消费）/ 值非严格 bool / 超龄（TTL）一律返回 False（不误唤醒，安全侧）。
        """
        record = self.get_record(genre)
        if is_sentinel_record_consumable(record, policy=policy, now=now):
            return record["degraded"]
        if (
            record
            and record.get("policy") == policy
            and is_record_stale(record.get("checked_at"), SENTINEL_STATE_MAX_AGE_HOURS, now)
        ):
            logger.warning(
                "哨兵状态缓存超龄（>%dh），降级为 False 安全侧: genre=%s checked_at=%s",
                SENTINEL_STATE_MAX_AGE_HOURS, genre, record.get("checked_at"),
            )
        return False

    def describe_signal(self, genre: str, *, policy: str, now: Optional[datetime] = None) -> dict:
        """
        面板观测口径（只读，不改状态）：degraded 为 tick 真实消费值（含降级）；
        checked_at 原样回显供排查；stale = 有记录但时间戳超龄；
        defaulted = 消费的是降级默认值（无记录 / policy 不一致 / 值非法 / 超龄）。
        """
        record = self.get_record(genre)
        checked_at = record.get("checked_at") if record else None
        stale = bool(record) and is_record_stale(checked_at, SENTINEL_STATE_MAX_AGE_HOURS, now)
        return {
            "degraded": self.is_degraded(genre, policy=policy, now=now),
            "checked_at": checked_at,
            "stale": stale,
            "defaulted": not is_sentinel_record_consumable(record, policy=policy, now=now),
        }


async def run_sentinel_probe_for_genre(
    genre: str,
    *,
    evaluator,
    sample_manager,
    storage,
    store: SentinelStateStore,
    policy: str,
    wake_ai_score_rise: float = DEFAULT_WAKE_AI_SCORE_RISE,
    now: Optional[str] = None,
) -> dict:
    """
    对单题材做一次哨兵探测并写缓存（beat 任务体逐题材调用）。

    跳过条件（均不调用外部评分）：无冠军提示词；无哨兵语料（该题材留出侧为空）。
    """
    selection = storage.get_prompt_selection(genre)
    prompt_text = (selection or {}).get("prompt_text")
    if not prompt_text:
        return {"status": "skipped_no_champion"}

    samples = select_sentinel_samples(sample_manager, genre)
    if not samples:
        return {"status": "skipped_no_sentinel_samples"}

    current_hash = champion_prompt_hash(prompt_text)
    last_score, _ = await evaluator.evaluate_prompt(prompt_text, samples)
    last_score = float(last_score)

    # 基线仅在同冠军 + 同 policy 下可比；否则（首测 / 冠军换代 / 策略升级）重建基线。
    cached = store.get_record(genre)
    baseline: Optional[float] = None
    if (
        cached
        and cached.get("policy") == policy
        and cached.get("champion_hash") == current_hash
        and isinstance(cached.get("baseline_score"), (int, float))
    ):
        baseline = float(cached["baseline_score"])

    if baseline is None:
        status = "baseline_established"
        baseline = last_score
        degraded = False
    else:
        status = "probed"
        degraded = (last_score - baseline) > wake_ai_score_rise

    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    store.set_record(
        genre,
        {
            "degraded": degraded,
            "baseline_score": baseline,
            "last_score": last_score,
            "checked_at": now,
            "champion_hash": current_hash,
            "policy": policy,
        },
    )
    logger.info(
        "哨兵探测完成: genre=%s status=%s degraded=%s (baseline=%.2f last=%.2f)",
        genre, status, degraded, baseline, last_score,
    )
    return {"status": status, "degraded": degraded, "last_score": last_score}
