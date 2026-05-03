from __future__ import annotations

import logging
import re
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ._dataclasses import MusicCue, ScriptSegment, SoundEffect

logger = logging.getLogger(__name__)

NARRATOR = "\u65c1\u767d"

VALID_SEGMENT_TYPES = {"narration", "dialogue", "monologue"}
SEGMENT_TYPE_ALIASES = {
    "narrator": "narration",
    "aside": "narration",
    "dialog": "dialogue",
    "\u65c1\u767d": "narration",
    "\u5bf9\u8bdd": "dialogue",
    "\u72ec\u767d": "monologue",
}

VALID_EMOTIONS = {
    "neutral",
    "happy",
    "sad",
    "angry",
    "calm",
    "tense",
    "excited",
    "tender",
    "solemn",
    "fearful",
    "surprised",
    "disgusted",
    "mysterious",
    "epic",
    "romantic",
    "peaceful",
    "joyful",
    "nervous",
    "focused",
    "gentle",
    "serious",
    "whisper",
    "shout",
}
EMOTION_ALIASES = {
    "natural": "neutral",
    "normal": "neutral",
    "unknown": "neutral",
    "exciting": "excited",
    "surprise": "surprised",
    "scared": "fearful",
    "fear": "fearful",
    "suspense": "tense",
}

VALID_INSTRUCT_EMOTIONS = {
    "neutral",
    "fearful",
    "angry",
    "sad",
    "surprised",
    "happy",
    "disgusted",
}
INSTRUCT_EMOTION_ALIASES = {
    "calm": "neutral",
    "tender": "neutral",
    "gentle": "neutral",
    "serious": "neutral",
    "focused": "neutral",
    "excited": "happy",
    "joyful": "happy",
    "tense": "fearful",
    "nervous": "fearful",
    "scared": "fearful",
    "solemn": "sad",
    "shout": "angry",
}
NARRATOR_ALIAS_KEYS = {
    "旁白",
    "叙述",
    "叙述者",
    "讲述",
    "讲述者",
    "播讲",
    "播讲者",
    "narrator",
    "narration",
    "voiceover",
    "reader",
}

_PUNCTUATION_ONLY = re.compile(r"^[\s\W_]+$", re.UNICODE)
_THINKING_TAG_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_LEADING_THINKING_CLOSE_RE = re.compile(r"^.*?</think>", re.IGNORECASE | re.DOTALL)
_BREAK_TAG_RE = re.compile(r"<break\b[^>]*\/?\s*>(?:\s*</break>)?", re.IGNORECASE)
_XML_LIKE_TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9_-]*)\b[^<>]*>", re.IGNORECASE)
_HTML_ENTITY_TAG_RE = re.compile(r"&lt;/?[A-Za-z][A-Za-z0-9_-]*\b.*?&gt;", re.IGNORECASE)
_CJK_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])\s+(?=[。！？；：，、])")
_CJK_SPACE_BETWEEN_TEXT_RE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff。！？；：，、])\s+(?=[\u3400-\u4dbf\u4e00-\u9fff])")
_SPACE_BEFORE_BREAK_RE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff。！？；：，、])\s+(?=<break\b)", re.IGNORECASE)
_SPACE_AFTER_BREAK_RE = re.compile(r"(?<=>)\s+(?=[\u3400-\u4dbf\u4e00-\u9fff])")
_BRACKETED_STAGE_DIRECTION_RE = re.compile(r"[\[【（(]\s*([^\]】）)]{1,32})\s*[\]】）)]")
_PRESERVED_BRACKET_TAG_RE = re.compile(r"^(?:pause|break)(?:\s*:.*)?$", re.IGNORECASE)

