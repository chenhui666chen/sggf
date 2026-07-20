import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import segment_preview_service
from app.services.audiobook.segment_preview_service import SegmentPreviewService


class FakeVoiceProfile:
    def get_tts_params(self, emotion):
        return {
            "speaker": "profile-speaker",
            "speed": 1.0,
            "emotion": emotion,
        }


class FakeVoiceManager:
    def __init__(self):
        self.applied_mapping = None

    def apply_project_voice_mapping(self, mapping):
        self.applied_mapping = mapping

    def get_narrator_voice(self):
        return FakeVoiceProfile()

    def get_voice(self, speaker):
        return None

    def assign_voice(self, speaker):
        return FakeVoiceProfile()


def install_fake_voice_manager(monkeypatch):
    manager = FakeVoiceManager()
    monkeypatch.setattr(
        segment_preview_service,
        "create_voice_manager",
        lambda **kwargs: manager,
    )
    return manager


def test_segment_preview_service_resolves_voice_params(monkeypatch):
    manager = install_fake_voice_manager(monkeypatch)
    service = SegmentPreviewService(
        tts_model="qwen3-tts-instruct-flash",
        voice_mapping={"旁白": {"voice_id": "voice-a"}},
        audio_fx={},
    )

    emotion, params = service.resolve_voice_params(
        {
            "type": "dialogue",
            "speaker": "narrator",
            "emotion": "neutral",
            "instruct_emotion": "whispering",
            "instruct_scene": "rainy alley",
            "performance_notes": "keep it quiet",
            "pause_before": 0.25,
            "voice_params": {
                "speaker": "should-not-override",
                "speed": 1.2,
                "pause_after": 0.4,
            },
        }
    )

    assert manager.applied_mapping == {"旁白": {"voice_id": "voice-a"}}
    assert emotion == "whispering"
    assert params["speaker"] == "profile-speaker"
    assert params["speed"] == 1.2
    assert params["rate"] == 1.2
    assert params["pause_before"] == 0.25
    assert params["pause_after"] == 0.4
    assert params["segment_speaker"] == "narrator"
    assert params["segment_type"] == "dialogue"
    assert params["instruct_scene"] == "rainy alley"
    assert params["performance_notes"] == "keep it quiet"
    assert params["use_instruct_mode"] is True


def test_segment_preview_service_keeps_rate_speed_and_emotion_consistent(monkeypatch):
    install_fake_voice_manager(monkeypatch)
    service = SegmentPreviewService(
        tts_model="qwen3-tts-instruct-flash",
        voice_mapping={},
        audio_fx={},
    )

    emotion, params = service.resolve_voice_params(
        {
            "type": "narration",
            "speaker": "narrator",
            "emotion": "calm",
            "instruct_emotion": "fearful",
            "voice_params": {
                "emotion": "calm",
                "speed": 1.15,
                "rate": 0.8,
                "pause_before": 0.3,
                "pause_after": 0.5,
            },
        }
    )

    assert emotion == "fearful"
    assert params["emotion"] == "fearful"
    assert params["rate"] == 0.8
    assert params["speed"] == 0.8
    assert params["pause_before"] == 0.3
    assert params["pause_after"] == 0.5


def test_segment_preview_service_normalizes_effects_and_music_cues():
    effect_specs = SegmentPreviewService.normalize_sound_effects(
        {
            "sound_effects": [
                {
                    "name": "door",
                    "audio_file": "door.mp3",
                    "start_time": 1.5,
                    "volume": 0.4,
                    "layer": "action",
                },
                "wind",
                {},
            ]
        }
    )

    assert effect_specs == [
        {
            "name": "door",
            "volume": 0.4,
            "delay": 1.5,
            "duration": None,
            "fade_in": None,
            "fade_out": None,
            "layer": "action",
            "timing": None,
            "file": "door.mp3",
        },
        {"name": "wind"},
    ]

    assert SegmentPreviewService.normalize_sound_effects(
        {"sound_effects_simple": "rain, thunder"}
    ) == [{"name": "rain"}, {"name": "thunder"}]

    music_cue = SegmentPreviewService.normalize_music_cue(
        {
            "music_cue": {
                "name": "tense bed",
                "audio_file": "tense.mp3",
                "volume": 0.3,
                "start_time": 2.0,
            }
        }
    )

    assert music_cue["style"] == "tense bed"
    assert music_cue["file"] == "tense.mp3"
    assert music_cue["volume"] == 0.3
    assert music_cue["start_time"] == 2.0
    assert music_cue["sync_with_dialogue"] is True


