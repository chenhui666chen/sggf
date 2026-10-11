"""音色标签受控词表。

画像打标、公共池筛选、前端展示的唯一事实源：任何一处要新增可选标签，只改本文件。
维度值一律是小写 ASCII code，中文/英文只用于展示，不参与匹配。

取值口径对齐 docs/AUDIOBOOK_VOICE_PROFILE_AND_CHARACTER_MATCHING_GUIDE.md：
§4.3 给出新维度的受控选项，§4.4 规定每个值的唯一主归属（旁白/对白的能力标签属于
performance，不属于 scenario；温柔属于 style，柔情倾向属于 emotion）。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

TAXONOMY_VERSION = "voice-tags-v2"

TAG_LIMIT = 5

GENDER_PRESENTATION_TAGS = ("female", "male", "neutral")
AGE_IMPRESSION_TAGS = ("child", "teen", "young_adult", "adult", "mature", "elder")
TIMBRE_TAGS = (
    "clear",
    "warm",
    "bright",
    "deep",
    "magnetic",
    "soft",
    "powerful",
    "slightly_husky",
    "husky",
    "airy",
    "rich",
    "pure",
    "thick",
    "transparent",
)
STYLE_TAGS = (
    "natural",
    "gentle",
    "sweet",
    "bright",
    "restrained",
    "intellectual",
    "powerful",
    "cold",
    "narration",
    "roleplay",
    "lively",
    "humorous",
    "solemn",
    "mysterious",
    "innocent",
    "elegant",
    "weary",
)
EMOTION_TAGS = (
    "calm",
    "happy",
    "sad",
    "angry",
    "fearful",
    "tender",
    "tense",
    "surprised",
    "neutral",
    "excited",
    "wistful",
)
SCENARIO_TAGS = (
    "audiobook",
    "dialogue",
    "narration",
    "suspense",
    "romance",
    "historical",
    "fantasy",
    "children",
    "documentary",
    "commercial",
    "wuxia",
    "urban",
    "sci_fi",
    "horror",
    "fable",
    "game",
)
# §4.4：旁白/对白是表演能力，新画像必须写进 performance；这里保留仅供读取历史公共池数据。
SCENARIO_WRITABLE_TAGS = tuple(
    code for code in SCENARIO_TAGS if code not in {"narration", "dialogue"}
)
TEMPERAMENT_TAGS = ("authoritative", "mysterious", "playful", "approachable", "solemn")
PERFORMANCE_TAGS = (
    "narration",
    "dialogue",
    "emotional",
    "whisper",
    "authority_delivery",
    "comedy",
    "long_form",
)
ROLE_ARCHETYPE_TAGS = (
    "narrator",
    "protagonist",
    "romantic_lead",
    "mentor",
    "authority_figure",
    "investigator",
    "professional",
    "antagonist",
    "comic_relief",
    "non_human",
)
PACE_TAGS = ("slow", "medium_slow", "medium", "medium_fast", "fast")
ENERGY_TAGS = ("low", "medium_low", "medium", "medium_high", "high")
ARTICULATION_TAGS = ("soft", "clear", "crisp")
PITCH_RANGE_TAGS = ("low", "low_mid", "mid", "mid_high", "high")

VOICE_TAG_DIMENSIONS: Mapping[str, tuple[str, ...]] = {
    "gender_presentation": GENDER_PRESENTATION_TAGS,
    "age_impression": AGE_IMPRESSION_TAGS,
    "timbre": TIMBRE_TAGS,
    "style": STYLE_TAGS,
    "emotion": EMOTION_TAGS,
    "scenario": SCENARIO_TAGS,
    "temperament": TEMPERAMENT_TAGS,
    "performance": PERFORMANCE_TAGS,
    "role_archetype": ROLE_ARCHETYPE_TAGS,
    "pace": PACE_TAGS,
    "energy": ENERGY_TAGS,
    "articulation": ARTICULATION_TAGS,
    "pitch_range": PITCH_RANGE_TAGS,
}

# 新画像写入时使用的取值集合；未列出的维度与读取集相同。
WRITABLE_TAG_DIMENSIONS: Mapping[str, tuple[str, ...]] = {
    **VOICE_TAG_DIMENSIONS,
    "scenario": SCENARIO_WRITABLE_TAGS,
}

# 这些维度描述同一个连续量的档位，或按合同只允许一个主值，同时出现两个只会互相抵消。
SINGLE_VALUE_DIMENSIONS = frozenset(
    {
        "gender_presentation",
        "age_impression",
        "style",
        "pace",
        "energy",
        "articulation",
        "pitch_range",
    }
)

DIMENSION_TAG_LIMITS: Mapping[str, int] = {
    "temperament": 3,
}

# 展示名按维度作用域：同一个 code 在不同维度含义不同（energy 的 low 是能量，
# pitch_range 的 low 是音高；timbre 的 clear 是清亮，articulation 的 clear 是咬字清晰）。
_LABELS: Mapping[str, Mapping[str, tuple[str, str]]] = {
    "gender_presentation": {
        "female": ("女声", "Female"),
        "male": ("男声", "Male"),
        "neutral": ("中性", "Neutral"),
    },
    "age_impression": {
        "child": ("儿童", "Child"),
        "teen": ("青少年", "Teen"),
        "young_adult": ("青年", "Young adult"),
        "adult": ("中年", "Middle-aged"),
        "mature": ("熟年", "Mature"),
        "elder": ("老年", "Elder"),
    },
    "timbre": {
        "clear": ("清亮", "Clear"),
        "warm": ("温暖", "Warm"),
        "bright": ("明亮", "Bright"),
        "deep": ("低沉", "Deep"),
        "magnetic": ("磁性", "Magnetic"),
        "soft": ("柔和", "Soft"),
        "powerful": ("有力", "Powerful"),
        "slightly_husky": ("微沙", "Slightly husky"),
        "husky": ("沙哑", "Husky"),
        "airy": ("气声", "Airy"),
        "rich": ("浑厚", "Rich"),
        "pure": ("干净", "Pure"),
        "thick": ("厚实", "Thick"),
        "transparent": ("通透", "Transparent"),
    },
    "style": {
        "natural": ("自然", "Natural"),
        "gentle": ("温柔", "Gentle"),
        "sweet": ("甜美", "Sweet"),
        "bright": ("明亮", "Bright"),
        "restrained": ("克制", "Restrained"),
        "intellectual": ("知性", "Intellectual"),
        "powerful": ("有力", "Powerful"),
        "cold": ("冷淡", "Cold"),
        "narration": ("叙述", "Narration"),
        "roleplay": ("角色化", "Roleplay"),
        "lively": ("活泼", "Lively"),
        "humorous": ("诙谐", "Humorous"),
        "solemn": ("庄重", "Solemn"),
        "mysterious": ("神秘", "Mysterious"),
        "innocent": ("天真", "Innocent"),
        "elegant": ("优雅", "Elegant"),
        "weary": ("疲惫", "Weary"),
    },
    "emotion": {
        "calm": ("平静", "Calm"),
        "happy": ("愉悦", "Happy"),
        "sad": ("低落", "Sad"),
        "angry": ("愤怒", "Angry"),
        "fearful": ("恐惧", "Fearful"),
        "tender": ("柔情倾向", "Tender"),
        "tense": ("紧绷", "Tense"),
        "surprised": ("惊讶", "Surprised"),
        "neutral": ("中性情绪", "Neutral"),
        "excited": ("亢奋", "Excited"),
        "wistful": ("怅然", "Wistful"),
    },
    "scenario": {
        "audiobook": ("有声书", "Audiobook"),
        "dialogue": ("对白", "Dialogue"),
        "narration": ("旁白叙述", "Narration"),
        "suspense": ("悬疑", "Suspense"),
        "romance": ("言情", "Romance"),
        "historical": ("历史", "Historical"),
        "fantasy": ("玄幻", "Fantasy"),
        "children": ("少儿", "Children"),
        "documentary": ("纪实", "Documentary"),
        "commercial": ("商用广告", "Commercial"),
        "wuxia": ("武侠", "Wuxia"),
        "urban": ("都市", "Urban"),
        "sci_fi": ("科幻", "Sci-fi"),
        "horror": ("恐怖", "Horror"),
        "fable": ("寓言", "Fable"),
        "game": ("游戏配音", "Game voice"),
    },
    "temperament": {
        "authoritative": ("威严", "Authoritative"),
        "mysterious": ("神秘", "Mysterious"),
        "playful": ("俏皮", "Playful"),
        "approachable": ("亲和", "Approachable"),
        "solemn": ("庄重", "Solemn"),
    },
    "performance": {
        "narration": ("旁白", "Narration"),
        "dialogue": ("对白", "Dialogue"),
        "emotional": ("情绪演绎", "Emotional delivery"),
        "whisper": ("低语", "Whisper"),
        "authority_delivery": ("权威播报", "Authority delivery"),
        "comedy": ("喜剧", "Comedy"),
        "long_form": ("长篇稳定", "Long form"),
    },
    "role_archetype": {
        "narrator": ("旁白叙述者", "Narrator"),
        "protagonist": ("主角", "Protagonist"),
        "romantic_lead": ("恋爱对象", "Romantic lead"),
        "mentor": ("导师", "Mentor"),
        "authority_figure": ("权威角色", "Authority figure"),
        "investigator": ("调查者", "Investigator"),
        "professional": ("专业人士", "Professional"),
        "antagonist": ("反派", "Antagonist"),
        "comic_relief": ("喜剧调剂", "Comic relief"),
        "non_human": ("非人角色", "Non-human"),
    },
    "pace": {
        "slow": ("缓慢", "Slow"),
        "medium_slow": ("偏慢", "Medium slow"),
        "medium": ("中速", "Medium"),
        "medium_fast": ("偏快", "Medium fast"),
        "fast": ("快速", "Fast"),
    },
    "energy": {
        "low": ("低能量", "Low energy"),
        "medium_low": ("偏低能量", "Medium low energy"),
        "medium": ("中能量", "Medium energy"),
        "medium_high": ("偏高能量", "Medium high energy"),
        "high": ("高能量", "High energy"),
    },
    "articulation": {
        "soft": ("咬字轻柔", "Soft articulation"),
        "clear": ("咬字清晰", "Clear articulation"),
        "crisp": ("咬字干脆", "Crisp articulation"),
    },
    "pitch_range": {
        "low": ("低音", "Low pitch"),
        "low_mid": ("中低音", "Low-mid pitch"),
        "mid": ("中音", "Mid pitch"),
        "mid_high": ("中高音", "Mid-high pitch"),
        "high": ("高音", "High pitch"),
    },
}

MISSING_LABEL_CODES = sorted(
    f"{dimension}.{code}"
    for dimension, codes in VOICE_TAG_DIMENSIONS.items()
    for code in codes
    if code not in _LABELS.get(dimension, {})
)
assert not MISSING_LABEL_CODES, f"missing display labels for: {MISSING_LABEL_CODES}"

VOICE_TAG_LABELS: Mapping[str, Mapping[str, Mapping[str, str]]] = {
    dimension: {
        code: {"zh": zh, "en": en}
        for code, (zh, en) in _LABELS[dimension].items()
    }
    for dimension in VOICE_TAG_DIMENSIONS
}


def voice_tag_label(dimension: str, code: str) -> Mapping[str, str]:
    labels = VOICE_TAG_LABELS.get(dimension) or {}
    label = labels.get(str(code or "").strip().lower())
    if label is None:
        raise ValueError(f"unknown tag label: {dimension}.{code}")
    return label


def dimension_tag_limit(dimension: str) -> int:
    if dimension in SINGLE_VALUE_DIMENSIONS:
        return 1
    return DIMENSION_TAG_LIMITS.get(dimension, TAG_LIMIT)


def normalize_voice_tags(
    value: Iterable[Any],
    *,
    dimension: str,
    limit: int | None = None,
    writable: bool = True,
) -> list[str]:
    """把某一维度的标签归一为去重后的小写 code 列表；未知标签直接报错。"""
    allowed = (WRITABLE_TAG_DIMENSIONS if writable else VOICE_TAG_DIMENSIONS).get(dimension)
    if allowed is None:
        raise ValueError(f"unknown tag dimension: {dimension}")
    effective_limit = limit or dimension_tag_limit(dimension)
    normalized: list[str] = []
    for raw in value or ():
        item = str(raw or "").strip().lower()
        if not item:
            continue
        if item not in allowed:
            raise ValueError(f"unsupported {dimension} tag: {item}")
        if item not in normalized:
            normalized.append(item)
    if len(normalized) > effective_limit:
        raise ValueError(f"{dimension} accepts at most {effective_limit} tag(s)")
    return normalized


def validate_voice_profile_tags(payload: Any) -> dict[str, list[str]]:
    """校验画像条目的 tags 子对象：未知维度报错，缺失或空列表的维度不落地。"""
    if not isinstance(payload, Mapping):
        raise ValueError("voice profile tags must be an object")
    result: dict[str, list[str]] = {}
    for dimension, value in payload.items():
        if dimension not in VOICE_TAG_DIMENSIONS:
            raise ValueError(f"unknown tag dimension: {dimension}")
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
            raise ValueError(f"{dimension} tags must be a list")
        tags = normalize_voice_tags(value, dimension=dimension)
        if tags:
            result[str(dimension)] = tags
    return result
