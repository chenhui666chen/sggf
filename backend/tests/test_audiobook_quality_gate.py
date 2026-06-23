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


def test_quality_review_does_not_call_llm_revision_when_gate_already_passes():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = AudioQualityReviewer()
    engine._audio_fx_config = {}
    engine.revision_calls = 0

    def fail_if_called(script_segments, quality_report, *, novel_genre):
        engine.revision_calls += 1
        return {"applied": False}

    engine._llm_revise_script_segments_from_quality_report = fail_if_called
    segments = [
        ScriptSegment(
            type="narration",
            text="陆衍压低呼吸，沿着南侧小道继续向前。",
            speaker="旁白",
            emotion="neutral",
            performance_notes="平稳叙述，句尾自然停顿。",
            pause_after=0.25,
        )
    ]

    report, revision = engine._run_quality_review_with_auto_revision(
        segments,
        novel_genre="玄幻",
        quality_threshold=70.0,
        max_revision_rounds=2,
    )

    assert revision["quality_gate"]["passed"] is True
    assert revision["applied"] is False
    assert engine.revision_calls == 0
    assert report.overall_score >= 70.0


def test_quality_review_uses_llm_revision_feedback_until_gate_passes():
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    class FakeQualityReviewer:
        quality_standards = {}

        def review_script(self, review_segments, novel_genre=""):
            text = "".join(segment.get("text", "") for segment in review_segments)
            passed = "陆衍从后窗翻出" in text
            return SimpleNamespace(
                script_quality={},
                audio_balance={},
                pacing={},
                issues=[] if passed else [
                    SimpleNamespace(
                        location="segment_0",
                        severity="major",
                        category="script",
                        description="剧本过短，缺少可播讲动作与情绪",
                        suggestion="补足逃亡动作、场景压力和停顿提示",
                    )
                ],
                overall_grade="A" if passed else "D",
                overall_score=95.0 if passed else 55.0,
                revision_suggestions=[] if passed else ["根据评审意见补足可播讲内容"],
            )

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = FakeQualityReviewer()
    engine._audio_fx_config = {}
    engine._last_source_text_for_script_revision = "陆衍逃出后堂，掌心裂隙剧烈震颤。"
    engine._last_llm_script_review = {"applied": False, "reason": "no_changes"}
    engine.revision_calls = 0

    def fake_llm_revision(script_segments, quality_report, *, novel_genre):
        engine.revision_calls += 1
        script_segments[:] = [
            ScriptSegment(
                type="narration",
                text=(
                    "陆衍从后窗翻出，夜风卷着腐土气息扑面而来。"
                    "他按住掌心裂隙，沿着南侧小道压低呼吸向前逃去。"
                ),
                speaker="旁白",
                emotion="tense",
                performance_notes="压低声线，保持逃亡压迫感，句尾短暂停顿。",
                pause_after=0.35,
            )
        ]
        return {
            "applied": True,
            "reason": "llm_revision_applied",
            "source": "llm_feedback",
        }

    engine._llm_revise_script_segments_from_quality_report = fake_llm_revision
    segments = [
        ScriptSegment(
            type="narration",
            text="短句。",
            speaker="旁白",
            emotion="neutral",
        )
    ]

    report, revision = engine._run_quality_review_with_auto_revision(
        segments,
        novel_genre="玄幻",
        quality_threshold=90.0,
        max_revision_rounds=2,
    )

    assert revision["quality_gate"]["passed"] is True
    assert revision["applied"] is True
    assert revision["rounds"] == 1
    assert revision["revision_rounds"][0]["llm_revision"]["applied"] is True
    assert engine.revision_calls == 1
    assert report.overall_score >= 90.0
    assert segments[0].text.startswith("陆衍从后窗翻出")


def test_quality_review_blocks_when_llm_revision_cannot_fix_gate():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = AudioQualityReviewer()
    engine._audio_fx_config = {}
    engine._last_source_text_for_script_revision = "陆衍逃出后堂。"
    engine._last_llm_script_review = None
    engine.revision_calls = 0

    def fake_noop_revision(script_segments, quality_report, *, novel_genre):
        engine.revision_calls += 1
        return {
            "applied": False,
            "reason": "no_valid_llm_revision",
            "source": "llm_feedback",
        }

    engine._llm_revise_script_segments_from_quality_report = fake_noop_revision
    segments = [
        ScriptSegment(
            type="narration",
            text="短句。",
            speaker="旁白",
            emotion="neutral",
        )
    ]

    report, revision = engine._run_quality_review_with_auto_revision(
        segments,
        novel_genre="玄幻",
        quality_threshold=101.0,
        max_revision_rounds=2,
    )

    assert revision["quality_gate"]["passed"] is False
    assert revision["quality_gate"]["blocked"] is True
    assert revision["applied"] is False
    assert revision["rounds"] == 0
    assert engine.revision_calls == 1
    assert report.overall_score < 101.0


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
