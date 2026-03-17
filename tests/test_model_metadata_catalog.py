from __future__ import annotations

from pathlib import Path


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

    spec = registry.get_spec("qwen3-tts-flash")

    assert spec is not None
    assert spec.documentation_url.startswith("https://help.aliyun.com/")
    assert "audiobook" in spec.tags
    assert any("text-to-speech" in url for url in spec.source_urls)


def test_catalog_files_exist() -> None:
    project_root = Path(__file__).parent.parent

    assert (project_root / "config" / "llm_models.yaml").exists()
    assert (project_root / "config" / "models.yaml").exists()
