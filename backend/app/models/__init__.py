"""模型模块初始化文件"""

from .user import User
from .project import Project
from .memory import Memory
from .setting import SettingCollection, SettingItem
from .character import Character, CharacterTechnique
from .review import Review
from .graph import KnowledgeGraphEdge
from .role import Role, Permission, user_roles, role_permissions
from .admin_log import AdminOperationLog, AdminLoginLog
from .book_parser import BookSource, BookChapter, BookAnalysis, SourceType, ParseStatus, AnalysisType
from .audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from .audiobook_delete_audit import AudiobookDeleteAudit
from .audiobook_task import AudiobookTask
from .dreamweaver import DreamweaverProject, DreamweaverEpisode, DreamweaverShot, DreamweaverAsset, DreamweaverRunEvent
from .model_catalog import ModelCatalogEntry, ModelCatalogSource
from .user_asset_record import UserAssetRecord
from .generation_feedback import GenerationFeedback
from .audio_library_asset import AudioLibraryAsset
from .audio_library_asset_rating import AudioLibraryAssetRating

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
    "Role",
    "Permission",
    "user_roles",
    "role_permissions",
    "AdminOperationLog",
    "AdminLoginLog",
    "BookSource",
    "BookChapter",
    "BookAnalysis",
    "SourceType",
    "ParseStatus",
    "AnalysisType",
    "AudiobookProject",
    "ChapterAudio",
    "ChapterAudioRun",
    "AudiobookDeleteAudit",
    "AudiobookTask",
    "DreamweaverProject",
    "DreamweaverEpisode",
    "DreamweaverShot",
    "DreamweaverAsset",
    "DreamweaverRunEvent",
    "ModelCatalogEntry",
    "ModelCatalogSource",
    "UserAssetRecord",
    "GenerationFeedback",
    "AudioLibraryAsset",
    "AudioLibraryAssetRating",
]
