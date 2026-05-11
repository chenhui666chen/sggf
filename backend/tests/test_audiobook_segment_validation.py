import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_segment_validation_normalizes_core_fields():
    from app.services.audiobook.script_adapter_pkg._dataclasses import MusicCue, SoundEffect
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "dialog",
            "text": "\u4f60\u597d",
            "speaker": "",
            "emotion": "exciting",
            "instruct_emotion": "tense",
            "voice_params": {
                "rate": 9,
                "speed": 0.1,
                "pitch": 200,
                "volume": 200,
                "pause_after": 9,
            },
            "pause_before": -1,
            "pause_after": 9,
            "sound_effects": [{"name": "\u96e8\u58f0", "volume": 9, "duration": "\u81ea\u7136\u7ed3\u675f"}],
            "music_cue": {
                "style": "\u7d27\u5f20\u5f26\u4e50",
                "volume": 9,
                "duration": "bad",
                "emotion_follow": "false",
            },
        }
    )

    assert segment is not None
    assert segment.type == "narration"
    assert segment.speaker == "\u65c1\u767d"
    assert segment.emotion == "excited"
    assert segment.instruct_emotion == "fearful"
    assert segment.pause_before == 0.0
    assert segment.pause_after == 2.0
    assert segment.voice_params["rate"] == 2.0
    assert segment.voice_params["speed"] == 0.5
    assert segment.voice_params["pitch"] == 100
    assert segment.voice_params["volume"] == 100
    assert isinstance(segment.sound_effects[0], SoundEffect)
    assert segment.sound_effects[0].volume == 1.0
    assert segment.sound_effects[0].duration is None
    assert isinstance(segment.music_cue, MusicCue)
    assert segment.music_cue.volume == 1.0
    assert segment.music_cue.duration is None
    assert segment.music_cue.emotion_follow is False


def test_segment_validation_skips_empty_or_punctuation_only_segments():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    assert build_script_segment({"text": "..."}) is None
    assert build_script_segment({"text": "   "}) is None


def test_segment_validation_replaces_performance_direction_with_original_text():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "\u65c1\u767d\u5c06\u6e29\u67d4\u5730\u8bb2\u8ff0\u63a5\u4e0b\u6765\u7684\u60c5\u8282",
            "original_text": "\u591c\u8272\u538b\u4e0b\u6765\uff0c\u8857\u706f\u4e00\u76cf\u76cf\u4eae\u8d77\u3002",
        }
    )

    assert segment is not None
    assert segment.text == "\u591c\u8272\u538b\u4e0b\u6765\uff0c\u8857\u706f\u4e00\u76cf\u76cf\u4eae\u8d77\u3002"


def test_segment_validation_strips_unsupported_emotion_tags_from_spoken_text():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "dialogue",
            "text": "\u522b\u8fc7\u6765 <gasp>\uff01<text_segment>",
            "speaker": "\u6797\u9752",
            "emotion": "",
            "performance_notes": "\u538b\u4f4e\u58f0\u97f3",
        }
    )

    assert segment is not None
    assert segment.text == "\u522b\u8fc7\u6765\uff01"
    assert segment.emotion == "surprised"
    assert "\u538b\u4f4e\u58f0\u97f3" in segment.performance_notes
    assert "\u5012\u5438\u6c14" in segment.performance_notes
    assert "<gasp>" not in segment.text
    assert "<text_segment>" not in segment.text


def test_segment_validation_normalizes_narrator_speaker_aliases_without_touching_characters():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    narrator_segment = build_script_segment(
        {
            "type": "dialogue",
            "text": "夜色压下来。",
            "speaker": "Narrator:",
        }
    )
    character_segment = build_script_segment(
        {
            "type": "dialogue",
            "text": "你终于来了。",
            "speaker": "林青：",
        }
    )

    assert narrator_segment is not None
    assert narrator_segment.type == "narration"
    assert narrator_segment.speaker == "旁白"
    assert character_segment is not None
    assert character_segment.type == "dialogue"
    assert character_segment.speaker == "林青"


def test_segment_validation_preserves_explicit_break_tags():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "\u7b2c\u4e00\u53e5\u3002<break time=\"2s\"/>\u7b2c\u4e8c\u53e5\u3002",
            "speaker": "\u65c1\u767d",
        }
    )

    assert segment is not None
    assert segment.text == "\u7b2c\u4e00\u53e5\u3002<break time=\"2s\"/>\u7b2c\u4e8c\u53e5\u3002"


