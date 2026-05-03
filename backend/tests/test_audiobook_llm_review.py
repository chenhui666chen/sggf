import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


class DummyLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def make_segment(text: str, **overrides):
    from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment

    data = {
        "type": "narration",
        "text": text,
        "speaker": "\u65c1\u767d",
        "emotion": "neutral",
    }
    data.update(overrides)
    return ScriptSegment(**data)


def test_calculate_text_coverage_detects_chinese_text_loss():
    from app.services.audiobook.script_adapter_pkg._llm_review import calculate_text_coverage

    original = [make_segment("\u591c\u8272\u538b\u4e0b\u6765\u3002\u8857\u706f\u4eae\u8d77\u3002")]

    assert calculate_text_coverage(original, [make_segment("\u591c\u8272\u538b\u4e0b\u6765\u3002\u8857\u706f\u4eae\u8d77\u3002")]) == 1.0
    assert calculate_text_coverage(original, [make_segment("\u591c\u8272\u538b\u4e0b\u6765\u3002")]) < 0.92


@pytest.mark.asyncio
async def test_llm_review_applies_structural_fix_with_flash_model():
    from app.services.audiobook.script_adapter_pkg._llm_review import review_script_segments_with_llm

    llm = DummyLLM(
        """
        {
          "segments": [
            {
              "type": "narration",
              "speaker": "\u65c1\u767d",
              "text": "\u591c\u8272\u538b\u4e0b\u6765\u3002\u8857\u706f\u4eae\u8d77\u3002",
              "emotion": "neutral",
              "performance_notes": "\u4f4e\u6c89\u5e73\u7a33\u3002"
            }
          ]
        }
        """
    )
    original = [make_segment("\u591c\u8272\u538b\u4e0b\u6765\u3002\u8857\u706f\u4eae\u8d77\u3002")]

    result = await review_script_segments_with_llm(llm, original)

    assert result.report["applied"] is True
    assert result.report["coverage_ratio"] == 1.0
    assert result.segments[0].performance_notes == "\u4f4e\u6c89\u5e73\u7a33\u3002"
    assert llm.calls[0]["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_llm_review_falls_back_when_text_coverage_is_low():
    from app.services.audiobook.script_adapter_pkg._llm_review import review_script_segments_with_llm

    llm = DummyLLM(
        """
        {
          "segments": [
            {
              "type": "narration",
              "speaker": "\u65c1\u767d",
              "text": "\u591c\u8272\u538b\u4e0b\u6765\u3002",
              "emotion": "neutral"
            }
          ]
        }
        """
    )
    original = [make_segment("\u591c\u8272\u538b\u4e0b\u6765\u3002\u8857\u706f\u4eae\u8d77\u3002")]

    result = await review_script_segments_with_llm(llm, original, min_text_coverage=0.92)

    assert result.report["applied"] is False
    assert result.report["failed_batches"] == 1
    assert result.segments[0].text == original[0].text


def test_summarize_script_review_report_keeps_stable_debug_fields():
    from app.services.audiobook.script_adapter_pkg._llm_review import summarize_script_review_report

    summary = summarize_script_review_report(
        {
            "attempted": True,
            "applied": True,
            "reason": "review_applied",
            "original_count": 2,
            "reviewed_count": 3,
            "coverage_ratio": 0.987654,
            "changed_batches": 1,
            "failed_batches": 0,
            "batches": [{"large": "payload"}],
        }
    )

    assert summary == {
        "attempted": True,
        "applied": True,
        "reason": "review_applied",
        "original_count": 2,
        "reviewed_count": 3,
        "coverage_ratio": 0.9877,
        "changed_batches": 1,
        "failed_batches": 0,
    }


@pytest.mark.asyncio
async def test_adapt_chapter_respects_script_review_env_kill_switch(monkeypatch):
    from app.services.audiobook.script_adapter_pkg._base import AudiobookScriptAgentBase

    class Harness(AudiobookScriptAgentBase):
        async def _analyze_chapter(self, *args, **kwargs):
            return {}

        async def _transform_to_script(self, *args, **kwargs):
            return [make_segment("\u591c\u8272\u538b\u4e0b\u6765\u3002")]

    monkeypatch.setenv("AUDIOBOOK_ENABLE_SCRIPT_REVIEW", "false")
    llm = DummyLLM('{"segments": []}')
    harness = Harness(llm_client=llm)

    segments = await harness.adapt_chapter(
        chapter_content="\u591c\u8272\u538b\u4e0b\u6765\u3002",
        enable_chapter_structure=False,
        enable_llm_script_review=True,
    )

    assert len(segments) == 1
    assert llm.calls == []
    assert harness.last_script_review == {
        "attempted": False,
        "applied": False,
        "reason": "disabled",
    }
