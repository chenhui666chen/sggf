from __future__ import annotations

from typing import Any, Dict, List, Optional

from .voice_manager import VoiceManager
from .voice_manager_cosyvoice_v3_plus import CosyVoiceV3PlusVoiceManager
from .voice_manager_mimo import MiMoVoiceManager
from .voice_manager_minimax import MiniMaxVoiceManager
from .voice_manager_seed_tts import SeedTTSVoiceManager
from .voice_manager_stepaudio import StepAudioVoiceManager
from .cosyvoice_clone_client import (
    COSYVOICE_V35_PLUS_MODEL_ID,
    COSYVOICE_V35_PLUS_VOICE_ID_PREFIX,
    list_cosyvoice_v3_plus_clones,
)
from .tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
    get_audiobook_tts_model_metadata,
    list_supported_audiobook_tts_models,
    normalize_audiobook_tts_model,
)


# 模型 -> 音色目录文件的映射
MODEL_VOICE_MAPPING = {
    "qwen3-tts-instruct-flash": "qwen3-tts-instruct-flash",
    "qwen3-tts-flash": "qwen3-tts-instruct-flash",
    "qwen3-tts-plus": "qwen3-tts-instruct-flash",
    COSYVOICE_V35_PLUS_MODEL_ID: COSYVOICE_V35_PLUS_MODEL_ID,
    "cosyvoice-v3-plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "minimax-speech-2.8-hd": "minimax-speech-2.8",
    "minimax-speech-2.8-turbo": "minimax-speech-2.8",
    "minimax-speech-2.8": "minimax-speech-2.8",
    MIMO_V25_TTS_MODEL: "mimo-v2.5-tts",
    STEPAUDIO_25_TTS_MODEL: STEPAUDIO_25_TTS_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL: SEED_TTS_20_EXPRESSIVE_MODEL,
}

