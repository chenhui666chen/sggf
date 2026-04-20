"""Story expansion coordinator package."""

from app.services.story_expansion_coord_pkg._base import StoryExpansionCoordinatorBase
from app.services.story_expansion_coord_pkg._estimation_mixin import EstimationMixin
from app.services.story_expansion_coord_pkg._planning_mixin import PlanningMixin
from app.services.story_expansion_coord_pkg._alignment_mixin import AlignmentMixin
from app.services.story_expansion_coord_pkg._execution_mixin import ExecutionMixin


class StoryExpansionCoordinator(
    StoryExpansionCoordinatorBase,
    EstimationMixin,
    PlanningMixin,
    AlignmentMixin,
    ExecutionMixin,
):
    pass


from app.services.story_expansion_coord_pkg._standalone import (
    OutlineBlock,
    normalize_character_name,
    parse_outline_blocks,
    render_outline,
    render_outline_with_original_numbers,
    normalize_outline_title,
    normalize_outline_text,
    extract_character_names,
    extract_character_blocks,
    build_delta_section_title,
    merge_character_delta,
    build_outline_delta_section,
    sanitize_outline_alignment_placeholders,
    is_character_alignment_placeholder_line,
    evaluate_story_coordination,
)

__all__ = [
    "StoryExpansionCoordinator",
    "OutlineBlock",
    "normalize_character_name",
    "parse_outline_blocks",
    "render_outline",
    "render_outline_with_original_numbers",
    "normalize_outline_title",
    "normalize_outline_text",
    "extract_character_names",
    "extract_character_blocks",
    "build_delta_section_title",
    "merge_character_delta",
    "build_outline_delta_section",
    "sanitize_outline_alignment_placeholders",
    "is_character_alignment_placeholder_line",
    "evaluate_story_coordination",
]