def test_segment_preview_service_preserves_explicit_audio_asset_ids():
    effect_specs = SegmentPreviewService.normalize_sound_effects(
        {
            "sound_effects": [
                {
                    "asset_id": "sfx-door-01",
                    "name": "Heavy door",
                }
            ]
        }
    )
    music_cue = SegmentPreviewService.normalize_music_cue(
        {
            "music_cue": {
                "asset_id": "music-tense-01",
                "style": "Tense bed",
            }
        }
    )

    assert effect_specs[0]["asset_id"] == "sfx-door-01"
    assert effect_specs[0]["name"] == "Heavy door"
    assert music_cue is not None
    assert music_cue["asset_id"] == "music-tense-01"
    assert music_cue["style"] == "Tense bed"


def test_segment_preview_service_matches_sound_effect_by_asset_id(monkeypatch):
    matched_descriptions = []

    class FakeDesigner:
        def __init__(self, llm_client=None):
            pass

        def _match_effect(self, description, timestamp, scene_id):
            matched_descriptions.append(description)
            return SimpleNamespace(
                effect_type=SimpleNamespace(value="action"),
                audio_file="sound_effects/selected.wav",
                volume=0.4,
                duration=1.0,
                fade_in=0.0,
                fade_out=0.0,
                loop=False,
            )

    monkeypatch.setattr(segment_preview_service, "SoundEffectDesigner", FakeDesigner)
    timeline = SegmentPreviewService.build_effect_timeline(
        [{"asset_id": "sfx-door-01", "name": "Heavy door"}]
    )

    assert matched_descriptions == ["sfx-door-01"]
    assert timeline[0]["description"] == "Heavy door"
    assert timeline[0]["file"] == "sound_effects/selected.wav"


def test_segment_preview_service_resolves_music_by_asset_id_before_style(tmp_path):
    audio_library = tmp_path / "audio_library"
    first_file = audio_library / "music_cache" / "first.wav"
    selected_file = audio_library / "music_cache" / "selected.wav"
    first_file.parent.mkdir(parents=True)
    first_file.write_bytes(b"first")
    selected_file.write_bytes(b"selected")
    music_index = [
        {
            "id": "music-first",
            "style": "Tense bed",
            "mood": "tense",
            "file_path": "music_cache/first.wav",
        },
        {
            "id": "music-selected",
            "style": "Tense bed",
            "mood": "tense",
            "file_path": "music_cache/selected.wav",
        },
    ]

    resolved = SegmentPreviewService.resolve_music_path(
        None,
        "Tense bed",
        "tense",
        audio_library,
        music_index,
        asset_id="music-selected",
    )

    assert resolved == selected_file


def test_segment_preview_service_uses_shared_narration_duration_estimate():
    assert SegmentPreviewService.estimate_duration_seconds("甲" * 45) == 10.0
    assert SegmentPreviewService.estimate_duration_seconds("短句") == 3.0


def test_segment_preview_service_generates_voice_preview(monkeypatch):
    install_fake_voice_manager(monkeypatch)
    synthesize_call = {}

    async def fake_synthesize_speech(**kwargs):
        synthesize_call.update(kwargs)
        return b"RIFFpreview-audio"

    service = SegmentPreviewService(
        tts_model="qwen3-tts-instruct-flash",
        voice_mapping={},
        audio_fx={},
        synthesize_speech=fake_synthesize_speech,
    )

    result = asyncio.run(
        service.generate_preview(
            {
                "type": "narration",
                "speaker": "narrator",
                "text": "Preview segment.",
                "emotion": "neutral",
            },
            preview_type="voice",
        )
    )

    assert result.audio == b"RIFFpreview-audio"
    assert result.media_type == "audio/wav"
    assert synthesize_call["model_id"] == "qwen3-tts-instruct-flash"
    assert synthesize_call["enable_cache"] is False
    assert synthesize_call["retry_config"].max_retries == 4
    assert synthesize_call["retry_config"].max_delay == 8.0
