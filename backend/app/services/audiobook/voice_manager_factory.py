from __future__ import annotations

from typing import Any

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


def get_voices_for_model(model: str) -> list:
    """获取指定模型支持的音色列表"""
    from .voice_catalog import load_voice_catalog_for_model
    
    try:
        catalog = load_voice_catalog_for_model(model)
        return catalog.get("voices", [])
    except Exception:
        return []


def list_all_models() -> list:
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

