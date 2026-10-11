"""
叙事风格预设配置
"""
from typing import Dict, Any, Optional

from app.services.audiobook.tts_model_ids import (
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
)
from app.services.audiobook.voice_description_policy import build_quality_voice_description


ALL_NARRATION_TTS_MODELS = (
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
)

EXPRESSIVE_NARRATION_TTS_MODELS = (
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
)


NARRATION_STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "professional": {
        "id": "professional",
        "name": "专业播报",
        "description": "清晰、专业、适合新闻/教育内容",
        "emotion_profile": {
            "default_emotion": "calm",
            "emotion_intensity": 0.3,  # 低情感强度
            "emotion_variation": False,  # 不随内容变化情感
        },
        "speed_range": {
            "min": 0.9,
            "max": 1.1,
            "default": 1.0,
        },
        "pitch_range": {
            "min": -2,
            "max": 2,
            "default": 0,
        },
        "pause_multiplier": 1.0,  # 标准停顿
        "supported_models": list(ALL_NARRATION_TTS_MODELS),
        "system_prompt_template": "请以专业、清晰、客观的语气朗读以下内容。语速适中，情感表达克制。",
    },
    "dramatic": {
        "id": "dramatic",
        "name": "戏剧表演",
        "description": "富有戏剧张力、情感饱满、适合小说/故事",
        "emotion_profile": {
            "default_emotion": "variable",  # 根据内容变化
            "emotion_intensity": 0.8,  # 高情感强度
            "emotion_variation": True,
        },
        "speed_range": {
            "min": 0.8,
            "max": 1.3,
            "default": 1.0,
        },
        "pitch_range": {
            "min": -5,
            "max": 5,
            "default": 0,
        },
        "pause_multiplier": 1.5,  # 增加停顿以增强戏剧效果
        "supported_models": list(EXPRESSIVE_NARRATION_TTS_MODELS),
        "system_prompt_template": "请以富有戏剧性和情感张力的方式朗读以下内容。根据情节变化调整语气，对话要有角色感。",
    },
    "relaxing": {
        "id": "relaxing",
        "name": "轻松舒缓",
        "description": "温和、放松、适合睡前故事/冥想",
        "emotion_profile": {
            "default_emotion": "calm",
            "emotion_intensity": 0.2,  # 极低情感强度
            "emotion_variation": False,
        },
        "speed_range": {
            "min": 0.7,
            "max": 0.9,
            "default": 0.8,
        },
        "pitch_range": {
            "min": -3,
            "max": 0,
            "default": -1,
        },
        "pause_multiplier": 1.8,  # 更长停顿
        "supported_models": list(ALL_NARRATION_TTS_MODELS),
        "system_prompt_template": "请以温和、舒缓、放松的语气朗读以下内容。语速较慢，语调轻柔。",
    },
    "expressive": {
        "id": "expressive",
        "name": "生动表现",
        "description": "变化丰富、表现力强、适合儿童故事/喜剧",
        "emotion_profile": {
            "default_emotion": "happy",
            "emotion_intensity": 0.7,
            "emotion_variation": True,
        },
        "speed_range": {
            "min": 0.9,
            "max": 1.4,
            "default": 1.1,
        },
        "pitch_range": {
            "min": -4,
            "max": 6,
            "default": 1,
        },
        "pause_multiplier": 1.2,
        "supported_models": list(EXPRESSIVE_NARRATION_TTS_MODELS),
        "system_prompt_template": "请以生动、活泼、富有表现力的方式朗读以下内容。根据情节变化调整语气，适当夸张情感。",
    },
    "custom": {
        "id": "custom",
        "name": "自定义",
        "description": "使用自定义提示词控制旁白语气",
        "emotion_profile": {
            "default_emotion": "calm",
            "emotion_intensity": 0.3,
            "emotion_variation": False,
        },
        "speed_range": {
            "min": 0.7,
            "max": 1.4,
            "default": 1.0,
        },
        "pitch_range": {
            "min": -5,
            "max": 6,
            "default": 0,
        },
        "pause_multiplier": 1.0,
        "supported_models": list(ALL_NARRATION_TTS_MODELS),
        "system_prompt_template": "",
    },
}


