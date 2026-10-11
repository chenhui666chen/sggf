"""
有声小说专业Agent模块

包含5个专业化Agent：
1. AudioDirector - 有声导演/总监
2. AudiobookScriptAdapter - 有声剧本编剧（已在上层实现）
3. SoundEffectDesigner - 音效设计师
4. MusicComposer - 音乐设计师
5. AudioQualityReviewer - 音频质量评审官
"""

from .audio_director import AudioDirector
from .sound_effect_designer import SoundEffectDesigner
from .music_composer import MusicComposer
from .audio_quality_reviewer import AudioQualityReviewer
from .llm_quality_reviewer import LLMQualityReviewer

__all__ = [
    "AudioDirector",
    "SoundEffectDesigner",
    "MusicComposer",
    "AudioQualityReviewer",
    "LLMQualityReviewer",
]
