import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def make_engine_harness():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = AudioQualityReviewer()
    engine._audio_fx_config = {}
    return engine


def test_quality_review_auto_revision_fixes_script_before_gate():
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    engine = make_engine_harness()
    long_action_text = (
        "一股无形吸力自他掌心爆发。守卫整条右臂的浊气如潮水倒灌，经脉中积蓄多年的祟意被强行抽离。"
        "一息之间，那手臂干瘪如朽木，皮肤龟裂，筋肉萎缩，连骨骼都发出脆响。"
        "守卫连惨叫都未及发出，双目翻白，轰然倒地。陆衍跪在地上干呕，眼前发黑。"
        "右手裂隙比平时扩大近一倍，暗金色漩涡在掌心疯狂转动。"
        "他知道，这种动静瞒不过巡逻队，必须立刻离开这里。"
    )
    segments = [
        ScriptSegment(
            type="narration",
            speaker="旁白",
            text=long_action_text,
            emotion="tense",
            pause_after=0.0,
        ),
        ScriptSegment(
            type="dialogue",
            speaker="",
            text="别过来！",
            emotion="fearful",
            pause_after=0.0,
        ),
    ]

    report, revision = engine._run_quality_review_with_auto_revision(
        segments,
        novel_genre="玄幻",
        quality_threshold=70.0,
    )

    assert revision["applied"] is True
    assert revision["quality_gate"]["passed"] is True
    assert len(segments) > 2
    assert all(len(segment.text) <= 140 for segment in segments if segment.type == "narration")
    assert all(segment.pause_after >= 0.2 for segment in segments if segment.emotion in {"tense", "fearful"})
    assert any(segment.sound_effects for segment in segments)
    assert segments[-1].type == "narration"
    assert segments[-1].speaker == "旁白"
    assert report.overall_score >= 70.0


@pytest.mark.asyncio
async def test_audio_from_script_quality_gate_blocks_tts_when_review_fails():
    from app.services.audiobook.engine_pkg._audio_from_script_mixin import AudioFromScriptMixin
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.task_tracker import StageType, TaskTracker
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    class Harness(AudioFromScriptMixin, AudiobookEngineBase):
        def __init__(self):
            self.task_tracker = TaskTracker()
            self.audio_director = SimpleNamespace(
                formulate_strategy=lambda **kwargs: SimpleNamespace(
                    style=SimpleNamespace(value="cinematic"),
                    sound_effect_density="medium",
                    music_density="medium",
                )
            )
            self.script_adapter = SimpleNamespace(strategy=None)
            self.audio_quality_reviewer = AudioQualityReviewer()
            self._audio_fx_config = {}
            self._last_effect_timeline = None
            self._last_music_timeline = None
            self.tts_calls = 0

        async def _parallel_design(self, *args, **kwargs):
            return {}, 0, 0

        def _assign_voices(self, script_segments):
            return None

        async def _synthesize_segments_with_resume(self, *args, **kwargs):
            self.tts_calls += 1
            return {"audio_list": [b"segment"], "reused_indices": [], "synthesized_count": 1}

    harness = Harness()

    result = await harness.generate_chapter_audio_from_script(
        script_segments_data=[
            {"type": "narration", "text": "短句。", "speaker": "旁白", "emotion": "neutral"},
        ],
        chapter_id=1,
        novel_genre="玄幻",
        enable_quality_review=True,
        quality_threshold=101.0,
    )

    assert result["success"] is False
    assert result["error"] == "script_quality_gate_failed"
    assert harness.tts_calls == 0
    assert result["quality_report_detail"].get("auto_revision") is None
    assert result["quality_report_detail"]["overall_score"] < 101.0
    assert result["quality_report_detail"]["quality_gate"]["passed"] is False

    task_status = harness.task_tracker.get_task_status(result["task_id"])
    assert task_status["stages"][StageType.QUALITY_REVIEW.value]["status"] == "failed"
    assert task_status["stages"][StageType.TTS_SYNTHESIS.value]["status"] == "pending"
