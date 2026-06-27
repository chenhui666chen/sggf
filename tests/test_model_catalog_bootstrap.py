from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for candidate in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_build_model_catalog_card_payloads_covers_current_integrated_models() -> None:
    from app.services.model_catalog_bootstrap import build_model_catalog_card_payloads

    payloads = build_model_catalog_card_payloads()
    by_key = {payload["model_key"]: payload for payload in payloads}

    assert len(payloads) >= 42
    assert by_key["qwen3.7-plus"]["category"] == "llm"
    assert by_key["wan2.6-t2i"]["category"] == "image"
    assert by_key["qwen3-tts-instruct-flash"]["category"] == "audio"
    assert by_key["mimo-v2.5-tts"]["category"] == "audio"
    assert by_key["mimo-v2.5-tts-voicedesign"]["category"] == "audio"
    assert by_key["mimo-v2.5-tts-voiceclone"]["category"] == "audio"
    assert "mimo-v2.5-tts-hd" not in by_key
    assert "mimo-v2.5-tts-turbo" not in by_key
    assert by_key["qwen3-vl-plus"]["category"] == "multimodal"
    assert by_key["qwen3.7-plus"]["config_source"] == "merged"
    assert by_key["wan2.7-t2v"]["name"] == "Wan 2.7 Text-to-Video"
    assert by_key["wan2.7-t2v"]["summary"].startswith("项目当前归档的主力文生视频模型。当前接入版本为 Wan 2.7")
    assert by_key["wan2.7-i2v"]["name"] == "Wan 2.7 Image-to-Video"
    assert by_key["wan2.7-r2v"]["name"] == "Wan 2.7 Reference-to-Video"
    assert by_key["qwen3.7-plus"]["raw_config_json"]["category_label"] == "多模态"
    assert by_key["qwen3.7-plus"]["verification_status"] == "pending"