def test_segment_validation_converts_bracketed_stage_directions_to_notes():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "dialogue",
            "text": "（低声）别出声，[laughs]我们还活着。[sfx:door slam]",
            "speaker": "林青",
            "emotion": "",
            "performance_notes": "贴近耳边",
        }
    )

    assert segment is not None
    assert segment.text == "别出声，我们还活着。"
    assert segment.emotion == "whisper"
    assert "贴近耳边" in segment.performance_notes
    assert "低声/耳语" in segment.performance_notes
    assert "笑声" in segment.performance_notes
    assert "音效提示：door slam" in segment.performance_notes
    assert "laughs" not in segment.text
    assert "sfx" not in segment.text


def test_segment_validation_keeps_pause_tags_for_render_plan():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "等一下。[pause:2s]继续。",
            "speaker": "旁白",
        }
    )

    assert segment is not None
    assert segment.text == "等一下。[pause:2s]继续。"


def test_segment_validation_moves_spoken_pause_directives_out_of_text():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "必须走。（停顿一秒）继续。",
            "speaker": "旁白",
        }
    )

    assert segment is not None
    assert segment.text == "必须走。继续。"
    assert segment.voice_params["pause_after_ms"] == 1000
    assert "停顿" in segment.performance_notes


def test_segment_validation_uses_original_text_when_text_is_only_pause_direction():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "旁白停顿三秒后继续讲述。",
            "original_text": "必须走。",
            "speaker": "旁白",
        }
    )

    assert segment is not None
    assert segment.text == "必须走。"
    assert segment.voice_params["pause_after_ms"] == 3000


def test_segment_validation_inferrs_clear_emotion_when_missing_or_neutral():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    fearful = build_script_segment(
        {
            "type": "dialogue",
            "text": "救命！别过来！",
            "speaker": "林青",
        }
    )
    angry = build_script_segment(
        {
            "type": "dialogue",
            "text": "滚出去！",
            "speaker": "林青",
            "emotion": "neutral",
        }
    )
    explicit = build_script_segment(
        {
            "type": "dialogue",
            "text": "救命！",
            "speaker": "林青",
            "emotion": "happy",
        }
    )

    assert fearful is not None
    assert fearful.emotion == "fearful"
    assert angry is not None
    assert angry.emotion == "angry"
    assert explicit is not None
    assert explicit.emotion == "happy"


def test_segment_validation_recovers_dialogue_speaker_from_clear_original_quote():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "别碰我。",
            "speaker": "旁白",
            "emotion": "neutral",
            "original_text": "陆衍低声道：“别碰我。”",
        }
    )

    assert segment is not None
    assert segment.type == "dialogue"
    assert segment.speaker == "陆衍"
    assert segment.emotion == "whisper"
    assert segment.instruct_emotion == "neutral"


def test_segment_validation_enriches_tense_narration_performance():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "黑色裂隙在掌心微弱起伏，像一张嵌在肉里的嘴，吞吐着空气中看不见的浊气。",
            "speaker": "旁白",
            "emotion": "neutral",
        }
    )

    assert segment is not None
    assert segment.type == "narration"
    assert segment.speaker == "旁白"
    assert segment.emotion == "mysterious"
    assert segment.instruct_emotion == "fearful"
    assert "压迫感" in segment.performance_notes
    assert "悬念停顿" in segment.performance_notes


def test_segment_validation_removes_thinking_blocks_from_spoken_text():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segment

    segment = build_script_segment(
        {
            "type": "narration",
            "text": "<think>\u4e0d\u5e94\u8be5\u8bfb\u51fa\u7684\u5206\u6790</think>\u771f\u6b63\u8981\u8bfb\u7684\u5185\u5bb9\u3002",
        }
    )

    assert segment is not None
    assert segment.text == "\u771f\u6b63\u8981\u8bfb\u7684\u5185\u5bb9\u3002"