# 模型成本和优先级配置
MODEL_CONFIGS = {
    "qwen3-tts-instruct-flash": {
        "cost_level": "low",
        "quality_level": "medium_high",
        "priority": 3,  # 默认使用
    },
    "qwen3-tts-flash": {
        "cost_level": "low",
        "quality_level": "medium_high",
        "priority": 3,
    },
    "qwen3-tts-plus": {
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 2,
    },
    COSYVOICE_V35_PLUS_MODEL_ID: {
        "cost_level": "high",
        "quality_level": "premium",
        "priority": 1,  # 高质量场景（需先创建复刻/设计音色）
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
    MIMO_V25_TTS_MODEL: {
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 2,
    },
    MIMO_V25_TTS_VOICE_DESIGN_MODEL: {
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 2,
    },
    MIMO_V25_TTS_VOICE_CLONE_MODEL: {
        "cost_level": "low",
        "quality_level": "medium_high",
        "priority": 4,
    },
    STEPAUDIO_25_TTS_MODEL: {
        "cost_level": "medium",
        "quality_level": "premium",
        "priority": 2,
    },
    SEED_TTS_20_EXPRESSIVE_MODEL: {
        "cost_level": "medium",
        "quality_level": "premium",
        "priority": 2,
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

    voice_id = str(voice_id or "").strip()
    if voice_id.startswith(COSYVOICE_V35_PLUS_VOICE_ID_PREFIX):
        return COSYVOICE_V35_PLUS_MODEL_ID

    raw_preferred_model = str(preferred_model or "").strip() or None
    preferred_model = normalize_audiobook_tts_model(preferred_model) if raw_preferred_model else None

    # 先检查偏好模型是否支持该音色
    for candidate_model in (raw_preferred_model, preferred_model):
        if not candidate_model:
            continue
        try:
            catalog = load_voice_catalog_for_model(candidate_model)
        except Exception:
            continue
        if voice_id in catalog.get("voices_by_id", {}):
            return normalize_audiobook_tts_model(candidate_model)
    
    # 遍历所有模型查找音色
    for model_key in MODEL_VOICE_MAPPING.values():
        try:
            catalog = load_voice_catalog_for_model(model_key)
            if voice_id in catalog.get("voices_by_id", {}):
                return normalize_audiobook_tts_model(model_key)
        except Exception:
            continue
    
    # 默认返回 qwen3-tts-instruct-flash
    return DEFAULT_AUDIOBOOK_TTS_MODEL


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
    def _has_cosyvoice_v35_clone_voice() -> bool:
        try:
            clones, _ = list_cosyvoice_v3_plus_clones(page_size=1, cache_ttl_seconds=5.0)
        except Exception:
            return False
        return bool(clones)

    # 如果有用户偏好，优先使用
    if preferred_model:
        return normalize_audiobook_tts_model(preferred_model)
    
    # 根据角色重要性和成本优先级推荐模型
    if character_profile:
        importance = character_profile.get("importance_level", "")
        role_position = character_profile.get("role_position", "")
        
        # 主角/重要角色 → 高质量模型
        if importance in ["主角", "重要角色"] or role_position in ["主角", "女主角"]:
            if cost_priority != "low_cost":
                if _has_cosyvoice_v35_clone_voice():
                    return COSYVOICE_V35_PLUS_MODEL_ID
                return "minimax-speech-2.8-hd"
        
        # 次要角色 → 平衡模型
        if importance in ["次要角色"]:
            if cost_priority == "high_quality":
                return MINIMAX_SPEECH_28_HD_MODEL
            return DEFAULT_AUDIOBOOK_TTS_MODEL
        
        # 群众角色 → 低成本模型
        if importance in ["群众角色"]:
            return MINIMAX_SPEECH_28_TURBO_MODEL
    
    # 默认根据成本优先级返回
    if cost_priority == "high_quality":
        if _has_cosyvoice_v35_clone_voice():
            return COSYVOICE_V35_PLUS_MODEL_ID
        return MINIMAX_SPEECH_28_HD_MODEL
    elif cost_priority == "low_cost":
        return MINIMAX_SPEECH_28_TURBO_MODEL
    else:
        return DEFAULT_AUDIOBOOK_TTS_MODEL


def get_model_config(model: str) -> Dict[str, Any]:
    """获取模型配置信息"""
    normalized_model = normalize_audiobook_tts_model(model, default="")
    metadata = get_audiobook_tts_model_metadata(normalized_model)
    if metadata:
        return {
            "cost_level": metadata.get("cost_level", "unknown"),
            "quality_level": metadata.get("quality_level", "unknown"),
            "priority": metadata.get("priority", 99),
        }
    return MODEL_CONFIGS.get(model, {
        "cost_level": "unknown",
        "quality_level": "unknown",
        "priority": 99,
    })


def list_supported_models() -> list:
    """列出所有支持的模型"""
    return list_supported_audiobook_tts_models()


def list_auto_voice_assignment_models(preferred_model: Optional[str] = None) -> list[str]:
    """列出可用于自动分配角色声线的模型。

    只返回带系统音色目录的模型；需要用户先创建自定义音色的模型不参与自动兜底，
    避免推荐出无法直接合成的角色音色。
    """
    from .voice_catalog import load_voice_catalog_for_model

    preferred = normalize_audiobook_tts_model(preferred_model, default=DEFAULT_AUDIOBOOK_TTS_MODEL)
    ordered_models = [
        preferred,
        *[model for model in list_supported_audiobook_tts_models() if model != preferred],
    ]
    result: list[str] = []

    for model in ordered_models:
        metadata = get_audiobook_tts_model_metadata(model)
        capabilities = metadata.get("capabilities") or {}
        if not capabilities.get("has_system_voices", False):
            continue
        try:
            catalog = load_voice_catalog_for_model(model)
        except Exception:
            continue
        if catalog.get("voices"):
            result.append(normalize_audiobook_tts_model(model))

    return result


def list_all_models() -> list:
    """向后兼容 routes_tts 的旧函数名。"""
    return list_supported_models()


def create_voice_manager(tts_model: str, llm_client: Any = None):
    """根据TTS模型创建对应的声音管理器"""
    tts_model = normalize_audiobook_tts_model(tts_model)

    if tts_model == COSYVOICE_V35_PLUS_MODEL_ID:
        return CosyVoiceV3PlusVoiceManager()
    elif tts_model in {
        MINIMAX_SPEECH_28_HD_MODEL,
        MINIMAX_SPEECH_28_TURBO_MODEL,
    }:
        return MiniMaxVoiceManager(model=tts_model)
    elif tts_model in {
        MIMO_V25_TTS_MODEL,
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        MIMO_V25_TTS_VOICE_CLONE_MODEL,
    }:
        return MiMoVoiceManager(model=tts_model)
    elif tts_model == STEPAUDIO_25_TTS_MODEL:
        return StepAudioVoiceManager(model=tts_model)
    elif tts_model == SEED_TTS_20_EXPRESSIVE_MODEL:
        return SeedTTSVoiceManager(model=tts_model)
    return VoiceManager(llm_client=llm_client)