_SUPPORTED_INLINE_TAGS = {"break"}
_EMOTION_TAG_HINTS: Dict[str, Tuple[str, str]] = {
    "laugh": ("happy", "笑声"),
    "chuckle": ("happy", "轻笑"),
    "sigh": ("sad", "叹息"),
    "cough": ("neutral", "咳嗽"),
    "sniffle": ("sad", "抽鼻/哽咽"),
    "groan": ("tense", "低声呻吟"),
    "yawn": ("calm", "打哈欠"),
    "gasp": ("surprised", "倒吸气"),
}
_STAGE_DIRECTION_HINTS: Tuple[Tuple[Tuple[str, ...], str, str], ...] = (
    (("whisper", "whispered", "whispering", "murmur", "murmured", "softly", "quietly", "低声", "轻声", "小声", "耳语", "压低声音"), "whisper", "低声/耳语"),
    (("laugh", "laughs", "laughed", "laughing", "chuckle", "chuckles", "chuckled", "chuckling", "笑", "轻笑", "笑声"), "happy", "笑声"),
    (("sigh", "sighs", "sighed", "sighing", "叹气", "叹息"), "sad", "叹息"),
    (("sob", "sobs", "sobbed", "sobbing", "cry", "cries", "crying", "哽咽", "抽泣", "哭腔", "哭"), "sad", "哽咽/哭腔"),
    (("gasp", "gasps", "gasped", "gasping", "惊呼", "倒吸气"), "surprised", "倒吸气"),
    (("shout", "shouts", "shouted", "shouting", "yell", "yelled", "yelling", "大喊", "喊", "怒吼", "吼"), "shout", "呼喊"),
    (("angry", "furious", "anger", "愤怒", "生气", "怒"), "angry", "愤怒"),
    (("pause", "beat", "silence", "停顿", "沉默"), "", "停顿"),
)
_TEXT_EMOTION_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("whisper", ("低声", "轻声", "小声", "耳语", "压低声音", "whisper", "whispered", "murmured", "softly", "quietly")),
    ("fearful", ("救命", "别过来", "不要过来", "我害怕", "好可怕", "恐惧", "惊恐", "颤抖", "terrified", "scared", "afraid", "frightened", "panic")),
    ("angry", ("滚出去", "闭嘴", "混蛋", "该死", "住手", "你疯了", "可恶", "愤怒", "怒吼", "angry", "furious", "enraged", "shouted")),
    ("sad", ("对不起", "眼泪", "泪水", "哭了", "哽咽", "抽泣", "悲伤", "心碎", "sobbing", "crying", "tears", "heartbroken")),
    ("happy", ("太好了", "真好", "哈哈", "开心", "高兴", "笑了", "delighted", "joyful", "happy", "laughed", "chuckled")),
    ("excited", ("快看", "成功了", "不可思议", "太棒了", "激动", "兴奋", "amazing", "incredible", "fantastic")),
)


def build_script_segments(
    raw_segments: Iterable[Any],
    *,
    fallback_text: str = "",
) -> List[ScriptSegment]:
    segments: List[ScriptSegment] = []
    for index, raw_segment in enumerate(raw_segments or []):
        segment = build_script_segment(raw_segment, index=index)
        if segment is not None:
            segments.append(segment)

    if not segments and str(fallback_text or "").strip():
        fallback_segment = build_script_segment(
            {
                "type": "narration",
                "text": fallback_text,
                "speaker": NARRATOR,
                "emotion": "neutral",
                "adaptation_reason": "fallback_from_invalid_llm_segments",
            },
            index=0,
        )
        if fallback_segment is not None:
            segments.append(fallback_segment)

    return segments


def build_script_segment(raw_segment: Any, *, index: int = 0) -> Optional[ScriptSegment]:
    data = sanitize_script_segment_dict(raw_segment, index=index)
    if data is None:
        return None
    return ScriptSegment(**data)


