"""模型模块初始化文件
"""
# 导出主要模型
from .user import User
from .project import Project
from .memory import Memory
from .setting import SettingCollection, SettingItem
from .character import Character, CharacterTechnique
from .review import Review
from .graph import KnowledgeGraphEdge

# 拆书工具模型
from .book_parser import (
    BookSource, 
    BookChapter, 
    BookAnalysis,
    SourceType,
    ParseStatus,
    AnalysisType
)

# 有声书模型
from .audiobook import AudiobookProject, ChapterAudio
from .audiobook_task import AudiobookTask
from .dreamweaver import DreamweaverProject, DreamweaverEpisode, DreamweaverShot, DreamweaverAsset, DreamweaverRunEvent

__all__ = [
    "User",
    "Project",
    "Memory",
    "SettingCollection",
    "SettingItem",
    "Character",
    "CharacterTechnique",
    "Review",
    "KnowledgeGraphEdge",
    # 拆书工具
    "BookSource",
    "BookChapter",
    "BookAnalysis",
    "SourceType",
    "ParseStatus",
    "AnalysisType",
    # 有声书
    "AudiobookProject",
    "ChapterAudio",
    "AudiobookTask",
    # 织梦映心（短剧/漫剧生产）
    "DreamweaverProject",
    "DreamweaverEpisode",
    "DreamweaverShot",
    "DreamweaverAsset",
    "DreamweaverRunEvent",
]
