"""首页资产工作台 API。"""

from __future__ import annotations

import asyncio
from math import gcd
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

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

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ASSET_STUDIO_UPLOAD_DIR = PROJECT_ROOT / "backend" / "data" / "asset_studio_uploads"
ASSET_STUDIO_OUTPUT_DIR = PROJECT_ROOT / "backend" / "data" / "asset_studio_outputs"

IMAGE_GENERATION_MODELS = {"wan2.6-t2i"}
IMAGE_EDIT_MODELS = {"qwen-image-edit-plus", "qwen-image-edit-max"}
VIDEO_MODELS = {"wan2.7-t2v", "wan2.6-t2v-fast", "wan2.7-i2v", "wan2.7-r2v", "wan2.7-videoedit"}
VISION_REVIEW_MODELS = {"qwen3-vl-plus"}
AUDIO_MODELS = {"mureka-o1-instrumental", "vidu-timing2audio"}
VIDEO_DURATION_OPTIONS: dict[str, tuple[float, ...]] = {
    "wan2.7-t2v": (3.0, 5.0, 10.0, 15.0),
    "wan2.6-t2v-fast": (3.0, 5.0),
    "wan2.7-i2v": (3.0, 5.0, 10.0),
    "wan2.7-r2v": (3.0, 5.0, 10.0, 15.0),
    "wan2.7-videoedit": (3.0, 5.0, 10.0),
}
AUDIO_DURATION_OPTIONS: dict[str, tuple[int, ...]] = {
    "music": (15, 30, 45, 60),
    "sound-effect": (3, 5, 8, 10),
}
IMAGE_FILE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_FILE_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
ALLOWED_OUTPUT_FILE_SUFFIXES = {
    *IMAGE_FILE_SUFFIXES,
    *VIDEO_FILE_SUFFIXES,
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".m4a",
}
MUSIC_STYLE_ALIASES: dict[str, MusicStyle] = {
    "流行": MusicStyle.POP,
    "pop": MusicStyle.POP,
    "摇滚": MusicStyle.ROCK,
    "rock": MusicStyle.ROCK,
    "爵士": MusicStyle.JAZZ,
    "jazz": MusicStyle.JAZZ,
    "古典": MusicStyle.CLASSICAL,
    "classical": MusicStyle.CLASSICAL,
    "国风": MusicStyle.CHINESE_STYLE,
    "chinese_style": MusicStyle.CHINESE_STYLE,
    "电子": MusicStyle.ELECTRONIC,
    "electronic": MusicStyle.ELECTRONIC,
    "氛围": MusicStyle.AMBIENT,
    "ambient": MusicStyle.AMBIENT,
    "管弦乐": MusicStyle.ORCHESTRAL,
    "orchestral": MusicStyle.ORCHESTRAL,
    "钢琴": MusicStyle.PIANO,
    "piano": MusicStyle.PIANO,
    "悬疑": MusicStyle.SUSPENSE,
    "suspense": MusicStyle.SUSPENSE,
    "浪漫": MusicStyle.ROMANTIC,
    "romantic": MusicStyle.ROMANTIC,
    "史诗": MusicStyle.EPIC,
    "epic": MusicStyle.EPIC,
    "民谣": MusicStyle.FOLK,
    "folk": MusicStyle.FOLK,
    "影视配乐": MusicStyle.SOUNDTRACK,
    "soundtrack": MusicStyle.SOUNDTRACK,
}
VISION_REVIEW_CRITERIA: dict[str, list[str]] = {
    "image": ["clarity", "composition", "lighting", "color", "style"],
    "video": ["clarity", "smoothness", "consistency", "lighting", "color"],
}
VISION_CRITERION_LABELS = {
    "clarity": "清晰度",
    "composition": "构图",
    "lighting": "光影",
    "color": "色彩",
    "style": "风格一致性",
    "smoothness": "运动流畅度",
    "consistency": "主体一致性",
}
VISION_CRITERION_ALIASES = {
    "sharpness": "clarity",
    "detail": "clarity",
    "details": "clarity",
    "framing": "composition",
    "shot_composition": "composition",
    "colour": "color",
    "colors": "color",
    "palette": "color",
    "style_consistency": "style",
    "motion": "smoothness",
    "motion_smoothness": "smoothness",
    "temporal_consistency": "consistency",
    "character_consistency": "consistency",
    "连续性": "consistency",
    "一致性": "consistency",
    "清晰度": "clarity",
    "构图": "composition",
    "光影": "lighting",
    "色彩": "color",
    "风格": "style",
    "流畅度": "smoothness",
}
VISION_CRITERION_PROMPT_HINTS = {
    "clarity": "补充主体清晰、边缘锐利、焦点准确、细节完整，避免模糊、重影和失焦。",
    "composition": "补充构图稳定、主体完整、主次分明、前中后景分层，避免画面拥挤和裁切。",
    "lighting": "补充主光源明确、明暗层次自然、曝光平衡，避免过曝、欠曝和光线混乱。",
    "color": "补充综合色彩统一、肤色自然、材质色温一致，避免偏色、脏灰和色彩断层。",
    "style": "补充风格统一、材质表达稳定、画面质感一致，避免风格跳变。",
    "smoothness": "补充动作连贯、过渡平滑、镜头稳定，避免跳帧、抖动和突兀运动。",
    "consistency": "补充主体造型一致、服饰与场景连续、角色特征稳定，避免人物漂移和细节突变。",
}
VISION_CRITERION_NEGATIVE_HINTS = {
    "clarity": "模糊、重影、失焦",
    "composition": "截肢构图、主体残缺、画面拥挤",
    "lighting": "过曝、欠曝、光线杂乱",
    "color": "偏色、脏灰、色彩断层",
    "style": "风格跳变、材质错乱",
    "smoothness": "抖动、跳帧、动作卡顿",
    "consistency": "人物漂移、造型不一致、服饰突变",
}
VISION_ISSUE_KEYWORD_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("模糊", "blur", "失焦", "重影"), VISION_CRITERION_PROMPT_HINTS["clarity"]),
    (("构图", "裁切", "主体不完整", "framing"), VISION_CRITERION_PROMPT_HINTS["composition"]),
    (("过曝", "欠曝", "曝光", "lighting"), VISION_CRITERION_PROMPT_HINTS["lighting"]),
    (("偏色", "色彩", "颜色", "colour", "color"), VISION_CRITERION_PROMPT_HINTS["color"]),
    (("风格", "材质", "style"), VISION_CRITERION_PROMPT_HINTS["style"]),
    (("抖动", "跳帧", "卡顿", "smooth"), VISION_CRITERION_PROMPT_HINTS["smoothness"]),
    (("一致性", "漂移", "角色变化", "consistency"), VISION_CRITERION_PROMPT_HINTS["consistency"]),
)