def sanitize_script_segment_dict(raw_segment: Any, *, index: int = 0) -> Optional[Dict[str, Any]]:
    if is_dataclass(raw_segment):
        raw_data = asdict(raw_segment)
    elif isinstance(raw_segment, dict):
        raw_data = dict(raw_segment)
    else:
        logger.warning("Skip invalid script segment at %s: %r", index, raw_segment)
        return None

    original_text = _clean_text(raw_data.get("original_text"))
    text = _clean_text(raw_data.get("text"))
    original_text, _, _ = _sanitize_spoken_markup(original_text)
    text, markup_note, suggested_emotion = _sanitize_spoken_markup(text)
    if _looks_like_performance_direction(text) and original_text:
        text = original_text

    if not text or _is_punctuation_only(text):
        logger.warning("Skip empty script segment at %s", index)
        return None

    segment_type = _normalize_segment_type(raw_data.get("type"))
    speaker = _normalize_speaker(raw_data.get("speaker"))
    if segment_type == "dialogue" and speaker == NARRATOR:
        segment_type = "narration"

    raw_emotion = raw_data.get("emotion")
    emotion = _normalize_emotion(raw_emotion)
    if suggested_emotion and (not str(raw_emotion or "").strip() or emotion == "neutral"):
        emotion = suggested_emotion
    elif not str(raw_emotion or "").strip() or emotion == "neutral":
        inferred_emotion = _infer_spoken_text_emotion(text)
        if inferred_emotion:
            emotion = inferred_emotion
    instruct_emotion = _normalize_instruct_emotion(raw_data.get("instruct_emotion"))
    voice_params = _sanitize_voice_params(raw_data.get("voice_params"))
    pause_before = _coerce_float(raw_data.get("pause_before"), 0.0, 0.0, 2.0)
    pause_after = _coerce_float(raw_data.get("pause_after"), 0.0, 0.0, 2.0)
    voice_params.setdefault("pause_before", pause_before)
    voice_params.setdefault("pause_after", pause_after)
    performance_notes = _clean_text(raw_data.get("performance_notes"))
    if markup_note:
        performance_notes = _append_performance_note(performance_notes, markup_note)

    return {
        "type": segment_type,
        "text": text,
        "speaker": speaker,
        "emotion": emotion,
        "performance_notes": performance_notes,
        "pause_before": pause_before,
        "pause_after": pause_after,
        "voice_params": voice_params,
        "instruct_emotion": instruct_emotion,
        "instruct_scene": _clean_text(raw_data.get("instruct_scene")),
        "instruct_role": _clean_text(raw_data.get("instruct_role")),
        "instruct_identity": _clean_text(raw_data.get("instruct_identity")),
        "sound_effects": _sanitize_sound_effects(raw_data.get("sound_effects")),
        "music_cue": _sanitize_music_cue(raw_data.get("music_cue")),
        "sound_effects_simple": _sanitize_string_list(raw_data.get("sound_effects_simple")),
        "music_cue_simple": _clean_text(raw_data.get("music_cue_simple")),
        "original_text": original_text,
        "adaptation_reason": _clean_text(raw_data.get("adaptation_reason")),
    }


def _normalize_segment_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = SEGMENT_TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in VALID_SEGMENT_TYPES else "narration"