def test_build_script_segments_falls_back_when_all_segments_invalid():
    from app.services.audiobook.script_adapter_pkg._segment_validation import build_script_segments

    segments = build_script_segments(
        [{"text": ""}, {"text": "!!!"}],
        fallback_text="\u8fd9\u662f\u4e00\u6bb5\u53ef\u7528\u7684\u539f\u6587\u3002",
    )

    assert len(segments) == 1
    assert segments[0].text == "\u8fd9\u662f\u4e00\u6bb5\u53ef\u7528\u7684\u539f\u6587\u3002"
    assert segments[0].adaptation_reason == "fallback_from_invalid_llm_segments"


def test_build_script_segments_splits_long_narration_for_audiobook_cadence():
    from app.services.audiobook.script_adapter_pkg._segment_validation import (
        AUDIOBOOK_NARRATION_MAX_CHARS,
        build_script_segments,
    )

    text = (
        "一股无形吸力自他掌心爆发。守卫整条右臂的浊气如潮水倒灌，经脉中积蓄多年的祟意被强行抽离。"
        "一息之间，那手臂干瘪如朽木，皮肤龟裂，筋肉萎缩，连骨骼都发出脆响。"
        "祟意沿裂隙涌入陆衍体内，狂暴、冰冷、带着腐蚀意志的尖啸。"
        "守卫连惨叫都未及发出，双目翻白，轰然倒地。陆衍跪在地上干呕，眼前发黑。"
        "他知道，这种动静瞒不过巡逻队。必须走！"
    )

    segments = build_script_segments(
        [
            {
                "type": "narration",
                "text": text,
                "speaker": "旁白",
                "emotion": "tense",
                "sound_effects": [{"name": "骨裂声"}],
                "music_cue": {"style": "低频紧张弦乐"},
                "voice_params": {"pause_before": 0.4, "pause_after": 0.6},
            }
        ]
    )

    assert len(segments) > 1
    assert "".join(segment.text for segment in segments) == text
    assert all(len(segment.text) <= AUDIOBOOK_NARRATION_MAX_CHARS for segment in segments)
    assert segments[0].sound_effects
    assert segments[0].music_cue is not None
    assert all(not segment.sound_effects for segment in segments[1:])
    assert all(segment.music_cue is None for segment in segments[1:])
    assert segments[0].pause_before == 0.4
    assert segments[-1].pause_after == 0.6
    assert all(segment.pause_after >= 0.15 for segment in segments[:-1])
    assert "auto_split_long_segment" in segments[0].adaptation_reason


@pytest.mark.asyncio
async def test_audio_from_script_skip_final_review_returns_explicit_status(monkeypatch):
    from app.services.audiobook.engine_pkg import _audio_from_script_mixin as audio_module
    from app.services.audiobook.engine_pkg._audio_from_script_mixin import AudioFromScriptMixin
    from app.services.audiobook.task_tracker import StageType, TaskTracker

    class Harness(AudioFromScriptMixin):
        def __init__(self):
            self.task_tracker = TaskTracker()
            self.audio_director = SimpleNamespace(
                formulate_strategy=lambda **kwargs: SimpleNamespace(
                    style=SimpleNamespace(value="cinematic"),
                    sound_effect_density="medium",
                )
            )
            self.script_adapter = SimpleNamespace(strategy=None)
            self.tts_engine = SimpleNamespace(get_cost_stats=lambda: {"estimated_cost": "¥0.00"})
            self.audio_mixer = SimpleNamespace(
                mix_chapter=lambda audio_list, segment_types=None: b"audio",
                get_audio_info=lambda audio: {"duration_seconds": 1.0},
            )
            self._last_effect_timeline = None
            self._last_music_timeline = None

        def _apply_audio_fx_to_strategy(self, strategy):
            return None

        async def _parallel_design(self, *args, **kwargs):
            return {}, 0, 0

        def _assign_voices(self, script_segments):
            return None

        async def _synthesize_segments_with_resume(self, script_segments, **kwargs):
            return {
                "audio_list": [b"segment"],
                "reused_indices": [],
                "synthesized_count": len(script_segments),
                "resume_source": None,
            }

        def _realign_timelines_with_audio(self, script_segments, audio_list):
            return None

        def _build_mixer_segment_types(self, script_segments):
            return [segment.type for segment in script_segments]

    monkeypatch.setattr(
        audio_module,
        "save_segment_audio_batch",
        lambda **kwargs: {"segment_count": 1, "cached_audio_paths": {"0": "temp.mp3"}},
    )

    harness = Harness()
    result = await harness.generate_chapter_audio_from_script(
        script_segments_data=[
            {"type": "narration", "text": "\u7b2c\u4e00\u6bb5\u3002", "speaker": "\u65c1\u767d"},
        ],
        chapter_id=1,
        enable_quality_review=False,
    )

    assert result["success"] is True
    assert result["stats"]["final_audio_review"] == {"skipped": True}

    task_status = harness.task_tracker.get_task_status(result["task_id"])
    assert task_status["stages"][StageType.FINAL_AUDIO_REVIEW.value]["metrics"] == {"skipped": True}


