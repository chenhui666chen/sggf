"""Keep fixed audiobook voices stable across segment-level performance edits."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping

from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    normalize_audiobook_tts_model,
)


VOICE_IDENTITY_POLICY_VERSION = 10

FIXED_VOICE_PERFORMANCE_BOUNDARY_PROMPT = """**固定音色表演边界（硬性要求）**
- voice_id 一经选定，说话人身份、性别、年龄感、基础声线、口音和辨识度不可改变。
- performance_notes 与 instruct_* 只能描述当前片段的情绪、语气、语速、音量、语势、强弱、停顿、断句、重读、呼吸和句尾处理。
- 片段级不得要求改变音高、声线或音色质感；不得要求童声、老人声、男声、女声、换声或变声。
- instruct_role / instruct_identity 只能表达叙事职能和角色关系，不得编码人口学或音色特征。
- 仅当原文或用户明确给出生病、感冒、受伤、重伤、缺水、失血或哭喊后等临时状态时，才允许写成“因相应状态，仅在原音色基础上轻微、短暂表现沙哑”；不得把沙哑作为常驻音色。
"""

_IDENTITY_TRANSFORM_TAG_TERMS = (
    "男声",
    "女声",
    "男性",
    "女性",
    "男人",
    "女人",
    "童声",
    "儿童",
    "小孩",
    "男孩",
    "女孩",
    "少年",
    "少女",
    "少年音",
    "少女音",
    "老人",
    "老者",
    "老人声",
    "老年",
    "中年",
    "青年",
    "年龄感",
    "大叔音",
    "御姐音",
    "萝莉音",
    "正太音",
    "御姐声",
    "萝莉声",
    "正太声",
    "大叔声",
    "奶音",
    "奶声",
    "娃娃音",
    "娃娃声",
    "宝宝音",
    "宝宝声",
    "夹子音",
    "夹子声",
    "假声",
    "伪声",
    "老奶奶声音",
    "老爷爷声音",
    "老奶奶声",
    "老爷爷声",
    "奶奶音",
    "爷爷音",
    "变声",
    "换声",
    "音色",
    "声线",
    "苍老",
    "低沉",
    "高亢",
    "甜美",
    "稚嫩",
    "沙哑",
    "嘶哑",
    "烟嗓",
    "粗粝",
    "粗哑",
    "干涩",
    "破锣嗓",
    "磁性",
    "浑厚",
    "空灵",
    "male voice",
    "female voice",
    "child voice",
    "children voice",
    "girl voice",
    "boy voice",
    "baby voice",
    "kid voice",
    "granny voice",
    "grandpa voice",
    "girl",
    "boy",
    "baby",
    "kid",
    "granny",
    "grandpa",
    "young voice",
    "middle-aged voice",
    "old voice",
    "elderly voice",
    "voice change",
    "voice swap",
    "change voice",
    "timbre",
    "voice identity",
    "voiceprint",
    "deep voice",
    "magnetic voice",
    "airy voice",
    "breathy voice",
    "airy timbre",
    "falsetto",
    "hoarse",
    "raspy",
    "raspy voice",
    "husky",
    "husky voice",
    "gravelly",
    "gravelly voice",
)
_TEMPORARY_TEXTURE_TAG_TERMS = (
    "沙哑",
    "嘶哑",
    "烟嗓",
    "粗粝",
    "粗哑",
    "干涩",
    "破锣嗓",
    "hoarse",
    "raspy",
    "raspy voice",
    "husky",
    "husky voice",
    "gravelly",
    "gravelly voice",
)
_TEMPORARY_TEXTURE_STATE_TERMS = (
    "生病",
    "病中",
    "感冒",
    "发烧",
    "重伤",
    "受伤",
    "哭喊后",
    "缺水",
    "失血",
    "喉咙受损",
    "illness",
    "sick",
    "a cold",
    "common cold",
    "injury",
    "injured",
    "after shouting",
    "dehydration",
)
_TEMPORARY_TEXTURE_STATE_LABELS = {
    "illness": "生病",
    "sick": "生病",
    "a cold": "感冒",
    "common cold": "感冒",
    "injury": "受伤",
    "injured": "受伤",
    "after shouting": "哭喊后",
    "dehydration": "缺水",
}
_DIRECTOR_IDENTITY_TERMS = (
    *_IDENTITY_TRANSFORM_TAG_TERMS,
    "低沉",
    "高亢",
    "甜美",
    "稚嫩",
)
_EXPLICIT_VOICE_IDENTITY_TERMS = (
    "童声",
    "少年音",
    "少女音",
    "老人声",
    "大叔音",
    "御姐音",
    "萝莉音",
    "正太音",
    "御姐声",
    "萝莉声",
    "正太声",
    "大叔声",
    "奶音",
    "奶声",
    "娃娃音",
    "娃娃声",
    "宝宝音",
    "宝宝声",
    "夹子音",
    "夹子声",
    "假声",
    "伪声",
    "老奶奶声音",
    "老爷爷声音",
    "老奶奶声",
    "老爷爷声",
    "奶奶音",
    "爷爷音",
    "变声",
    "换声",
    "male voice",
    "female voice",
    "child voice",
    "children voice",
    "girl voice",
    "boy voice",
    "baby voice",
    "kid voice",
    "granny voice",
    "grandpa voice",
    "young voice",
    "middle-aged voice",
    "old voice",
    "elderly voice",
    "voice change",
    "voice swap",
    "change voice",
    "deep voice",
    "magnetic voice",
    "airy voice",
    "breathy voice",
    "airy timbre",
    "falsetto",
)
_VOICE_IDENTITY_DESCRIPTOR_TERMS = (
    "男声",
    "女声",
    "男性",
    "女性",
    "男人",
    "女人",
    "儿童",
    "小孩",
    "幼童",
    "幼儿",
    "男孩",
    "女孩",
    "少年",
    "少女",
    "年长",
    "年幼",
    "年轻",
    "年轻男子",
    "年轻女子",
    "成熟男性",
    "成熟女性",
    "男性化",
    "女性化",
    "老人",
    "老者",
    "老太太",
    "老头",
    "老翁",
    "老年",
    "中年",
    "青年",
    "年龄感",
    "萝莉",
    "御姐",
    "正太",
    "大叔",
    "苍老",
    "磁性",
    "浑厚",
    "空灵",
    "稚嫩",
    "甜美",
    "male",
    "female",
    "child",
    "young",
    "middle-aged",
    "old",
    "elderly",
    "girl",
    "boy",
    "baby",
    "kid",
    "granny",
    "grandpa",
)
_VOICE_CONTROL_CONTEXT_TERMS = (
    "声音",
    "声线",
    "音色",
    "嗓音",
    "嗓子",
    "发声",
    "voice",
    "男声",
    "女声",
    "模仿",
    "模拟",
    "改成",
    "变成",
    "换成",
    "使用",
    "采用",
    "听起来像",
    "voice",
    "timbre",
    "voiceprint",
    "imitate",
    "sound like",
    "change into",
    "switch to",
    "use a",
)
_VOICE_IDENTITY_CHANGE_PATTERNS = (
    re.compile(
        r"(?:基础)?(?:音高|音调).{0,6}"
        r"(?:降低|下降|下调|调低|升高|提高|上升|上调|调高|改变|调整|更低|更高)"
    ),
    re.compile(
        r"(?:音高|音调|声调).{0,4}"
        r"(?:偏低|偏高|更低|更高|降低|升高|下调|上调|调低|调高)"
    ),
    re.compile(
        r"(?:降低|下降|下调|调低|升高|提高|上升|上调|调高|改变|调整).{0,6}"
        r"(?:基础)?(?:音高|音调)"
    ),
    re.compile(
        r"(?:声音|声线|嗓音|嗓子).{0,6}"
        r"(?:调低|调高|降低|升高|提高|下调|上调).{0,4}"
        r"[零〇一二两三四五六七八九十\d]+(?:个)?(?:半音|全音|度|八度)"
    ),
    re.compile(
        r"(?:声音|声线|嗓音|嗓子).{0,4}(?:变得|变为|变成).{0,3}(?:很|更|偏)?[低高]"
    ),
    re.compile(
        r"(?:用|以|采用)?(?:低|高|上|下)?[零〇一二两三四五六七八九十\d]+"
        r"(?:个)?(?:半音|全音|度|八度).{0,5}(?:发声|声音|声线|音高|音调|声调)"
    ),
    re.compile(
        r"(?:改成|变成|换成|切换成|使用|采用|用|以).{0,12}"
        r"(?:口音|腔调|方言)"
    ),
    re.compile(
        r"(?:模仿|模拟).{0,16}(?:声音|声线|嗓音|音色|发声|说话方式)"
    ),
    re.compile(
        r"(?:声音|声线|嗓音|音色).{0,6}(?:更|偏|很|非常)?"
        r"(?:成熟|尖细|尖锐|清亮|醇厚|圆润|鼻音)"
    ),
    re.compile(
        r"(?:使用|采用|改成|变成|换成).{0,8}"
        r"(?:成熟|尖细|尖锐|清亮|醇厚|圆润|鼻音).{0,4}"
        r"(?:声音|声线|嗓音|音色)"
    ),
    re.compile(
        r"\bpitch\b.{0,12}\b(?:lower|higher|down|up|shift|change|semitones?)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:lower|raise|shift|change)\b.{0,12}\bpitch\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:switch(?: to)?|change(?: to)?|use|adopt)\b.{0,20}"
        r"\b(?:accent|dialect)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:imitate|mimic)\b.{0,24}"
        r"\b(?:voice|speaker|person|celebrity)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:voice|timbre)\b.{0,12}\b(?:nasal|thin|bright|mature)\b",
        flags=re.IGNORECASE,
    ),
)
_SSML_IDENTITY_ATTRIBUTE_RE = re.compile(
    r"\s+(?:pitch|range|contour|vocal[-_]tract[-_]length|voice|speaker|timbre|"
    r"voice[-_]?(?:id|name)|style)\s*="
    r"\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    flags=re.IGNORECASE,
)
_SSML_IDENTITY_WRAPPER_RE = re.compile(
    r"</?(?:voice|speaker)\b[^>]*>",
    flags=re.IGNORECASE,
)
_SSML_PITCH_ELEMENT_RE = re.compile(
    r"<pitch\b[^>]*>(.*?)</pitch\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_TEMPORARY_STATE_CARRY_PREFIXES = ("因", "因为", "由于")
_TEMPORARY_STATE_CARRY_SUFFIXES = ("后", "时", "中", "期间")
_VALID_SEGMENT_TYPES = {
    "narration",
    "dialogue",
    "monologue",
    "inner_monologue",
}
_DELIVERY_PLAN_ENUM_FIELDS = {
    "segment_type": _VALID_SEGMENT_TYPES,
    "delivery_mode": {
        "narration",
        "dialogue",
        "monologue",
        "inner_monologue",
        "sob",
        "whisper",
        "shout",
        "laugh",
    },
    "pace": {"slow", "medium", "fast"},
    "pitch": {"lower", "neutral", "higher"},
    "intensity": {"low", "medium", "high"},
    "pause_profile": {"balanced", "natural", "dramatic"},
    "ending_style": {"lengthened", "clipped"},
    "cadence_profile": {
        "continuation",
        "speaker_turn",
        "reveal",
        "scene_transition",
        "suspense",
        "emotional_beat",
        "action_beat",
        "explicit",
        "script_pause",
        "calm",
    },
}
_PERFORMANCE_CLAUSE_SPLIT_RE = re.compile(r"[，,；;。！？!?\n]+")
_PERFORMANCE_TEXT_REPLACEMENTS = (
    ("低沉压抑", "压低语气并保持压抑"),
    ("声调更低更沉", "收紧语势并保持沉重"),
    ("声调更低", "收紧语势"),
    ("声调低沉", "收紧语势并保持沉重"),
    ("声调更高", "提高情绪强度"),
    ("声线更低更沉", "收紧语势并保持沉重"),
    ("声线更低", "收紧语势"),
    ("语气低沉", "语气压低"),
    ("压低声线", "压低语气"),
    ("降低声线", "降低语气"),
    ("提高声线", "提高语气"),
    ("抬高声线", "提高语气"),
    ("声音低沉", "语气压低"),
    ("声线低沉", "语气压低"),
    ("低沉的声音", "压低语气"),
    ("音色低沉", "收紧语势并保持沉重"),
    ("音调低沉", "收紧语势并保持沉重"),
    ("音调高亢", "提高情绪强度"),
    ("低沉", "压低语气"),
    ("高亢", "提高情绪强度"),
)
_EMPTY_VOICE_FRAGMENT_TERMS = (
    "声音",
    "声线",
    "音色",
    "嗓音",
    "嗓子",
    "发声",
    "voice",
    "永久",
    "长期",
    "始终",
    "明显",
    "很",
    "非常",
    "并",
    "且",
    "而",
    "用",
    "使用",
    "采用",
    "说话",
    "说",
    "地",
)


def is_voice_design_model(model: Any) -> bool:
    return (
        normalize_audiobook_tts_model(model, default=str(model or ""))
        == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    )


def is_voice_design_creation_request(
    model: Any,
    voice_params: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether a MiMo Voice Design call is creating a new voice recipe.

    A saved ``mimo_design`` asset is an identity baseline. Once an asset id is
    present, the request is a fixed-voice synthesis request and segment text
    may only contribute performance direction. Calls without an asset remain
    the explicit voice-design/preview path.
    """

    if not is_voice_design_model(model):
        return False
    params = voice_params if isinstance(voice_params, Mapping) else {}
    if str(params.get("mimo_voice_asset_id") or "").strip():
        return False
    for field_name in ("voice_id", "speaker"):
        value = str(params.get(field_name) or "").strip().lower()
        if value.startswith("mimo_design:"):
            return False
    return True