NARRATION_VOICE_DESCRIPTION_PRESETS: Dict[str, Dict[str, Any]] = {
    "professional": {
        "age_group": "中年",
        "pitch": "中音",
        "pace": "中速",
        "traits": ["吐字清晰", "客观克制"],
        "use_case": "新闻播报和知识类有声书旁白",
    },
    "dramatic": {
        "age_group": "中年",
        "pitch": "中低音",
        "pace": "中速",
        "traits": ["有张力", "停顿层次明确"],
        "use_case": "剧情有声书旁白",
    },
    "relaxing": {
        "age_group": "中年",
        "pitch": "中低音",
        "pace": "缓慢",
        "traits": ["温和", "舒缓"],
        "use_case": "有声书旁白",
    },
    "expressive": {
        "age_group": "青年",
        "pitch": "中高音",
        "pace": "偏快",
        "traits": ["明亮", "节奏变化丰富"],
        "use_case": "儿童故事和轻喜剧有声书旁白",
    },
    "custom": {
        "age_group": "中年",
        "pitch": "中音",
        "pace": "中速",
        "traits": ["吐字清晰", "风格跟随自定义提示"],
        "use_case": "有声书旁白",
    },
}


def normalize_narration_style_id(style_id: str) -> str:
    """规范化叙事风格 ID。"""
    return str(style_id or "").strip().lower()


def find_narration_style_preset(style_id: str) -> Optional[Dict[str, Any]]:
    """严格查找叙事风格预设配置。"""
    return NARRATION_STYLE_PRESETS.get(normalize_narration_style_id(style_id))


def get_narration_style_preset(style_id: str) -> Dict[str, Any]:
    """获取叙事风格预设配置，未知风格回退到专业播报。"""
    return find_narration_style_preset(style_id) or NARRATION_STYLE_PRESETS["professional"]


def get_all_narration_styles() -> list:
    """获取所有叙事风格预设列表"""
    return [
        {
            "id": preset["id"],
            "name": preset["name"],
            "description": preset["description"],
            "supported_models": preset["supported_models"],
        }
        for preset in NARRATION_STYLE_PRESETS.values()
    ]


def build_narration_voice_description(style_id: str, emotion: str) -> str:
    """生成旁白专用声音描述，避免沿用角色对白画像。"""
    style_key = normalize_narration_style_id(style_id)
    preset = NARRATION_VOICE_DESCRIPTION_PRESETS.get(
        style_key,
        NARRATION_VOICE_DESCRIPTION_PRESETS["professional"],
    )
    return build_quality_voice_description(
        gender="neutral",
        age_group=preset["age_group"],
        pitch=preset["pitch"],
        pace=preset["pace"],
        emotion=emotion or "calm",
        traits=preset["traits"],
        use_case=preset["use_case"],
    )


def apply_narration_style_to_tts_params(
    style_id: str,
    base_params: Dict[str, Any],
    custom_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """保留历史旁白风格输入，但不再覆盖运行时表演参数。

    新链路中旁白只保存 TTS 模型与音色引用，语速、音高、停顿和风格指令
    均由片段文本、上下文与 delivery_plan 动态决定。该函数仅保留历史
    style_id/custom_prompt 作为可审计兼容输入，避免旧项目数据丢失。
    """
    updated_params = base_params.copy()
    normalized_style = normalize_narration_style_id(style_id)
    if normalized_style:
        updated_params["narration_style_legacy"] = normalized_style
    prompt = str(custom_prompt or "").strip()
    if prompt:
        updated_params["narration_style_prompt_legacy"] = prompt
    return updated_params
