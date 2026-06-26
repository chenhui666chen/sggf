from pathlib import Path

import yaml

from core.semantic_matcher import SCENARIO_VOCABULARY, STYLE_VOCABULARY


ROOT = Path(__file__).resolve().parents[1]


def test_intent_domains_include_audiobook_tts_domain() -> None:
    config = yaml.safe_load((ROOT / "config" / "intent_domains.yaml").read_text(encoding="utf-8"))
    tts = config["domains"].get("tts")

    assert tts
    assert "audiobook" in tts["modalities"]
    assert "natural_language_control" in tts["creative_modes"]
    assert "audio_tag_control" in tts["creative_modes"]
    assert "director_mode" in tts["creative_modes"]
    assert "whisper" in tts["styles"]
    assert "sobbing" in tts["styles"]
    assert "breathy" in tts["styles"]
    assert "audiobook_narration" in tts["scene_rules"][0]["keywords"]


def test_semantic_matcher_includes_tts_style_and_scene_vocabulary() -> None:
    assert "低语" in STYLE_VOCABULARY["tts_whisper"]
    assert "哽咽" in STYLE_VOCABULARY["tts_sobbing"]
    assert "笑意" in STYLE_VOCABULARY["tts_laughter"]
    assert "气声" in STYLE_VOCABULARY["tts_breathy"]
    assert "破音" in STYLE_VOCABULARY["tts_voice_break"]

    assert "有声书" in SCENARIO_VOCABULARY["audiobook_narration"]
    assert "角色对白" in SCENARIO_VOCABULARY["character_dialogue"]
    assert "独白" in SCENARIO_VOCABULARY["character_monologue"]
    assert "情绪爆发" in SCENARIO_VOCABULARY["emotional_outburst"]
    assert "导演模式" in SCENARIO_VOCABULARY["tts_director_mode"]
