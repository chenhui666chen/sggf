"""Keep fixed-voice identity parameters separate from segment performance."""

from __future__ import annotations

from typing import Any, Collection, Dict, Mapping

from .tts_model_ids import model_supports_instruct_style_control


_PITCH_CONTROL_FIELDS = frozenset(
    {
        "pitch",
        "pitch_ratio",
        "pitch_semitones",
        "character_base_pitch",
    }
)

_SEGMENT_IDENTITY_OVERRIDE_FIELDS = frozenset(
    {
        "voice_description",
        "voice_design_prompt",
    }
)

_NUMERIC_SPEED_CONTROL_FIELDS = frozenset(
    {
        "speed",
        "rate",
        "character_base_speed",
    }
)


def stabilize_fixed_voice_pitch(voice_params: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Remove pitch controls before a fixed-voice request crosses a segment boundary.

    The selected voice already owns its acoustic identity. Restoring a numeric
    baseline here would still expose a provider pitch control and allow a
    downstream adapter to reinterpret it, so fixed-voice segments carry no
    pitch field at all.
    """

    stabilized = dict(voice_params or {})
    for field_name in _PITCH_CONTROL_FIELDS:
        stabilized.pop(field_name, None)
    return stabilized


def stabilize_instruct_model_speed(
    voice_params: Mapping[str, Any] | None,
    model: Any,
) -> Dict[str, Any]:
    """Keep numeric speed controls out of instruction-capable TTS requests.

    For these models, pace belongs to the semantic delivery instruction. Numeric
    speed fields would apply a second, provider-specific transform and can make
    adjacent segments sound abruptly faster or slower. Basic models retain the
    fields as their explicit fallback control surface.
    """

    stabilized = dict(voice_params or {})
    if model_supports_instruct_style_control(model):
        for field_name in _NUMERIC_SPEED_CONTROL_FIELDS:
            stabilized.pop(field_name, None)
    return stabilized


def merge_segment_performance_params(
    base_voice_params: Mapping[str, Any] | None,
    segment_voice_params: Mapping[str, Any] | None,
    *,
    ignored_fields: Collection[str] = (),
) -> Dict[str, Any]:
    """Merge segment performance controls without replacing fixed voice identity."""

    merged = dict(base_voice_params or {})
    blocked_fields = (
        _PITCH_CONTROL_FIELDS
        | _SEGMENT_IDENTITY_OVERRIDE_FIELDS
        | frozenset(ignored_fields)
    )
    for key, value in dict(segment_voice_params or {}).items():
        if value is None or key in blocked_fields:
            continue
        merged[key] = value
    return stabilize_fixed_voice_pitch(merged)


__all__ = [
    "merge_segment_performance_params",
    "stabilize_fixed_voice_pitch",
    "stabilize_instruct_model_speed",
]
