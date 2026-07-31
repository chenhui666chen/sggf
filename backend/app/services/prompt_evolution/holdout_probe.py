# -*- coding: utf-8 -*-
"""
holdout 过拟合探针（设计文档 §11.1 holdout_score_gap · §13#3 · §14 第 10 步子块 B）

冠军提示词在「训练样本」vs「留出样本」上的新鲜复评分差（信号 2，休眠门槛）：
gap = holdout_avg - training_avg（平均 AI 得分越低越好，留出显著更差 = 过拟合假象，
阻止带水分入眠）。复评走低频 beat + JSON 缓存，tick 只读缓存不触发外部调用；
无缓存 / 损坏 / policy 不一致 / 超龄（TTL）/ 时间戳缺失一律降级为 0.0 中性
（不阻止入眠、不误触发）。

成本控制：缓存记录冠军全文哈希（champion_hash），冠军与 policy 均未变时跳过重算。
持久化复用 scheduler_state 的临时文件 + os.replace 原子写范式。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HOLDOUT_SCORES_FILENAME = "holdout_scores.json"
# 缓存新鲜度上限：2× 每日 beat 复评周期（结构参数）。超龄说明复评任务停摆，
# 旧 gap 不再可信，消费侧按无缓存降级。
HOLDOUT_GAP_MAX_AGE_HOURS = 48


def champion_prompt_hash(prompt_text: str) -> str:
    """冠军提示词全文内容哈希（缓存新鲜度判定，不存原文）。"""
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]


def is_record_stale(timestamp: object, max_age_hours: float, now: Optional[datetime] = None) -> bool:
    """
    缓存时间戳陈旧判定：距 now 超过 max_age_hours 为陈旧；
    时间戳缺失 / 不可解析 / 位于未来（时钟异常、人工改动，不可信）均按超龄处理
    （保守降级）。
    """
    if not isinstance(timestamp, str) or not timestamp:
        return True
    try:
        recorded = datetime.fromisoformat(timestamp)
    except ValueError:
        return True
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    age = now - recorded
    if age < timedelta(0):
        return True
    return age > timedelta(hours=max_age_hours)


def is_finite_number(value: object) -> bool:
    """
    严格有限数值判定：排除 bool（int 子类会穿透 isinstance 检查）与
    NaN/Infinity（Python json 默认解析的非标准值；NaN 会让休眠门槛比较恒 False）。
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def is_gap_record_consumable(
    record: Optional[dict], *, policy: str, now: Optional[datetime] = None
) -> bool:
    """
    gap 缓存记录可消费判定——get_gap / describe_signal / evaluate_holdout_gap
    统一口径（防三处漂移）：policy 一致 + gap 为严格有限数值 + 时间戳新鲜。
    """
    if not record or record.get("policy") != policy:
        return False
    if not is_finite_number(record.get("gap")):
        return False
    return not is_record_stale(record.get("computed_at"), HOLDOUT_GAP_MAX_AGE_HOURS, now)


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
        logger.warning("holdout 分差缓存损坏，按空缓存处理: %s", path.name)
        return {}


