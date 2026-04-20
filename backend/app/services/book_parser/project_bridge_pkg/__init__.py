"""Project bridge package."""

from app.services.book_parser.project_bridge_pkg._base import ProjectBridgeBase
from app.services.book_parser.project_bridge_pkg._character_import_mixin import CharacterImportMixin
from app.services.book_parser.project_bridge_pkg._character_sync_mixin import CharacterSyncMixin
from app.services.book_parser.project_bridge_pkg._settings_import_mixin import SettingsImportMixin
from app.services.book_parser.project_bridge_pkg._chapter_import_mixin import ChapterImportMixin
from app.services.book_parser.project_bridge_pkg._preview_mixin import PreviewMixin
from app.services.book_parser.project_bridge_pkg._memory_mixin import MemoryMixin
from app.services.book_parser.project_bridge_pkg._builders_mixin import BuildersMixin


class ProjectBridge(
    ProjectBridgeBase,
    CharacterImportMixin,
    CharacterSyncMixin,
    SettingsImportMixin,
    ChapterImportMixin,
    PreviewMixin,
    MemoryMixin,
    BuildersMixin,
):
    pass


__all__ = ["ProjectBridge"]
