"""
script_adapter_pkg - 有声剧本编剧Agent

将小说文本改编为适合音频化播放的有声剧本
"""
from ._dataclasses import (
    SoundEffect,
    MusicCue,
    ChapterOpening,
    ChapterClosing,
    ChapterStructure,
    ScriptSegment,
)
from ._base import AudiobookScriptAgentBase
from ._analysis import AnalysisMixin
from ._transform import TransformMixin
from ._merge import MergeMixin
from ._structure import StructureMixin


class AudiobookScriptAgent(
    AudiobookScriptAgentBase,
    AnalysisMixin,
    TransformMixin,
    MergeMixin,
    StructureMixin,
):
    """
    有声剧本编剧Agent
    
    基于专业编剧工作流程，将小说文本改编为适合音频化的剧本
    """
    pass


__all__ = [
    "AudiobookScriptAgent",
    "SoundEffect",
    "MusicCue",
    "ChapterOpening",
    "ChapterClosing",
    "ChapterStructure",
    "ScriptSegment",
]
