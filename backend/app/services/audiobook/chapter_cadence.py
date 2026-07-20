"""Chapter-level pacing decisions for audiobook segment boundaries."""

from __future__ import annotations

from typing import Any, Iterable, List


_SCENE_TRANSITION_CUES = (
    "与此同时",
    "另一边",
    "此刻",
    "不久后",
    "几天后",
    "翌日",
    "第二天",
    "片刻后",
    "转眼",
    "回到",
    "画面转向",
)
_REVEAL_CUES = (
    "真相",
    "答案",
    "原来",
    "终于明白",
    "终于知道",
    "竟然",
    "难怪",
    "秘密",
)
_ACTION_CUES = (
    "突然",
    "猛地",
    "轰然",
    "砰",
    "冲",
    "倒地",
    "爆发",
    "拔出",
    "响起",
)
_SUSPENSE_CUES = (
    "没有人",
    "脚步声",
    "别回头",
    "黑暗",
    "沉默",
    "安静下来",
    "谁也没有",
)
_STRONG_EMOTIONS = {"fearful", "angry", "surprised", "tense", "nervous", "shout"}
_AUTO_CADENCE_PROFILES = {
    "continuation",
    "speaker_turn",
    "reveal",
    "scene_transition",
    "suspense",
    "emotional_beat",
    "action_beat",
}


def apply_chapter_cadence(segments: Iterable[Any]) -> List[Any]:
    """Annotate adjacent spoken segments with post-production pause decisions.

    ``timeline_pause_after_ms`` belongs to final chapter mixing. It is deliberately
    separate from ``pause_after`` because some providers already use that field for
    an in-segment pause or an SSML break.
    """

    items = list(segments or [])
    for index, segment in enumerate(items):
        voice_params = _voice_params(segment)
        if index >= len(items) - 1:
            voice_params.pop("timeline_pause_after_ms", None)
            voice_params.pop("cadence_profile", None)
            voice_params.pop("cadence_reason", None)
            _set_voice_params(segment, voice_params)
            continue

        explicit_pause_ms = _coerce_pause_ms(voice_params.get("timeline_pause_after_ms"))
        existing_profile = str(voice_params.get("cadence_profile") or "").strip()
        if explicit_pause_ms is not None and existing_profile not in _AUTO_CADENCE_PROFILES:
            profile, reason, pause_ms = "explicit", "保留已配置章节停顿", explicit_pause_ms
        else:
            structural_pause_ms = _coerce_pause_ms(voice_params.get("pause_after_ms"))
            if structural_pause_ms is not None:
                profile, reason, pause_ms = "explicit", "保留结构化停顿标记", structural_pause_ms
            else:
                profile, reason, pause_ms = _infer_boundary_cadence(segment, items[index + 1])
                script_pause_ms = _coerce_pause_seconds_ms(voice_params.get("pause_after"))
                if script_pause_ms is not None and script_pause_ms >= pause_ms:
                    profile, reason, pause_ms = "script_pause", "保留改编剧本指定停顿", script_pause_ms
                elif script_pause_ms is not None:
                    reason = f"{reason}；保留改编剧本最小停顿{script_pause_ms}毫秒"

        voice_params["timeline_pause_after_ms"] = pause_ms
        voice_params["cadence_profile"] = profile
        voice_params["cadence_reason"] = reason
        voice_params["timeline_boundary_managed"] = True
        _set_voice_params(segment, voice_params)

    return items


def _infer_boundary_cadence(current: Any, following: Any) -> tuple[str, str, int]:
    current_text = _text(current)
    next_text = _text(following)
    boundary_text = f"{current_text} {next_text}"

    if _contains_any(next_text, _SCENE_TRANSITION_CUES):
        return "scene_transition", "转场前留白，帮助听众重建时间或场景", 1050
    if _contains_any(boundary_text, _REVEAL_CUES):
        return "reveal", "揭示信息前后留白，给听众消化关键事实", 760
    if _speaker_changed(current, following):
        return "speaker_turn", "换人前留短白，明确对白归属", 440
    if _contains_any(boundary_text, _SUSPENSE_CUES):
        return "suspense", "悬念处延长留白，保留不安感", 650
    if _strong_emotion(current) or _strong_emotion(following):
        return "emotional_beat", "强情绪后留出呼吸，避免情绪连读", 560
    if _contains_any(boundary_text, _ACTION_CUES):
        return "action_beat", "动作拍点后短停，便于听清因果", 380
    return "continuation", "同一叙事动作连续推进，保持自然呼吸", 280


def _voice_params(segment: Any) -> dict[str, Any]:
    if isinstance(segment, dict):
        value = segment.get("voice_params")
    else:
        value = getattr(segment, "voice_params", None)
    return dict(value) if isinstance(value, dict) else {}


def _set_voice_params(segment: Any, voice_params: dict[str, Any]) -> None:
    if isinstance(segment, dict):
        segment["voice_params"] = voice_params
    else:
        setattr(segment, "voice_params", voice_params)


def _text(segment: Any) -> str:
    value = segment.get("text") if isinstance(segment, dict) else getattr(segment, "text", "")
    return str(value or "").strip()


def _speaker_changed(current: Any, following: Any) -> bool:
    current_speaker = _speaker(current)
    next_speaker = _speaker(following)
    return bool(current_speaker and next_speaker and current_speaker != next_speaker)


def _speaker(segment: Any) -> str:
    value = segment.get("speaker") if isinstance(segment, dict) else getattr(segment, "speaker", "")
    return str(value or "").strip()


def _strong_emotion(segment: Any) -> bool:
    value = segment.get("emotion") if isinstance(segment, dict) else getattr(segment, "emotion", "")
    return str(value or "").strip().lower() in _STRONG_EMOTIONS


def _contains_any(value: str, cues: tuple[str, ...]) -> bool:
    return any(cue in value for cue in cues)


def _coerce_pause_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        pause_ms = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if pause_ms <= 0:
        return None
    return max(80, min(3000, pause_ms))


def _coerce_pause_seconds_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return _coerce_pause_ms(seconds * 1000)
