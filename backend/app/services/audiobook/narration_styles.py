"""
叙事风格预设配置
"""
from typing import Dict, Any


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
        "supported_models": ["qwen3-tts-instruct-flash", "cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"],
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
        "supported_models": ["cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"],
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
        "supported_models": ["qwen3-tts-instruct-flash", "cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"],
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
        "supported_models": ["cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"],
        "system_prompt_template": "请以生动、活泼、富有表现力的方式朗读以下内容。根据情节变化调整语气，适当夸张情感。",
    },
}


def get_narration_style_preset(style_id: str) -> Dict[str, Any]:
    """获取叙事风格预设配置"""
    return NARRATION_STYLE_PRESETS.get(style_id, NARRATION_STYLE_PRESETS["professional"])


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


def apply_narration_style_to_tts_params(
    style_id: str,
    base_params: Dict[str, Any],
    custom_prompt: str = None,
) -> Dict[str, Any]:
    """将叙事风格应用到 TTS 参数

    Args:
        style_id: 风格ID
        base_params: 基础TTS参数
        custom_prompt: 自定义prompt（如果用户提供）

    Returns:
        更新后的TTS参数
    """
    preset = get_narration_style_preset(style_id)

    updated_params = base_params.copy()

    # 应用语速
    if "speed" not in updated_params or updated_params["speed"] is None:
        updated_params["speed"] = preset["speed_range"]["default"]

    # 应用音调
    if "pitch" not in updated_params or updated_params["pitch"] is None:
        updated_params["pitch"] = preset["pitch_range"]["default"]

    # 应用情感（仅对支持的模型）
    if preset["emotion_profile"]["emotion_variation"]:
        # 允许情感变化，不强制覆盖
        if "emotion" not in updated_params:
            updated_params["emotion"] = preset["emotion_profile"]["default_emotion"]
    else:
        # 固定情感
        updated_params["emotion"] = preset["emotion_profile"]["default_emotion"]

    # 应用停顿倍数
    updated_params["pause_multiplier"] = preset["pause_multiplier"]

    # 应用系统prompt
    if custom_prompt:
        updated_params["system_prompt"] = custom_prompt
    else:
        updated_params["system_prompt"] = preset.get("system_prompt_template", "")

    return updated_params
