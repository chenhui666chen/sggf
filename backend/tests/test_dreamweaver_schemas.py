from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for p in (PROJECT_ROOT, BACKEND_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


from app.api.v1.dreamweaver_api._schemas import (
    RunRequest,
    LibraryApproveRequest,
    LibraryAssetProviderRefUpdateRequest,
    LibraryAssetProviderRefSyncRequest,
    LibraryRegenerateRequest,
    LibraryAutoRegenerateRolesRequest,
    LibraryPromptSuggestRequest,
    RestartAsyncRequest,
    ShotFramePromptUpdateRequest,
    ShotVideoPromptUpdateRequest,
    ScriptUpdateRequest,
    ScriptApproveRequest,
    PromptReviewApproveRequest,
)


class TestRunRequest:
    def test_minimal(self):
        req = RunRequest(project_id=1)
        assert req.project_id == 1
        assert req.chapter_ids == []
        assert req.quality_mode is None

    def test_with_chapter_ids(self):
        req = RunRequest(project_id=1, chapter_ids=[10, 20, 30])
        assert req.chapter_ids == [10, 20, 30]

    def test_quality_mode_quality(self):
        req = RunRequest(project_id=1, quality_mode="quality")
        assert req.quality_mode == "quality"

    def test_quality_mode_cost(self):
        req = RunRequest(project_id=1, quality_mode="cost")
        assert req.quality_mode == "cost"

    def test_quality_mode_invalid(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RunRequest(project_id=1, quality_mode="fast")

    def test_safety_fail_policy_valid(self):
        req = RunRequest(project_id=1, safety_fail_policy="warn")
        assert req.safety_fail_policy == "warn"
        req = RunRequest(project_id=1, safety_fail_policy="block")
        assert req.safety_fail_policy == "block"

    def test_safety_fail_policy_invalid(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RunRequest(project_id=1, safety_fail_policy="ignore")

    def test_video_fps_range(self):
        req = RunRequest(project_id=1, video_fps=30)
        assert req.video_fps == 30

    def test_video_fps_too_low(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RunRequest(project_id=1, video_fps=0)

    def test_video_fps_too_high(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RunRequest(project_id=1, video_fps=61)


class TestLibraryApproveRequest:
    def test_defaults(self):
        req = LibraryApproveRequest()
        assert req.approve_all is False
        assert req.roles == []
        assert req.approved is True

    def test_approve_all_with_roles(self):
        req = LibraryApproveRequest(approve_all=True, roles=["character:1:front"], approved=True)
        assert req.approve_all is True
        assert len(req.roles) == 1


class TestLibraryAssetProviderRefUpdateRequest:
    def test_defaults(self):
        req = LibraryAssetProviderRefUpdateRequest()
        assert req.provider == "kling"
        assert req.subject_id is None
        assert req.source_asset_uri is None

    def test_with_subject_id(self):
        req = LibraryAssetProviderRefUpdateRequest(subject_id="abc123")
        assert req.subject_id == "abc123"

    def test_subject_id_max_length(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LibraryAssetProviderRefUpdateRequest(subject_id="x" * 129)

    def test_invalid_provider(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LibraryAssetProviderRefUpdateRequest(provider="openai")


class TestLibraryAssetProviderRefSyncRequest:
    def test_defaults(self):
        req = LibraryAssetProviderRefSyncRequest()
        assert req.provider == "kling"
        assert req.include_related_views is True
        assert req.timeout_s == 90.0
        assert req.poll_interval_s == 2.0

    def test_timeout_range(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LibraryAssetProviderRefSyncRequest(timeout_s=4.0)
        with pytest.raises(ValidationError):
            LibraryAssetProviderRefSyncRequest(timeout_s=301.0)

    def test_poll_interval_range(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LibraryAssetProviderRefSyncRequest(poll_interval_s=0.1)
        with pytest.raises(ValidationError):
            LibraryAssetProviderRefSyncRequest(poll_interval_s=11.0)


class TestLibraryRegenerateRequest:
    def test_required_field(self):
        req = LibraryRegenerateRequest(role="character:1:front")
        assert req.role == "character:1:front"
        assert req.run_id is None
        assert req.prompt is None

    def test_all_fields(self):
        req = LibraryRegenerateRequest(
            role="scene:2",
            run_id="run-abc",
            prompt="a beautiful scene",
            style_preset="cinematic_realistic",
            image_ratio="16:9",
            image_resolution="1080p",
            prefer_image_edit=True,
            prefer_view_chain_edit_base=False,
        )
        assert req.role == "scene:2"
        assert req.prefer_image_edit is True


class TestLibraryAutoRegenerateRolesRequest:
    def test_defaults(self):
        req = LibraryAutoRegenerateRolesRequest()
        assert req.run_id is None
        assert req.character_ids == []

    def test_with_character_ids(self):
        req = LibraryAutoRegenerateRolesRequest(character_ids=[1, 2, 3])
        assert req.character_ids == [1, 2, 3]


class TestLibraryPromptSuggestRequest:
    def test_required_field(self):
        req = LibraryPromptSuggestRequest(role="character:1:front")
        assert req.role == "character:1:front"
        assert req.mode == "template"

    def test_mode_ai(self):
        req = LibraryPromptSuggestRequest(role="scene:1", mode="ai")
        assert req.mode == "ai"

    def test_invalid_mode(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LibraryPromptSuggestRequest(role="scene:1", mode="custom")


class TestRestartAsyncRequest:
    def test_required_field(self):
        req = RestartAsyncRequest(start_state="SCRIPT_APPROVAL")
        assert req.start_state == "SCRIPT_APPROVAL"
        assert req.reset_policy == "downstream"

    def test_reset_policy_none(self):
        req = RestartAsyncRequest(start_state="INIT", reset_policy="none")
        assert req.reset_policy == "none"

    def test_invalid_reset_policy(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RestartAsyncRequest(start_state="INIT", reset_policy="all")

    def test_empty_start_state(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RestartAsyncRequest(start_state="")


class TestShotFramePromptUpdateRequest:
    def test_valid_prompt(self):
        req = ShotFramePromptUpdateRequest(prompt="a beautiful landscape")
        assert req.prompt == "a beautiful landscape"

    def test_empty_prompt(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ShotFramePromptUpdateRequest(prompt="")

    def test_too_long_prompt(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ShotFramePromptUpdateRequest(prompt="x" * 2001)


class TestShotVideoPromptUpdateRequest:
    def test_optional_prompt(self):
        req = ShotVideoPromptUpdateRequest()
        assert req.prompt is None

    def test_with_prompt(self):
        req = ShotVideoPromptUpdateRequest(prompt="cinematic shot")
        assert req.prompt == "cinematic shot"


class TestScriptUpdateRequest:
    def test_valid(self):
        req = ScriptUpdateRequest(script_text="INT. ROOM - DAY")
        assert req.script_text == "INT. ROOM - DAY"

    def test_empty(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ScriptUpdateRequest(script_text="")


class TestScriptApproveRequest:
    def test_default(self):
        req = ScriptApproveRequest()
        assert req.approved is True

    def test_reject(self):
        req = ScriptApproveRequest(approved=False)
        assert req.approved is False


class TestPromptReviewApproveRequest:
    def test_default(self):
        req = PromptReviewApproveRequest()
        assert req.approved is True

    def test_reject(self):
        req = PromptReviewApproveRequest(approved=False)
        assert req.approved is False
