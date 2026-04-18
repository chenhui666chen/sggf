from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.adapter_helpers import analyze_video, get_model_info

DEFAULT_SAFETY_VLM_ADAPTER = "qwen3-vl-plus"
DEFAULT_SAFETY_FAIL_POLICY = "warn"
SAFETY_ANALYSIS_TYPES = ("safety", "quality")
SAFETY_CRITERIA = ["violence", "sexual", "hate", "self_harm", "illegal", "harassment"]
BLOCK_POLICIES = {"block", "fail", "deny", "hard", "strict"}
WARN_POLICIES = {"warn", "warning", "soft", "allow", "ignore"}
SAFE_FALSEY = {"0", "false", "no", "none", "safe", "pass", "passed", "ok"}
SAFE_TRUTHY = {"1", "true", "yes", "unsafe", "flagged", "blocked", "violation", "fail", "failed"}
SAFETY_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("violence", ("violence", "violent", "gore", "blood", "weapon", "打斗", "暴力", "血腥", "伤害", "武器")),
    ("sexual", ("sexual", "nudity", "nude", "porn", "explicit", "sex", "裸露", "色情", "性暗示", "成人内容")),
    ("hate", ("hate", "hateful", "extremism", "terror", "仇恨", "极端主义", "恐怖主义")),
    ("self_harm", ("self-harm", "self_harm", "suicide", "自残", "自杀", "伤己")),
    ("illegal", ("illegal", "crime", "drug", "criminal", "违法", "毒品", "犯罪")),
    ("harassment", ("harassment", "abuse", "bully", "骚扰", "辱骂", "虐待")),
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if not lowered:
            return None
        if lowered in SAFE_TRUTHY:
            return True
        if lowered in SAFE_FALSEY:
            return False
    return None


def _try_parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
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


def _split_text_block(value: str) -> List[str]:
    cleaned = re.sub(r"^[\s\-*\d\.\)\(]+", "", str(value or "").strip())
    if not cleaned:
        return []
    parts = re.split(r"[\r\n;,，；]+", cleaned)
    return [part.strip(" -") for part in parts if part.strip(" -")]


def _text_list_from_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_text_block(value)
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


def _unique_texts(values: List[str], *, limit: int | None = None) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if limit is not None and len(result) >= limit:
            break
    return result


def _collect_text_list(payload: Dict[str, Any], keys: tuple[str, ...], *, limit: int = 6) -> List[str]:
    items: List[str] = []
    for key in keys:
        items.extend(_text_list_from_value(payload.get(key)))
    return _unique_texts(items, limit=limit)


