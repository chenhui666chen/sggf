from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_unified_model_spec_metadata_roundtrip() -> None:
    from schemas.unified_model_spec import ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="meta-llm",
        name="Meta LLM",
        provider="test",
        model_type=ModelType.LLM,
        summary="summary",
        recommended_scenarios=["scenario-a"],
        limitations=["limit-a"],
        integration_notes=["note-a"],
        source_urls=["https://example.com/spec"],
    )

    data = spec.to_dict()

    assert data["summary"] == "summary"
    assert data["recommended_scenarios"] == ["scenario-a"]
    assert data["limitations"] == ["limit-a"]
    assert data["integration_notes"] == ["note-a"]
    assert data["source_urls"] == ["https://example.com/spec"]


def test_model_spec_metadata_roundtrip() -> None:
    from schemas.model_spec import ModelSpec

    spec = ModelSpec.from_dict(
        {
            "id": "meta-image",
            "name": "Meta Image",
            "provider": "test",
            "summary": "image summary",
            "recommended_scenarios": ["preview"],
            "limitations": ["slow"],
            "integration_notes": ["project note"],
            "source_urls": ["https://example.com/image"],
        }
    )

    data = spec.to_dict()

    assert spec.summary == "image summary"
    assert data["recommended_scenarios"] == ["preview"]
    assert data["limitations"] == ["slow"]
    assert data["integration_notes"] == ["project note"]
    assert data["source_urls"] == ["https://example.com/image"]


def test_model_registry_auto_loads_catalog_yaml() -> None:
    from adapters.registry import ModelRegistry

    registry = ModelRegistry()
    registry.clear()

    spec = registry.get_spec("qwen-audio-3.1-tts-flash")

    assert spec is not None
    assert spec.documentation_url.startswith("https://help.aliyun.com/")
    assert "audiobook" in spec.tags
    assert any("qwen-audio-tts" in url for url in spec.source_urls)
    assert any("qwen-audio-tts-voice-list" in url for url in spec.source_urls)


def test_qwen_audio_31_tts_catalog_uses_official_voice_ids() -> None:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = {model["id"]: model for model in data["models"]}

    qwen = models["qwen-audio-3.1-tts-flash"]
    voice_synthesis = qwen["detailed_specs"]["voice_synthesis"]
    voices = [
        voice
        for category in voice_synthesis["voice_catalog"]["categories"]
        for voice in category["voices"]
    ]
    voice_ids = {voice["id"] for voice in voices}

    # 3.1 官方系统角色统一带 _v3.1 后缀，且与已退役的 Qwen-TTS 音色体系不互通
    assert all(voice_id.endswith("_v3.1") for voice_id in voice_ids)
    assert {"longsanshu_v3.1", "yeqinghe_v3.1", "longxiaoxia_v3.1"}.issubset(voice_ids)
    assert voice_synthesis["voice_catalog"]["total_count"] == len(voice_ids) == 68
    assert voice_synthesis["voice_catalog_source"] == "shared/qwen_audio_3_1_tts_voices.json"
    assert voice_synthesis["calling_method"]["param_name"] == "input.voice"
    assert "speaker=" not in voice_synthesis["calling_method"]["example"]
    assert '"voice": "longsanshu_v3.1"' in voice_synthesis["calling_method"]["example"]


def test_mimo_v25_tts_catalog_uses_official_model_line_and_voice_ids() -> None:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = {model["id"]: model for model in data["models"]}

    assert "mimo-v2.5-tts-hd" not in models
    assert "mimo-v2.5-tts-turbo" not in models
    assert {"mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"}.issubset(models)

    preset = models["mimo-v2.5-tts"]
    assert preset["api_config"]["base_url"] == "https://api.xiaomimimo.com/v1"
    assert preset["api_config"]["endpoint"] == "/chat/completions"
    assert preset["api_config"]["api_key_env"] == "MIMO_API_KEY"
    voice_synthesis = preset["detailed_specs"]["voice_synthesis"]
    voices = [
        voice
        for category in voice_synthesis["voice_catalog"]["categories"]
        for voice in category["voices"]
    ]
    assert {voice["id"] for voice in voices} == {
        "mimo_default",
        "冰糖",
        "茉莉",
        "苏打",
        "白桦",
        "Mia",
        "Chloe",
        "Milo",
        "Dean",
    }
    assert voice_synthesis["voice_catalog"]["total_count"] == 9
    assert voice_synthesis["calling_method"]["param_name"] == "audio.voice"

    design = models["mimo-v2.5-tts-voicedesign"]["detailed_specs"]["voice_synthesis"]
    assert design["voice_design"]["enabled"] is True
    assert design["voice_design"]["message_role"] == "user"
    assert design["voice_catalog"]["total_count"] == 0
    assert "director-mode" not in models["mimo-v2.5-tts-voicedesign"]["tags"]
    assert "voice-design-prompt" in models["mimo-v2.5-tts-voicedesign"]["tags"]
    assert {item["name"] for item in models["mimo-v2.5-tts-voicedesign"]["capabilities"]} >= {
        "voice_design",
        "voice_design_style_instruction",
    }
    assert "director_style_control" not in {
        item["name"] for item in models["mimo-v2.5-tts-voicedesign"]["capabilities"]
    }

    clone = models["mimo-v2.5-tts-voiceclone"]["detailed_specs"]["voice_synthesis"]
    assert clone["voice_clone"]["enabled"] is True
    assert clone["voice_clone"]["param_name"] == "audio.voice"
    assert clone["voice_clone"]["max_base64_size_mb"] == 10
    assert clone["voice_catalog"]["total_count"] == 0