class AssetStudioGenerateResponse(BaseModel):
    kind: str
    mode: str
    model_id: str
    outputs: list[str] = Field(default_factory=list)
    primary_output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetStudioVisionCriterionScore(BaseModel):
    name: str
    label: str
    score: float | None = None
    comment: str | None = None


class AssetStudioVisionReviewResponse(BaseModel):
    kind: str
    mode: str
    model_id: str
    asset_type: str
    overall_score: float | None = None
    summary: str
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    prompt_suggestions: list[str] = Field(default_factory=list)
    revised_prompt: str
    criteria_scores: list[AssetStudioVisionCriterionScore] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    merged_metadata = dict(result.metadata or {})
    if metadata:
        merged_metadata.update(metadata)

    return AssetStudioGenerateResponse(
        kind=kind,
        mode=mode,
        model_id=str(result.model_id or ""),
        outputs=list(result.outputs or []),
        primary_output=(result.outputs[0] if result.outputs else None),
        metadata=merged_metadata,
    )


def _build_audio_response(
    *,
    mode: str,
    model_id: str,
    output_path: Path,
    metadata: dict[str, Any] | None = None,
) -> AssetStudioGenerateResponse:
    primary_output = _build_output_url(output_path)
    return AssetStudioGenerateResponse(
        kind="audio",
        mode=mode,
        model_id=model_id,
        outputs=[primary_output],
        primary_output=primary_output,
        metadata=metadata or {},
    )


@router.get("/files/{file_path:path}")
def get_asset_studio_output_file(file_path: str):
    """读取资产工作台生成文件。

    这里不加鉴权，依赖随机文件名避免可枚举访问，方便前端 <img>/<video>/<audio> 直接加载。
    """

    resolved = _resolve_output_file(file_path)
    media_type, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(path=str(resolved), media_type=media_type or "application/octet-stream", filename=resolved.name)


