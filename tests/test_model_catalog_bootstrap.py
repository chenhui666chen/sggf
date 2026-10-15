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
    assert by_key["qwen-plus"]["category"] == "llm"
    assert by_key["qwen-image-3.0"]["category"] == "image"
    assert by_key["qwen-audio-3.1-tts-flash"]["category"] == "audio"
    assert by_key["mimo-v2.5-tts"]["category"] == "audio"
    assert by_key["mimo-v2.5-tts-voicedesign"]["category"] == "audio"
    assert by_key["mimo-v2.5-tts-voiceclone"]["category"] == "audio"
    assert "mimo-v2.5-tts-hd" not in by_key
    assert "mimo-v2.5-tts-turbo" not in by_key
    assert by_key["qwen3.8-omni-flash"]["category"] == "multimodal"
    assert by_key["qwen-plus"]["config_source"] == "merged"
    assert by_key["wan3.0-video"]["name"] == "Wan 3.0 Video"
    assert by_key["wan3.0-video"]["summary"].startswith("万相 3.0 全能参考视频生成模型")
    assert by_key["wan3.0-video"]["category"] == "video"
    assert by_key["qwen-plus"]["raw_config_json"]["category_label"] == "多模态"
    assert by_key["qwen-plus"]["verification_status"] == "pending"
