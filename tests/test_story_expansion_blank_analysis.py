from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import backend.app.api.v1.workflow as workflow
from backend.app.services.story_expansion_coordinator import StoryExpansionCoordinator


def test_validate_expand_story_request_allows_empty_targets_in_analysis_mode() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1章：开场\n- 主要内容：主角入城。",
        world_setting="蒸汽仙侠世界",
        characters="",
        expansion_mode="total",
        target_total_chapters=None,
        target_total_characters=None,
    )

    with pytest.raises(workflow.HTTPException):
        workflow._validate_expand_story_request(request)

    workflow._validate_expand_story_request(request, allow_empty_targets_for_analysis=True)


def test_analyze_expansion_request_estimates_targets_when_both_blank() -> None:
    coordinator = StoryExpansionCoordinator(project_id=1, genre="", planned_chapters_max=0)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：开场\n- 主要内容：主角入城。",
        characters="",
        world_setting="",
        target_total_chapters=None,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="total",
    )

    assert analysis["auto_supplement_applied"] is True
    assert int(analysis["auto_supplement"]["chapter_delta"] or 0) > 0
    assert int(analysis["auto_supplement"]["character_delta"] or 0) > 0
    assert int(analysis["effective_target_chapter_count"] or 0) > 0
    assert int(analysis["effective_target_character_count"] or 0) > 0
