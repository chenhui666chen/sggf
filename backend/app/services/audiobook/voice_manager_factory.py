from __future__ import annotations

from typing import Any, Dict, List, Optional

from .voice_manager import VoiceManager
from .voice_manager_cosyvoice_v3_plus import CosyVoiceV3PlusVoiceManager
from .voice_manager_minimax import MiniMaxVoiceManager


# 模型 -> 音色目录文件的映射
MODEL_VOICE_MAPPING = {
    "qwen3-tts-flash": "qwen3-tts-flash",
    "qwen3-tts-plus": "qwen3-tts-flash",
    "cosyvoice-v3-plus": "cosyvoice-v3-plus",
    "minimax-speech-2.8-hd": "minimax-speech-2.8",
    "minimax-speech-2.8-turbo": "minimax-speech-2.8",
    "minimax-speech-2.8": "minimax-speech-2.8",
}

# 模型成本和优先级配置
MODEL_CONFIGS = {
    "qwen3-tts-flash": {
        "cost_level": "low",
        "quality_level": "medium",
        "priority": 3,  # 默认使用
    },
    "qwen3-tts-plus": {
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 2,
    },
    "cosyvoice-v3-plus": {
        "cost_level": "high",
        "quality_level": "premium",
        "priority": 1,  # 高质量场景
    },
    "minimax-speech-2.8-hd": {
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 4,
    },
    "minimax-speech-2.8-turbo": {
        "cost_level": "low",
        "quality_level": "medium",
        "priority": 5,  # 快速场景
    },
}


def get_model_for_voice(voice_id: str, preferred_model: str = None) -> str:
    """根据音色ID反推适用的模型，避免音色与模型不匹配
    
    Args:
        voice_id: 音色ID
        preferred_model: 用户偏好的模型（如果该模型支持此音色则优先使用）
    
    Returns:
        适用的模型名称
    """
    from .voice_catalog import load_voice_catalog_for_model
    
    # 先检查偏好模型是否支持该音色
    if preferred_model:
        catalog = load_voice_catalog_for_model(preferred_model)
        if voice_id in catalog.get("voices_by_id", {}):
            return preferred_model
    
    # 遍历所有模型查找音色
    for model_key in MODEL_VOICE_MAPPING.values():
        try:
            catalog = load_voice_catalog_for_model(model_key)
            if voice_id in catalog.get("voices_by_id", {}):
                return model_key
        except Exception:
            continue
    
    # 默认返回 qwen3-tts-flash
    return "qwen3-tts-flash"


def suggest_model_for_character(
    character_profile: Optional[Dict[str, Any]] = None,
    preferred_model: Optional[str] = None,
    cost_priority: str = "balanced",  # low_cost / balanced / high_quality
) -> str:
    """根据角色档案智能推荐TTS模型
    
    Args:
        character_profile: 角色档案（包含importance_level, role_position等）
        preferred_model: 用户偏好模型
        cost_priority: 成本优先级（low_cost/balanced/high_quality）
    
    Returns:
        推荐的模型名称
    """
    # 如果有用户偏好，优先使用
    if preferred_model:
        return preferred_model
    
    # 根据角色重要性和成本优先级推荐模型
    if character_profile:
        importance = character_profile.get("importance_level", "")
        role_position = character_profile.get("role_position", "")
        
        # 主角/重要角色 → 高质量模型
        if importance in ["主角", "重要角色"] or role_position in ["主角", "女主角"]:
            if cost_priority != "low_cost":
                return "cosyvoice-v3-plus"  # 高质量
        
        # 次要角色 → 平衡模型
        if importance in ["次要角色"]:
            if cost_priority == "high_quality":
                return "qwen3-tts-plus"
            return "qwen3-tts-flash"
        
        # 群众角色 → 低成本模型
        if importance in ["群众角色"]:
            return "minimax-speech-2.8-turbo"
    
    # 默认根据成本优先级返回
    if cost_priority == "high_quality":
        return "cosyvoice-v3-plus"
    elif cost_priority == "low_cost":
        return "minimax-speech-2.8-turbo"
    else:
        return "qwen3-tts-flash"


def get_model_config(model: str) -> Dict[str, Any]:
    """获取模型配置信息"""
    return MODEL_CONFIGS.get(model, {
        "cost_level": "unknown",
        "quality_level": "unknown",
        "priority": 99,
    })


def list_supported_models() -> list:
    """列出所有支持的模型"""
    return list(MODEL_VOICE_MAPPING.keys())


def create_voice_manager(tts_model: str, llm_client: Any = None):
    """根据TTS模型创建对应的声音管理器"""
    tts_model = (tts_model or "").strip() or "qwen3-tts-flash"
    
    if tts_model == "cosyvoice-v3-plus":
        return CosyVoiceV3PlusVoiceManager()
    elif tts_model.startswith("minimax-speech"):
        return MiniMaxVoiceManager()
    return VoiceManager(llm_client=llm_client)