def is_current_voice_identity_snapshot(
    snapshot: Any,
    *,
    model: Any = None,
    voice_id: Any = None,
) -> bool:
    if not isinstance(snapshot, Mapping):
        return False
    if snapshot.get("voice_identity_policy_version") != VOICE_IDENTITY_POLICY_VERSION:
        return False
    expected_model = normalize_audiobook_tts_model(model, default=str(model or ""))
    if expected_model:
        snapshot_model = normalize_audiobook_tts_model(
            snapshot.get("model"),
            default=str(snapshot.get("model") or ""),
        )
        if snapshot_model != expected_model:
            return False
    expected_voice = str(voice_id or "").strip()
    if expected_voice and str(snapshot.get("voice_id") or "").strip() != expected_voice:
        return False
    return True


def _contains_any_term(value: Any, terms: Iterable[str]) -> bool:
    return any(_contains_term(value, term) for term in terms)


def _first_matching_term(value: Any, terms: Iterable[str]) -> str:
    return next((str(term) for term in terms if _contains_term(value, term)), "")


def _contains_term(value: Any, term: Any) -> bool:
    text = str(value or "")
    candidate = str(term or "")
    if not text or not candidate:
        return False
    if re.search(r"[A-Za-z]", candidate):
        return bool(
            re.search(
                rf"(?<![A-Za-z]){re.escape(candidate)}(?![A-Za-z])",
                text,
                flags=re.IGNORECASE,
            )
        )
    return candidate.casefold() in text.casefold()


