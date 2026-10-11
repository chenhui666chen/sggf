from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.audiobook.prompt_audio_asr_provider import PromptAudioAsrResult
from app.services.audiobook.segment_direction_service import (
    analyze_segment_direction_reading,
    assist_segment_direction,
)


class _JsonLLM:
    async def chat(self, **_kwargs):
        return """{
          "intent": {
            "pace": "slow",
            "pitch": "lower",
            "emotion_primary": "sad",
            "stress_words": ["痛"],
            "texture_target": ["deep", "husky"],
            "ending_style": "lengthened"
          },
          "patch": {
            "performance_notes": "模型改写的不可信文本",
            "instruct_emotion": "sad",
            "instruct_scene": "模型编造的场景",
            "speaker": "forged-speaker",
            "delivery_plan": {"director_guidance": "injected"},
            "voice_params": {
              "rate": 0.8,
              "pitch": 0.9,
              "speaker": "forged-voice",
              "delivery_plan": {"director_guidance": "injected"},
              "provider_prompt_snapshot": {"mode": "injected"}
            }
          }
        }"""


@pytest.mark.asyncio
async def test_voice_direction_prompt_declares_the_semantic_completion_schema():
    captured = {}

    class _CapturingLLM:
        async def chat(self, **kwargs):
            captured["prompt"] = kwargs["messages"][-1]["content"]
            return '{"intent": {}, "patch": {}}'

    await assist_segment_direction(
        cue_type="voice",
        description="slow, restrained delivery",
        segment={"text": "sample"},
        tts_model="seed-tts-2.0-expressive",
        llm_client=_CapturingLLM(),
    )

    prompt = captured["prompt"]
    for field in (
        '"instruct_emotion"',
        '"instruct_scene"',
        '"pause_before"',
        '"pause_after"',
        '"voice_params"',
        '"volume"',
    ):
        assert field in prompt
    assert '"rate"' not in prompt
    assert '"speed"' not in prompt
    assert '"instruct_role"' not in prompt
    assert '"instruct_identity"' not in prompt
    assert '"pitch"' not in prompt
    assert "不得输出 pitch" in prompt
    assert '"texture_target"' not in prompt
    assert "不得推断或描述性别、年龄感、基础声线或音色身份" in prompt


