from __future__ import annotations

import os
import pytest

from app.api.v1.dreamweaver_api._helpers_request_build import (
    _quality_mode_to_runtime_config,
    _build_dreamweaver_runtime_config_from_request,
)
from app.api.v1.dreamweaver_api._schemas import RunRequest


class TestQualityModeToRuntimeConfig:
    def test_quality_mode(self):
        image_cfg, qc_cfg, video_cfg = _quality_mode_to_runtime_config("quality")
        assert image_cfg["t2i_candidates"] == 2
        assert image_cfg["image_selector"] == "semantic"
        assert qc_cfg["enable_semantic_qc"] is True
        assert video_cfg["engine"] == "wan_auto"

    def test_cost_mode(self):
        image_cfg, qc_cfg, video_cfg = _quality_mode_to_runtime_config("cost")
        assert image_cfg["t2i_candidates"] == 1
        assert image_cfg["image_selector"] == "first"
        assert qc_cfg["enable_semantic_qc"] is False
        assert video_cfg["engine"] == "ffmpeg_slideshow"

    def test_unknown_mode_returns_empty(self):
        image_cfg, qc_cfg, video_cfg = _quality_mode_to_runtime_config("unknown")
        assert image_cfg == {}
        assert qc_cfg == {}
        assert video_cfg == {}

    def test_none_mode_returns_empty(self):
        image_cfg, qc_cfg, video_cfg = _quality_mode_to_runtime_config(None)
        assert image_cfg == {}
        assert qc_cfg == {}
        assert video_cfg == {}

    def test_empty_mode_returns_empty(self):
        image_cfg, qc_cfg, video_cfg = _quality_mode_to_runtime_config("")
        assert image_cfg == {}
        assert qc_cfg == {}
        assert video_cfg == {}

    def test_case_insensitive(self):
        image_cfg, _, _ = _quality_mode_to_runtime_config("Quality")
        assert image_cfg["t2i_candidates"] == 2

    def test_whitespace_trimmed(self):
        image_cfg, _, _ = _quality_mode_to_runtime_config("  quality  ")
        assert image_cfg["t2i_candidates"] == 2


class TestBuildDreamweaverRuntimeConfigFromRequest:
    def test_empty_request(self):
        req = RunRequest(project_id=1)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert "prompt_review_required" in config
        assert "video_config" in config

    def test_quality_mode_sets_configs(self):
        req = RunRequest(project_id=1, quality_mode="quality")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["quality_mode"] == "quality"
        assert config["image_config"]["t2i_candidates"] == 2
        assert config["qc_config"]["enable_semantic_qc"] is True
        assert config["video_config"]["engine"] == "wan_auto"

    def test_smart_tuning(self):
        req = RunRequest(project_id=1, smart_tuning=True)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["smart_tuning"] is True

    def test_smart_tuning_false(self):
        req = RunRequest(project_id=1, smart_tuning=False)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["smart_tuning"] is False

    def test_ab_variant(self):
        req = RunRequest(project_id=1, ab_variant="experiment_a")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["ab_variant"] == "experiment_a"

    def test_qc_allow_fail(self):
        req = RunRequest(project_id=1, qc_allow_fail=True)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["qc_config"]["allow_fail"] is True

    def test_style_preset(self):
        req = RunRequest(project_id=1, style_preset="cinematic_realistic")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["style_preset"] == "cinematic_realistic"

    def test_image_ratio(self):
        req = RunRequest(project_id=1, image_ratio="16:9")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["image_config"]["ratio"] == "16:9"

    def test_image_resolution(self):
        req = RunRequest(project_id=1, image_resolution="1080p")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["image_config"]["resolution"] == "1080p"

    def test_image_model(self):
        req = RunRequest(project_id=1, image_model="flux-pro")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["image_config"]["adapter"] == "flux-pro"

    def test_video_fps(self):
        req = RunRequest(project_id=1, video_fps=24)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["video_config"]["fps"] == 24

    def test_enable_safety_audit(self):
        req = RunRequest(project_id=1, enable_safety_audit=True)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["qc_config"]["enable_safety_audit"] is True

    def test_safety_fail_policy(self):
        req = RunRequest(project_id=1, safety_fail_policy="block")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["qc_config"]["safety_fail_policy"] == "block"

    def test_video_require_confirmation(self):
        req = RunRequest(project_id=1, video_require_confirmation=True)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["video_config"]["require_confirmation"] is True

    def test_enable_video_edit(self):
        req = RunRequest(project_id=1, enable_video_edit=True, video_edit_model="ve_model")
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["video_edit_config"]["enabled"] is True
        assert config["video_edit_config"]["adapter"] == "ve_model"

    def test_prompt_review_required_true(self):
        req = RunRequest(project_id=1, prompt_review_required=True)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["prompt_review_required"] is True
        assert config["prompt_review"]["approved"] is False

    def test_prompt_review_required_false(self):
        req = RunRequest(project_id=1, prompt_review_required=False)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["prompt_review_required"] is False
        assert "prompt_review" not in config

    def test_prompt_review_required_env_default(self):
        os.environ.pop("DREAMWEAVER_PROMPT_REVIEW_REQUIRED", None)
        req = RunRequest(project_id=1)
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["prompt_review_required"] is False

    def test_prompt_review_required_env_override(self):
        os.environ["DREAMWEAVER_PROMPT_REVIEW_REQUIRED"] = "true"
        try:
            req = RunRequest(project_id=1)
            config = _build_dreamweaver_runtime_config_from_request(req)
            assert config["prompt_review_required"] is True
        finally:
            os.environ.pop("DREAMWEAVER_PROMPT_REVIEW_REQUIRED", None)

    def test_combined_quality_and_overrides(self):
        req = RunRequest(
            project_id=1,
            quality_mode="quality",
            image_ratio="9:16",
            video_fps=24,
            qc_allow_fail=True,
        )
        config = _build_dreamweaver_runtime_config_from_request(req)
        assert config["quality_mode"] == "quality"
        assert config["image_config"]["ratio"] == "9:16"
        assert config["image_config"]["t2i_candidates"] == 2
        assert config["video_config"]["fps"] == 24
        assert config["qc_config"]["allow_fail"] is True