def _replace_term(value: str, term: str, replacement: str = "") -> str:
    if re.search(r"[A-Za-z]", term):
        return re.sub(
            rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])",
            replacement,
            value,
            flags=re.IGNORECASE,
        )
    return value.replace(term, replacement)


def _requests_voice_identity_change(
    value: Any,
    *,
    preserve_scene_demographics: bool = False,
) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _VOICE_IDENTITY_CHANGE_PATTERNS):
        return True
    if _contains_any_term(text, _EXPLICIT_VOICE_IDENTITY_TERMS):
        return True
    has_identity_descriptor = _contains_any_term(
        text,
        _VOICE_IDENTITY_DESCRIPTOR_TERMS,
    )
    if has_identity_descriptor and not preserve_scene_demographics:
        return True
    return has_identity_descriptor and _contains_any_term(text, _VOICE_CONTROL_CONTEXT_TERMS)


def _is_allowed_temporary_texture_tag(tag: str) -> bool:
    return (
        _contains_any_term(tag, _TEMPORARY_TEXTURE_TAG_TERMS)
        and _contains_any_term(tag, _TEMPORARY_TEXTURE_STATE_TERMS)
        and not any(
            str(term).casefold() in tag.casefold()
            for term in _IDENTITY_TRANSFORM_TAG_TERMS
            if term not in _TEMPORARY_TEXTURE_TAG_TERMS
        )
    )


