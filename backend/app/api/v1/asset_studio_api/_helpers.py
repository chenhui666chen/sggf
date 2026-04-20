"""首页资产工作台 API。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from math import gcd
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.audiobook.ai_music import MusicGenerationRequest, MusicStyle, create_music_generator
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import UnifiedMediaResult, media_runtime

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api._constants import (
    IMAGE_GENERATION_MODELS,
    IMAGE_EDIT_MODELS,
    VIDEO_MODELS,
    VIDEO_EDIT_MODELS,
    VIDEO_EDIT_FEATURES,
    AUDIO_MODELS,
    VIDEO_DURATION_OPTIONS,
    AUDIO_DURATION_OPTIONS,
    IMAGE_FILE_SUFFIXES,
    VIDEO_FILE_SUFFIXES,
    ASSET_STUDIO_UPLOAD_DIR,
    ASSET_STUDIO_OUTPUT_DIR,
)

def _normalize_criterion_name(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return VISION_CRITERION_ALIASES.get(normalized, normalized)


def _format_criterion_label(name: str) -> str:
    normalized = _normalize_criterion_name(name)
    if normalized in VISION_CRITERION_LABELS:
        return VISION_CRITERION_LABELS[normalized]
    return str(name or "").strip().replace("_", " ") or normalized


def _unique_texts(values: list[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
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


def _split_text_block(value: str) -> list[str]:
    cleaned = re.sub(r"^[\s\-*•\d\.\)\(]+", "", str(value or "").strip())
    if not cleaned:
        return []
    parts = re.split(r"[\r\n;；]+", cleaned)
    return _unique_texts([part.strip(" ，,") for part in parts if part.strip(" ，,")])


def _text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return str(int(float(value)))
        return f"{float(value):.1f}"
    if isinstance(value, dict):
        for key in ("text", "content", "summary", "description", "comment", "message", "analysis", "reason"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def _text_list_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_text_block(value)
    if isinstance(value, list):
        items: list[str] = []
        for entry in value:
            items.extend(_text_list_from_value(entry))
        return _unique_texts(items)
    if isinstance(value, dict):
        items: list[str] = []
        for key, inner in value.items():
            text = _text_from_value(inner)
            if not text:
                continue
            label = _format_criterion_label(str(key))
            if text == label:
                items.append(text)
            else:
                items.append(f"{label}：{text}")
        return _unique_texts(items)
    text = _text_from_value(value)
    return [text] if text else []


def _collect_text_list(payload: dict[str, Any], keys: tuple[str, ...], *, limit: int | None = None) -> list[str]:
    items: list[str] = []
    for key in keys:
        items.extend(_text_list_from_value(payload.get(key)))
    return _unique_texts(items, limit=limit)


def _extract_first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _text_from_value(payload.get(key))
        if text:
            return text
    return ""


def _normalize_score(value: Any) -> float | None:
    candidate: float | None = None
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
    elif candidate > 10.0 and candidate <= 100.0:
        candidate /= 10.0
    return round(max(0.0, min(candidate, 10.0)), 1)


def _extract_first_score(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        score = _normalize_score(payload.get(key))
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
        "prompt_suggestions",
        "revised_prompt",
        "analysis_type",
        "content",
        "raw",
        "metadata",
    }


def _extract_criteria_scores(payload: dict[str, Any], *, asset_type: str) -> list[AssetStudioVisionCriterionScore]:
    items_by_name: dict[str, AssetStudioVisionCriterionScore] = {}
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

    def upsert(name: str, score: float | None, comment: str) -> None:
        normalized_name = _normalize_criterion_name(name)
        if not normalized_name:
            return
        existing = items_by_name.get(normalized_name)
        if existing is None:
            items_by_name[normalized_name] = AssetStudioVisionCriterionScore(
                name=normalized_name,
                label=_format_criterion_label(normalized_name),
                score=score,
                comment=comment or None,
            )
            return
        if existing.score is None and score is not None:
            existing.score = score
        if not existing.comment and comment:
            existing.comment = comment

    for container in containers:
        if isinstance(container, dict):
            for key, value in container.items():
                if _is_non_score_key(str(key)):
                    continue
                if isinstance(value, dict):
                    comment = _extract_first_text(
                        value,
                        ("comment", "summary", "analysis", "description", "reason", "issue", "suggestion"),
                    )
                    score = _extract_first_score(value, ("score", "value", "rating", "overall_score"))
                    if score is not None or comment:
                        upsert(str(key), score, comment)
                        continue
                score = _normalize_score(value)
                if score is not None:
                    upsert(str(key), score, "")
        elif isinstance(container, list):
            for item in container:
                if not isinstance(item, dict):
                    continue
                name = (
                    item.get("name")
                    or item.get("criterion")
                    or item.get("aspect")
                    or item.get("metric")
                    or item.get("label")
                    or item.get("dimension")
                )
                if not name:
                    continue
                score = _extract_first_score(item, ("score", "value", "rating", "overall_score"))
                comment = _extract_first_text(
                    item,
                    ("comment", "summary", "analysis", "description", "reason", "issue", "suggestion"),
                )
                if score is not None or comment:
                    upsert(str(name), score, comment)

    preferred_order = {
        name: index for index, name in enumerate(VISION_REVIEW_CRITERIA.get(asset_type, []))
    }
    return sorted(
        items_by_name.values(),
        key=lambda item: (preferred_order.get(item.name, 99), item.label),
    )


def _infer_strengths(criteria_scores: list[AssetStudioVisionCriterionScore]) -> list[str]:
    strengths = [
        f"{item.label}表现较好（{item.score:.1f}/10）"
        for item in criteria_scores
        if item.score is not None and item.score >= 8.0
    ]
    return _unique_texts(strengths, limit=3)


def _infer_issues(criteria_scores: list[AssetStudioVisionCriterionScore]) -> list[str]:
    issues = [
        f"{item.label}需要重点优化（{item.score:.1f}/10）"
        for item in criteria_scores
        if item.score is not None and item.score < 7.0
    ]
    return _unique_texts(issues, limit=4)


def _build_prompt_suggestions(
    *,
    payload: dict[str, Any],
    asset_type: str,
    issues: list[str],
    criteria_scores: list[AssetStudioVisionCriterionScore],
) -> list[str]:
    suggestions = _collect_text_list(
        payload,
        (
            "prompt_suggestions",
            "suggestions",
            "recommendations",
            "improvement_suggestions",
            "prompt_tips",
            "fix_suggestions",
        ),
        limit=6,
    )
    if suggestions:
        return suggestions

    heuristic_suggestions: list[str] = []
    for item in criteria_scores:
        if item.score is not None and item.score < 7.0:
            hint = VISION_CRITERION_PROMPT_HINTS.get(item.name)
            if hint:
                heuristic_suggestions.append(hint)

    issue_text = " ".join(issues).casefold()
    for keywords, hint in VISION_ISSUE_KEYWORD_HINTS:
        if any(keyword.casefold() in issue_text for keyword in keywords):
            heuristic_suggestions.append(hint)

    if not heuristic_suggestions:
        heuristic_suggestions.append(
            "补充主体清晰、构图稳定、光影自然、色彩统一的要求。"
            if asset_type == "image"
            else "补充主体一致、动作连贯、镜头稳定、光影自然的要求。"
        )
    return _unique_texts(heuristic_suggestions, limit=6)


def _build_revised_prompt(
    *,
    asset_type: str,
    original_prompt: str,
    prompt_suggestions: list[str],
    criteria_scores: list[AssetStudioVisionCriterionScore],
) -> str:
    base_prompt = original_prompt.strip()
    focus_items = _unique_texts(prompt_suggestions, limit=5)
    if not focus_items:
        focus_items = [
            "主体清晰、细节完整、构图稳定、光影自然、色彩统一。"
            if asset_type == "image"
            else "主体一致、动作连贯、镜头稳定、细节清晰、光影自然。"
        ]

    negative_items = _unique_texts(
        [
            VISION_CRITERION_NEGATIVE_HINTS[item.name]
            for item in criteria_scores
            if item.score is not None and item.score < 7.0 and item.name in VISION_CRITERION_NEGATIVE_HINTS
        ],
        limit=4,
    )

    if base_prompt:
        parts = [base_prompt, f"请重点优化：{'；'.join(focus_items)}"]
    else:
        base_requirement = (
            "请生成一张高质量图片，主体明确，构图稳定，细节清晰。"
            if asset_type == "image"
            else "请生成一段高质量视频，主体一致，动作连贯，镜头稳定。"
        )
        parts = [base_requirement, f"重点要求：{'；'.join(focus_items)}"]

    if negative_items:
        parts.append(f"避免：{'；'.join(negative_items)}")
    return "\n".join(parts)


def _resolve_review_asset_type(upload: UploadFile) -> str:
    content_type = str(upload.content_type or "").strip().lower()
    suffix = Path(upload.filename or "").suffix.lower()
    if content_type.startswith("image/") or suffix in IMAGE_FILE_SUFFIXES:
        return "image"
    if content_type.startswith("video/") or suffix in VIDEO_FILE_SUFFIXES:
        return "video"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="视觉识别仅支持上传图片或视频素材",
    )


def _build_vision_review_response(
    *,
    asset_type: str,
    original_prompt: str,
    upload: UploadFile,
    result: UnifiedMediaResult,
    criteria: list[str],
) -> AssetStudioVisionReviewResponse:
    raw_data = result.data
    payload = dict(raw_data) if isinstance(raw_data, dict) else {}
    if not payload:
        content_text = _text_from_value(raw_data)
        if content_text:
            payload = {"content": content_text}

    criteria_scores = _extract_criteria_scores(payload, asset_type=asset_type)
    overall_score = _extract_first_score(
        payload,
        ("overall_score", "score", "quality_score", "total_score", "final_score"),
    )
    if overall_score is None and criteria_scores:
        available_scores = [item.score for item in criteria_scores if item.score is not None]
        if available_scores:
            overall_score = round(sum(available_scores) / len(available_scores), 1)

    strengths = _collect_text_list(
        payload,
        ("strengths", "highlights", "advantages", "positive_points", "good_points", "merits"),
        limit=4,
    )
    issues = _collect_text_list(
        payload,
        ("issues", "weaknesses", "problems", "concerns", "defects", "improvement_points"),
        limit=5,
    )
    if not strengths:
        strengths = _infer_strengths(criteria_scores)
    if not issues:
        issues = _infer_issues(criteria_scores)

    summary = _extract_first_text(
        payload,
        ("summary", "overview", "evaluation", "overall_comment", "conclusion", "description", "content"),
    )
    if not summary:
        if overall_score is not None:
            if overall_score >= 8.5:
                summary = "整体质量较好，可直接作为可用素材继续微调。"
            elif overall_score >= 6.5:
                summary = "素材基础可用，但仍有一些细节需要继续优化。"
            else:
                summary = "素材已经识别完成，但存在较明显的优化空间，建议根据问题点重新出图或重生视频。"
        else:
            summary = "素材已经识别完成，可根据下方评价和修改后的提示词继续优化。"
        if issues:
            summary = f"{summary} 当前最需要处理的是：{issues[0]}"

    prompt_suggestions = _build_prompt_suggestions(
        payload=payload,
        asset_type=asset_type,
        issues=issues,
        criteria_scores=criteria_scores,
    )
    revised_prompt = _extract_first_text(
        payload,
        ("revised_prompt", "improved_prompt", "optimized_prompt", "recommended_prompt"),
    )
    if not revised_prompt:
        revised_prompt = _build_revised_prompt(
            asset_type=asset_type,
            original_prompt=original_prompt,
            prompt_suggestions=prompt_suggestions,
            criteria_scores=criteria_scores,
        )

    metadata = dict(result.metadata or {})
    metadata.update(
        {
            "source_filename": upload.filename or "",
            "source_content_type": upload.content_type or "",
            "original_prompt_provided": bool(original_prompt.strip()),
            "criteria_requested": criteria,
            "analysis_keys": sorted(payload.keys()),
            "latency_seconds": round(float(result.latency or 0.0), 3),
        }
    )

    return AssetStudioVisionReviewResponse(
        kind="vision_review",
        mode="quality_review",
        model_id=str(result.model_id or ""),
        asset_type=asset_type,
        overall_score=overall_score,
        summary=summary,
        strengths=strengths,
        issues=issues,
        prompt_suggestions=prompt_suggestions,
        revised_prompt=revised_prompt,
        criteria_scores=criteria_scores,
        metadata=metadata,
    )


def _ensure_upload_dir() -> None:
    ASSET_STUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_output_dir() -> None:
    ASSET_STUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _save_upload_file(upload: UploadFile, *, subdir: str) -> Path:
    _ensure_upload_dir()
    target_dir = ASSET_STUDIO_UPLOAD_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(upload.filename or "").suffix or ".bin"
    target_path = target_dir / f"{uuid.uuid4().hex}{suffix}"
    with target_path.open("wb") as file_obj:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            file_obj.write(chunk)
    return target_path


def _allocate_output_path(*, subdir: str, suffix: str = ".bin") -> Path:
    _ensure_output_dir()
    target_dir = ASSET_STUDIO_OUTPUT_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{uuid.uuid4().hex}{suffix}"


def _save_binary_output(binary: bytes, *, subdir: str, suffix: str = ".bin") -> Path:
    target_path = _allocate_output_path(subdir=subdir, suffix=suffix)
    target_path.write_bytes(binary)
    return target_path


def _copy_output_file(source_path: Path, *, subdir: str) -> Path:
    suffix = source_path.suffix if source_path.suffix else ".bin"
    target_path = _allocate_output_path(subdir=subdir, suffix=suffix)
    shutil.copy2(source_path, target_path)
    return target_path


def _build_output_url(target_path: Path) -> str:
    try:
        relative_path = target_path.resolve().relative_to(ASSET_STUDIO_OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成结果文件不在资产输出目录中",
        ) from exc
    return f"/api/v1/asset-studio/files/{relative_path.as_posix()}"


def _resolve_media_kind(kind: str) -> str:
    return MEDIA_KIND_BY_RESULT_KIND.get(kind, kind)


def _guess_output_suffix(*, source_ref: str, fallback_suffix: str, content_type: str | None = None) -> str:
    parsed_path = urlparse(source_ref).path if "://" in source_ref else source_ref
    suffix = Path(parsed_path).suffix.lower()
    if suffix in ALLOWED_OUTPUT_FILE_SUFFIXES:
        return suffix

    normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    guessed_suffix = mimetypes.guess_extension(normalized_content_type) if normalized_content_type else None
    if guessed_suffix:
        guessed_suffix = guessed_suffix.lower()
        if guessed_suffix in ALLOWED_OUTPUT_FILE_SUFFIXES:
            return guessed_suffix

    normalized_fallback = fallback_suffix.lower()
    if normalized_fallback in ALLOWED_OUTPUT_FILE_SUFFIXES:
        return normalized_fallback
    return ".bin"


def _download_remote_output(source_url: str, *, subdir: str, fallback_suffix: str) -> Path:
    request = Request(source_url, headers={"User-Agent": "novel-writing-agent/1.0"})
    try:
        with urlopen(request, timeout=180) as response:
            content_type = response.headers.get("Content-Type")
            suffix = _guess_output_suffix(
                source_ref=source_url,
                fallback_suffix=fallback_suffix,
                content_type=content_type,
            )
            target_path = _allocate_output_path(subdir=subdir, suffix=suffix)
            with target_path.open("wb") as file_obj:
                shutil.copyfileobj(response, file_obj)
            return target_path
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"无法拉取远端生成结果: {exc}",
        ) from exc


def _materialize_output_reference(output_ref: str, *, kind: str, subdir: str) -> Path:
    cleaned_output_ref = str(output_ref or "").strip()
    if not cleaned_output_ref:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="生成结果为空")

    fallback_suffix = DEFAULT_OUTPUT_SUFFIXES.get(kind, ".bin")
    if cleaned_output_ref.startswith(("http://", "https://")):
        return _download_remote_output(
            cleaned_output_ref,
            subdir=subdir,
            fallback_suffix=fallback_suffix,
        )

    if cleaned_output_ref.startswith("/api/v1/asset-studio/files/"):
        relative_path = cleaned_output_ref.removeprefix("/api/v1/asset-studio/files/")
        return _copy_output_file(_resolve_output_file(relative_path), subdir=subdir)

    candidate_path = Path(cleaned_output_ref)
    if candidate_path.exists() and candidate_path.is_file():
        return _copy_output_file(candidate_path, subdir=subdir)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="无法解析生成结果文件",
    )


def _collect_result_output_refs(result: UnifiedMediaResult) -> list[str]:
    result_refs: list[str] = []
    seen: set[str] = set()

    for raw_value in list(result.outputs or []):
        cleaned = str(raw_value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result_refs.append(cleaned)

    if isinstance(result.data, dict):
        for key in ("url", "image_url", "video_url", "audio_url"):
            cleaned = str(result.data.get(key) or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result_refs.append(cleaned)

    return result_refs


def _build_media_asset_from_file(*, kind: str, target_path: Path) -> AssetStudioMediaAsset:
    asset_url = _build_output_url(target_path)
    media_kind = _resolve_media_kind(kind)
    mime_type, _ = mimetypes.guess_type(target_path.name)
    fallback_mime_types = {
        "image": "image/png",
        "video": "video/mp4",
        "audio": "audio/mpeg",
    }

    return AssetStudioMediaAsset(
        asset_uuid=target_path.stem,
        media_kind=media_kind,
        storage_mode="temp_cloud",
        source_uri=asset_url,
        preview_uri=asset_url,
        download_uri=asset_url,
        file_name=target_path.name,
        mime_type=mime_type or fallback_mime_types.get(media_kind),
        file_size=target_path.stat().st_size,
        expires_at=None,
    )


def _resolve_output_file(file_path: str) -> Path:
    if not file_path.strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    resolved = (ASSET_STUDIO_OUTPUT_DIR / file_path).resolve()
    output_root = ASSET_STUDIO_OUTPUT_DIR.resolve()
    if output_root not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无效的文件路径")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    if resolved.suffix.lower() not in ALLOWED_OUTPUT_FILE_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不支持的文件类型")
    return resolved


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    try:
        return int(str(raw_value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="seed 必须是整数") from exc


def _get_runtime_duration_values(model_ids: set[str]) -> tuple[float, ...]:
    runtime_index = get_model_catalog_runtime_index()
    values: list[float] = []
    for model_id in model_ids:
        task_constraints = runtime_index.get_task_constraints(model_id)
        for raw_value in task_constraints.get("duration_values") or []:
            try:
                parsed = float(raw_value)
            except (TypeError, ValueError):
                continue
            if all(abs(existing - parsed) >= 0.001 for existing in values):
                values.append(parsed)
    return tuple(sorted(values))


def _get_aspect_ratio(width: int, height: int) -> str:
    normalized_divisor = gcd(int(width), int(height)) or 1
    return f"{int(width) // normalized_divisor}:{int(height) // normalized_divisor}"


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _get_effective_task_constraints(model_id: str) -> dict[str, Any]:
    info = media_runtime.get_model_info(model_id) or {}
    runtime_constraints = (
        info.get("catalog_task_constraints")
        if isinstance(info.get("catalog_task_constraints"), dict)
        else {}
    )
    static_constraints = (
        info.get("constraints")
        if isinstance(info.get("constraints"), dict)
        else {}
    )
    return {
        "min_width": _coerce_int(runtime_constraints.get("min_width"))
        if _coerce_int(runtime_constraints.get("min_width")) is not None
        else _coerce_int(static_constraints.get("min_width")),
        "max_width": _coerce_int(runtime_constraints.get("max_width"))
        if _coerce_int(runtime_constraints.get("max_width")) is not None
        else _coerce_int(static_constraints.get("max_width")),
        "min_height": _coerce_int(runtime_constraints.get("min_height"))
        if _coerce_int(runtime_constraints.get("min_height")) is not None
        else _coerce_int(static_constraints.get("min_height")),
        "max_height": _coerce_int(runtime_constraints.get("max_height"))
        if _coerce_int(runtime_constraints.get("max_height")) is not None
        else _coerce_int(static_constraints.get("max_height")),
        "ratio_values": _coerce_str_list(runtime_constraints.get("ratio_values"))
        or _coerce_str_list(static_constraints.get("ratios")),
    }


def _matches_dimension_constraints(
    width: int,
    height: int,
    *,
    ratio: str,
    constraints: dict[str, Any],
) -> bool:
    min_width = _coerce_int(constraints.get("min_width"))
    max_width = _coerce_int(constraints.get("max_width"))
    min_height = _coerce_int(constraints.get("min_height"))
    max_height = _coerce_int(constraints.get("max_height"))
    ratio_values = _coerce_str_list(constraints.get("ratio_values"))

    if min_width is not None and width < min_width:
        return False
    if max_width is not None and width > max_width:
        return False
    if min_height is not None and height < min_height:
        return False
    if max_height is not None and height > max_height:
        return False
    if ratio_values and ratio not in ratio_values:
        return False
    return True


def _validate_dimensions_for_models(
    model_ids: set[str],
    width: int,
    height: int,
    *,
    request_label: str,
) -> tuple[int, int]:
    normalized_width = int(width)
    normalized_height = int(height)
    if normalized_width <= 0 or normalized_height <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{request_label}尺寸必须为正整数",
        )

    ratio = _get_aspect_ratio(normalized_width, normalized_height)
    constraint_entries = [
        _get_effective_task_constraints(model_id)
        for model_id in model_ids
    ]
    if any(
        _matches_dimension_constraints(
            normalized_width,
            normalized_height,
            ratio=ratio,
            constraints=constraints,
        )
        for constraints in constraint_entries
    ):
        return normalized_width, normalized_height

    ratio_values = sorted(
        {
            item
            for constraints in constraint_entries
            for item in _coerce_str_list(constraints.get("ratio_values"))
        }
    )
    min_widths = [value for value in (_coerce_int(item.get("min_width")) for item in constraint_entries) if value is not None]
    max_widths = [value for value in (_coerce_int(item.get("max_width")) for item in constraint_entries) if value is not None]
    min_heights = [value for value in (_coerce_int(item.get("min_height")) for item in constraint_entries) if value is not None]
    max_heights = [value for value in (_coerce_int(item.get("max_height")) for item in constraint_entries) if value is not None]

    detail = f"当前资产工作台无可用模型支持 {normalized_width}x{normalized_height}（{ratio}）的{request_label}尺寸"
    if ratio_values:
        detail += f"，可用画幅比为 {' / '.join(ratio_values)}"
    if min_widths and max_widths and min_heights and max_heights:
        detail += (
            f"，当前可用尺寸范围约为 "
            f"{min(min_widths)}-{max(max_widths)} x {min(min_heights)}-{max(max_heights)}"
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
    )


def _validate_video_duration(model_id: str, duration: float) -> float:
    normalized_duration = float(duration)
    del model_id

    allowed_durations = _get_runtime_duration_values(VIDEO_MODELS)
    if not allowed_durations:
        allowed_duration_values = {
            float(value)
            for values in VIDEO_DURATION_OPTIONS.values()
            for value in values
        }
        allowed_durations = tuple(sorted(allowed_duration_values))

    if not allowed_durations or normalized_duration in allowed_durations:
        return normalized_duration

    allowed_text = " / ".join(f"{int(value)} 秒" for value in allowed_durations)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"当前资产工作台可用视频时长仅支持 {allowed_text}",
    )


def _validate_audio_duration(generation_type: str, duration: int) -> int:
    normalized_duration = int(duration)
    allowed_durations = AUDIO_DURATION_OPTIONS.get(generation_type)
    if not allowed_durations:
        return normalized_duration
    if normalized_duration in allowed_durations:
        return normalized_duration

    allowed_text = " / ".join(f"{value} 秒" for value in allowed_durations)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{generation_type} 仅支持 {allowed_text} 的时长配置",
    )


def _resolve_music_style(raw_style: str | None) -> MusicStyle:
    normalized = str(raw_style or "").strip().lower().replace("-", "_")
    return MUSIC_STYLE_ALIASES.get(normalized, MUSIC_STYLE_ALIASES.get(str(raw_style or "").strip(), MusicStyle.AMBIENT))


def _raise_for_failed_result(result: UnifiedMediaResult, *, fallback_message: str) -> None:
    if result.success:
        return

    error_message = str(result.error or fallback_message).strip() or fallback_message
    lowered = error_message.lower()
    error_code = str(result.error_code or "").strip().lower()
    bad_request_codes = {"invalid_parameter", "unsupported_task", "content_safety"}
    is_bad_request = (
        error_code in bad_request_codes
        or "safety" in lowered
        or "inspection" in lowered
        or "invalidparameter" in lowered
        or "invalid parameter" in lowered
        or "400 client error" in lowered
        or "bad request" in lowered
    )
    status_code = status.HTTP_400_BAD_REQUEST if is_bad_request else status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(status_code=status_code, detail=error_message)


def _build_response(
    *,
    kind: str,
    mode: str,
    result: UnifiedMediaResult,
    metadata: dict[str, Any] | None = None,
) -> AssetStudioGenerateResponse:
    output_refs = _collect_result_output_refs(result)
    merged_metadata = dict(result.metadata or {})
    if output_refs:
        merged_metadata.setdefault("upstream_outputs", output_refs)
    if metadata:
        merged_metadata.update(metadata)

    materialized_paths = [
        _materialize_output_reference(output_ref, kind=kind, subdir=kind)
        for output_ref in output_refs
    ]
    if not materialized_paths and result.binary is not None:
        materialized_paths = [
            _save_binary_output(
                result.binary,
                subdir=kind,
                suffix=DEFAULT_OUTPUT_SUFFIXES.get(kind, ".bin"),
            )
        ]
    if not materialized_paths:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成成功，但未返回可用的媒体结果",
        )

    assets = [_build_media_asset_from_file(kind=kind, target_path=path) for path in materialized_paths]
    merged_metadata["materialized_asset_count"] = len(assets)

    return AssetStudioGenerateResponse(
        kind=kind,
        mode=mode,
        model_id=str(result.model_id or ""),
        assets=assets,
        primary_asset=assets[0] if assets else None,
        metadata=merged_metadata,
    )


def _build_audio_response(
    *,
    mode: str,
    model_id: str,
    output_path: Path,
    metadata: dict[str, Any] | None = None,
) -> AssetStudioGenerateResponse:
    asset = _build_media_asset_from_file(kind="audio", target_path=output_path)
    return AssetStudioGenerateResponse(
        kind="audio",
        mode=mode,
        model_id=model_id,
        assets=[asset],
        primary_asset=asset,
        metadata=metadata or {},
    )

