from __future__ import annotations

import math
from typing import Any, Dict, Optional

from pipeline.media_presets import ensure_media_payload


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _clamp(value: float, *, min_value: float, max_value: float) -> float:
    if value < min_value:
        return float(min_value)
    if value > max_value:
        return float(max_value)
    return float(value)


def _storyboard_shot_count(storyboard: Any) -> int:
    if not isinstance(storyboard, list):
        return 0
    count = 0
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if shot_id:
            count += 1
    return count


def _tune_candidates(*, goal: str, shot_count: int, source_len: int) -> int:
    if goal == "cost":
        return 1

    # 质量优先：短内容/少镜头提升候选数，提高选优概率；长内容控制上限避免成本爆炸。
    if shot_count > 0:
        if shot_count <= 8:
            return 3
        return 2
    if source_len > 0 and source_len <= 2000:
        return 3
    return 2


def _tune_semantic_frames(*, goal: str, shot_count: int) -> str:
    if goal != "quality":
        return "head"
    if shot_count > 0 and shot_count <= 8:
        return "both"
    return "head"


def _tune_semantic_sample_rate(*, goal: str, shot_count: int) -> float:
    if goal != "quality":
        return 0.0
    if shot_count > 0 and shot_count <= 8:
        return 1.0
    if shot_count > 0 and shot_count <= 20:
        return 0.75
    return 0.6


def _tune_semantic_max_checks(*, goal: str, shot_count: int, frames: str, sample_rate: float) -> int:
    if goal != "quality":
        return 0
    if shot_count <= 0:
        return 12

    frames_factor = 2 if frames == "both" else 1
    expected = int(math.ceil(shot_count * _clamp(sample_rate, min_value=0.0, max_value=1.0) * frames_factor))
    # always_first/always_last 默认开启，给 2 个 shot 的冗余，避免“刚好卡预算”。
    expected += frames_factor * 2
    expected = max(12, expected)
    return int(min(48, expected))


def _tune_max_subject_pos_delta(*, ratio: str) -> float:
    # 质量优先：竖屏更容易暴露构图跳变，适度收紧连续性阈值（同时 storyboarder 会按该阈值做平滑）。
    if str(ratio).strip() == "9:16":
        return 0.08
    return 0.1


def apply_smart_tuning(payload: Dict[str, Any], *, stage: str) -> Dict[str, Any]:
    """
    规则化智能调参（可复现、可解释）：
    - 仅在 payload.smart_tuning=True 时生效
    - 默认目标：quality_mode=quality 时质量优先；quality_mode=cost 时成本优先
    - 输出：直接写回 payload.image_config / payload.qc_config，并记录 payload.smart_tuning_snapshot（便于排查）
    """
    if not isinstance(payload, dict):
        return payload
    if not isinstance(payload.get("smart_tuning"), bool) or not bool(payload.get("smart_tuning")):
        return payload

    try:
        ensure_media_payload(payload)
    except Exception:  # noqa: BLE001
        # ensure_media_payload 仅用于补齐 ratio/resolution/fps，失败不应阻断主流程
        pass

    goal = str(payload.get("quality_mode") or "quality").strip().lower()
    goal = "cost" if goal == "cost" else "quality"

    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    qc_cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}
    payload["image_config"] = image_cfg
    payload["qc_config"] = qc_cfg

    ratio = str(image_cfg.get("ratio") or "").strip()
    source_text = str(payload.get("script_text") or payload.get("source_text") or "")
    source_len = len(source_text)
    shot_count = _storyboard_shot_count(payload.get("storyboard"))

    candidates = _tune_candidates(goal=goal, shot_count=shot_count, source_len=source_len)
    image_cfg["t2i_candidates"] = int(max(1, min(4, candidates)))
    image_cfg["mid_candidates"] = int(max(1, min(4, candidates)))

    qc_cfg["max_subject_pos_delta"] = _tune_max_subject_pos_delta(ratio=ratio)

    enable_semantic = bool(qc_cfg.get("enable_semantic_qc")) if isinstance(qc_cfg.get("enable_semantic_qc"), bool) else False
    if goal == "quality":
        # 质量优先：若未显式禁用语义质检，则启用并按镜头规模调整预算。
        if "enable_semantic_qc" not in qc_cfg:
            enable_semantic = True
            qc_cfg["enable_semantic_qc"] = True

    if enable_semantic:
        frames = _tune_semantic_frames(goal=goal, shot_count=shot_count)
        sample_rate = _tune_semantic_sample_rate(goal=goal, shot_count=shot_count)
        max_checks = _tune_semantic_max_checks(goal=goal, shot_count=shot_count, frames=frames, sample_rate=sample_rate)

        qc_cfg["semantic_frames"] = frames
        qc_cfg["semantic_sample_rate"] = float(_clamp(sample_rate, min_value=0.0, max_value=1.0))
        qc_cfg["semantic_max_checks"] = int(max(0, max_checks))

    weights = qc_cfg.get("weights") if isinstance(qc_cfg.get("weights"), dict) else None
    if weights:
        # 容错：确保权重可转 float，避免 AutoQC 侧 float() 抛异常。
        for k in list(weights.keys()):
            v = _safe_float(weights.get(k))
            if v is None:
                weights.pop(k, None)
            else:
                weights[k] = float(v)
        qc_cfg["weights"] = weights

    payload["smart_tuning_snapshot"] = {
        "version": 1,
        "stage": str(stage or "").strip() or "unknown",
        "goal": goal,
        "inputs": {"ratio": ratio, "source_len": source_len, "shot_count": shot_count},
        "image_config": {"t2i_candidates": image_cfg.get("t2i_candidates"), "mid_candidates": image_cfg.get("mid_candidates")},
        "qc_config": {
            "max_subject_pos_delta": qc_cfg.get("max_subject_pos_delta"),
            "enable_semantic_qc": qc_cfg.get("enable_semantic_qc"),
            "semantic_frames": qc_cfg.get("semantic_frames"),
            "semantic_sample_rate": qc_cfg.get("semantic_sample_rate"),
            "semantic_max_checks": qc_cfg.get("semantic_max_checks"),
        },
    }

    return payload

