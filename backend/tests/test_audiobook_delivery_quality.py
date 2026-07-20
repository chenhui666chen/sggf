import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_audio_prompt_review_metrics_summarize_inline_tag_strategy_snapshots():
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    segments = [
        ScriptSegment(
            type="dialogue",
            speaker="A",
            text="Hold the door.",
            emotion="tense",
            sound_effects=["door-hit"],
            music_cue="low strings",
            instruct_emotion="tense",
            voice_params={
                "provider_prompt_snapshot": {
                    "provider_prompt": {
                        "inline_tag_strategy": {
                            "model_family": "mimo",
                            "placement": "assistant_prefix",
                            "style_tags": ["tense", "tense"],
                            "inline_tags": ["whisper", "breath"],
                            "use_tag_parser": False,
                        }
                    }
                }
            },
        ),
        {
            "type": "narration",
            "text": "The corridor fell silent.",
            "sound_effects": [],
            "music_cue_simple": "",
            "voice_params": {
                "provider_prompt_snapshot": {
                    "provider_prompt": {
                        "inline_tag_strategy": {
                            "model_family": "doubao",
                            "placement": "text_prefix",
                            "style_tags": ["narration"],
                            "inline_tags": ["whisper"],
                            "use_tag_parser": True,
                        }
                    }
                }
            },
        },
        ScriptSegment(
            type="narration",
            speaker="Narrator",
            text="No inline strategy here.",
            emotion="neutral",
            voice_params={},
        ),
    ]

    metrics = engine._build_audio_prompt_review_metrics(
        segments,
        llm_script_review_summary={"applied": True},
    )

    assert metrics["segments_count"] == 3
    assert metrics["sound_effects_count"] == 1
    assert metrics["music_cues_count"] == 1
    assert metrics["instruct_count"] == 1
    assert metrics["llm_script_review"] == {"applied": True}
    assert metrics["inline_tag_strategy_count"] == 2
    assert metrics["inline_tag_strategy_by_model_family"] == {"mimo": 1, "doubao": 1}
    assert metrics["inline_tag_strategy_by_placement"] == {
        "assistant_prefix": 1,
        "text_prefix": 1,
    }
    assert metrics["inline_tag_strategy_use_tag_parser_count"] == 1
    assert metrics["inline_tag_strategy_tag_count"] == 5


def test_audio_prompt_review_metrics_omit_inline_strategy_fields_when_absent():
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    metrics = engine._build_audio_prompt_review_metrics(
        [
            ScriptSegment(
                type="narration",
                speaker="Narrator",
                text="Plain narration.",
                emotion="neutral",
                voice_params={"provider_prompt_snapshot": {"provider_prompt": {}}},
            )
        ]
    )

    assert metrics == {
        "segments_count": 1,
        "sound_effects_count": 0,
        "music_cues_count": 0,
        "instruct_count": 0,
    }


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
    snapshot = voice_params["provider_prompt_snapshot"]
    assert snapshot["model"] == "mimo-v2.5-tts"
    assert snapshot["voice_id"] == ""
    assert snapshot["mode"] == "mimo_director"
    assert snapshot["provider_prompt"]["messages"][0]["role"] == "user"
    assert "长期压抑情绪的继承人" in snapshot["provider_prompt"]["messages"][0]["content"]