class HoldoutScoreStore:
    """holdout 分差缓存（holdout_scores.json，按题材一条记录）。"""

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.storage_dir / HOLDOUT_SCORES_FILENAME
        self._records = _load_json(self.store_file)

    def get_record(self, genre: str) -> Optional[dict]:
        """读取题材缓存记录原样返回；无记录返回 None。"""
        raw = self._records.get(genre)
        return dict(raw) if isinstance(raw, dict) else None

    def set_record(self, genre: str, record: dict) -> None:
        """写入题材缓存记录（原子写）。"""
        self._records[genre] = dict(record)
        _atomic_write_json(self.store_file, self._records)

    def get_gap(self, genre: str, *, policy: str, now: Optional[datetime] = None) -> float:
        """
        tick 消费口径：返回缓存 gap；无缓存 / 记录不完整 / policy 不一致（§8.1
        不跨评审策略版本消费）/ 超龄（TTL）一律返回 0.0 中性。
        """
        record = self.get_record(genre)
        if is_gap_record_consumable(record, policy=policy, now=now):
            return float(record["gap"])
        if (
            record
            and record.get("policy") == policy
            and is_record_stale(record.get("computed_at"), HOLDOUT_GAP_MAX_AGE_HOURS, now)
        ):
            logger.warning(
                "holdout 分差缓存超龄（>%dh），降级为 0.0 中性: genre=%s computed_at=%s",
                HOLDOUT_GAP_MAX_AGE_HOURS, genre, record.get("computed_at"),
            )
        return 0.0

    def describe_signal(self, genre: str, *, policy: str, now: Optional[datetime] = None) -> dict:
        """
        面板观测口径（只读，不改状态）：gap 为 tick 真实消费值（含降级）；
        computed_at 原样回显供排查；stale = 有记录但时间戳超龄；
        defaulted = 消费的是降级默认值（无记录 / policy 不一致 / 值非法 / 超龄）。
        """
        record = self.get_record(genre)
        computed_at = record.get("computed_at") if record else None
        stale = bool(record) and is_record_stale(computed_at, HOLDOUT_GAP_MAX_AGE_HOURS, now)
        return {
            "gap": self.get_gap(genre, policy=policy, now=now),
            "computed_at": computed_at,
            "stale": stale,
            "defaulted": not is_gap_record_consumable(record, policy=policy, now=now),
        }


async def evaluate_holdout_gap(
    genre: str,
    *,
    evaluator,
    sample_manager,
    storage,
    store: HoldoutScoreStore,
    policy: str,
    now: Optional[str] = None,
) -> dict:
    """
    对单题材做一次冠军新鲜复评并写缓存（beat 任务体逐题材调用）。

    跳过条件（均不调用外部评分）：无冠军提示词；缓存 champion_hash 与 policy 均
    未变且记录仍新鲜（成本控制；超龄必须重算刷新，否则消费端 TTL 降级后
    永久停留在 0.0 默认值不可恢复）；训练/留出任一侧无样本（证据不足）。
    """
    selection = storage.get_prompt_selection(genre)
    prompt_text = (selection or {}).get("prompt_text")
    if not prompt_text:
        return {"status": "skipped_no_champion"}

    current_hash = champion_prompt_hash(prompt_text)
    cached = store.get_record(genre)
    if (
        cached
        and cached.get("champion_hash") == current_hash
        and is_gap_record_consumable(cached, policy=policy)
    ):
        return {"status": "skipped_cached", "gap": cached.get("gap")}

    training = sample_manager.get_samples_by_genre(genre, holdout=False)
    holdout = sample_manager.get_samples_by_genre(genre, holdout=True)
    if not training or not holdout:
        return {"status": "skipped_insufficient_samples"}

    training_avg, _ = await evaluator.evaluate_prompt(prompt_text, training)
    holdout_avg, _ = await evaluator.evaluate_prompt(prompt_text, holdout)
    # 落盘边界：外部评分必须为严格有限数值，否则抛明确异常由任务层单题材兜底
    # （不覆盖旧缓存，保留至 TTL 到期后消费端自然降级 0.0 中性）
    for field_name, value in (("training_avg", training_avg), ("holdout_avg", holdout_avg)):
        if not is_finite_number(value):
            raise ValueError(
                f"holdout 复评评分非法（非有限数值）: genre={genre} {field_name}={value!r}"
            )
    gap = float(holdout_avg) - float(training_avg)

    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    store.set_record(
        genre,
        {
            "gap": gap,
            "training_avg": float(training_avg),
            "holdout_avg": float(holdout_avg),
            "computed_at": now,
            "champion_hash": current_hash,
            "policy": policy,
        },
    )
    logger.info(
        "holdout 复评完成: genre=%s gap=%.2f (training=%.2f holdout=%.2f)",
        genre, gap, training_avg, holdout_avg,
    )
    return {"status": "updated", "gap": gap}
