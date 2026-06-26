from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for candidate in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _make_stored_entry(model_key: str) -> SimpleNamespace:
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        model_key=model_key,
        verification_status="verified",
        verification_scope="manual_review",
        verification_score=0.91,
        total_source_count=4,
        reachable_source_count=3,
        verified_source_count=2,
        verification_notes="人工校验已完成",
        last_synced_at=now,
        last_verified_at=now,
        updated_at=now,
        sources=[],
    )


def test_projected_catalog_prefers_latest_config_metadata_and_keeps_verification_state() -> None:
    from app.services.model_catalog_projection import build_projected_model_catalog_entries

    projected = build_projected_model_catalog_entries([_make_stored_entry("wan2.7-t2v")])
    by_key = {item["model_key"]: item for item in projected}

    target = by_key["wan2.7-t2v"]
    assert target["name"] == "Wan 2.7 Text-to-Video"
    assert target["summary"].startswith("项目当前归档的主力文生视频模型")
    assert target["verification_status"] == "verified"
    assert target["verification_scope"] == "manual_review"
    assert target["verification_notes"] == "人工校验已完成"
    assert target["total_source_count"] == 4


def test_projected_catalog_hides_stale_database_only_entries() -> None:
    from app.services.model_catalog_projection import build_projected_model_catalog_entries

    projected = build_projected_model_catalog_entries([_make_stored_entry("legacy-removed-model")])
    projected_keys = {item["model_key"] for item in projected}

    assert "legacy-removed-model" not in projected_keys
    assert len(projected) >= 42
    assert "qwen3-tts-instruct-flash" in projected_keys
    assert "mimo-v2.5-tts" in projected_keys
    assert "mimo-v2.5-tts-voicedesign" in projected_keys
    assert "mimo-v2.5-tts-voiceclone" in projected_keys
    assert "mimo-v2.5-tts-hd" not in projected_keys
    assert "mimo-v2.5-tts-turbo" not in projected_keys


def test_projected_catalog_detail_returns_none_for_non_integrated_model() -> None:
    from app.services.model_catalog_projection import build_projected_model_catalog_entry

    detail = build_projected_model_catalog_entry("legacy-removed-model", _make_stored_entry("legacy-removed-model"))
    assert detail is None


def test_projected_tts_catalog_exposes_model_aware_style_control_specs() -> None:
    from app.services.model_catalog_projection import build_projected_model_catalog_entries

    projected = build_projected_model_catalog_entries([])
    by_key = {item["model_key"]: item for item in projected}

    qwen_style_control = by_key["qwen3-tts-instruct-flash"]["detailed_specs"]["voice_synthesis"]["style_control"]
    assert qwen_style_control["model_family"] == "qwen"
    assert qwen_style_control["preferred_mode"] == "natural_language"
    assert [mode["id"] for mode in qwen_style_control["modes"]] == ["natural_language"]
    assert qwen_style_control["control_message_roles"]["natural_language"] == "parameters.instructions"
    assert qwen_style_control["supports_voice_description"] is True
    assert qwen_style_control["supports_audio_tags"] is False

    mimo_style_control = by_key["mimo-v2.5-tts"]["detailed_specs"]["voice_synthesis"]["style_control"]
    assert mimo_style_control["model_family"] == "mimo"
    assert mimo_style_control["preferred_mode"] == "director"
    assert [mode["id"] for mode in mimo_style_control["modes"]] == [
        "director",
        "audio_tags",
        "natural_language",
    ]
    assert mimo_style_control["control_message_roles"]["director"] == "user"
    assert mimo_style_control["control_message_roles"]["audio_tags"] == "assistant"
    assert mimo_style_control["supports_director_mode"] is True
    assert mimo_style_control["supports_audio_tags"] is True
    assert mimo_style_control["supports_emotion_mixing"] is True

    design_specs = by_key["mimo-v2.5-tts-voicedesign"]["detailed_specs"]["voice_synthesis"]
    assert design_specs["voice_design"]["enabled"] is True
    assert design_specs["voice_design"]["message_role"] == "user"
    assert design_specs["style_control"]["model_family"] == "mimo"
    assert [mode["id"] for mode in design_specs["style_control"]["modes"]] == [
        "voice_design",
        "natural_language",
    ]
    assert design_specs["style_control"]["preferred_mode"] == "voice_design"
    assert design_specs["style_control"]["supports_director_mode"] is False
    assert design_specs["style_control"]["supports_audio_tags"] is False

    clone_specs = by_key["mimo-v2.5-tts-voiceclone"]["detailed_specs"]["voice_synthesis"]
    assert clone_specs["voice_clone"]["enabled"] is True
    assert clone_specs["voice_clone"]["param_name"] == "audio.voice"
    assert clone_specs["style_control"]["model_family"] == "mimo"
