from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from app.services.audiobook.agents.sound_effect_designer import SoundEffectDesigner


RECORDS = [
    {"id": "chain_hit", "description": "锁链撞击声", "file_path": "sound_effects/chain_hit.mp3", "source": "ai_generated", "category": "action/realistic"},
    {"id": "chain_rattle", "description": "锁链晃动声", "file_path": "sound_effects/chain_rattle.mp3", "source": "ai_generated", "category": "action/realistic"},
    {"id": "hum_low", "description": "低沉嗡鸣", "file_path": "sound_effects/hum_low.mp3", "source": "ai_generated", "category": "environment/peaceful"},
    {"id": "blade_swish", "description": "刀锋破空声", "file_path": "sound_effects/blade_swish.mp3", "source": "ai_generated", "category": "action/realistic"},
    {"id": "bone_crack", "description": "骨裂声", "file_path": "sound_effects/bone_crack.mp3", "source": "ai_generated", "category": "action/realistic"},
]


def _make_designer(tmp_path) -> SoundEffectDesigner:
    sfx_dir = tmp_path / "sound_effects"
    sfx_dir.mkdir(parents=True)
    for record in RECORDS:
        (sfx_dir / record["file_path"].split("/")[-1]).write_bytes(b"fake-mp3")
    index_path = tmp_path / "sound_effects_index.json"
    index_path.write_text(json.dumps(RECORDS), encoding="utf-8")
    return SoundEffectDesigner(index_path=str(index_path))


def _match(designer: SoundEffectDesigner, description: str):
    return designer._match_effect(description=description, timestamp=0.0, scene_id="scene_test")


def test_exact_description_still_matches_first(tmp_path):
    designer = _make_designer(tmp_path)
    cue = _match(designer, "chain_hit")
    assert cue is not None
    assert cue.effect_id == "chain_hit"


def test_fuzzy_chain_break_matches_chain_library(tmp_path):
    """“锁链断裂声”应通过中文二元词组匹配到锁链类音效，而非占位。"""
    designer = _make_designer(tmp_path)
    cue = _match(designer, "锁链断裂声")
    assert cue is not None
    assert cue.audio_file != "placeholder.mp3"
    assert cue.effect_id in {"chain_hit", "chain_rattle"}


def test_fuzzy_hum_matches_low_hum(tmp_path):
    """“轻微嗡鸣声”应匹配到“低沉嗡鸣”。"""
    designer = _make_designer(tmp_path)
    cue = _match(designer, "轻微嗡鸣声")
    assert cue is not None
    assert cue.effect_id == "hum_low"


def test_fuzzy_swish_matches_blade_swish(tmp_path):
    """“衣袂破空声”应匹配到“刀锋破空声”（共享“破空”）。"""
    designer = _make_designer(tmp_path)
    cue = _match(designer, "衣袂破空声")
    assert cue is not None
    assert cue.effect_id == "blade_swish"


def test_fuzzy_does_not_false_match_generic_suffix(tmp_path):
    """“石壁碎裂声”不得因共享泛化后缀“裂声”而误匹配“骨裂声”。"""
    designer = _make_designer(tmp_path)
    cue = _match(designer, "石壁碎裂声")
    assert cue is not None
    assert cue.audio_file == "placeholder.mp3"


def test_no_candidate_keeps_placeholder(tmp_path):
    """索引中确实没有对应素材时仍走占位（如“急促喘息声”）。"""
    designer = _make_designer(tmp_path)
    cue = _match(designer, "急促喘息声")
    assert cue is not None
    assert cue.audio_file == "placeholder.mp3"
