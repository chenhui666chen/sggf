from __future__ import annotations

import os

from core.model_resolution import normalize_model_id


DEFAULT_AUDIOBOOK_LLM_MODEL = "deepseek-flash"
AUDIOBOOK_LLM_MODEL_ENV = "AUDIOBOOK_LLM_MODEL"
AUDIOBOOK_ENABLE_SCRIPT_REVIEW_ENV = "AUDIOBOOK_ENABLE_SCRIPT_REVIEW"


def get_audiobook_llm_model() -> str:
    configured_model = os.getenv(AUDIOBOOK_LLM_MODEL_ENV, "").strip()
    normalized_model = normalize_model_id(configured_model or DEFAULT_AUDIOBOOK_LLM_MODEL)
    return normalized_model or DEFAULT_AUDIOBOOK_LLM_MODEL


def is_audiobook_script_review_enabled(default: bool = True) -> bool:
    configured = os.getenv(AUDIOBOOK_ENABLE_SCRIPT_REVIEW_ENV)
    if configured is None:
        return default
    return str(configured).strip().lower() in {"1", "true", "yes", "on"}