def test_stepaudio_25_tts_catalog_exposes_contextual_tts_contract() -> None:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = {model["id"]: model for model in data["models"]}

    model = models["stepaudio-3-tts"]

    assert model["provider"] == "stepfun"
    assert model["api_config"]["base_url"] == "https://api.stepfun.com/v1"
    assert model["api_config"]["endpoint"] == "/audio/speech"
    assert model["api_config"]["api_key_env"] == "STEP_API_KEY"
    assert model["api_config"]["auth_type"] == "bearer"
    assert model["constraints"]["max_input_chars"] == 1000
    assert model["constraints"]["instruction_max_chars"] == 500

    voice_synthesis = model["detailed_specs"]["voice_synthesis"]
    assert voice_synthesis["calling_method"]["param_name"] == "voice"
    assert "voice_label" not in voice_synthesis["calling_method"]["example"]
    assert "\"voice\": \"cixingnansheng\"" in voice_synthesis["calling_method"]["example"]
    voices = [
        voice
        for category in voice_synthesis["voice_catalog"]["categories"]
        for voice in category["voices"]
    ]
    voice_ids = {voice["id"] for voice in voices}
    assert voice_synthesis["voice_catalog"]["total_count"] == 36
    assert {
        "vibrant-youth",
        "lively-girl",
        "soft-spoken-gentleman",
        "magnetic-voiced-male",
        "cixingnansheng",
        "wenrounvsheng",
        "shuangkuainansheng",
        "huolinvsheng",
    }.issubset(voice_ids)

    contextual_control = voice_synthesis["contextual_control"]
    assert contextual_control["global_context"]["enabled"] is True
    assert contextual_control["global_context"]["param_name"] == "instruction"
    assert contextual_control["global_context"]["max_chars"] == 500
    assert contextual_control["inline_context"]["enabled"] is True
    assert contextual_control["inline_context"]["syntax"] == "圆括号()"

    voice_clone = voice_synthesis["voice_clone"]
    assert voice_clone["enabled"] is True
    assert voice_clone["preview_endpoint"] == "/audio/voices/preview"
    assert voice_clone["min_reference_audio_seconds"] == 3
    assert voice_clone["creates_asset"] is False


def test_qwen_audio_31_tts_catalog_matches_runtime_voice_list() -> None:
    project_root = Path(__file__).parent.parent
    data = yaml.safe_load((project_root / "config" / "models.yaml").read_text(encoding="utf-8"))
    models = {model["id"]: model for model in data["models"]}

    model = models["qwen-audio-3.1-tts-flash"]

    assert model["provider"] == "alibaba"
    assert "text_to_speech" in model["modality"]
    assert model["api_config"]["base_url"] == "https://dashscope.aliyuncs.com"
    assert model["api_config"]["endpoint"] == "/api/v1/services/audio/tts/SpeechSynthesizer"
    assert model["api_config"]["api_key_env"] == "DASHSCOPE_API_KEY"
    # 服务商按 token 计价，档案里的万字价是实测折算值，不是官方刊例价。
    assert model["cost_profile"]["pricing_basis"] == "derived_from_token_price"

    voice_synthesis = model["detailed_specs"]["voice_synthesis"]
    assert voice_synthesis["calling_method"]["param_name"] == "input.voice"
    assert voice_synthesis["instruction_control"]["project_budget_chars"] == 1200

    catalog = voice_synthesis["voice_catalog"]
    voices = [voice for category in catalog["categories"] for voice in category["voices"]]
    voice_ids = {voice["id"] for voice in voices}
    assert catalog["total_count"] == len(voice_ids) == 68
    assert all(voice_id.endswith("_v3.1") for voice_id in voice_ids)
    assert "longsanshu_v3.1" in voice_ids

    runtime_ids = {
        voice["id"]
        for voice in json.loads(
            (project_root / "shared" / "qwen_audio_3_1_tts_voices.json").read_text(encoding="utf-8")
        )["voices"]
    }
    assert voice_ids == runtime_ids


def test_model_registry_load_from_yaml_does_not_reenter_bootstrap(monkeypatch, tmp_path: Path) -> None:
    from adapters.registry import ModelRegistry

    registry = ModelRegistry()
    registry.clear()

    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text(
        """
models:
  - id: demo-image
    name: Demo Image
    provider: demo
    modality:
      - text_to_image
""".strip(),
        encoding="utf-8",
    )

    def _should_not_run() -> None:
        raise AssertionError("_ensure_builtin_registration should not be called from load_from_yaml")

    monkeypatch.setattr(registry, "_ensure_builtin_registration", _should_not_run)

    try:
        loaded = registry.load_from_yaml(str(yaml_path))

        assert loaded == 1
        assert registry._specs["demo-image"].name == "Demo Image"
    finally:
        # 注册中心是共享单例：残留的 demo-image 会让 _specs 非空，
        # 后续 _ensure_builtin_registration 因此跳过 reload 分支，适配器类再也注册不回来。
        # 清空即可让下一个调用方重新走完整 bootstrap。
        monkeypatch.undo()
        registry.clear()


def test_catalog_files_exist() -> None:
    project_root = Path(__file__).parent.parent

    assert (project_root / "config" / "llm_models.yaml").exists()
    assert (project_root / "config" / "models.yaml").exists()