@router.post("/audio", response_model=AssetStudioGenerateResponse)
async def generate_audio_asset(
    prompt: str = Form(...),
    generation_type: str = Form(default="music"),
    model_id: str = Form(default="mureka-o1-instrumental"),
    duration: int = Form(default=30),
    style: str = Form(default="氛围"),
    mood: str = Form(default="calm"),
    tempo: str = Form(default="medium"),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    normalized_generation_type = str(generation_type or "").strip().lower()
    if normalized_generation_type not in {"music", "sound-effect"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的音频生成类型")

    requested_model_id = (model_id or "").strip() or (
        "mureka-o1-instrumental" if normalized_generation_type == "music" else "vidu-timing2audio"
    )
    normalized_mood = str(mood or "").strip() or "calm"
    normalized_tempo = str(tempo or "").strip() or "medium"

    if normalized_generation_type == "music":
        resolved_duration = _validate_audio_duration("music", duration)
        resolved_model_id = "mureka-o1-instrumental"
        music_generator = create_music_generator(enable_cache=True)
        music_result = await music_generator.client.generate_music(
            MusicGenerationRequest(
                prompt=cleaned_prompt,
                style=_resolve_music_style(style),
                duration=resolved_duration,
                tempo=normalized_tempo,
                mood=normalized_mood,
            )
        )
        if not music_result.success:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=music_result.error_message or "音乐生成失败",
            )

        if music_result.audio_data:
            output_path = _save_binary_output(music_result.audio_data, subdir="audio/music", suffix=".mp3")
        elif music_result.audio_file_path:
            source_path = PROJECT_ROOT / "backend" / "data" / "audio_library" / music_result.audio_file_path
            if not source_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="音乐文件已生成，但本地结果文件不存在",
                )
            output_path = _copy_output_file(source_path, subdir="audio/music")
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="音乐生成成功，但没有可返回的音频结果",
            )

        return _build_audio_response(
            mode="text_to_music",
            model_id=resolved_model_id,
            output_path=output_path,
            metadata={
                "requested_model_id": requested_model_id,
                "resolved_model_id": resolved_model_id,
                "generation_type": normalized_generation_type,
                "duration_seconds": resolved_duration,
                "style": _resolve_music_style(style).value,
                "mood": normalized_mood,
                "tempo": normalized_tempo,
                "cached": bool(music_result.cached),
            },
        )

    resolved_duration = _validate_audio_duration("sound-effect", duration)
    from app.services.audiobook.vidu_timing2audio_generator import ViduTiming2AudioGenerator
    
    requested_vidu = requested_model_id == "vidu-timing2audio"
    vidu_generator = ViduTiming2AudioGenerator() if requested_vidu else None
    vidu_available = bool(vidu_generator and vidu_generator.api_key)

    if requested_vidu and vidu_available:
        vidu_output_path = _allocate_output_path(subdir="audio/sound-effects", suffix=".mp3")
        timing_prompts = [
            {
                "from": 0.0,
                "to": float(resolved_duration),
                "prompt": cleaned_prompt
            }
        ]
        vidu_result = await asyncio.to_thread(
            vidu_generator.generate_and_download,
            timing_prompts,
            vidu_output_path,
            float(resolved_duration),
            "mp3",
            120,
        )
        if vidu_result.success and vidu_result.local_file_path:
            output_path = Path(vidu_result.local_file_path)
            return _build_audio_response(
                mode="text_to_sound_effect",
                model_id="vidu-timing2audio",
                output_path=output_path,
                metadata={
                    "requested_model_id": requested_model_id,
                    "resolved_model_id": "vidu-timing2audio",
                    "generation_type": normalized_generation_type,
                    "duration_seconds": resolved_duration,
                    "fallback_used": False,
                },
            )

        fallback_reason = vidu_result.error or "Vidu 音效生成失败，已回退到 Mureka 环境音链路。"
    elif requested_vidu:
        fallback_reason = "当前未配置 Vidu API Key，已回退到 Mureka 环境音链路。"
    else:
        fallback_reason = "音效生成失败"

    music_generator = create_music_generator(enable_cache=True)
    fallback_prompt = f"短音效或环境音，干净利落，无人声，不过度旋律化：{cleaned_prompt}"
    music_result = await music_generator.client.generate_music(
        MusicGenerationRequest(
            prompt=fallback_prompt,
            style=MusicStyle.AMBIENT,
            duration=resolved_duration,
            tempo=normalized_tempo,
            mood=normalized_mood,
        )
    )
    if not music_result.success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=music_result.error_message or fallback_reason or "音效生成失败",
        )

    if music_result.audio_data:
        output_path = _save_binary_output(music_result.audio_data, subdir="audio/sound-effects", suffix=".mp3")
    elif music_result.audio_file_path:
        source_path = PROJECT_ROOT / "backend" / "data" / "audio_library" / music_result.audio_file_path
        if not source_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="音效文件已生成，但本地结果文件不存在",
            )
        output_path = _copy_output_file(source_path, subdir="audio/sound-effects")
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="音效生成成功，但没有可返回的音频结果",
        )

    return _build_audio_response(
        mode="text_to_sound_effect",
        model_id="mureka-o1-instrumental",
        output_path=output_path,
        metadata={
            "requested_model_id": requested_model_id,
            "resolved_model_id": "mureka-o1-instrumental",
            "generation_type": normalized_generation_type,
            "duration_seconds": resolved_duration,
            "style": MusicStyle.AMBIENT.value,
            "mood": normalized_mood,
            "tempo": normalized_tempo,
            "fallback_used": requested_kling,
            "fallback_reason": fallback_reason or None,
            "cached": bool(music_result.cached),
        },
    )