def filter_fixed_voice_identity_tags(
    values: Iterable[Any],
) -> tuple[List[str], List[str]]:
    """Remove strong tags that can alter a fixed speaker's voice identity."""

    safe_tags: List[str] = []
    blocked_tags: List[str] = []
    for value in values:
        tag = str(value or "").strip()
        if not tag:
            continue
        changes_identity = _contains_any_term(
            tag,
            _IDENTITY_TRANSFORM_TAG_TERMS,
        ) or _requests_voice_identity_change(tag)
        target = blocked_tags if changes_identity else safe_tags
        if tag not in target:
            target.append(tag)
    return safe_tags, blocked_tags


def _unique_nonempty(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _contains_temporary_texture_state(value: str) -> bool:
    return _contains_any_term(value, _TEMPORARY_TEXTURE_STATE_TERMS)


def _normalize_temporary_hoarseness(clause: str, fallback_state: str = "") -> str:
    state = _first_matching_term(clause, _TEMPORARY_TEXTURE_STATE_TERMS) or fallback_state or "特殊状态"
    state = _TEMPORARY_TEXTURE_STATE_LABELS.get(state.casefold(), state)
    canonical = f"因{state}，仅在原音色基础上轻微、短暂表现沙哑"

    # Keep pace, emphasis and vocal-effort guidance from the same clause. Only
    # the temporary texture itself is normalized to the fixed-voice wording.
    performance = _remove_unqualified_hoarseness(clause)
    for state_term in _TEMPORARY_TEXTURE_STATE_TERMS:
        performance = _replace_term(performance, state_term)
    for connector in (
        "because of",
        "due to",
        "after",
        "while",
        "but",
        "and",
        "an",
        "a",
        "the",
        "因为",
        "由于",
        "因",
        "而",
        "后",
        "时",
        "中",
        "期间",
        "轻微",
        "短暂",
        "轻度",
    ):
        performance = _replace_term(performance, connector)
    performance = performance.strip(" ，,；;。！？!?、的地")
    return "，".join(_unique_nonempty((canonical, performance)))


def _remove_unqualified_hoarseness(clause: str) -> str:
    cleaned = clause
    for source, target in _PERFORMANCE_TEXT_REPLACEMENTS:
        cleaned = cleaned.replace(source, target)
    for term in _TEMPORARY_TEXTURE_TAG_TERMS:
        cleaned = _replace_term(cleaned, term)
    for term in _EMPTY_VOICE_FRAGMENT_TERMS:
        cleaned = cleaned.replace(term, "")
    return cleaned.strip(" ，,；;。！？!?、")


def _can_carry_temporary_state(clause: str, state: str) -> bool:
    text = str(clause or "").strip()
    if not text or not state:
        return False
    lowered = text.casefold()
    if re.search(r"[A-Za-z]", state):
        return bool(
            re.search(r"\b(because(?: of)?|due to|after|while)\b", lowered)
        ) and len(text) <= 48
    return (
        len(text) <= 20
        and (
            text == state
            or text.startswith(_TEMPORARY_STATE_CARRY_PREFIXES)
            or text.endswith(_TEMPORARY_STATE_CARRY_SUFFIXES)
        )
    )


def _is_pure_temporary_state_clause(clause: str, state: str) -> bool:
    remainder = str(clause or "")
    if state:
        remainder = _replace_term(remainder, state)
    for connector in (
        "because of",
        "due to",
        "after",
        "while",
        "but",
        "and",
        "an",
        "a",
        "the",
        "因为",
        "由于",
        "因",
        "而",
        "后",
        "时",
        "中",
        "期间",
    ):
        remainder = _replace_term(remainder, connector)
    return not remainder.strip(" ，,；;。！？!?")


def stable_prompt_speaker(value: Any, *, segment_type: Any = None) -> str:
    speaker = str(value or "").strip()
    normalized_type = str(segment_type or "").strip().lower()
    if normalized_type == "narration" or speaker.casefold() == "narrator" or speaker == "旁白":
        return "旁白"
    if _contains_any_term(speaker, _IDENTITY_TRANSFORM_TAG_TERMS):
        return "当前角色"
    return speaker


def sanitize_fixed_voice_performance_text(
    value: Any,
    *,
    preserve_scene_demographics: bool = False,
) -> tuple[str, List[str]]:
    """Keep delivery instructions while removing fixed-voice identity changes."""

    source = " ".join(str(value or "").split()).strip()
    if not source:
        return "", []

    safe_clauses: List[str] = []
    blocked_clauses: List[str] = []
    pending_temporary_state = ""
    for raw_clause in _PERFORMANCE_CLAUSE_SPLIT_RE.split(source):
        clause = raw_clause.strip()
        if not clause:
            continue
        carried_state = pending_temporary_state
        pending_temporary_state = ""
        clause_state = _first_matching_term(clause, _TEMPORARY_TEXTURE_STATE_TERMS)
        normalized_clause = clause
        if not preserve_scene_demographics:
            for original, replacement in _PERFORMANCE_TEXT_REPLACEMENTS:
                normalized_clause = _replace_term(
                    normalized_clause,
                    original,
                    replacement,
                )

        has_hoarseness = _contains_any_term(normalized_clause, _TEMPORARY_TEXTURE_TAG_TERMS)
        authorized_state = clause_state or carried_state
        already_scoped_to_original_voice = (
            has_hoarseness
            and bool(authorized_state)
            and "原音色基础" in normalized_clause
            and any(term in normalized_clause for term in ("轻微", "短暂", "轻度"))
        )
        if already_scoped_to_original_voice:
            if carried_state and not clause_state:
                state_label = _TEMPORARY_TEXTURE_STATE_LABELS.get(
                    carried_state.casefold(),
                    carried_state,
                )
                normalized_clause = f"因{state_label}，{normalized_clause}"
            if normalized_clause not in safe_clauses:
                safe_clauses.append(normalized_clause)
            continue
        has_other_identity_change = _requests_voice_identity_change(
            normalized_clause,
            preserve_scene_demographics=preserve_scene_demographics,
        )
        if has_other_identity_change:
            blocked_clauses.append(clause)
            continue
        if has_hoarseness:
            if authorized_state:
                normalized_clause = _normalize_temporary_hoarseness(
                    normalized_clause,
                    fallback_state=authorized_state,
                )
            else:
                blocked_clauses.append(clause)
                if "原音色基础" in normalized_clause:
                    continue
                normalized_clause = _remove_unqualified_hoarseness(normalized_clause)
                if not normalized_clause:
                    continue
        elif clause_state and _can_carry_temporary_state(clause, clause_state):
            pending_temporary_state = clause_state
            if _is_pure_temporary_state_clause(clause, clause_state):
                continue

        normalized_clause = normalized_clause.strip(" ，,；;。！？!?、")
        if normalized_clause and normalized_clause not in safe_clauses:
            safe_clauses.append(normalized_clause)

    return "，".join(safe_clauses), _unique_nonempty(blocked_clauses)


def sanitize_fixed_voice_scene_text(value: Any) -> tuple[str, List[str]]:
    """Preserve demographic scene context while rejecting voice-change commands."""

    return sanitize_fixed_voice_performance_text(
        value,
        preserve_scene_demographics=True,
    )


def sanitize_fixed_voice_ssml_text(value: Any) -> tuple[str, List[str]]:
    """Remove SSML controls that can switch a fixed speaker or its pitch."""

    source = str(value or "")
    if not source or "<" not in source:
        return source, []
    blocked: List[str] = []

    def _remove_attribute(match: re.Match[str]) -> str:
        blocked.append(match.group(0).strip())
        return ""

    cleaned = _SSML_IDENTITY_ATTRIBUTE_RE.sub(_remove_attribute, source)

    def _remove_element(match: re.Match[str]) -> str:
        blocked.append(match.group(0).strip())
        return match.group(1) if match.lastindex else ""

    cleaned = _SSML_IDENTITY_WRAPPER_RE.sub(_remove_element, cleaned)
    cleaned = _SSML_PITCH_ELEMENT_RE.sub(_remove_element, cleaned)
    return cleaned, _unique_nonempty(blocked)


def extract_fixed_voice_temporary_hoarseness_instructions(value: Any) -> List[str]:
    """Return canonical temporary-hoarseness clauses safe for natural-language control."""

    cleaned, _ = sanitize_fixed_voice_performance_text(value)
    if not cleaned or "仅在原音色基础上" not in cleaned or "沙哑" not in cleaned:
        return []

    instructions: List[str] = []
    for state in _TEMPORARY_TEXTURE_STATE_TERMS:
        canonical = _normalize_temporary_hoarseness("", fallback_state=state)
        if canonical in cleaned and canonical not in instructions:
            instructions.append(canonical)
    return instructions


def _temporary_hoarseness_instructions_from_tags(values: Iterable[Any]) -> List[str]:
    instructions: List[str] = []
    for value in values:
        tag = str(value or "").strip()
        if not tag or not _is_allowed_temporary_texture_tag(tag):
            continue
        for instruction in extract_fixed_voice_temporary_hoarseness_instructions(tag):
            if instruction not in instructions:
                instructions.append(instruction)
    return instructions


def _append_performance_instructions(
    params: Dict[str, Any],
    instructions: Iterable[str],
) -> None:
    pending = _unique_nonempty(instructions)
    if not pending:
        return

    plan = params.get("delivery_plan")
    plan = plan if isinstance(plan, Mapping) else {}
    existing_sources = "；".join(
        _unique_nonempty(
            (
                params.get("performance_notes"),
                params.get("instructions"),
                params.get("instruction"),
                plan.get("performance_notes"),
                plan.get("style_instruction"),
                plan.get("director_guidance"),
            )
        )
    )
    additions = [instruction for instruction in pending if instruction not in existing_sources]
    if not additions:
        return

    existing_notes = str(params.get("performance_notes") or "").strip().rstrip("，,；;。 ")
    params["performance_notes"] = "，".join(
        _unique_nonempty((existing_notes, *additions))
    )


def stable_director_identity(requested_identity: Any) -> str:
    identity = str(requested_identity or "").strip()
    if _contains_any_term(identity, _DIRECTOR_IDENTITY_TERMS):
        return ""
    return identity


def stable_director_role(
    *,
    segment_type: Any,
    segment_speaker: Any,
    requested_role: Any,
) -> str:
    """Keep narrator identity stable while retaining non-voice role context."""

    normalized_type = str(segment_type or "").strip().lower()
    speaker = str(segment_speaker or "").strip()
    role = str(requested_role or "").strip()
    is_narration = normalized_type == "narration" or speaker in {
        "旁白",
        "narrator",
        "Narrator",
    }
    if not role or _contains_any_term(role, _DIRECTOR_IDENTITY_TERMS):
        return "有声书旁白" if is_narration else ""
    if is_narration and role in {"旁白", "narrator", "Narrator"}:
        return "有声书旁白"
    return role


def sanitize_fixed_voice_prompt_params(
    voice_params: Mapping[str, Any],
) -> tuple[Dict[str, Any], List[str]]:
    """Sanitize every free-text surface before compiling a fixed-voice prompt."""

    params: Dict[str, Any] = dict(voice_params or {})
    blocked: List[str] = []
    temporary_hoarseness_instructions: List[str] = []

    if "segment_type" in params:
        raw_segment_type = str(params.get("segment_type") or "").strip()
        normalized_segment_type = raw_segment_type.lower()
        if normalized_segment_type in _VALID_SEGMENT_TYPES:
            params["segment_type"] = normalized_segment_type
        else:
            if raw_segment_type:
                blocked.append(raw_segment_type)
            params.pop("segment_type", None)

    for field_name in (
        "performance_notes",
        "instructions",
        "instruction",
        "instruct_emotion",
        "emotion",
    ):
        if field_name not in params:
            continue
        cleaned, removed = sanitize_fixed_voice_performance_text(params.get(field_name))
        blocked.extend(removed)
        if cleaned:
            params[field_name] = cleaned
        else:
            params.pop(field_name, None)

    if "instruct_scene" in params:
        cleaned_scene, removed_scene = sanitize_fixed_voice_scene_text(
            params.get("instruct_scene")
        )
        blocked.extend(removed_scene)
        if cleaned_scene:
            params["instruct_scene"] = cleaned_scene
        else:
            params.pop("instruct_scene", None)

    original_speaker = str(params.get("segment_speaker") or "").strip()
    prompt_speaker = stable_prompt_speaker(
        original_speaker,
        segment_type=params.get("segment_type"),
    )
    if prompt_speaker:
        params["segment_speaker"] = prompt_speaker
    else:
        params.pop("segment_speaker", None)
    if original_speaker and prompt_speaker != original_speaker:
        blocked.append(original_speaker)

    for field_name in ("style_tags", "inline_audio_tags"):
        values = params.get(field_name)
        if not isinstance(values, (list, tuple, set, str)):
            continue
        normalized_values = [values] if isinstance(values, str) else values
        temporary_hoarseness_instructions.extend(
            _temporary_hoarseness_instructions_from_tags(normalized_values)
        )
        safe_tags, blocked_tags = filter_fixed_voice_identity_tags(normalized_values)
        blocked.extend(blocked_tags)
        if safe_tags:
            params[field_name] = safe_tags
        else:
            params.pop(field_name, None)

    params["instruct_role"] = stable_director_role(
        segment_type=params.get("segment_type"),
        segment_speaker=params.get("segment_speaker"),
        requested_role=params.get("instruct_role"),
    )
    if not params["instruct_role"]:
        params.pop("instruct_role", None)
    identity = stable_director_identity(params.get("instruct_identity"))
    if identity:
        params["instruct_identity"] = identity
    else:
        if params.get("instruct_identity"):
            blocked.append(str(params["instruct_identity"]).strip())
        params.pop("instruct_identity", None)

    raw_plan = params.get("delivery_plan")
    if isinstance(raw_plan, Mapping):
        plan = dict(raw_plan)
        # Structured pitch is a voice transformation control. Fixed voices do
        # not carry segment-level pitch through structured or prompt fields.
        plan.pop("pitch", None)
        for field_name, allowed_values in _DELIVERY_PLAN_ENUM_FIELDS.items():
            if field_name not in plan:
                continue
            raw_value = str(plan.get(field_name) or "").strip()
            normalized_value = raw_value.lower()
            if normalized_value in allowed_values:
                plan[field_name] = normalized_value
            else:
                if raw_value:
                    blocked.append(raw_value)
                plan.pop(field_name, None)
        for field_name in (
            "performance_notes",
            "style_instruction",
            "director_guidance",
            "pause_strategy",
            "cadence_reason",
            "emotion_primary",
            "emotion",
        ):
            if field_name not in plan:
                continue
            cleaned, removed = sanitize_fixed_voice_performance_text(plan.get(field_name))
            blocked.extend(removed)
            if cleaned:
                plan[field_name] = cleaned
            else:
                plan.pop(field_name, None)

        if "director_scene" in plan:
            cleaned_scene, removed_scene = sanitize_fixed_voice_scene_text(
                plan.get("director_scene")
            )
            blocked.extend(removed_scene)
            if cleaned_scene:
                plan["director_scene"] = cleaned_scene
            else:
                plan.pop("director_scene", None)

        stress_words = plan.get("stress_words")
        if isinstance(stress_words, (list, tuple, set, str)):
            normalized_words = [stress_words] if isinstance(stress_words, str) else stress_words
            source_text = str(plan.get("text") or params.get("text") or "")
            safe_words: List[str] = []
            for value in normalized_words:
                word = str(value or "").strip()
                if not word:
                    continue
                invalid = (
                    len(word) > 24
                    or _requests_voice_identity_change(word)
                    or _contains_any_term(word, _TEMPORARY_TEXTURE_TAG_TERMS)
                    or (bool(source_text) and word not in source_text)
                )
                if invalid:
                    blocked.append(word)
                    continue
                if word not in safe_words:
                    safe_words.append(word)
            if safe_words:
                plan["stress_words"] = safe_words
            else:
                plan.pop("stress_words", None)

        plan["director_role"] = stable_director_role(
            segment_type=plan.get("segment_type") or params.get("segment_type"),
            segment_speaker=plan.get("speaker") or params.get("segment_speaker"),
            requested_role=plan.get("director_role") or params.get("instruct_role"),
        )
        if not plan["director_role"]:
            plan.pop("director_role", None)
        director_identity = stable_director_identity(plan.get("director_identity"))
        if director_identity:
            plan["director_identity"] = director_identity
        else:
            if plan.get("director_identity"):
                blocked.append(str(plan["director_identity"]).strip())
            plan.pop("director_identity", None)

        for field_name in ("emotion_mix", "micro_tags", "style_tags", "inline_audio_tags"):
            values = plan.get(field_name)
            if not isinstance(values, (list, tuple, set, str)):
                continue
            normalized_values = [values] if isinstance(values, str) else values
            temporary_hoarseness_instructions.extend(
                _temporary_hoarseness_instructions_from_tags(normalized_values)
            )
            safe_tags, blocked_tags = filter_fixed_voice_identity_tags(normalized_values)
            blocked.extend(blocked_tags)
            if safe_tags:
                plan[field_name] = safe_tags
            else:
                plan.pop(field_name, None)
        params["delivery_plan"] = plan

    _append_performance_instructions(params, temporary_hoarseness_instructions)

    return params, _unique_nonempty(blocked)


__all__ = [
    "FIXED_VOICE_PERFORMANCE_BOUNDARY_PROMPT",
    "VOICE_IDENTITY_POLICY_VERSION",
    "extract_fixed_voice_temporary_hoarseness_instructions",
    "filter_fixed_voice_identity_tags",
    "is_current_voice_identity_snapshot",
    "is_voice_design_creation_request",
    "is_voice_design_model",
    "sanitize_fixed_voice_performance_text",
    "sanitize_fixed_voice_prompt_params",
    "sanitize_fixed_voice_scene_text",
    "sanitize_fixed_voice_ssml_text",
    "stable_director_identity",
    "stable_director_role",
    "stable_prompt_speaker",
]
