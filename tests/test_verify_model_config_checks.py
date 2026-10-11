# -*- coding: utf-8 -*-
"""verify_model_config.py 的检查项必须对齐 intent_domains.yaml 的真实结构。

背景：config/intent_domains.yaml 的顶层是 `domains: {wan, tts, runway, kling}` + `common`，
每个 domain 用 `modalities` 声明它覆盖哪些生成模态，**没有任何模型 ID 清单**。
但 check_video_models_in_tags 去读 `domains["video_generation"]["models"]`，
这个键从来不存在，于是 registered_video_models 恒为空集，models.yaml 里每一个视频模型
都会被误报「未注册」。同理 check_camera_terms 读的 `camera_control.terms` 也不存在，
它比对的 CAMERA_VOCABULARY 在 core/semantic_matcher.py 里同样不存在（那边只有
STYLE_VOCABULARY 和 SCENARIO_VOCABULARY），所以该检查恒为空转、恒不报警。

修正方向：把检查 4 换成 intent_domains.yaml 真正能保证的不变量——
models.yaml 用到的每个视频模态，至少要被某个 domain 的 modalities 声明过，
否则意图路由拿到该模态时无词表可用。
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "scripts" / "verify_model_config.py"


def _load_module():
    module_name = "test_verify_model_config_module"
    spec = spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 verify_model_config.py")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


verify_model_config = _load_module()


def _domains(*modalities_per_domain):
    return {
        f"domain{i}": {"modalities": {m: m for m in mods}}
        for i, mods in enumerate(modalities_per_domain)
    }


def _model(model_id, modality):
    return {"id": model_id, "modality": [modality], "tags": []}


class TestVideoModalityCoverage:
    def test_declared_modality_passes(self) -> None:
        issues = verify_model_config.Issues()
        verify_model_config.check_video_modality_coverage(
            _domains({"text_to_video", "image_to_video"}),
            [_model("wan3.0-video", "text_to_video")],
            issues,
        )
        assert issues.warnings == []

    def test_undeclared_modality_warns_once_naming_model_and_modality(self) -> None:
        issues = verify_model_config.Issues()
        verify_model_config.check_video_modality_coverage(
            _domains({"text_to_video"}),
            [_model("some-model", "video_to_video")],
            issues,
        )
        assert len(issues.warnings) == 1
        assert "some-model" in issues.warnings[0]
        assert "video_to_video" in issues.warnings[0]

    def test_non_video_models_are_ignored(self) -> None:
        issues = verify_model_config.Issues()
        verify_model_config.check_video_modality_coverage(
            _domains({"text_to_video"}),
            [_model("qwen-image-3.0", "text_to_image"), _model("cosyvoice", "text_to_speech")],
            issues,
        )
        assert issues.warnings == []

    def test_secondary_modality_entries_are_also_checked(self) -> None:
        issues = verify_model_config.Issues()
        verify_model_config.check_video_modality_coverage(
            _domains({"text_to_video"}),
            [{"id": "multi", "modality": ["text_to_video", "image_to_video"], "tags": []}],
            issues,
        )
        assert len(issues.warnings) == 1
        assert "image_to_video" in issues.warnings[0]


class TestRealConfigHasNoBogusVideoWarning:
    """回归护栏：当前仓库的真实配置下，13 个视频模型一个都不该被误报。"""

    def test_load_all_domains_exposes_every_domain(self) -> None:
        # load_domains() 只返回 wan domain（供风格词表检查用），
        # 模态覆盖检查需要跨 domain 汇总，因此必须另有加载器
        all_domains = verify_model_config.load_all_domains()
        assert {"wan", "tts", "runway", "kling"} <= set(all_domains)
        assert all(isinstance(d, dict) for d in all_domains.values())

    def test_no_warning_for_shipped_config(self) -> None:
        issues = verify_model_config.Issues()
        verify_model_config.check_video_modality_coverage(
            verify_model_config.load_all_domains(),
            verify_model_config.load_models(),
            issues,
        )
        assert issues.warnings == []

    def test_shipped_config_actually_has_video_models(self) -> None:
        models = verify_model_config.load_models()
        video_ids = [
            m["id"]
            for m in models
            if set(m.get("modality", [])) & {"text_to_video", "image_to_video", "video_to_video"}
        ]
        assert "wan3.0-video" in video_ids
        assert len(video_ids) >= 10


class TestDeadCameraCheckRemoved:
    def test_camera_check_is_gone(self) -> None:
        # 它比对的 CAMERA_VOCABULARY 在 semantic_matcher.py 里不存在，留着只会恒空转
        assert not hasattr(verify_model_config, "check_camera_terms")

    def test_matcher_has_no_camera_vocabulary(self) -> None:
        matcher_src = (ROOT_DIR / "core" / "semantic_matcher.py").read_text(encoding="utf-8")
        assert "CAMERA_VOCABULARY" not in matcher_src
