import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.tts_model_ids import MINIMAX_SPEECH_28_HD_MODEL
from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin
from app.services.audiobook.script_adapter import ScriptSegment
from app.services.audiobook.segment_preview_service import SegmentPreviewService
from app.services.audiobook.segment_synthesis_contract import compile_segment_synthesis_input
from app.services.audiobook.voice_manager import VoiceManager, VoiceProfile
from app.services.audiobook.voice_manager_cosyvoice_v3_plus import (
    CosyVoiceV3PlusProfile,
)
from app.services.audiobook.voice_manager_mimo import MiMoInlineVoiceProfile
from app.services.audiobook.voice_manager_minimax import MiniMaxVoiceManager


def test_voice_profile_does_not_emit_pitch_across_segment_emotions() -> None:
    profile = VoiceProfile(
        voice_id="narrator",
        character_name="narrator",
        gender="male",
        age_group="adult",
        personality="calm",
        tts_model="seed-tts-2.0-expressive",
        tts_speaker_id="fixed-speaker",
        pitch_base=50,
        speed_base=1.0,
        volume_base=50,
    )

    neutral = profile.get_tts_params("neutral")
    sad = profile.get_tts_params("sad")
    angry = profile.get_tts_params("angry")

    for params in (neutral, sad, angry):
        assert "pitch" not in params
        assert "character_base_pitch" not in params
        assert "speed" not in params
        assert "rate" not in params
        assert "character_base_speed" not in params
        assert "voice_description" not in params


def test_minimax_catalog_default_uses_provider_neutral_pitch() -> None:
    manager = MiniMaxVoiceManager.__new__(MiniMaxVoiceManager)
    VoiceManager.__init__(manager)
    manager.model = MINIMAX_SPEECH_28_HD_MODEL
    manager.voice_catalog = {
        "voices": [],
        "voices_by_id": {
            "male-qn-qingse": {
                "id": "male-qn-qingse",
                "speaker": "male-qn-qingse",
                "gender": "male",
                "category": "youth",
                "style": "calm",
                "default_params": {},
            }
        },
    }

    profile = manager._build_profile("narrator", "male-qn-qingse")

    assert profile.pitch_base == 0
    assert "pitch" not in profile.get_tts_params("sad")


def test_specialized_fixed_voice_profiles_do_not_emit_pitch() -> None:
    cosy_profile = CosyVoiceV3PlusProfile(
        voice_id="cosy-unit",
        character_name="旁白",
        tts_speaker_id="cosy-unit",
        pitch_base=23,
    )
    mimo_profile = MiMoInlineVoiceProfile(
        voice_id="mimo_design:asset-1",
        character_name="旁白",
        tts_model="mimo-v2.5-tts-voicedesign",
        pitch_base=77,
        voice_design_prompt="青年女性，中音，声线清晰。",
        mimo_voice_asset_id="asset-1",
    )

    cosy_params = cosy_profile.get_tts_params("sad")
    mimo_params = mimo_profile.get_tts_params("sad")

    assert "pitch" not in cosy_params
    assert "pitch" not in mimo_params
    assert "speed" not in cosy_params
    assert "speed" not in mimo_params
    assert "voice_description" not in mimo_params
    assert mimo_params["voice_design_prompt"] == "青年女性，中音，声线清晰。"


class _StablePitchProfile:
    def get_tts_params(self, _emotion: str):
        return {
            "speaker": "fixed-speaker",
            "pitch": 50,
            "character_base_pitch": 50,
            "speed": 1.0,
            "volume": 50,
        }


class _StablePitchManager:
    def __init__(self) -> None:
        self.profile = _StablePitchProfile()

    def get_narrator_voice(self):
        return self.profile

    def get_voice(self, _speaker: str):
        return self.profile

    def assign_voice(self, _speaker: str):
        return self.profile


def test_pipeline_voice_assignment_drops_all_segment_pitch_fields() -> None:
    engine = ScriptUtilsMixin()
    engine.voice_manager = _StablePitchManager()
    engine.tts_model = "seed-tts-2.0-expressive"
    engine._narration_style_id = ""
    segment = ScriptSegment(
        type="narration",
        text="Pain.",
        speaker="narrator",
        emotion="sad",
        voice_params={
            "pitch": 0.9,
            "pitch_ratio": 0.8,
            "pitch_semitones": -5,
            "rate": 0.8,
        },
    )

    engine._assign_voices([segment])

    assert "pitch" not in segment.voice_params
    assert "pitch_ratio" not in segment.voice_params
    assert "pitch_semitones" not in segment.voice_params
    assert "speed" not in segment.voice_params
    assert "rate" not in segment.voice_params
    assert "character_base_speed" not in segment.voice_params


def test_workbench_preview_drops_all_segment_pitch_fields() -> None:
    service = SegmentPreviewService.__new__(SegmentPreviewService)
    service.voice_manager = _StablePitchManager()

    _, voice_params = service.resolve_voice_params(
        {
            "speaker": "narrator",
            "type": "narration",
            "emotion": "sad",
            "voice_params": {
                "pitch": 0.9,
                "pitch_ratio": 0.8,
                "pitch_semitones": -5,
                "rate": 0.8,
            },
        }
    )

    assert "pitch" not in voice_params
    assert "pitch_ratio" not in voice_params
    assert "pitch_semitones" not in voice_params
    assert "speed" not in voice_params
    assert "rate" not in voice_params
    assert "character_base_speed" not in voice_params


def test_candidate_contract_drops_all_segment_pitch_fields() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "narrator",
            "text": "Pain.",
            "voice_params": {
                "pitch": 0.9,
                "pitch_ratio": 0.8,
                "pitch_semitones": -5,
                "character_base_pitch": 50,
                "rate": 0.8,
            },
        },
        tts_model="seed-tts-2.0-expressive",
        voice_id="fixed-speaker",
        emotion="sad",
        preview_type="voice",
    )

    voice_params = compiled["segment"]["voice_params"]
    assert "pitch" not in voice_params
    assert "pitch_ratio" not in voice_params
    assert "pitch_semitones" not in voice_params
    assert "speed" not in voice_params
    assert "rate" not in voice_params
    assert "character_base_speed" not in voice_params


def test_basic_model_keeps_numeric_speed_as_instruction_fallback() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "Pain.",
            "performance_notes": "语速偏慢。",
            "voice_params": {
                "speaker": "fixed-speaker",
                "speed": 0.8,
            },
        },
        tts_model=MINIMAX_SPEECH_28_HD_MODEL,
        voice_id="fixed-speaker",
        emotion="neutral",
        preview_type="voice",
    )

    voice_params = compiled["segment"]["voice_params"]
    assert voice_params["speed"] == 0.8