@pytest.mark.asyncio
async def test_transform_paragraph_validates_llm_segments():
    from app.services.audiobook.script_adapter_pkg._transform import (
        TRANSFORM_OUTPUT_TOKEN_MIN,
        TransformMixin,
    )

    class DummyLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            return """
            ```json
            [
              "invalid item",
              {"type": "dialog", "text": "!!!"},
              {
                "type": "dialog",
                "text": "\u4f60\u7ec8\u4e8e\u6765\u4e86\u3002",
                "speaker": "",
                "emotion": "exciting",
                "instruct_emotion": "tense",
                "voice_params": {"rate": 9, "pause_after": 9}
              }
            ]
            ```
            """

    class Harness(TransformMixin):
        def __init__(self):
            self.llm_client = DummyLLM()
            self.tts_model = "qwen3-tts-instruct-flash"
            self.strategy = None

    harness = Harness()
    segments = await harness._transform_paragraph(
        "\u539f\u6587\u5185\u5bb9\u3002",
        character_list=[],
        analysis={},
    )

    assert len(segments) == 1
    assert segments[0].text == "\u4f60\u7ec8\u4e8e\u6765\u4e86\u3002"
    assert segments[0].type == "narration"
    assert segments[0].emotion == "excited"
    assert segments[0].instruct_emotion == "fearful"
    assert segments[0].voice_params["rate"] == 2.0
    assert segments[0].voice_params["pause_after"] == 2.0
    assert harness.llm_client.calls[0]["model"] == "deepseek-v4-flash"
    assert TRANSFORM_OUTPUT_TOKEN_MIN <= harness.llm_client.calls[0]["max_tokens"] < 32000
    assert harness.llm_client.calls[0]["timeout"] >= 90
    assert harness.llm_client.calls[0]["max_retries"] == 2


@pytest.mark.asyncio
async def test_transform_prompt_requires_dialogue_speaker_attribution():
    from app.services.audiobook.script_adapter_pkg._transform import TransformMixin

    class CapturingLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            return '{"segments": [{"type": "dialogue", "text": "别碰我。", "speaker": "陆衍"}]}'

    class Harness(TransformMixin):
        def __init__(self):
            self.llm_client = CapturingLLM()
            self.tts_model = "qwen3-tts-instruct-flash"
            self.strategy = None

    harness = Harness()
    await harness._transform_paragraph(
        "陆衍低声道：“别碰我。”",
        character_list=["陆衍"],
        analysis={"recommended_emotions": ["tense", "fearful"], "emotional_tone": "tense"},
    )

    prompt = harness.llm_client.calls[0]["messages"][0]["content"]
    assert "直接引语必须拆成 dialogue" in prompt
    assert "不要把角色台词归到旁白" in prompt
    assert "只有叙述性文字才使用 speaker=旁白" in prompt
    assert "旁白也必须有情绪层次" in prompt


@pytest.mark.asyncio
async def test_transform_to_script_preserves_short_source_lines():
    from app.services.audiobook.script_adapter_pkg._transform import TransformMixin

    class Harness(TransformMixin):
        def __init__(self):
            self.strategy = None
            self.seen_batches = []

        async def _transform_paragraph(self, paragraph, *args, **kwargs):
            self.seen_batches.append(paragraph)
            return [SimpleNamespace(text=paragraph)]

    harness = Harness()
    segments = await harness._transform_to_script(
        "他说：\n是。\n别走。\n门外的风忽然停了。",
        character_list=[],
        analysis={},
    )

    assert len(segments) == 1
    assert "是。" in harness.seen_batches[0]
    assert "别走。" in harness.seen_batches[0]


