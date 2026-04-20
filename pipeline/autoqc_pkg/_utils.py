from __future__ import annotations

import base64
import json
import os
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.adapter_helpers import analyze_video, chat_messages, get_model_info
from agents.vlm_utils import clamp_text_list
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    is_dreamweaver_auto_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_engine,
)


DEFAULT_SIMILARITY_THRESHOLD = 0.9
DEFAULT_MAX_SUBJECT_POS_DELTA = 0.1
DEFAULT_WEIGHTS = {"identity": 0.4, "structure": 0.4, "style": 0.2}
DEFAULT_SEMANTIC_THRESHOLD = 0.6
DEFAULT_SEMANTIC_VLM_ADAPTER = "qwen3_vl_plus"
DEFAULT_SEMANTIC_FRAMES = "both"  # head|tail|both
DEFAULT_SEMANTIC_SAMPLE_RATE = 1.0
DEFAULT_SEMANTIC_MAX_CHECKS = 0  # 0 表示不设上限（保持历史行为）
DEFAULT_SEMANTIC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_STATE_QC_THRESHOLD = 0.65
DEFAULT_STATE_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_STATE_QC_SAMPLE_RATE = 1.0
DEFAULT_STATE_QC_MAX_CHECKS = 0  # 0 表示不设上限（与 semantic_max_checks 一致语义）
DEFAULT_STATE_QC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_VIDEO_CLIP_QC_THRESHOLD = 6.5
DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_VIDEO_CLIP_QC_SAMPLE_RATE = 1.0
DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS = 0  # 0 表示不设上限，可通过 qc_config/ENV 收紧
DEFAULT_VIDEO_CLIP_QC_CRITERIA = ["clarity", "smoothness", "consistency", "lighting", "color"]

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _stable_hash01(*parts: str) -> float:
    payload = "|".join([p for p in parts if p is not None]).encode("utf-8", errors="ignore")
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return float(value / 18446744073709551615)  # 2^64-1


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _is_dreamweaver_i2v_configured() -> bool:
    api_key = str(os.getenv("WAN_I2V_API_KEY") or "").strip()
    base_url = str(os.getenv("WAN_I2V_BASE_URL") or "").strip()
    model = (
        str(os.getenv("WAN_I2V_MODEL_NAME") or "").strip()
        or str(os.getenv("WAN_I2V_MODEL_ID") or "").strip()
        or str(os.getenv("WAN_I2V_MODEL") or "").strip()
    )
    return bool(api_key and base_url and model)


def _parse_role_from_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    p = Path(path)
    stem = p.stem
    suffix = p.suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        if stem.endswith("_head"):
            return stem[: -len("_head")], "head"
        if stem.endswith("_tail"):
            return stem[: -len("_tail")], "tail"
        if stem.endswith("_mid"):
            return stem[: -len("_mid")], "mid"
        return None, None

    if suffix in {".mp4", ".mov", ".mkv"}:
        return stem, "clip"

    return None, None


