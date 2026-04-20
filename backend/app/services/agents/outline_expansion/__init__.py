"""Outline expansion package - split from outline_expander.py using Mixin pattern."""
from ._constants import *
from ._base import OutlineExpanderBase
from ._legacyoutline import LegacyOutlineMixin
from ._characterexpansion import CharacterExpansionMixin
from ._epicframework import EpicFrameworkMixin
from ._volumedetail import VolumeDetailMixin
from ._storyhelper import StoryHelperMixin
from ._volumeparser import VolumeParserMixin
from ._rendering import RenderingMixin
from ._incrementalexpansion import IncrementalExpansionMixin


class OutlineExpander(
    OutlineExpanderBase,
    LegacyOutlineMixin,
    CharacterExpansionMixin,
    EpicFrameworkMixin,
    VolumeDetailMixin,
    StoryHelperMixin,
    VolumeParserMixin,
    RenderingMixin,
    IncrementalExpansionMixin,
):
    """Outline expander - composed from mixin classes."""
    pass


def create_outline_expander(knowledge_base=None, memory_manager=None, genre="", planned_chapters_max=0, project_id=None):
    """Factory function for creating OutlineExpander instances."""
    expander = OutlineExpander(knowledge_base, memory_manager, genre, planned_chapters_max)
    if project_id is not None:
        expander.set_project_context(project_id)
    return expander


__all__ = ["OutlineExpander", "create_outline_expander"]
