import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_audio_quality_reviewer_flags_missing_delivery_plan_for_expressive_segments():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    segments = [
        {
            "type": "dialogue",
            "speaker": "岑霜",
            "text": "别过来！我真的撑不住了！",
            "emotion": "fearful",
            "pause_after": 0.3,
            "performance_notes": "压低声音，句尾带一点哽咽并留白。",
            "voice_params": {"tts_model": "mimo-v2.5-tts"},
        }
    ]

    report = reviewer.review_script(segments, novel_genre="悬疑")

    descriptions = "\n".join(issue.description for issue in report.issues)
    assert "强表现片段缺少可执行朗读意图" in descriptions
    assert report.script_quality["delivery_plan_coverage"] == 0.0
    assert report.script_quality["missing_delivery_plan_count"] == 1


def test_audio_quality_reviewer_accepts_delivery_plan_for_expressive_segments():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    segments = [
        {
            "type": "dialogue",
            "speaker": "岑霜",
            "text": "别过来！我真的撑不住了！",
            "emotion": "fearful",
            "pause_after": 0.3,
            "performance_notes": "压低声音，句尾带一点哽咽并留白。",
            "voice_params": {
                "tts_model": "mimo-v2.5-tts",
                "delivery_plan": {
                    "model": "mimo-v2.5-tts",
                    "model_family": "mimo",
                    "model_control_preference": "director",
                    "delivery_mode": "sob",
                    "micro_tags": ["哽咽"],
                    "director_guidance": "压低声音，语速偏慢，句尾留白。",
                },
            },
        }
    ]

    report = reviewer.review_script(segments, novel_genre="悬疑")

    descriptions = "\n".join(issue.description for issue in report.issues)
    assert "强表现片段缺少可执行朗读意图" not in descriptions
    assert report.script_quality["delivery_plan_coverage"] == 1.0
    assert report.script_quality["missing_delivery_plan_count"] == 0


def test_engine_review_segments_prepare_temporary_delivery_plan_before_voice_assignment():
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.tts_model = "qwen3-tts-instruct-flash"
    segment = ScriptSegment(
        type="dialogue",
        speaker="岑霜",
        text="别过来！我真的撑不住了！",
        emotion="fearful",
        instruct_emotion="fearful",
        instruct_scene="雨夜逃亡后短暂停下",
        instruct_role="长期压抑情绪的继承人",
        performance_notes="压低声音，语速偏慢，句尾带一点哽咽并留白。",
        pause_after=0.3,
        voice_params={"tts_model": "mimo-v2.5-tts"},
    )

    review_segment = engine._build_review_segments([segment])[0]
    voice_params = review_segment["voice_params"]
    delivery_plan = voice_params["delivery_plan"]

    assert voice_params["resolved_tts_model"] == "mimo-v2.5-tts"
    assert delivery_plan["model"] == "mimo-v2.5-tts"
    assert delivery_plan["model_family"] == "mimo"
    assert delivery_plan["model_control_preference"] == "director"
    assert "哽咽" in delivery_plan["micro_tags"]