@pytest.mark.asyncio
async def test_transform_to_script_splits_large_source_into_smaller_batches():
    from app.services.audiobook.script_adapter_pkg._transform import (
        TRANSFORM_BATCH_HARD_CHARS,
        TransformMixin,
    )

    class Harness(TransformMixin):
        def __init__(self):
            self.strategy = None
            self.seen_batches = []

        async def _transform_paragraph(self, paragraph, *args, **kwargs):
            self.seen_batches.append(paragraph)
            return [SimpleNamespace(text=paragraph)]

    line = "风声压过巷口，脚步声贴着墙根追来。"
    content = "\n".join(line * 6 for _ in range(20))

    harness = Harness()
    await harness._transform_to_script(
        content,
        character_list=[],
        analysis={},
    )

    assert len(harness.seen_batches) > 1
    assert max(len(batch) for batch in harness.seen_batches) <= TRANSFORM_BATCH_HARD_CHARS


@pytest.mark.asyncio
async def test_transform_to_script_passes_continuity_context_between_batches():
    from app.services.audiobook.script_adapter_pkg._transform import TransformMixin

    class Harness(TransformMixin):
        def __init__(self):
            self.strategy = None
            self.contexts = []

        async def _transform_paragraph(
            self,
            paragraph,
            *args,
            continuity_context="",
            **kwargs,
        ):
            self.contexts.append(continuity_context)
            batch_no = len(self.contexts)
            return [
                SimpleNamespace(
                    type="narration",
                    text=f"第{batch_no}批改编后的结尾。",
                    speaker="旁白",
                    emotion="tense",
                )
            ]

    line = "风声压过巷口，脚步声贴着墙根追来。"
    content = "\n".join(line * 6 for _ in range(20))

    harness = Harness()
    await harness._transform_to_script(
        content,
        character_list=[],
        analysis={},
    )

    assert len(harness.contexts) > 1
    assert harness.contexts[0] == ""
    assert "第1批改编后的结尾" in harness.contexts[1]
    assert "不要复述" not in harness.contexts[1]


@pytest.mark.asyncio
async def test_transform_paragraph_falls_back_to_source_text_on_llm_failure():
    from app.services.audiobook.script_adapter_pkg._transform import TransformMixin

    class BrokenLLM:
        async def chat(self, **kwargs):
            raise RuntimeError("llm unavailable")

    class Harness(TransformMixin):
        def __init__(self):
            self.llm_client = BrokenLLM()
            self.tts_model = "qwen3-tts-instruct-flash"
            self.strategy = None

    harness = Harness()
    segments = await harness._transform_paragraph(
        "别走。\n门外的风忽然停了。",
        character_list=[],
        analysis={},
    )

    assert len(segments) == 1
    assert segments[0].type == "narration"
    assert segments[0].speaker == "旁白"
    assert segments[0].text == "别走。门外的风忽然停了。"
    assert segments[0].adaptation_reason == "fallback_from_invalid_llm_segments"


@pytest.mark.asyncio
async def test_transform_paragraph_retries_smaller_chunks_after_json_parse_failure():
    from app.services.audiobook.script_adapter_pkg._transform import TransformMixin

    class FlakyLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            prompt = kwargs["messages"][0]["content"]
            source_text = prompt.split("**原文段落**:", 1)[-1].split("**输出格式**", 1)[0]
            if len(self.calls) == 1:
                return '{"segments": [{"type": "narration", "text": "坏 JSON"'
            if "第一句" in source_text:
                return '{"segments": [{"type": "narration", "text": "第一句。", "speaker": "旁白"}]}'
            if "第二句" in source_text:
                return '{"segments": [{"type": "narration", "text": "第二句。", "speaker": "旁白"}]}'
            return '{"segments": []}'

    class Harness(TransformMixin):
        def __init__(self):
            self.llm_client = FlakyLLM()
            self.tts_model = "qwen3-tts-instruct-flash"
            self.strategy = None

    harness = Harness()
    segments = await harness._transform_paragraph(
        "第一句。\n第二句。",
        character_list=[],
        analysis={},
    )

    assert [segment.text for segment in segments] == ["第一句。", "第二句。"]
    assert len(harness.llm_client.calls) == 3
