import json
import os
import sys
from types import SimpleNamespace

import pytest


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

for path in (ROOT_DIR, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.audiobook.script_adapter import AudiobookScriptAgent
from app.services.chapter_adaptation_assets import (
    attach_cross_media_adaptation_hints,
    build_drama_source_text,
)


def test_attach_cross_media_adaptation_hints_builds_audio_and_drama_assets() -> None:
    summary_data = {
        "core_summary": "Investigation deepens inside the archive vault.",
        "scene_goal": "infiltrate archive vault",
        "key_events": ["find hidden passage", "secure old file"],
        "appearing_characters": ["Lin", "Gu"],
        "conflict_arc": {
            "type": "pursuit",
            "description": "guards close in",
            "result": "narrow escape",
        },
        "emotion_curve": "calm -> tense -> shock",
        "highlight": {"type": "reveal", "description": "strange echo behind the wall"},
        "ending_hook": {"type": "mystery", "content": "strange echo from the vault end"},
        "foreshadowing": ["someone else already entered the passage"],
    }

    enriched = attach_cross_media_adaptation_hints(
        summary_data,
        chapter_title="Chapter 12",
        chapter_summary="Investigation deepens inside the archive vault.",
    )

    assert enriched["audio_adaptation_hint"]["voice_cast"] == ["Lin", "Gu"]
    assert "infiltrate archive vault" in enriched["audio_adaptation_hint"]["highlight_scenes"]
    assert "strange echo from the vault end" in enriched["audio_adaptation_hint"]["ending_hook"]
    assert enriched["drama_adaptation_hint"]["scene_objective"] == "infiltrate archive vault"
    assert "guards close in" in enriched["drama_adaptation_hint"]["core_conflict"]
    assert any("strange echo" in item for item in enriched["drama_adaptation_hint"]["visual_hooks"])


def test_build_drama_source_text_includes_short_drama_brief_and_body() -> None:
    chapter = SimpleNamespace(
        title="Chapter 12",
        summary="Investigation deepens inside the archive vault.",
        summary_data=json.dumps(
            {
                "scene_goal": "infiltrate archive vault",
                "key_events": ["find hidden passage", "secure old file"],
                "appearing_characters": ["Lin", "Gu"],
                "conflict_arc": {"description": "guards close in"},
                "ending_hook": {"content": "strange echo from the vault end"},
            }
        ),
        content="Full chapter body for adaptation.",
    )

    source_text = build_drama_source_text([chapter])

    assert "【短剧改编提示】" in source_text
    assert "Investigation deepens inside the archive vault." in source_text
    assert "infiltrate archive vault" in source_text
    assert "Full chapter body for adaptation." in source_text


class _FakeLLMClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        prompt = messages[0]["content"]
        self.prompts.append(prompt)

        if "章节内容节选" in prompt:
            return json.dumps(
                {
                    "theme": "archive pursuit",
                    "emotional_tone": "tense",
                    "emotion_transitions": ["calm", "tense", "shock"],
                    "rhythm_pattern": "变化丰富",
                    "highlight_scenes": ["vault reveal"],
                    "adaptation_challenges": ["keep suspense"],
                    "recommended_emotions": ["tense", "solemn"],
                    "voice_control_strategy": {
                        "pace_changes": "slow to fast",
                        "pitch_variations": "rise on reveal",
                        "pause_points": "before the echo",
                    },
                },
                ensure_ascii=False,
            )

        return json.dumps(
            [
                {
                    "type": "narration",
                    "text": "The echo rolled through the hidden vault.",
                    "speaker": "旁白",
                    "emotion": "tense",
                    "voice_params": {
                        "rate": 1.0,
                        "pitch": 1.0,
                        "pause_before": 0.2,
                        "pause_after": 0.3,
                    },
                    "performance_notes": "hold tension before the reveal",
                    "sound_effects_simple": ["echo"],
                    "music_cue_simple": "low strings",
                    "original_text": "A tense paragraph with enough length to transform.",
                    "adaptation_reason": "Keep suspense with a pause before the reveal.",
                }
            ],
            ensure_ascii=False,
        )


@pytest.mark.asyncio
async def test_audiobook_script_adapter_injects_audio_adaptation_brief_into_prompts() -> None:
    llm_client = _FakeLLMClient()
    agent = AudiobookScriptAgent(llm_client=llm_client)

    segments = await agent.adapt_chapter(
        chapter_content="A tense paragraph with enough length to transform.",
        character_list=["Lin"],
        chapter_title="Chapter 12",
        genre="mystery",
        enable_chapter_structure=False,
        adaptation_context={
            "narration_focus": "archive vault pursuit",
            "voice_cast": ["Lin", "Gu"],
            "emotion_curve": "calm -> tense -> shock",
            "highlight_scenes": ["find hidden passage"],
            "dialogue_conflicts": ["guards close in"],
            "soundscape_cues": ["strange echo from the vault end"],
            "ending_hook": "strange echo from the vault end",
        },
    )

    assert len(segments) == 1
    assert any("archive vault pursuit" in prompt for prompt in llm_client.prompts)
    assert any("strange echo from the vault end" in prompt for prompt in llm_client.prompts)