@router.post("/image", response_model=AssetStudioGenerateResponse)
def generate_image_asset(
    prompt: str = Form(...),
    negative_prompt: str = Form(default=""),
    model_id: str = Form(default="wan2.6-t2i"),
    width: int = Form(default=1024),
    height: int = Form(default=1024),
    quality: str = Form(default="standard"),
    style: str | None = Form(default=None),
    seed: str | None = Form(default=None),
    strength: float = Form(default=0.72),
    reference_images: list[UploadFile] | None = File(default=None),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    saved_reference_paths = [
        _save_upload_file(upload, subdir="image")
        for upload in (reference_images or [])
        if upload and upload.filename
    ]
    seed_value = _parse_optional_int(seed)

    if saved_reference_paths:
        resolved_width, resolved_height = _validate_dimensions_for_models(
            IMAGE_EDIT_MODELS,
            width,
            height,
            request_label="图片",
        )
        normalized_model_id = normalize_model_id(model_id) or ""
        resolved_model_id = normalized_model_id if normalized_model_id in IMAGE_EDIT_MODELS else "qwen-image-edit-plus"
        result = media_runtime.edit_image(
            image_path=str(saved_reference_paths[0]),
            edit_prompt=cleaned_prompt,
            strength=max(0.0, min(float(strength), 1.0)),
            width=resolved_width,
            height=resolved_height,
            reference_images=[str(path) for path in saved_reference_paths[1:]] or None,
            seed=seed_value,
            model_id=resolved_model_id,
            use_fallback=False,
        )
        _raise_for_failed_result(result, fallback_message="参考图生成失败")
        return _build_response(
            kind="image",
            mode="reference_edit",
            result=result,
            metadata={
                "reference_count": len(saved_reference_paths),
                "workspace_note": "已自动切换到图像编辑/参考图生成链路。",
            },
        )

    if model_id in IMAGE_EDIT_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图像编辑模型需要至少上传一张参考图",
        )

    resolved_width, resolved_height = _validate_dimensions_for_models(
        IMAGE_GENERATION_MODELS,
        width,
        height,
        request_label="图片",
    )
    normalized_model_id = normalize_model_id(model_id) or ""
    resolved_model_id = normalized_model_id if normalized_model_id in IMAGE_GENERATION_MODELS else "wan2.6-t2i"
    result = media_runtime.generate_image(
        prompt=cleaned_prompt,
        negative_prompt=negative_prompt.strip(),
        width=resolved_width,
        height=resolved_height,
        seed=seed_value,
        style=(style or "").strip() or None,
        quality=quality,
        num_outputs=1,
        model_id=resolved_model_id,
        use_fallback=False,
    )
    _raise_for_failed_result(result, fallback_message="图片生成失败")
    return _build_response(kind="image", mode="text_to_image", result=result)


