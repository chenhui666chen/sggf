from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class TaskType(str, Enum):
    """统一任务类型枚举。"""

    CONCEPT_WORLD = "concept_world"
    CONCEPT_CHARACTER = "concept_character"
    CONCEPT_STORY = "concept_story"
    STRUCTURE_PLOT = "structure_plot"
    STRUCTURE_EVENTS = "structure_events"
    CONTENT_DRAFT = "content_draft"
    CONTENT_STYLE = "content_style"
    REVIEW_CHECK = "review_check"
    ITERATION_OPTIMIZE = "iteration_optimize"
    REWRITE = "rewrite"
    BOOK_ANALYSIS = "book_analysis"
    BOOK_SYNTHESIS = "book_synthesis"
    AUDIOBOOK_DIRECTOR = "audiobook_director"
    AUDIOBOOK_SCRIPT = "audiobook_script"
    AUDIOBOOK_VOICE = "audiobook_voice"
    AUDIOBOOK_SOUND = "audiobook_sound"
    AUDIOBOOK_MUSIC = "audiobook_music"
    AUDIOBOOK_REVIEW = "audiobook_review"
    ASSET_MUSIC = "asset_music"
    ASSET_SFX = "asset_sfx"
    ASSET_AUDIO = "asset_audio"


TASK_TYPE_ALIASES = {
    "default": "chapter",
    "concept_world": "concept",
    "concept_character": "character",
    "concept_story": "concept",
    "outline": "outline_expand",
    "content_draft": "chapter",
    "content_style": "dialogue",
    "review_check": "review",
    "iteration_optimize": "rewrite",
    "ai_trace": "rewrite",
    "book_analysis": "entity_extract",
    "book_synthesis": "book_synthesis",
    "chapter_summary": "summarize",
}

MODEL_ALIASES = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "qwen3_vl_plus": "qwen3-vl-plus",
    "qwen3_tts": "qwen3-tts-instruct-flash",
    "qwen3-tts-flash": "qwen3-tts-instruct-flash",
    "cosyvoice-v3-plus": "cosyvoice-v3.5-plus",
    "cosyvoice_v3_plus": "cosyvoice-v3.5-plus",
    "qwen_image_edit_plus": "qwen-image-edit-plus",
    "qwen_image_edit_max": "qwen-image-edit-max",
    "qwen_multiperson_fusion": "qwen-image-edit-plus",
    "wan_image_edit": "qwen-image-edit-plus",
    "kling-v3-image-generation": "kling/kling-v3-image-generation",
    # MiniMax TTS 模型别名（前端使用短横线格式，注册中心使用斜杠格式）
    "minimax-speech-2.8-turbo": "MiniMax/speech-2.8-turbo",
    "minimax-speech-2.8-hd": "MiniMax/speech-2.8-hd",
    "minimax/speech-2.8-turbo": "MiniMax/speech-2.8-turbo",
    "minimax/speech-2.8-hd": "MiniMax/speech-2.8-hd",
    "minimax/minimax-m3": "MiniMax/MiniMax-M3",
    "minimax-m3": "MiniMax/MiniMax-M3",
}


def _coerce_value(value: Any) -> Optional[str]:
    if value is None:
        return None

    raw = value.value if hasattr(value, "value") else value
    text = str(raw).strip()
    if not text:
        return None
    return text


def normalize_task_type(task_type: Any) -> Optional[str]:
    """将历史任务类型和值对象统一映射到当前中心可识别的任务名。"""

    text = _coerce_value(task_type)
    if text is None:
        return None

    normalized = text.strip().lower().replace("-", "_")
    return TASK_TYPE_ALIASES.get(normalized, normalized)


def normalize_model_id(model_id: Any) -> Optional[str]:
    """将历史模型别名统一映射到当前注册中心中的模型 ID。"""

    text = _coerce_value(model_id)
    if text is None:
        return None

    normalized = text.strip().lower()
    return MODEL_ALIASES.get(normalized, normalized)
