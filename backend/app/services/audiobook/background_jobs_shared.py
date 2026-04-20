from __future__ import annotations

from typing import Any, List, Optional

from app.models.audiobook import AudiobookProject
from app.services.audiobook import AudiobookEngine, set_engine_instance
from app.services.audiobook.task_support import (
    StageTracker,
    build_progress_handler as _build_progress_handler,
)


def create_background_engine(
    *,
    audiobook_project: AudiobookProject,
    chapter_ids: List[int],
    tts_model: str,
    tracker: Optional[StageTracker],
) -> AudiobookEngine:
    from core.unified_llm_client import get_llm_client

    llm_client = get_llm_client(strategy="conservative")
    progress_handler = _build_progress_handler(tracker, chapter_ids)
    engine = AudiobookEngine(
        enable_cache=audiobook_project.enable_cache,
        max_concurrent=1,
        llm_client=llm_client,
        tts_model=tts_model,
        progress_handler=progress_handler,
    )
    set_engine_instance(engine)
    return engine


def parse_duration_seconds(raw_value: Any) -> Optional[float]:
    try:
        return float(str(raw_value).replace("秒", ""))
    except Exception:
        return None


def parse_estimated_cost(raw_value: Any) -> Optional[float]:
    try:
        return float(str(raw_value).replace("¥", "").replace("$", ""))
    except Exception:
        return None


__all__ = [
    "create_background_engine",
    "parse_duration_seconds",
    "parse_estimated_cost",
]
