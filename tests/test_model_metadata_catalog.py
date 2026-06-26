from __future__ import annotations

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

    spec = registry.get_spec("qwen3-tts-instruct-flash")

    assert spec is not None
    assert spec.documentation_url.startswith("https://help.aliyun.com/")
    assert "audiobook" in spec.tags
    assert any("qwen-tts-api" in url for url in spec.source_urls)
    assert any("qwen-tts-voice-list" in url for url in spec.source_urls)


def test_qwen3_tts_instruct_flash_catalog_uses_official_voice_ids() -> None:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = {model["id"]: model for model in data["models"]}

    qwen = models["qwen3-tts-instruct-flash"]
    voice_synthesis = qwen["detailed_specs"]["voice_synthesis"]
    voices = [
        voice
        for category in voice_synthesis["voice_catalog"]["categories"]
        for voice in category["voices"]
    ]
    voice_ids = {voice["id"] for voice in voices}

    assert voice_ids == {
        "Arthur",
        "Bella",
        "Bellona",
        "Bunny",
        "Chelsie",
        "Cherry",
        "Eldric Sage",
        "Elias",
        "Ethan",
        "Kai",
        "Maia",
        "Mia",
        "Mochi",
        "Momo",
        "Moon",
        "Neil",
        "Nini",
        "Nofish",
        "Pip",
        "Seren",
        "Serena",
        "Stella",
        "Vincent",
        "Vivian",
    }
    assert voice_synthesis["voice_catalog"]["total_count"] == len(voice_ids)
    assert voice_synthesis["calling_method"]["param_name"] == "voice"
    assert "speaker=" not in voice_synthesis["calling_method"]["example"]
    assert "voice=\"Cherry\"" in voice_synthesis["calling_method"]["example"]


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

    model = models["stepaudio-2.5-tts"]

    assert model["provider"] == "stepfun"
    assert model["api_config"]["base_url"] == "https://api.stepfun.com/v1"
    assert model["api_config"]["endpoint"] == "/audio/speech"
    assert model["api_config"]["api_key_env"] == "STEP_API_KEY"
    assert model["api_config"]["auth_type"] == "bearer"
    assert model["constraints"]["max_input_chars"] == 1000
    assert model["constraints"]["instruction_max_chars"] == 200

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
    assert contextual_control["global_context"]["max_chars"] == 200
    assert contextual_control["inline_context"]["enabled"] is True
    assert contextual_control["inline_context"]["syntax"] == "圆括号()"

    voice_clone = voice_synthesis["voice_clone"]
    assert voice_clone["enabled"] is True
    assert voice_clone["preview_endpoint"] == "/audio/voices/preview"
    assert voice_clone["min_reference_audio_seconds"] == 3
    assert voice_clone["creates_asset"] is False


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

    loaded = registry.load_from_yaml(str(yaml_path))

    assert loaded == 1
    assert registry._specs["demo-image"].name == "Demo Image"


def test_catalog_files_exist() -> None:
    project_root = Path(__file__).parent.parent

    assert (project_root / "config" / "llm_models.yaml").exists()
    assert (project_root / "config" / "models.yaml").exists()