@router.post("/video", response_model=AssetStudioGenerateResponse)
def generate_video_asset(
    prompt: str = Form(...),
    negative_prompt: str = Form(default=""),
    model_id: str = Form(default="wan2.7-t2v"),
    width: int = Form(default=1280),
    height: int = Form(default=720),
    duration: float = Form(default=5.0),
    seed: str | None = Form(default=None),
    camera_control: str | None = Form(default=None),
    reference_image: UploadFile | None = File(default=None),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    seed_value = _parse_optional_int(seed)
    reference_path = (
        _save_upload_file(reference_image, subdir="video")
        if reference_image and reference_image.filename
        else None
    )
    resolved_model_id = model_id if model_id in VIDEO_MODELS else "wan2.7-t2v"
    if reference_path and resolved_model_id not in {"wan2.7-i2v"}:
        resolved_model_id = "wan2.7-i2v"
    if resolved_model_id == "wan2.7-i2v" and not reference_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wan2.7-i2v 需要上传首帧参考图",
        )
    resolved_width, resolved_height = _validate_dimensions_for_models(
        VIDEO_MODELS,
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, max(1.0, min(float(duration), 15.0)))

    result = media_runtime.generate_video(
        prompt=cleaned_prompt,
        negative_prompt=negative_prompt.strip(),
        duration=resolved_duration,
        width=resolved_width,
        height=resolved_height,
        seed=seed_value,
        image_path=str(reference_path) if reference_path else None,
        camera_control=(camera_control or "").strip() or None,
        model_id=resolved_model_id,
        use_fallback=False,
    )
    _raise_for_failed_result(result, fallback_message="视频生成失败")
    return _build_response(
        kind="video",
        mode="image_to_video" if reference_path else "text_to_video",
        result=result,
        metadata={"has_reference_image": bool(reference_path)},
    )


@router.post("/motion", response_model=AssetStudioGenerateResponse)
def generate_motion_asset(
    prompt: str = Form(...),
    model_id: str = Form(default="wan2.7-i2v"),
    width: int = Form(default=1280),
    height: int = Form(default=720),
    duration: float = Form(default=5.0),
    seed: str | None = Form(default=None),
    motion_control: str = Form(default="medium"),
    camera_control: str | None = Form(default=None),
    reference_image: UploadFile | None = File(default=None),
    current_user: User = Depends(get_current_user),
):
    del current_user

    if not reference_image or not reference_image.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动作控制至少需要上传一张参考图")

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动作描述不能为空")

    seed_value = _parse_optional_int(seed)
    reference_path = _save_upload_file(reference_image, subdir="motion")
    resolved_model_id = model_id if model_id in VIDEO_MODELS else "wan2.7-i2v"
    resolved_width, resolved_height = _validate_dimensions_for_models(
        VIDEO_MODELS,
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, max(1.0, min(float(duration), 15.0)))

    result = media_runtime.generate_video(
        prompt=cleaned_prompt,
        duration=resolved_duration,
        width=resolved_width,
        height=resolved_height,
        seed=seed_value,
        image_path=str(reference_path),
        camera_control=(camera_control or "").strip() or None,
        motion_control=(motion_control or "").strip() or "medium",
        model_id=resolved_model_id,
        use_fallback=False,
    )
    _raise_for_failed_result(result, fallback_message="动作控制生成失败")
    return _build_response(
        kind="motion",
        mode="image_to_video_motion",
        result=result,
        metadata={"motion_control": motion_control},
    )


@router.post("/vision-review", response_model=AssetStudioVisionReviewResponse)
def review_vision_asset(
    asset_file: UploadFile = File(...),
    original_prompt: str = Form(default=""),
    model_id: str = Form(default="qwen3-vl-plus"),
    current_user: User = Depends(get_current_user),
):
    del current_user

    resolved_model_id = (model_id or "").strip() or "qwen3-vl-plus"
    if resolved_model_id not in VISION_REVIEW_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前视觉识别入口仅支持 qwen3-vl-plus",
        )

    asset_type = _resolve_review_asset_type(asset_file)
    saved_path = _save_upload_file(asset_file, subdir="vision_review")
    criteria = VISION_REVIEW_CRITERIA.get(asset_type, [])

    if asset_type == "image":
        result = media_runtime.analyze_image(
            image_path=str(saved_path),
            analysis_type="quality",
            criteria=criteria,
            model_id=resolved_model_id,
            strategy="quality",
        )
        _raise_for_failed_result(result, fallback_message="图片识别失败")
    else:
        result = media_runtime.analyze_video(
            video_path=str(saved_path),
            analysis_type="quality",
            criteria=criteria,
            model_id=resolved_model_id,
            strategy="quality",
        )
        _raise_for_failed_result(result, fallback_message="视频识别失败")

    return _build_vision_review_response(
        asset_type=asset_type,
        original_prompt=original_prompt,
        upload=asset_file,
        result=result,
        criteria=criteria,
    )
