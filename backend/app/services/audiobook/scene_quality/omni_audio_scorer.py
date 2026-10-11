"""离线音频评分调用器；仅显式调用时发出单次请求，不接入章节生产。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx

from .audio_score_contract import AudioScore, SCORER_MODELS, parse_audio_score
from .audio_understanding import understand_audio


@dataclass(frozen=True)
class AudioScorerResult:
    model: str
    status: str
    score: AudioScore | None = None
    usage: Mapping[str, Any] | None = None
    error_kind: str | None = None


def score_audio(
    *, audio_path: str | Path, prompt: str, model: str, kind: str,
    api_key: str, scope: str = "single_clip", client: httpx.Client | None = None,
) -> AudioScorerResult:
    """请求一次并严格校验评分；传输层复用 understand_audio，本层只管合同。"""
    if model not in SCORER_MODELS:
        raise ValueError("unknown scorer model")
    if kind not in {"tts", "audiogen"} or scope not in {"single_clip", "sequence"}:
        raise ValueError("invalid kind or scope")
    result = understand_audio(
        audio_path=audio_path, prompt=prompt, model=model, api_key=api_key, client=client,
    )
    if result.status != "ok":
        return AudioScorerResult(model, "recorded_error", usage=result.usage, error_kind=result.error_kind)
    try:
        score = parse_audio_score(result.raw, kind=kind, scope=scope)
    except ValueError:
        return AudioScorerResult(model, "recorded_error", usage=result.usage, error_kind="schema_invalid")
    return AudioScorerResult(model, "reviewed", score=score, usage=result.usage)
