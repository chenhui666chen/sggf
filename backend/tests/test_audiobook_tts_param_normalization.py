import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin
from app.services.audiobook.narration_styles import apply_narration_style_to_tts_params
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment
from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment


class DummyScriptUtils(ScriptUtilsMixin):
    _narration_style_id = ""
    _narration_style_prompt = None


class FakeVoiceProfile:
    tts_model = "qwen-audio-3.1-tts-flash"

    def __init__(self):
        self.requested_emotion = None

    def get_tts_params(self, emotion):
        self.requested_emotion = emotion
        return {
            "speaker": "Kai",
            "pitch": 1.0,
            "speed": 1.15,
            "volume": 45,
            "pause_before": 0.1,
            "pause_after": 0.2,
        }


class FakeVoiceManager:
    def __init__(self, profile):
        self.profile = profile

    def get_narrator_voice(self):
        return self.profile

    def get_voice(self, speaker):
        return self.profile

    def assign_voice(self, speaker):
        return self.profile


def test_narration_style_prefers_explicit_instruct_emotion_over_weak_default():
    params = apply_narration_style_to_tts_params(
        "professional",
        {
            "emotion": "calm",
            "instruct_emotion": "fearful",
            "performance_notes": "lower the voice and leave a suspenseful pause",
        },
    )

    assert params["emotion"] == "calm"
    assert "instructions" not in params


def test_narration_style_keeps_runtime_voice_description_unchanged():
    params = apply_narration_style_to_tts_params(
        "relaxing",
        {
            "emotion": "neutral",
            "voice_description": "性别：女性，年龄感：青年，音调：偏高，语速：快速，情绪：激动，特点：明亮，用途：角色对白",
        },
    )

    description = params["voice_description"]

    assert description == "性别：女性，年龄感：青年，音调：偏高，语速：快速，情绪：激动，特点：明亮，用途：角色对白"
    assert params["narration_style_legacy"] == "relaxing"


def test_segment_validation_uses_voice_params_pause_as_effective_top_level_pause():
    segment = build_script_segment(
        {
            "type": "narration",
            "text": "A breath came from the dark.",
            "speaker": "narrator",
            "pause_before": 0,
            "pause_after": 0,
            "voice_params": {
                "pause_before": 0.3,
                "pause_after": 0.5,
            },
        }
    )

    assert segment is not None
    assert segment.pause_before == 0.3
    assert segment.pause_after == 0.5
    assert segment.voice_params["pause_before"] == 0.3
    assert segment.voice_params["pause_after"] == 0.5


def test_assign_voices_normalizes_conflicting_instruct_rate_and_pause_fields():
    profile = FakeVoiceProfile()
    engine = DummyScriptUtils()
    engine._narration_style_id = "professional"
    engine.voice_manager = FakeVoiceManager(profile)
    segment = ScriptSegment(
        type="narration",
        text="A breath came from the dark.",
        speaker="narrator",
        emotion="calm",
        instruct_emotion="fearful",
        performance_notes="lower the voice and leave a suspenseful pause",
        pause_before=0.0,
        pause_after=0.0,
        voice_params={
            "emotion": "calm",
            "speed": 1.15,
            "rate": 0.8,
            "pause_before": 0.3,
            "pause_after": 0.5,
        },
    )

    engine._assign_voices([segment])

    assert profile.requested_emotion == "fearful"
    assert segment.emotion == "fearful"
    assert segment.voice_params["emotion"] == "fearful"
    assert segment.voice_params["instruct_emotion"] == "fearful"
    assert "rate" not in segment.voice_params
    assert "speed" not in segment.voice_params
    assert segment.pause_before == 0.3
    assert segment.pause_after == 0.5


def test_assign_voices_keeps_instruct_emotion_added_by_narration_style():
    profile = FakeVoiceProfile()
    engine = DummyScriptUtils()
    engine._narration_style_id = "professional"
    engine.voice_manager = FakeVoiceManager(profile)
    segment = ScriptSegment(
        type="narration",
        text="A calm transition follows.",
        speaker="narrator",
        emotion="neutral",
        instruct_emotion="",
        voice_params={},
    )

    engine._assign_voices([segment])

    assert segment.instruct_emotion == ""
    assert segment.voice_params["instruct_emotion"] == ""
    assert "use_instruct_mode" not in segment.voice_params


def test_assign_voices_prepares_delivery_plan_with_segment_model_for_review():
    profile = FakeVoiceProfile()
    engine = DummyScriptUtils()
    engine._narration_style_id = ""
    engine.tts_model = "qwen-audio-3.1-tts-flash"
    engine.voice_manager = FakeVoiceManager(profile)
    segment = ScriptSegment(
        type="dialogue",
        text="她压低声音说，我真的撑不住了。",
        speaker="岑霜",
        emotion="sad",
        instruct_emotion="sad",
        instruct_scene="雨夜逃亡后短暂停下",
        instruct_role="长期压抑情绪的继承人",
        performance_notes="压低声音，语速偏慢，句尾带一点哽咽并留白。",
        voice_params={"tts_model": "mimo-v2.5-tts"},
    )

    engine._assign_voices([segment])

    assert segment.voice_params["resolved_tts_model"] == "mimo-v2.5-tts"
    delivery_plan = segment.voice_params["delivery_plan"]
    assert delivery_plan["model"] == "mimo-v2.5-tts"
    assert delivery_plan["model_family"] == "mimo"
    assert delivery_plan["model_control_preference"] == "director"
    assert "哽咽" in delivery_plan["micro_tags"]
    snapshot = segment.voice_params["provider_prompt_snapshot"]
    assert snapshot["model"] == "mimo-v2.5-tts"
    assert snapshot["mode"] == "mimo_director"
    assert snapshot["provider_prompt"]["messages"][0]["role"] == "user"