def _extract_first_text(payload: Dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _text_from_value(payload.get(key))
        if text:
            return text
    return ""


def _normalize_score(value: Any) -> Optional[float]:
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


def _extract_first_score(payload: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        score = _normalize_score(payload.get(key))
        if score is not None:
            return score
    return None


def _coerce_analysis_payload(result: Any) -> Dict[str, Any]:
    if isinstance(getattr(result, "data", None), dict):
        payload = dict(result.data)
    else:
        payload = {}

    if isinstance(payload.get("result"), str):
        parsed = _try_parse_json_object(payload["result"])
        if parsed:
            payload = {**payload, **parsed}

    if not payload:
        text = _text_from_value(getattr(result, "data", None))
        parsed = _try_parse_json_object(text) if text else None
        if parsed:
            payload = parsed
        elif text:
            payload = {"content": text}

    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        raw_result_data = metadata.get("result_data")
        if isinstance(raw_result_data, dict):
            payload = {**raw_result_data, **payload}
        content = metadata.get("content")
        if not payload and isinstance(content, str) and content.strip():
            parsed = _try_parse_json_object(content)
            payload = parsed or {"content": content.strip()}

    return payload


def _normalize_severity(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"critical", "severe"}:
        return "critical"
    if raw in {"high", "danger", "unsafe"}:
        return "high"
    if raw in {"medium", "moderate"}:
        return "medium"
    if raw in {"low", "minor"}:
        return "low"
    score = _normalize_score(value)
    if score is None:
        return ""
    if score >= 8.5:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def _extract_categories(payload: Dict[str, Any], *, summary: str, issues: List[str]) -> List[str]:
    categories: List[str] = []

    for key in (
        "categories",
        "category",
        "labels",
        "violations",
        "violation_categories",
        "safety_categories",
        "risk_categories",
        "flagged_categories",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    name = (
                        item.get("name")
                        or item.get("category")
                        or item.get("label")
                        or item.get("type")
                    )
                    text = _normalize_optional_text(name)
                    if text:
                        categories.append(text.lower().replace(" ", "_"))
                else:
                    text = _normalize_optional_text(item)
                    if text:
                        categories.append(text.lower().replace(" ", "_"))
        elif isinstance(value, dict):
            for key_name, inner in value.items():
                marker = _to_bool(inner)
                if marker is False:
                    continue
                text = _normalize_optional_text(key_name)
                if text:
                    categories.append(text.lower().replace(" ", "_"))
        else:
            text = _normalize_optional_text(value)
            if text:
                categories.append(text.lower().replace(" ", "_"))

    combined_text = " ".join([summary, *issues]).casefold()
    for category, keywords in SAFETY_CATEGORY_KEYWORDS:
        if any(keyword.casefold() in combined_text for keyword in keywords):
            categories.append(category)

    return _unique_texts(categories, limit=6)


def _infer_unsafe_flag(
    payload: Dict[str, Any],
    *,
    categories: List[str],
    summary: str,
    issues: List[str],
    severity: str,
) -> bool:
    explicit_pairs = (
        ("unsafe", True),
        ("flagged", True),
        ("blocked", True),
        ("disallowed", True),
        ("violation", True),
        ("contains_violation", True),
        ("content_safe", False),
        ("safe", False),
        ("pass", False),
        ("passed", False),
        ("is_safe", False),
        ("is_unsafe", True),
    )
    for key, unsafe_when_true in explicit_pairs:
        if key not in payload:
            continue
        marker = _to_bool(payload.get(key))
        if marker is None:
            continue
        return marker if unsafe_when_true else not marker

    status = str(payload.get("status") or payload.get("result") or "").strip().lower()
    if status in {"unsafe", "flagged", "blocked", "violation", "failed"}:
        return True
    if status in {"safe", "pass", "passed", "ok"}:
        return False

    if categories:
        return True
    if severity in {"high", "critical"}:
        return True

    combined_text = " ".join([summary, *issues]).casefold()
    heuristic_keywords = (
        "unsafe",
        "flagged",
        "violation",
        "not safe",
        "disallowed",
        "blocked",
        "不安全",
        "违规",
        "高风险",
        "不合规",
        "需拦截",
        "建议拦截",
    )
    return any(keyword in combined_text for keyword in heuristic_keywords)


def _collect_output_issues(merged_video: Any) -> tuple[List[Dict[str, Any]], Optional[Path]]:
    issues: List[Dict[str, Any]] = []
    merged_path: Optional[Path] = None

    if not isinstance(merged_video, str) or not merged_video:
        issues.append({"category": "output", "message": "merged_video missing"})
        return issues, None

    merged_path = Path(merged_video)
    if not merged_path.exists():
        issues.append({"category": "output", "message": "merged_video file missing", "path": merged_video})
        return issues, merged_path

    try:
        if merged_path.stat().st_size < 1024:
            issues.append({"category": "output", "message": "merged_video too small", "path": merged_video})
    except Exception as exc:  # noqa: BLE001
        issues.append({"category": "output", "message": f"merged_video stat failed: {exc}", "path": merged_video})

    return issues, merged_path


def _resolve_safety_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    qc_cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}
    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}

    enabled = (
        bool(qc_cfg.get("enable_safety_audit"))
        if isinstance(qc_cfg.get("enable_safety_audit"), bool)
        else _env_flag("DREAMWEAVER_ENABLE_SAFETY_AUDIT", default=False)
    )

    fail_policy = (
        str(qc_cfg.get("safety_fail_policy") or os.getenv("DREAMWEAVER_SAFETY_AUDIT_FAIL_POLICY") or DEFAULT_SAFETY_FAIL_POLICY)
        .strip()
        .lower()
    )
    if fail_policy not in BLOCK_POLICIES | WARN_POLICIES:
        fail_policy = DEFAULT_SAFETY_FAIL_POLICY

    adapter = (
        _normalize_optional_text(qc_cfg.get("safety_vlm_adapter"))
        or _normalize_optional_text(os.getenv("DREAMWEAVER_SAFETY_AUDIT_VLM_ADAPTER"))
        or _normalize_optional_text(image_cfg.get("vlm_adapter"))
        or _normalize_optional_text(qc_cfg.get("semantic_vlm_adapter"))
        or _normalize_optional_text(qc_cfg.get("state_vlm_adapter"))
        or _normalize_optional_text(qc_cfg.get("video_clip_vlm_adapter"))
        or DEFAULT_SAFETY_VLM_ADAPTER
    )

    return {
        "enabled": enabled,
        "fail_policy": fail_policy,
        "warn_only": fail_policy in WARN_POLICIES,
        "adapter": adapter,
    }


def _run_safety_audit(payload: Dict[str, Any], *, merged_path: Optional[Path]) -> Dict[str, Any]:
    config = _resolve_safety_config(payload)
    result: Dict[str, Any] = {
        "enabled": config["enabled"],
        "executed": False,
        "pass": True,
        "effective_pass": True,
        "unsafe": False,
        "blocked": False,
        "fail_policy": config["fail_policy"],
        "warn_only": config["warn_only"],
        "model_id": config["adapter"],
        "analysis_type": "",
        "summary": "",
        "issues": [],
        "categories": [],
        "severity": "",
        "warnings": [],
    }

    if not config["enabled"]:
        return result

    if merged_path is None or not merged_path.exists():
        result["warnings"] = ["safety audit skipped: merged video not ready"]
        return result

    if not config["adapter"]:
        result["warnings"] = ["safety audit skipped: no safety VLM adapter configured"]
        return result

    try:
        if get_model_info(config["adapter"]) is None:
            result["warnings"] = [f"safety audit skipped: adapter unavailable: {config['adapter']}"]
            return result
    except Exception as exc:  # noqa: BLE001
        result["warnings"] = [f"safety audit skipped: adapter lookup failed: {exc}"]
        return result

    call_error: Optional[str] = None
    payload_data: Dict[str, Any] = {}
    used_analysis_type = ""
    runtime_result: Any = None
    for analysis_type in SAFETY_ANALYSIS_TYPES:
        try:
            runtime_result = analyze_video(
                video_path=str(merged_path),
                analysis_type=analysis_type,
                criteria=SAFETY_CRITERIA,
                model_id=config["adapter"],
            )
        except Exception as exc:  # noqa: BLE001
            call_error = str(exc)
            continue

        if not getattr(runtime_result, "success", False):
            call_error = str(getattr(runtime_result, "error", "") or getattr(runtime_result, "message", "") or "unknown error")
            continue

        payload_data = _coerce_analysis_payload(runtime_result)
        used_analysis_type = analysis_type
        break

    if not payload_data:
        warning = "safety audit skipped: empty analysis result"
        if call_error:
            warning = f"safety audit skipped: {call_error}"
        result["warnings"] = [warning]
        return result

    summary = _extract_first_text(
        payload_data,
        ("summary", "overview", "description", "analysis", "evaluation", "conclusion", "content"),
    )
    issues = _collect_text_list(
        payload_data,
        ("issues", "violations", "problems", "weaknesses", "risk_points", "findings"),
        limit=6,
    )
    severity = _normalize_severity(
        payload_data.get("severity")
        or payload_data.get("risk_level")
        or payload_data.get("risk")
        or payload_data.get("unsafe_score")
        or payload_data.get("risk_score")
        or _extract_first_score(payload_data, ("overall_score", "score", "safety_score"))
    )
    categories = _extract_categories(payload_data, summary=summary, issues=issues)
    unsafe = _infer_unsafe_flag(
        payload_data,
        categories=categories,
        summary=summary,
        issues=issues,
        severity=severity,
    )
    blocked = unsafe and not config["warn_only"]

    result.update(
        {
            "executed": True,
            "pass": not unsafe,
            "effective_pass": not blocked,
            "unsafe": unsafe,
            "blocked": blocked,
            "model_id": str(getattr(runtime_result, "model_id", "") or config["adapter"]),
            "analysis_type": used_analysis_type,
            "summary": summary,
            "issues": issues,
            "categories": categories,
            "severity": severity,
            "warnings": [],
        }
    )
    return result


def run(ctx: Any) -> Dict[str, Any]:
    output_issues, merged_path = _collect_output_issues(ctx.payload.get("merged_video"))
    safety_audit = _run_safety_audit(ctx.payload, merged_path=merged_path)

    issues: List[Dict[str, Any]] = list(output_issues)
    failure_type: Optional[str] = "output_audit_failed" if output_issues else None

    if safety_audit.get("blocked"):
        safety_issue: Dict[str, Any] = {
            "category": "safety",
            "message": safety_audit.get("summary") or "safety audit blocked merged video",
            "severity": safety_audit.get("severity") or "high",
        }
        if isinstance(safety_audit.get("categories"), list) and safety_audit["categories"]:
            safety_issue["categories"] = list(safety_audit["categories"])
        if isinstance(safety_audit.get("issues"), list) and safety_audit["issues"]:
            safety_issue["issues"] = list(safety_audit["issues"])
        issues.append(safety_issue)
        failure_type = "safety_audit_failed"

    result = {
        "pass": not output_issues and bool(safety_audit.get("effective_pass", True)),
        "issues": issues,
        "output_issues": output_issues,
        "failure_type": failure_type,
        "safety_audit": safety_audit,
    }
    ctx.payload["audit"] = result
    return result
