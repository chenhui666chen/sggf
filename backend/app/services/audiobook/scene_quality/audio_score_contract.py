"""离线评分输出合同；不负责发送音频或调用供应商。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Mapping

TTS_DIMENSIONS = (
    "emotion_match", "prosody_pause", "fidelity", "contamination",
    "voice_identity", "overall_naturalness",
)
AUDIOGEN_DIMENSIONS = (
    "prompt_adherence", "sound_event", "speaker_separation",
    "mix_balance", "duration_fit", "overall_quality",
)
SCORER_MODELS = (
    "qwen3.5-omni-flash", "qwen3.8-omni-flash",
    "qwen3.5-omni-plus", "doubao-seed-2-1-lite",
)

# 采信分工（2026-10-10 G1–G7 盲评复测裁定，见 docs/TTS_PROMPT_EVIDENCE_20261010.md §9.1）：
# qwen3.8-omni-flash 在情绪维度上会把提示词里的表演要求复述成"听感"，且盲评仍编造可听细节；
# 它与 ASR 逐字转写一致的部分只有保真与污染两类，故情绪/表演维度只采信豆包复核。
# 两者都不是真值：与人耳冲突时以人耳为准，评分器正向证据不得单独作为"提示词有效"的结论。
EMOTION_AUTHORITY_MODEL = "doubao-seed-2-1-lite"
VERIFIABLE_AUTHORITY_MODEL = "qwen3.8-omni-flash"
TTS_EMOTION_DIMENSIONS = (
    "emotion_match", "prosody_pause", "voice_identity", "overall_naturalness",
)
TTS_VERIFIABLE_DIMENSIONS = ("fidelity", "contamination")


def tts_dimension_authority(dimension: str) -> str:
    """返回该 TTS 维度应采信的评分模型；未知或非 TTS 维度直接报错，不做默认回落。"""
    if dimension in TTS_VERIFIABLE_DIMENSIONS:
        return VERIFIABLE_AUTHORITY_MODEL
    if dimension in TTS_EMOTION_DIMENSIONS:
        return EMOTION_AUTHORITY_MODEL
    raise ValueError(f"no TTS authority defined for dimension: {dimension}")


@dataclass(frozen=True)
class DimensionScore:
    score: int | None
    evidence: str
    confidence: float


@dataclass(frozen=True)
class AudioScore:
    kind: str
    scope: str
    dimensions: Mapping[str, DimensionScore]


@dataclass(frozen=True)
class ScorerOutcome:
    status: str
    score: AudioScore | None = None
    error_kind: str | None = None


def parse_scoring_batch(
    responses: Mapping[str, str], *, kind: str, scope: str = "single_clip"
) -> dict[str, ScorerOutcome]:
    """只解析已取得的响应；缺失和非法响应均不进入分数统计。"""
    if set(responses) - set(SCORER_MODELS):
        raise ValueError("unknown scorer model")
    outcomes = {}
    for model in SCORER_MODELS:
        if model not in responses:
            outcomes[model] = ScorerOutcome(status="recorded_error", error_kind="missing_response")
            continue
        try:
            score = parse_audio_score(responses[model], kind=kind, scope=scope)
        except ValueError:
            outcomes[model] = ScorerOutcome(status="recorded_error", error_kind="schema_invalid")
        else:
            outcomes[model] = ScorerOutcome(status="reviewed", score=score)
    return outcomes


def parse_audio_score(raw: str, *, kind: str, scope: str = "single_clip") -> AudioScore:
    """严格解析两种 rubric；空分数表示弃评，理由仍须明确。"""
    if kind not in {"tts", "audiogen"} or scope not in {"single_clip", "sequence"}:
        raise ValueError("invalid kind or scope")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid score JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"dimensions"}:
        raise ValueError("invalid score payload")
    dimensions = payload["dimensions"]
    expected = TTS_DIMENSIONS if kind == "tts" else AUDIOGEN_DIMENSIONS
    if not isinstance(dimensions, dict) or set(dimensions) != set(expected):
        raise ValueError("invalid score dimensions")
    parsed = {}
    for name in expected:
        entry = dimensions[name]
        if not isinstance(entry, dict) or set(entry) != {"score", "evidence", "confidence"}:
            raise ValueError(f"invalid {name} fields")
        score = entry["score"]
        if score is not None and (type(score) is not int or not 1 <= score <= 5):
            raise ValueError(f"invalid {name} score")
        if kind == "tts" and scope == "single_clip" and name == "voice_identity" and score is not None:
            raise ValueError("voice_identity requires a sequence")
        evidence = entry["evidence"]
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"invalid {name} evidence")
        confidence = entry["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f"invalid {name} confidence")
        parsed[name] = DimensionScore(score=score, evidence=evidence.strip(), confidence=float(confidence))
    return AudioScore(kind=kind, scope=scope, dimensions=parsed)