def _index_assets(payload: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    by_shot: Dict[str, Dict[str, str]] = {}

    def push(path: Any) -> None:
        if not isinstance(path, str):
            return
        shot_key, role = _parse_role_from_path(path)
        if not shot_key or not role:
            return
        by_shot.setdefault(shot_key, {})[role] = path

    for item in payload.get("keyframes") or []:
        if isinstance(item, dict):
            push(item.get("path"))
    for item in payload.get("midframes") or []:
        if isinstance(item, dict):
            push(item.get("path"))
    for item in payload.get("video_clips") or []:
        if isinstance(item, dict):
            push(item.get("path"))

    return by_shot


def _file_exists(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except Exception:  # noqa: BLE001
        return False


def _mime_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _file_to_data_url(path: Path) -> str:
    mime = _mime_from_path(path)
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _try_parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return str(int(float(value)))
        return f"{float(value):.1f}"
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "summary",
            "description",
            "comment",
            "message",
            "analysis",
            "reason",
            "evaluation",
            "conclusion",
        ):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def _extract_first_text(payload: Dict[str, Any], keys: Tuple[str, ...]) -> str:
    for key in keys:
        text = _text_from_value(payload.get(key))
        if text:
            return text
    return ""


def _text_list_from_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[\r\n;；]+", value)
        return [part.strip(" -•*") for part in parts if part.strip(" -•*")]
    if isinstance(value, list):
        items: List[str] = []
        for entry in value:
            items.extend(_text_list_from_value(entry))
        return items
    if isinstance(value, dict):
        items: List[str] = []
        for inner in value.values():
            items.extend(_text_list_from_value(inner))
        return items
    text = _text_from_value(value)
    return [text] if text else []


def _collect_text_list(payload: Dict[str, Any], keys: Tuple[str, ...], *, max_items: int = 6) -> List[str]:
    items: List[str] = []
    for key in keys:
        items.extend(_text_list_from_value(payload.get(key)))
    return clamp_text_list(items, max_items=max_items, max_chars=120)


def _normalize_review_score(value: Any) -> Optional[float]:
    candidate: Optional[float] = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        candidate = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            candidate = float(match.group(0))

    if candidate is None:
        return None
    if candidate <= 1.0:
        candidate *= 10.0
    elif 10.0 < candidate <= 100.0:
        candidate /= 10.0
    return round(max(0.0, min(candidate, 10.0)), 1)


def _extract_first_score(payload: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for key in keys:
        score = _normalize_review_score(payload.get(key))
        if score is not None:
            return score
    return None


def _is_non_score_key(key: str) -> bool:
    return key in {
        "summary",
        "overview",
        "description",
        "evaluation",
        "conclusion",
        "strengths",
        "highlights",
        "advantages",
        "issues",
        "weaknesses",
        "problems",
        "suggestions",
        "recommendations",
        "prompt_suggestions",
        "revised_prompt",
        "analysis_type",
        "content",
        "raw",
        "metadata",
        "message",
        "error",
        "result",
    }


def _extract_criteria_review_scores(payload: Dict[str, Any]) -> List[float]:
    scores: List[float] = []
    candidate_keys = (
        "criteria_scores",
        "scores",
        "criteria",
        "dimensions",
        "dimension_scores",
        "metrics",
        "aspect_scores",
    )
    containers = [payload.get(key) for key in candidate_keys if payload.get(key)]
    if not containers:
        containers = [payload]

    for container in containers:
        if isinstance(container, dict):
            for key, value in container.items():
                if _is_non_score_key(str(key)):
                    continue
                if isinstance(value, dict):
                    score = _extract_first_score(value, ("score", "value", "rating", "overall_score"))
                else:
                    score = _normalize_review_score(value)
                if score is not None:
                    scores.append(score)
        elif isinstance(container, list):
            for item in container:
                if not isinstance(item, dict):
                    continue
                score = _extract_first_score(item, ("score", "value", "rating", "overall_score"))
                if score is not None:
                    scores.append(score)
    return scores


def _coerce_video_review_payload(result: Any) -> Dict[str, Any]:
    raw_data = getattr(result, "data", None)
    if isinstance(raw_data, dict):
        payload = dict(raw_data)
    else:
        payload = {}

    if isinstance(payload.get("result"), str):
        parsed = _try_parse_json_object(str(payload.get("result") or ""))
        if parsed:
            payload = {**payload, **parsed}

    if not payload:
        text = _text_from_value(raw_data)
        parsed = _try_parse_json_object(text) if text else None
        if parsed:
            payload = parsed
        elif text:
            payload = {"content": text}

    return payload


def _extract_video_review_result(result: Any) -> Dict[str, Any]:
    payload = _coerce_video_review_payload(result)
    overall_score = _extract_first_score(
        payload,
        ("overall_score", "score", "quality_score", "total_score", "final_score"),
    )
    criteria_scores = _extract_criteria_review_scores(payload)
    if overall_score is None and criteria_scores:
        overall_score = round(sum(criteria_scores) / len(criteria_scores), 1)

    issues = _collect_text_list(
        payload,
        ("issues", "weaknesses", "problems", "suggestions", "recommendations"),
        max_items=6,
    )
    summary = _extract_first_text(
        payload,
        ("summary", "overview", "evaluation", "analysis", "description", "conclusion", "content"),
    )
    return {
        "score": overall_score,
        "criteria_scores": criteria_scores,
        "issues": issues,
        "summary": summary,
        "payload": payload,
    }


