"""Audiobook engine package."""

from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
from app.services.audiobook.engine_pkg._generation_mixin import GenerationMixin
from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin
from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin
from app.services.audiobook.engine_pkg._timeline_mixin import TimelineMixin
from app.services.audiobook.engine_pkg._sfx_mixin import SfxMixin
from app.services.audiobook.engine_pkg._music_mixin import MusicMixin
from app.services.audiobook.engine_pkg._review_mixin import ReviewMixin
from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin
from app.services.audiobook.engine_pkg._task_mixin import TaskMixin
from app.services.audiobook.engine_pkg._script_prep_mixin import ScriptPrepMixin
from app.services.audiobook.engine_pkg._audio_from_script_mixin import AudioFromScriptMixin
from app.services.audiobook.engine_pkg._project_mixin import ProjectMixin


class AudiobookEngine(
    AudiobookEngineBase,
    GenerationMixin,
    ScriptUtilsMixin,
    TTSMixin,
    TimelineMixin,
    SfxMixin,
    MusicMixin,
    ReviewMixin,
    ParallelMixin,
    TaskMixin,
    ScriptPrepMixin,
    AudioFromScriptMixin,
    ProjectMixin,
):
    pass


__all__ = ["AudiobookEngine"]
