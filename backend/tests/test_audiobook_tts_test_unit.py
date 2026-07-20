from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


def test_catalog_covers_every_supported_model_without_project_context() -> None:
    from app.services.audiobook.tts_model_ids import list_supported_audiobook_tts_models
    from app.services.audiobook.tts_test_unit import build_tts_test_catalog

    catalog = build_tts_test_catalog()

    assert [entry["model"] for entry in catalog] == list_supported_audiobook_tts_models()
    assert all(entry["cases"] for entry in catalog)
    for entry in catalog:
        for case in entry["cases"]:
            assert case["model"] == entry["model"]
            assert case["text"]
            assert case["provider_prompt_snapshot"]["model"] == entry["model"]
            assert "project_id" not in case
            assert "chapter_id" not in case


def test_model_cases_compile_to_their_native_prompt_surfaces() -> None:
    from app.services.audiobook.tts_test_unit import get_tts_test_case

    qwen = get_tts_test_case("qwen3-tts-instruct-flash", "emotion_pause_stress")
    cosy = get_tts_test_case("cosyvoice-v3.5-plus", "compact_emotion_cues")
    minimax = get_tts_test_case("minimax-speech-2.8-hd", "basic_prosody")
    mimo = get_tts_test_case("mimo-v2.5-tts", "audio_tag_leak")
    stepaudio = get_tts_test_case("stepaudio-2.5-tts", "global_and_inline_context")
    seed = get_tts_test_case("seed-tts-2.0-expressive", "query_response_tags")

    qwen_prompt = qwen["provider_prompt_snapshot"]["provider_prompt"]
    assert qwen["style_control_mode"] == "natural_language"
    assert "情绪目标" in qwen_prompt["instructions"]
    assert "重读词" in qwen_prompt["instructions"]

    cosy_prompt = cosy["provider_prompt_snapshot"]["provider_prompt"]
    assert cosy["style_control_mode"] == "natural_language"
    assert "emotion=" in cosy_prompt["instructions"]
    assert "pause=" in cosy_prompt["instructions"]
    assert cosy["provider_prompt_snapshot"]["budget"]["used"] <= 100

    minimax_snapshot = minimax["provider_prompt_snapshot"]
    assert minimax["style_control_mode"] == "basic"
    assert minimax_snapshot["provider_prompt"]["instructions"] == ""
    assert minimax["voice_params"]["basic_voice_settings"]["speed"] < 1.0
    assert minimax_snapshot["warnings"]

    mimo_prompt = mimo["provider_prompt_snapshot"]["provider_prompt"]
    assert mimo["style_control_mode"] == "mimo_audio_tags"
    assert mimo_prompt["text_prefix"]
    assert mimo_prompt["inline_tag_strategy"]["placement"] == "assistant_prefix"

    step_prompt = stepaudio["provider_prompt_snapshot"]["provider_prompt"]
    assert stepaudio["style_control_mode"] == "stepaudio_global_context"
    assert "停顿策略" in step_prompt["instructions"]
    assert step_prompt["text_prefix"].startswith("（")

    seed_prompt = seed["provider_prompt_snapshot"]["provider_prompt"]
    assert seed["style_control_mode"] == "doubao_query_response"
    assert seed_prompt["context_texts"]
    assert seed_prompt["text_prefix"].startswith("[")


def test_custom_voice_variants_are_marked_without_hiding_prompt_compilation() -> None:
    from app.services.audiobook.tts_test_unit import get_tts_test_case

    cosy = get_tts_test_case("cosyvoice-v3.5-plus", "compact_emotion_cues")
    mimo_design = get_tts_test_case("mimo-v2.5-tts-voicedesign", "voice_design_emotion")
    mimo_clone = get_tts_test_case("mimo-v2.5-tts-voiceclone", "clone_director_control")

    assert cosy["requires_custom_voice"] is True
    assert mimo_design["requires_custom_voice"] is True
    assert mimo_clone["requires_custom_voice"] is True
    assert mimo_design["provider_prompt_snapshot"]["provider_prompt"]["messages"]
    assert mimo_clone["provider_prompt_snapshot"]["provider_prompt"]["messages"]


def test_preview_endpoint_synthesizes_with_the_displayed_prompt_snapshot(monkeypatch) -> None:
    from app.api.v1.audiobook_api import routes_tts
    from app.schemas.audiobook import TTSPromptTestPreviewRequest

    captured: dict = {}

    async def fake_synthesize_preview_payload(**kwargs):
        captured.update(kwargs)
        return {
            "audio_bytes": b"ID3-unit-test",
            "format": "mp3",
            "provider": "unit-provider",
            "provider_model": kwargs["model_name"],
        }

    monkeypatch.setattr(routes_tts, "_synthesize_preview_payload", fake_synthesize_preview_payload)

    response = asyncio.run(
        routes_tts.preview_tts_prompt_test_case(
            request=TTSPromptTestPreviewRequest(
                model="qwen3-tts-instruct-flash",
                case_id="emotion_pause_stress",
                voice_id="Neil",
            ),
            current_user=SimpleNamespace(id=1),
        )
    )

    snapshot = response.provider_prompt_snapshot
    assert response.model == "qwen3-tts-instruct-flash"
    assert response.case_id == "emotion_pause_stress"
    assert response.audio_data_base64
    assert captured["text"] == response.text
    assert captured["voice_params"]["provider_prompt_snapshot"] == snapshot
