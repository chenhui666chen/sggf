"""音效素材库的来源策略。

音效库只接受用户上传和有声书流程中由 AI 生成的素材。旧的 AI 来源标识
仍可在迁移/兼容路径中归一化，但公开素材平台来源一律拒绝写入。
"""
from __future__ import annotations

from typing import Any


ALLOWED_SFX_SOURCES = {"user_upload", "ai_generated"}
_USER_UPLOAD_ALIASES = {"user_upload", "upload", "uploaded"}
_AI_GENERATED_ALIASES = {
    "ai",
    "ai_generated",
    "generated",
    "generated_by_ai",
    "model_generated",
    "vidu",
    "vidu_ai",
}


def _normalize_source_text(source: Any) -> str:
    return str(source or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_sfx_source(source: Any) -> str:
    """返回规范化来源；来源不属于允许集合时抛出 ``ValueError``。"""
    normalized = _normalize_source_text(source)
    if normalized in _USER_UPLOAD_ALIASES:
        return "user_upload"
    if normalized in _AI_GENERATED_ALIASES:
        return "ai_generated"
    raise ValueError("SFX source must be user_upload or ai_generated")


def is_allowed_sfx_source(source: Any) -> bool:
    try:
        normalize_sfx_source(source)
    except ValueError:
        return False
    return True


def normalize_sfx_record_source(record: dict[str, Any], *, default: Any = None) -> dict[str, Any]:
    """复制记录并归一化来源，避免调用方持有的字典被隐式修改。"""
    normalized_record = dict(record)
    source = normalized_record.get("source") or default
    normalized_record["source"] = normalize_sfx_source(source)
    return normalized_record


__all__ = [
    "ALLOWED_SFX_SOURCES",
    "is_allowed_sfx_source",
    "normalize_sfx_record_source",
    "normalize_sfx_source",
]
