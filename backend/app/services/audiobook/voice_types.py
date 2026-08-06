"""
声音类型系统 - 为角色配置更丰富的声音属性

兼容现有音色系统，不冲突现有音色映射机制。
参考 Alexandria Audiobook Generator 的声音类型概念，但简化为配置层。

功能：
1. 声音类型预设（威严/温柔/活泼/沧桑/清冷等）
2. 角色性格与声音类型的映射
3. 情感倾向配置
4. 与现有 VoiceManager 集成
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class VoiceType(str, Enum):
    """声音类型枚举"""
    MAJESTIC = "majestic"  # 威严（适合帝王、长者）
    GENTLE = "gentle"  # 温柔（适合母亲、恋人）
    LIVELY = "lively"  # 活泼（适合年轻人、儿童）
    WEATHERED = "weathered"  # 沧桑（适合老兵、饱经风霜者）
    COLD = "cold"  # 清冷（适合高冷角色、反派）
    WARM = "warm"  # 温暖（适合暖男、治愈系）
    MYSTERIOUS = "mysterious"  # 神秘（适合隐士、智者）
    POWERFUL = "powerful"  # 力量（适合战士、英雄）
    SCHOLARLY = "scholarly"  # 书卷气（适合学者、文人）
    PLAYFUL = "playful"  # 俏皮（适合喜剧角色）


class PersonalityType(str, Enum):
    """性格类型"""
    INTROVERT = "introvert"  # 内向
    EXTROVERT = "extrovert"  # 外向
    AMBITIOUS = "ambitious"  # 野心型
    CALM = "calm"  # 冷静
    EMOTIONAL = "emotional"  # 感性
    RATIONAL = "rational"  # 理性
    REBEL = "rebel"  # 叛逆
    LOYAL = "loyal"  # 忠诚


class EmotionTendency(str, Enum):
    """情感倾向"""
    POSITIVE = "positive"  # 偏向积极情感
    NEGATIVE = "negative"  # 偏向消极情感
    NEUTRAL = "neutral"  # 中性
    VARIABLE = "variable"  # 多变


@dataclass
class VoiceTypeProfile:
    """声音类型配置"""
    voice_type: str
    name: str
    description: str
    # 声音参数调整
    speed_modifier: float = 1.0  # 语速调整（1.0 为标准）
    pitch_modifier: int = 0  # 已弃用兼容字段；运行时不应用到固定音色
    volume_modifier: int = 0  # 音量调整（0 为标准，-20~+20）
    # 情感配置
    emotion_intensity: float = 0.5  # 情感强度（0-1）
    emotion_tendency: str = "neutral"  # 情感倾向
    default_emotion: str = "calm"  # 默认情感
    # 音色偏好
    preferred_gender: Optional[str] = None  # 偏好性别（male/female/any）
    preferred_age_range: str = "adult"  # 偏好年龄段（child/teen/adult/elderly）
    # 适用性格
    compatible_personalities: List[str] = field(default_factory=list)
    # 适合的场景
    suitable_scenarios: List[str] = field(default_factory=list)


# 预定义的声音类型配置
VOICE_TYPE_PRESETS: Dict[str, VoiceTypeProfile] = {
    "majestic": VoiceTypeProfile(
        voice_type="majestic",
        name="威严",
        description="庄重、有气势，适合帝王、长者、权威人物",
        speed_modifier=0.85,  # 稍慢
        pitch_modifier=0,
        emotion_intensity=0.6,
        emotion_tendency="positive",
        default_emotion="calm",
        preferred_age_range="elderly",
        compatible_personalities=["ambitious", "calm", "rational"],
        suitable_scenarios=["朝堂", "训话", "宣旨"],
    ),
    "gentle": VoiceTypeProfile(
        voice_type="gentle",
        name="温柔",
        description="温和、亲切，适合母亲、恋人、治愈系角色",
        speed_modifier=0.9,
        pitch_modifier=0,
        volume_modifier=-5,
        emotion_intensity=0.4,
        emotion_tendency="positive",
        default_emotion="calm",
        preferred_gender="female",
        compatible_personalities=["introvert", "emotional", "loyal"],
        suitable_scenarios=["安慰", "倾诉", "回忆"],
    ),
    "lively": VoiceTypeProfile(
        voice_type="lively",
        name="活泼",
        description="明快、有活力，适合年轻人、儿童、喜剧角色",
        speed_modifier=1.15,
        pitch_modifier=0,
        emotion_intensity=0.8,
        emotion_tendency="positive",
        default_emotion="happy",
        preferred_age_range="teen",
        compatible_personalities=["extrovert", "emotional", "rebel"],
        suitable_scenarios=["嬉闹", "争论", "兴奋"],
    ),
    "weathered": VoiceTypeProfile(
        voice_type="weathered",
        name="沧桑",
        description="沧桑、有故事感，适合老兵、流浪者、饱经风霜者",
        speed_modifier=0.9,
        pitch_modifier=0,
        emotion_intensity=0.5,
        emotion_tendency="negative",
        default_emotion="sad",
        preferred_age_range="adult",
        compatible_personalities=["introvert", "calm", "loyal"],
        suitable_scenarios=["回忆", "感慨", "独白"],
    ),
    "cold": VoiceTypeProfile(
        voice_type="cold",
        name="清冷",
        description="冷淡、疏离，适合高冷角色、反派、隐士",
        speed_modifier=0.95,
        pitch_modifier=0,
        volume_modifier=-10,
        emotion_intensity=0.2,
        emotion_tendency="neutral",
        default_emotion="calm",
        compatible_personalities=["rational", "introvert", "ambitious"],
        suitable_scenarios=["威胁", "冷漠", "命令"],
    ),
    "warm": VoiceTypeProfile(
        voice_type="warm",
        name="温暖",
        description="阳光、亲切，适合暖男、治愈系、正能量角色",
        speed_modifier=1.0,
        pitch_modifier=0,
        emotion_intensity=0.5,
        emotion_tendency="positive",
        default_emotion="happy",
        compatible_personalities=["extrovert", "emotional", "loyal"],
        suitable_scenarios=["鼓励", "安慰", "陪伴"],
    ),
    "mysterious": VoiceTypeProfile(
        voice_type="mysterious",
        name="神秘",
        description="低沉、有磁性，适合隐士、智者、神秘人物",
        speed_modifier=0.85,
        pitch_modifier=0,
        emotion_intensity=0.3,
        emotion_tendency="neutral",
        default_emotion="calm",
        preferred_age_range="adult",
        compatible_personalities=["introvert", "rational", "calm"],
        suitable_scenarios=["提示", "预言", "暗示"],
    ),
    "powerful": VoiceTypeProfile(
        voice_type="powerful",
        name="力量",
        description="有力、震撼，适合战士、英雄、强者",
        speed_modifier=1.0,
        pitch_modifier=0,
        volume_modifier=10,
        emotion_intensity=0.7,
        emotion_tendency="positive",
        default_emotion="angry",
        compatible_personalities=["extrovert", "ambitious", "rebel"],
        suitable_scenarios=["战斗", "宣言", "挑战"],
    ),
    "scholarly": VoiceTypeProfile(
        voice_type="scholarly",
        name="书卷气",
        description="文雅、沉稳，适合学者、文人、智者",
        speed_modifier=0.9,
        pitch_modifier=0,
        emotion_intensity=0.3,
        emotion_tendency="neutral",
        default_emotion="calm",
        preferred_age_range="adult",
        compatible_personalities=["introvert", "rational", "calm"],
        suitable_scenarios=["讲学", "辩论", "引用"],
    ),
    "playful": VoiceTypeProfile(
        voice_type="playful",
        name="俏皮",
        description="灵动、有趣，适合喜剧角色、小丑、开心果",
        speed_modifier=1.2,
        pitch_modifier=0,
        emotion_intensity=0.9,
        emotion_tendency="positive",
        default_emotion="happy",
        compatible_personalities=["extrovert", "emotional", "rebel"],
        suitable_scenarios=["调侃", "开玩笑", "恶作剧"],
    ),
}


def get_voice_type_preset(voice_type: str) -> Optional[VoiceTypeProfile]:
    """获取声音类型预设"""
    return VOICE_TYPE_PRESETS.get(voice_type)


def get_all_voice_types() -> List[Dict[str, Any]]:
    """获取所有声音类型列表"""
    return [
        {
            "voice_type": preset.voice_type,
            "name": preset.name,
            "description": preset.description,
            "compatible_personalities": preset.compatible_personalities,
            "suitable_scenarios": preset.suitable_scenarios,
        }
        for preset in VOICE_TYPE_PRESETS.values()
    ]


def recommend_voice_type(
    personality: Optional[str] = None,
    gender: Optional[str] = None,
    age_range: Optional[str] = None,
) -> List[str]:
    """根据角色属性推荐声音类型"""
    personality_aliases = {
        "rebellious": "rebel",
        "rebel": "rebel",
    }
    gender_aliases = {
        "男": "male",
        "男性": "male",
        "man": "male",
        "boy": "male",
        "m": "male",
        "女": "female",
        "女性": "female",
        "woman": "female",
        "girl": "female",
        "f": "female",
    }
    age_aliases = {
        "old": "elderly",
        "elder": "elderly",
        "elderly": "elderly",
        "young": "adult",
        "youth": "teen",
        "teenager": "teen",
    }
    personality = personality_aliases.get(
        str(personality or "").strip().lower(),
        str(personality or "").strip().lower() or None,
    )
    gender = gender_aliases.get(
        str(gender or "").strip().lower(),
        str(gender or "").strip().lower() or None,
    )
    age_range = age_aliases.get(
        str(age_range or "").strip().lower(),
        str(age_range or "").strip().lower() or None,
    )
    recommendations = []

    for voice_type, preset in VOICE_TYPE_PRESETS.items():
        score = 0

        # 性格匹配
        if personality and personality in preset.compatible_personalities:
            score += 3

        # 性别匹配
        if gender and preset.preferred_gender:
            if preset.preferred_gender == gender:
                score += 2
            elif preset.preferred_gender == "any":
                score += 1

        # 年龄匹配
        if age_range and preset.preferred_age_range == age_range:
            score += 2

        if score > 0:
            recommendations.append((voice_type, score))

    # 按分数排序
    recommendations.sort(key=lambda x: x[1], reverse=True)
    if recommendations:
        return [v[0] for v in recommendations[:3]]

    if age_range == "teen":
        return ["lively", "playful", "gentle"]
    if age_range == "elderly":
        return ["majestic", "weathered", "scholarly"]
    if age_range == "child":
        return ["playful", "lively", "gentle"]
    if gender == "female":
        return ["gentle", "warm", "lively"]
    if gender == "male":
        return ["powerful", "majestic", "warm"]
    return ["warm", "gentle", "mysterious"]


def apply_voice_type_to_tts_params(
    voice_type: str,
    base_params: Dict[str, Any],
    *,
    preserve_pitch: bool = False,
) -> Dict[str, Any]:
    """将声音类型应用到表演参数，不新增或改写音高。

    ``preserve_pitch`` 仅为旧调用兼容参数；无论取值如何，调用方已有的
    ``pitch`` 都保持原样，缺失时也不会由声音类型预设补入。
    """
    del preserve_pitch
    preset = get_voice_type_preset(voice_type)
    if not preset:
        return base_params

    updated = base_params.copy()

    # 应用语速调整
    if "speed" not in updated or updated["speed"] is None:
        updated["speed"] = preset.speed_modifier
    else:
        # 在原有语速基础上调整
        updated["speed"] *= preset.speed_modifier

    # 应用音量调整
    if "volume" not in updated or updated["volume"] is None:
        base_volume = 50 + preset.volume_modifier
        updated["volume"] = max(0, min(100, base_volume))
    else:
        updated["volume"] = max(0, min(100, updated["volume"] + preset.volume_modifier))

    # 设置情感
    if "emotion" not in updated or updated["emotion"] is None:
        updated["emotion"] = preset.default_emotion

    return updated


def create_character_voice_profile(
    character_name: str,
    voice_id: str,
    voice_type: Optional[str] = None,
    personality: Optional[str] = None,
    emotion_tendency: Optional[str] = None,
    custom_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """创建角色声音配置"""
    profile = {
        "character_name": character_name,
        "voice_id": voice_id,
        "voice_type": voice_type,
        "personality": personality,
        "emotion_tendency": emotion_tendency,
    }

    # 应用声音类型预设
    if voice_type:
        base_params = {}
        enhanced = apply_voice_type_to_tts_params(voice_type, base_params)
        profile.update({
            "speed": enhanced.get("speed"),
            "volume": enhanced.get("volume"),
            "emotion": enhanced.get("emotion"),
        })

    # 自定义设置覆盖
    if custom_settings:
        profile.update(
            {
                key: value
                for key, value in custom_settings.items()
                if key not in {"pitch", "pitch_ratio", "pitch_semitones", "character_base_pitch"}
            }
        )

    return profile
