"""
有声书生成服务模块

核心组件：
- AudiobookEngine: 有声书生成引擎（主入口）
- TextParser: 文本解析器（对话/旁白分离）
- VoiceManager: 音色管理器（角色音色映射）
- TTSEngine: TTS语音合成引擎
- AudioMixer: 音频混合器
"""

from .engine import AudiobookEngine
from .text_parser import TextParser
from .voice_manager import VoiceManager, VoiceProfile
from .tts_engine import TTSEngine
from .audio_mixer import AudioMixer

# 全局Engine实例（用于任务状态查询）
# ⚠️ 重要：reload时会重置为None，强制重建实例
# 每次模块加载时重置，确保使用最新配置
_global_engine_instance = None


def get_engine_instance() -> AudiobookEngine:
    """
    获取全局Engine实例
    
    用于任务状态查询API
    """
    global _global_engine_instance
    if _global_engine_instance is None:
        # 🆕 创建LLM客户端用于初始化引擎
        from core.unified_llm_client import get_llm_client
        llm_client = get_llm_client()
        _global_engine_instance = AudiobookEngine(llm_client=llm_client)
    return _global_engine_instance


def set_engine_instance(engine: AudiobookEngine):
    """
    设置全局Engine实例
    
    用于后台任务中
    """
    global _global_engine_instance
    _global_engine_instance = engine

__all__ = [
    "AudiobookEngine",
    "TextParser",
    "VoiceManager",
    "VoiceProfile",
    "TTSEngine",
    "AudioMixer",
    "get_engine_instance",
    "set_engine_instance",
]