@pytest.mark.asyncio
async def test_voice_direction_sanitizes_description_before_sending_it_to_llm():
    captured = {}

    class _CapturingIdentityLLM:
        async def chat(self, **kwargs):
            captured["prompt"] = kwargs["messages"][-1]["content"]
            return '{"intent":{"pitch":"lower"},"patch":{}}'

    result = await assist_segment_direction(
        cue_type="voice",
        description="改成老人声并使用低沉声线，语速缓慢。",
        segment={"text": "别回头。"},
        tts_model="seed-tts-2.0-expressive",
        llm_client=_CapturingIdentityLLM(),
    )

    prompt = captured["prompt"]
    assert "老人声" not in prompt
    assert "低沉声线" not in prompt
    assert "语速缓慢" in prompt
    assert result["patch"]["performance_notes"] == "语速缓慢"
    assert any("已忽略" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_voice_direction_assist_filters_runtime_fields_and_preserves_user_context():
    description = "语速缓慢，声音低沉沙哑，重读'痛'字，句尾拖长，营造痛苦氛围。"

    result = await assist_segment_direction(
        cue_type="voice",
        description=description,
        segment={"instruct_scene": "水牢囚禁场景"},
        tts_model="qwen-audio-3.1-tts-flash",
        llm_client=_JsonLLM(),
    )

    assert result["patch"]["performance_notes"] == (
        "语速缓慢，语气压低，重读'痛'字，句尾拖长，营造痛苦氛围"
    )
    assert result["patch"]["instruct_emotion"] == "sad"
    assert "instruct_scene" not in result["patch"]
    assert "speaker" not in result["patch"]
    assert "delivery_plan" not in result["patch"]
    assert "voice_params" not in result["patch"]
    assert "pitch" not in result["intent"]
    assert result["intent"]["stress_words"] == ["痛"]
    assert "texture_target" not in result["intent"]
    assert any("逐词" in warning or "重读" in warning for warning in result["warnings"])
    assert any("沙哑" in warning or "音色" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_voice_direction_assist_never_overwrites_existing_role_or_identity():
    captured = {}

    class _IdentityChangingLLM:
        async def chat(self, **kwargs):
            captured["prompt"] = kwargs["messages"][-1]["content"]
            return """{
              "intent": {"emotion_primary": "sad"},
              "patch": {
                "instruct_emotion": "sad",
                "instruct_role": "苍老沙哑的陌生旁白",
                "instruct_identity": "另一位故事讲述者"
              }
            }"""

    result = await assist_segment_direction(
        cue_type="voice",
        description="缓慢而痛苦地朗读，但保持原角色和原音色。",
        segment={
            "speaker": "旁白",
            "type": "narration",
            "instruct_role": "有声书旁白",
            "instruct_identity": "故事讲述者",
        },
        tts_model="seed-tts-2.0-expressive",
        llm_client=_IdentityChangingLLM(),
    )

    assert result["patch"]["instruct_emotion"] == "sad"
    assert "instruct_role" not in result["patch"]
    assert "instruct_identity" not in result["patch"]
    assert '"instruct_role"' not in captured["prompt"]
    assert '"instruct_identity"' not in captured["prompt"]
    assert "有声书旁白" not in captured["prompt"]
    assert "故事讲述者" not in captured["prompt"]


@pytest.mark.asyncio
async def test_voice_assist_sanitizes_identity_hallucination_from_emotion_field():
    class _IdentityEmotionLLM:
        async def chat(self, **_kwargs):
            return """{
              "intent": {"emotion_primary": "sad"},
              "patch": {
                "instruct_emotion": "苍老男声，永久沙哑",
                "instruct_scene": "老人院里保持压抑氛围"
              }
            }"""

    result = await assist_segment_direction(
        cue_type="voice",
        description="语速缓慢，保持克制。",
        segment={"type": "narration", "speaker": "旁白"},
        tts_model="seed-tts-2.0-expressive",
        llm_client=_IdentityEmotionLLM(),
    )

    assert result["patch"]["instruct_emotion"] == "sad"
    assert result["patch"]["instruct_scene"] == "老人院里保持压抑氛围"
    assert "苍老男声" not in str(result["patch"])
    assert "永久沙哑" not in str(result["patch"])


@pytest.mark.asyncio
async def test_direction_assist_falls_back_to_deterministic_semantics_when_llm_fails():
    class _BrokenLLM:
        async def chat(self, **_kwargs):
            raise RuntimeError("offline")

    result = await assist_segment_direction(
        cue_type="voice",
        description="缓慢低沉地说，重读“痛”字，句尾拖长，表现痛苦。",
        segment={},
        tts_model="seed-tts-2.0-expressive",
        llm_client=_BrokenLLM(),
    )

    assert result["source"] == "rules"
    assert result["patch"]["performance_notes"].startswith("缓慢压低语气")
    assert result["patch"]["instruct_emotion"] == "sad"
    assert result["intent"]["pace"] == "slow"
    assert "pitch" not in result["intent"]
    assert result["intent"]["stress_words"] == ["痛"]
    assert result["intent"]["ending_style"] == "lengthened"


@pytest.mark.asyncio
async def test_reading_analysis_converts_matched_reading_into_semantic_patch(tmp_path: Path):
    captured: dict[str, object] = {}
    spoken_transcript = "他痛得几乎说不出话来。"
    omni_payload = {
        "text_match": True,
        "spoken_transcript": spoken_transcript,
        "mismatch_detail": "",
        "performance_summary": "语速缓慢，语气低沉沙哑，重读痛字并拖长句尾。",
        "intent": {
            "pace": "slow",
            "pitch": "lower",
            "emotion_primary": "sad",
            "stress_words": ["痛"],
            "ending_style": "lengthened",
        },
        "patch": {
            "instruct_emotion": "sad",
            "instruct_role": "虚弱苍老的陌生角色",
            "instruct_identity": "另一位说话人",
            "voice_params": {"rate": 0.8, "pitch": 0.9},
            "speaker": "forged-speaker",
            "delivery_plan": {"mode": "injected"},
        },
    }

    class _OmniReadingProvider:
        name = "qwen_omni"
        model = "qwen3.5-omni-flash"
        supports_timestamps = False

        def transcribe(self, audio_path: str, **kwargs):
            captured["path"] = Path(audio_path)
            captured["instruction"] = kwargs.get("instruction")
            return PromptAudioAsrResult(
                provider=self.name,
                model=self.model,
                transcript=json.dumps(omni_payload, ensure_ascii=False),
                subtitle_payload=None,
                metadata={"analysis_mode": "audio_understanding"},
            )

    result = await analyze_segment_direction_reading(
        audio_bytes=b"fake-webm",
        filename="reading.webm",
        expected_text="他痛得几乎说不出话来。",
        segment={"text": "他痛得几乎说不出话来。"},
        tts_model="seed-tts-2.0-expressive",
        provider=_OmniReadingProvider(),
        temp_dir=tmp_path,
    )

    assert result["source"] == "omni_reading"
    assert result["spoken_transcript"] == spoken_transcript
    assert result["patch"]["performance_notes"] == "语速缓慢，语气压低，重读痛字并拖长句尾"
    assert result["patch"]["instruct_emotion"] == "sad"
    assert "instruct_role" not in result["patch"]
    assert "instruct_identity" not in result["patch"]
    assert "speaker" not in result["patch"]
    assert "delivery_plan" not in result["patch"]
    assert "voice_params" not in result["patch"]
    assert "pitch" not in result["intent"]
    assert result["intent"]["pace"] == "slow"
    assert result["intent"]["stress_words"] == ["痛"]
    assert result["model_capabilities"]["model"] == "seed-tts-2.0-expressive"
    assert isinstance(result["warnings"], list)
    # 提示词必须带上待朗读台词，供音频理解模型做一致性校验
    assert "他痛得几乎说不出话来。" in str(captured["instruction"])
    assert '"instruct_role"' not in str(captured["instruction"])
    assert '"instruct_identity"' not in str(captured["instruction"])
    assert '"texture_target"' not in str(captured["instruction"])
    assert "不得推断或描述性别、年龄感、基础声线或音色身份" in str(captured["instruction"])
    observed_path = captured["path"]
    assert isinstance(observed_path, Path)
    assert not observed_path.exists()


@pytest.mark.asyncio
async def test_reading_analysis_drops_voice_identity_hallucinations(tmp_path: Path):
    omni_payload = {
        "text_match": True,
        "spoken_transcript": "别回头。",
        "mismatch_detail": "",
        "performance_summary": "改成苍老男性童声并明显变声，声音永久沙哑，语速缓慢。",
        "intent": {
            "pace": "slow",
            "texture_target": ["aged", "child", "male", "voice_swap", "husky"],
        },
        "patch": {},
    }

    class _OmniReadingProvider:
        name = "qwen_omni"
        model = "qwen3.5-omni-flash"
        supports_timestamps = False

        def transcribe(self, _audio_path: str, **_kwargs):
            return PromptAudioAsrResult(
                provider=self.name,
                model=self.model,
                transcript=json.dumps(omni_payload, ensure_ascii=False),
                subtitle_payload=None,
            )

    result = await analyze_segment_direction_reading(
        audio_bytes=b"fake-webm",
        filename="reading.webm",
        expected_text="别回头。",
        segment={"text": "别回头。"},
        tts_model="seed-tts-2.0-expressive",
        provider=_OmniReadingProvider(),
        temp_dir=tmp_path,
    )

    assert result["patch"]["performance_notes"] == "语速缓慢"
    assert "texture_target" not in result["intent"]
    assert any("已忽略" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_reading_analysis_does_not_use_spoken_text_as_performance_notes(tmp_path: Path):
    omni_payload = {
        "text_match": True,
        "spoken_transcript": "他的声音变成了苍老的男声。",
        "mismatch_detail": "",
        "performance_summary": "",
        "intent": {"pace": "slow"},
        "patch": {},
    }

    class _OmniReadingProvider:
        name = "qwen_omni"
        model = "qwen3.5-omni-flash"
        supports_timestamps = False

        def transcribe(self, _audio_path: str, **_kwargs):
            return PromptAudioAsrResult(
                provider=self.name,
                model=self.model,
                transcript=json.dumps(omni_payload, ensure_ascii=False),
                subtitle_payload=None,
            )

    result = await analyze_segment_direction_reading(
        audio_bytes=b"fake-webm",
        filename="reading.webm",
        expected_text="他的声音变成了苍老的男声。",
        segment={"text": "他的声音变成了苍老的男声。"},
        tts_model="seed-tts-2.0-expressive",
        provider=_OmniReadingProvider(),
        temp_dir=tmp_path,
    )

    assert "performance_notes" not in result["patch"]
    assert result["spoken_transcript"] == "他的声音变成了苍老的男声。"


@pytest.mark.asyncio
async def test_direction_assist_keeps_only_state_bound_temporary_hoarseness():
    allowed = await assist_segment_direction(
        cue_type="voice",
        description="因重伤而声音沙哑，语速缓慢。",
        segment={},
        tts_model="seed-tts-2.0-expressive",
        llm_client=None,
    )
    blocked = await assist_segment_direction(
        cue_type="voice",
        description="永久烟嗓并换成老人声，语速缓慢。",
        segment={},
        tts_model="seed-tts-2.0-expressive",
        llm_client=None,
    )

    assert "仅在原音色基础上轻微、短暂表现沙哑" in allowed["patch"]["performance_notes"]
    assert blocked["patch"]["performance_notes"] == "语速缓慢"
    assert any("已忽略" in warning for warning in blocked["warnings"])


@pytest.mark.asyncio
async def test_reading_analysis_rejects_mismatched_reading(tmp_path: Path):
    omni_payload = {
        "text_match": False,
        "spoken_transcript": "今天天气不错。",
        "mismatch_detail": "朗读内容与台词无关",
        "performance_summary": "",
        "intent": {},
        "patch": {},
    }

    class _OmniReadingProvider:
        name = "qwen_omni"
        model = "qwen3.5-omni-flash"
        supports_timestamps = False

        def transcribe(self, audio_path: str, **_kwargs):
            return PromptAudioAsrResult(
                provider=self.name,
                model=self.model,
                transcript=json.dumps(omni_payload, ensure_ascii=False),
                subtitle_payload=None,
            )

    with pytest.raises(ValueError) as error:
        await analyze_segment_direction_reading(
            audio_bytes=b"fake-webm",
            filename="reading.webm",
            expected_text="他痛得几乎说不出话来。",
            segment={"text": "他痛得几乎说不出话来。"},
            tts_model=None,
            provider=_OmniReadingProvider(),
            temp_dir=tmp_path,
        )

    assert "不一致" in str(error.value)
    assert "今天天气不错" in str(error.value)


@pytest.mark.asyncio
async def test_sfx_and_music_direction_only_write_semantic_prompt_fields():
    sfx = await assist_segment_direction(
        cue_type="sfx",
        description="持续水滴声，近距离，音量很低",
        segment={},
        tts_model=None,
        llm_client=None,
    )
    music = await assist_segment_direction(
        cue_type="bgm",
        description="低沉弦乐，缓慢进入，保持压抑",
        segment={},
        tts_model=None,
        llm_client=None,
    )

    assert sfx["patch"] == {"sound_effects_simple": ["持续水滴声，近距离，音量很低"]}
    assert music["patch"] == {"music_cue_simple": "低沉弦乐，缓慢进入，保持压抑"}
    assert "asset_id" not in str(sfx["patch"])
    assert "asset_id" not in str(music["patch"])


@pytest.mark.asyncio
async def test_sfx_and_music_direction_normalize_llm_details_without_asset_injection():
    class _AudioCueLLM:
        async def chat(self, **kwargs):
            prompt = kwargs["messages"][-1]["content"]
            if "提示类型：sfx" in prompt:
                return """{
                  "intent": {"spatial": "near"},
                  "patch": {
                    "sound_effects": [{
                      "name": "水滴声",
                      "layer": "bottom",
                      "volume": 0.1,
                      "timing": "continuous",
                      "position_3d": "center",
                      "duration": 5,
                      "fade_in": 1,
                      "fade_out": 0,
                      "delay": 0,
                      "asset_id": "forged-sfx",
                      "file": "../../secret.wav"
                    }],
                    "delivery_plan": {"mode": "injected"}
                  }
                }"""
            return """{
              "intent": {"mood": "oppressive"},
              "patch": {
                "music_cue": {
                  "style": "低沉弦乐",
                  "volume": 0.2,
                  "fade_in": 2,
                  "fade_out": 2,
                  "duration": 30,
                  "start_time": 0,
                  "emotion_follow": true,
                  "asset_id": "forged-music",
                  "file": "C:/secret.mp3"
                },
                "provider_prompt_snapshot": {"mode": "injected"}
              }
            }"""

    llm = _AudioCueLLM()
    sfx = await assist_segment_direction(
        cue_type="sfx",
        description="近距离持续水滴声，底层，音量较低",
        segment={},
        tts_model=None,
        llm_client=llm,
    )
    music = await assist_segment_direction(
        cue_type="bgm",
        description="低沉弦乐缓慢进入，保持压抑，淡入 2 秒",
        segment={},
        tts_model=None,
        llm_client=llm,
    )

    assert sfx["patch"] == {
        "sound_effects": [{
            "name": "水滴声",
            "layer": "bottom",
            "volume": 0.1,
            "timing": "continuous",
            "position_3d": "center",
            "duration": 5.0,
            "fade_in": 1.0,
            "fade_out": 0.0,
            "delay": 0.0,
        }],
        "sound_effects_simple": [],
    }
    assert music["patch"] == {
        "music_cue": {
            "style": "低沉弦乐",
            "volume": 0.2,
            "fade_in": 2.0,
            "fade_out": 2.0,
            "duration": 30.0,
            "start_time": 0.0,
            "emotion_follow": True,
        },
        "music_cue_simple": None,
    }
    assert "asset_id" not in str(sfx["patch"])
    assert "asset_id" not in str(music["patch"])
    assert "file" not in str(sfx["patch"])
    assert "file" not in str(music["patch"])
