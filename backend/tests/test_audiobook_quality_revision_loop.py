from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer
from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment


class CapturingLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def make_engine(response: str):
    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = AudioQualityReviewer()
    engine._audio_fx_config = {}
    engine._last_source_text_for_script_revision = "陆衍从后窗翻出，守卫一掌拍向后心。"
    engine._last_llm_script_review = {"applied": False, "reason": "no_changes"}
    engine.script_adapter = SimpleNamespace(llm_client=CapturingLLM(response))
    return engine


def test_llm_quality_revision_prompt_carries_review_feedback_and_fidelity_contract():
    engine = make_engine(
        """{
          "segments": [
            {
              "type": "narration",
              "text": "陆衍从后窗翻出，守卫一掌拍向后心。",
              "speaker": "旁白",
              "emotion": "tense",
              "performance_notes": "压低声线，句尾停顿。",
              "pause_after": 0.35
            }
          ]
        }"""
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="陆衍从后窗翻出，守卫一掌拍向后心。",
            speaker="旁白",
            emotion="tense",
        )
    ]
    quality_report = engine.audio_quality_reviewer.review_script(
        engine._build_review_segments(segments),
        novel_genre="玄幻",
    )

    result = engine._llm_revise_script_segments_from_quality_report(
        segments,
        quality_report,
        novel_genre="玄幻",
    )

    assert result["applied"] is True
    prompt = engine.script_adapter.llm_client.calls[0]["messages"][1]["content"]
    assert "质量评审意见" in prompt
    assert "不得新增原文不存在的武器、招式、道具、台词或人物行动" in prompt
    assert "直接引语必须来自原文或当前剧本" in prompt
    assert "陆衍从后窗翻出，守卫一掌拍向后心" in prompt
    assert "issues:" in prompt


def test_llm_quality_revision_rejects_low_coverage_output():
    engine = make_engine(
        """{
          "segments": [
            {
              "type": "narration",
              "text": "完全不同的新剧情。",
              "speaker": "旁白",
              "emotion": "tense"
            }
          ]
        }"""
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="陆衍从后窗翻出，守卫一掌拍向后心。",
            speaker="旁白",
            emotion="tense",
        )
    ]
    quality_report = engine.audio_quality_reviewer.review_script(
        engine._build_review_segments(segments),
        novel_genre="玄幻",
    )

    result = engine._llm_revise_script_segments_from_quality_report(
        segments,
        quality_report,
        novel_genre="玄幻",
    )

    assert result["applied"] is False
    assert result["reason"].startswith("text_coverage_below_threshold")
    assert segments[0].text == "陆衍从后窗翻出，守卫一掌拍向后心。"