def _normalize_emotion(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = EMOTION_ALIASES.get(normalized, normalized)
    return normalized if normalized in VALID_EMOTIONS else "neutral"


def _normalize_instruct_emotion(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = INSTRUCT_EMOTION_ALIASES.get(normalized, normalized)
    if not normalized:
        return ""
    return normalized if normalized in VALID_INSTRUCT_EMOTIONS else "neutral"


def _infer_spoken_text_emotion(text: str) -> str:
    normalized = _clean_text(text).lower()
    if not normalized:
        return ""
    compact = re.sub(r"\s+", "", normalized)
    for emotion, keywords in _TEXT_EMOTION_HINTS:
        for keyword in keywords:
            key = keyword.lower()
            if _contains_emotion_keyword(normalized, compact, key):
                return emotion
    if re.search(r"[!！]{2,}", normalized):
        return "excited"
    return ""


def _contains_emotion_keyword(normalized: str, compact: str, keyword: str) -> bool:
    if not keyword:
        return False
    if keyword.isascii():
        return bool(re.search(rf"(?<![a-z]){re.escape(keyword)}(?:s|ed|ing)?(?![a-z])", normalized))
    return keyword in compact


def _normalize_speaker(value: Any) -> str:
    normalized = _clean_text(value)
    if not normalized:
        return NARRATOR
    normalized = normalized.strip("[]()（）【】\"'“”‘’").strip().rstrip(":：").strip()
    key = re.sub(r"[\s_\-]+", "", normalized).lower()
    if key in NARRATOR_ALIAS_KEYS:
        return NARRATOR
    return normalized or NARRATOR


def _sanitize_voice_params(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    output = dict(value)
    if "rate" in output:
        output["rate"] = _coerce_float(output.get("rate"), 1.0, 0.5, 2.0)
    if "speed" in output:
        output["speed"] = _coerce_float(output.get("speed"), 1.0, 0.5, 2.0)
    if "volume" in output:
        output["volume"] = _coerce_int(output.get("volume"), 50, 0, 100)
    if "pitch" in output:
        pitch = _coerce_float(output.get("pitch"), 1.0, -100.0, 100.0)
        output["pitch"] = max(0.5, min(2.0, pitch)) if pitch <= 10 else max(0, min(100, pitch))
    if "pause_before" in output:
        output["pause_before"] = _coerce_float(output.get("pause_before"), 0.0, 0.0, 2.0)
    if "pause_after" in output:
        output["pause_after"] = _coerce_float(output.get("pause_after"), 0.0, 0.0, 2.0)
    return output


def _sanitize_sound_effects(value: Any) -> List[SoundEffect]:
    items = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    effects: List[SoundEffect] = []
    for item in items:
        effect = _sanitize_sound_effect(item)
        if effect is not None:
            effects.append(effect)
    return effects


def _sanitize_sound_effect(value: Any) -> Optional[SoundEffect]:
    if isinstance(value, SoundEffect):
        return value
    if isinstance(value, str):
        name = _clean_text(value)
        return SoundEffect(name=name) if name else None
    if not isinstance(value, dict):
        return None

    name = _clean_text(value.get("name") or value.get("effect") or value.get("id"))
    if not name:
        return None
    return SoundEffect(
        name=name,
        layer=_clean_text(value.get("layer")) or "action",
        volume=_coerce_float(value.get("volume"), 0.3, 0.0, 1.0),
        timing=_clean_text(value.get("timing")) or "trigger",
        position_3d=_clean_text(value.get("position_3d")) or None,
        duration=_optional_float(value.get("duration"), 0.0, 120.0),
        fade_in=_coerce_float(value.get("fade_in"), 0.0, 0.0, 30.0),
        fade_out=_coerce_float(value.get("fade_out"), 0.0, 0.0, 30.0),
        delay=_coerce_float(value.get("delay"), 0.0, 0.0, 60.0),
    )


def _sanitize_music_cue(value: Any) -> Optional[MusicCue]:
    if isinstance(value, MusicCue):
        return value
    if isinstance(value, str):
        style = _clean_text(value)
        return MusicCue(style=style) if style else None
    if not isinstance(value, dict):
        return None

    style = _clean_text(value.get("style") or value.get("name") or value.get("cue"))
    if not style:
        return None
    return MusicCue(
        style=style,
        volume=_coerce_float(value.get("volume"), 0.2, 0.0, 1.0),
        fade_in=_coerce_float(value.get("fade_in"), 2.0, 0.0, 30.0),
        fade_out=_coerce_float(value.get("fade_out"), 2.0, 0.0, 30.0),
        duration=_optional_float(value.get("duration"), 0.0, 600.0),
        start_time=_coerce_float(value.get("start_time"), 0.0, 0.0, 600.0),
        emotion_follow=_coerce_bool(value.get("emotion_follow", True), default=True),
    )


def _sanitize_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        value = [] if value in (None, "") else [value]
    return [item for item in (_clean_text(v) for v in value) if item]


def _looks_like_performance_direction(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    starts_like_direction = value.startswith(
        (
            "\u65c1\u767d\u5c06",
            "\u65c1\u767d\u4ee5",
            "\u65c1\u767d\u7528",
            "\u8bf7\u4ee5",
        )
    )
    has_direction_verb = any(
        token in value
        for token in (
            "\u6717\u8bfb",
            "\u8bb2\u8ff0",
            "\u53d9\u8ff0",
            "\u64ad\u62a5",
        )
    )
    return starts_like_direction and has_direction_verb


def _is_punctuation_only(text: str) -> bool:
    return bool(_PUNCTUATION_ONLY.fullmatch(str(text or "").strip()))


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sanitize_spoken_markup(text: str) -> Tuple[str, str, str]:
    value = str(text or "")
    if not value:
        return "", "", ""

    value = _HTML_ENTITY_TAG_RE.sub(lambda match: _html_unescape_minimal(match.group(0)), value)
    value = _THINKING_TAG_BLOCK_RE.sub(" ", value)
    value = _LEADING_THINKING_CLOSE_RE.sub(" ", value)
    value = re.sub(r"</?think\b[^>]*>", " ", value, flags=re.IGNORECASE)

    break_tags: List[str] = []

    def keep_break(match: re.Match[str]) -> str:
        break_tags.append(match.group(0))
        return f" __AUDIOBOOK_BREAK_TAG_{len(break_tags) - 1}__ "

    value = _BREAK_TAG_RE.sub(keep_break, value)

    removed_emotion_notes: List[str] = []
    suggested_emotion = ""

    def strip_tag(match: re.Match[str]) -> str:
        nonlocal suggested_emotion
        tag_name = match.group(1).strip().lower()
        if tag_name in _SUPPORTED_INLINE_TAGS:
            return match.group(0)
        hint = _EMOTION_TAG_HINTS.get(tag_name)
        if hint:
            emotion, note = hint
            if note not in removed_emotion_notes:
                removed_emotion_notes.append(note)
            if not suggested_emotion and emotion in VALID_EMOTIONS:
                suggested_emotion = emotion
        return " "

    value = _XML_LIKE_TAG_RE.sub(strip_tag, value)

    value, stage_notes, stage_emotion = _strip_bracketed_stage_directions(value)
    for note in stage_notes:
        if note not in removed_emotion_notes:
            removed_emotion_notes.append(note)
    if stage_emotion and not suggested_emotion:
        suggested_emotion = stage_emotion

    for index, tag in enumerate(break_tags):
        value = value.replace(f"__AUDIOBOOK_BREAK_TAG_{index}__", tag)

    value = _cleanup_spoken_markup_text(value)
    note = ""
    if removed_emotion_notes:
        note = "保留" + "、".join(removed_emotion_notes) + "的表演意图，不要读出标签文字"
    return value, note, suggested_emotion


def _strip_bracketed_stage_directions(text: str) -> Tuple[str, List[str], str]:
    notes: List[str] = []
    suggested_emotion = ""

    def replace(match: re.Match[str]) -> str:
        nonlocal suggested_emotion
        body = _clean_text(match.group(1))
        hint = _stage_direction_hint(body)
        if hint is None:
            return match.group(0)
        emotion, note = hint
        if note and note not in notes:
            notes.append(note)
        if emotion and not suggested_emotion and emotion in VALID_EMOTIONS:
            suggested_emotion = emotion
        return " "

    cleaned = _BRACKETED_STAGE_DIRECTION_RE.sub(replace, str(text or ""))
    return cleaned, notes, suggested_emotion


def _stage_direction_hint(value: str) -> Optional[Tuple[str, str]]:
    normalized = _clean_text(value).strip("[]()（）【】").strip().lower()
    if not normalized:
        return None
    if _PRESERVED_BRACKET_TAG_RE.fullmatch(normalized):
        return None
    if normalized.startswith(("sfx:", "sound:", "sound effect:", "音效:", "音效：")):
        description = normalized.split(":", 1)[-1].split("：", 1)[-1].strip()
        return "", f"音效提示：{description}" if description else "音效提示"

    compact = re.sub(r"[\s_\-·,，.。:：;；!！?？]+", "", normalized)
    for keywords, emotion, note in _STAGE_DIRECTION_HINTS:
        for keyword in keywords:
            normalized_keyword = keyword.lower()
            compact_keyword = re.sub(r"[\s_\-·,，.。:：;；!！?？]+", "", normalized_keyword)
            if normalized == normalized_keyword or compact == compact_keyword:
                return emotion, note
            if normalized_keyword.isascii():
                if re.search(rf"(?<![a-z]){re.escape(normalized_keyword)}(?:s|ed|ing)?(?![a-z])", normalized):
                    return emotion, note
            elif compact_keyword and compact_keyword in compact:
                return emotion, note
    return None


def _html_unescape_minimal(value: str) -> str:
    return (
        str(value or "")
        .replace("&lt;", "<")
        .replace("&LT;", "<")
        .replace("&gt;", ">")
        .replace("&GT;", ">")
    )


def _cleanup_spoken_markup_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = _CJK_SPACE_BEFORE_PUNCTUATION_RE.sub("", cleaned)
    cleaned = _CJK_SPACE_BETWEEN_TEXT_RE.sub("", cleaned)
    cleaned = _SPACE_BEFORE_BREAK_RE.sub("", cleaned)
    cleaned = _SPACE_AFTER_BREAK_RE.sub("", cleaned)
    return cleaned


def _append_performance_note(existing: str, addition: str) -> str:
    existing = _clean_text(existing)
    addition = _clean_text(addition)
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing}；{addition}"


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _optional_float(value: Any, minimum: float, maximum: float) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, result))


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default
