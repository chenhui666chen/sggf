from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer
from app.services.audiobook.engine_pkg._base import (
    QUALITY_REVISION_MAX_TOKEN_CAP,
    QUALITY_REVISION_RETRY_MAX_TOKEN_CAP,
    AudiobookEngineBase,
)
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment


class CapturingLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class SequencedLLM:
    """按调用次序依次返回预设响应，用于模拟首次截断 + 重试完整的场景。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def make_engine(response: str):
    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = AudioQualityReviewer()
    engine._audio_fx_config = {}
    engine._last_source_text_for_script_revision = "陆衍从后窗翻出，守卫一掌拍向后心。"
    engine._last_llm_script_review = {"applied": False, "reason": "no_changes"}
    engine.script_adapter = SimpleNamespace(llm_client=CapturingLLM(response))
    return engine


def make_engine_with_llm(llm):
    engine = AudiobookEngineBase.__new__(AudiobookEngineBase)
    engine.audio_quality_reviewer = AudioQualityReviewer()
    engine._audio_fx_config = {}
    engine._last_source_text_for_script_revision = "陆衍从后窗翻出，守卫一掌拍向后心。"
    engine._last_llm_script_review = {"applied": False, "reason": "no_changes"}
    engine.script_adapter = SimpleNamespace(llm_client=llm)
    return engine


def test_quality_gate_default_performance_note_does_not_change_selected_voice():
    engine = make_engine('{"segments": []}')
    segment = ScriptSegment(
        type="narration",
        text="门外的脚步突然停下。",
        speaker="旁白",
        emotion="fearful",
    )

    note = engine._default_performance_note_for_segment(segment)

    assert "语势" in note
    assert "语速" in note
    assert "停顿" in note
    for forbidden in ("声线", "音色", "低沉", "童声", "老人声"):
        assert forbidden not in note


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
    assert "固定音色表演边界" in prompt


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


def test_llm_quality_revision_retries_with_larger_budget_when_output_truncated():
    """首次输出被 max_tokens 截断（salvage 只能恢复前缀）时，应扩容重试并采用完整输出。"""
    truncated_response = (
        '{"segments": ['
        '{"type": "narration", "text": "陆衍从后窗翻出，守卫一掌拍向后心。", '
        '"speaker": "旁白", "emotion": "tense", "performance_notes": "压低声线，句尾停顿。", "pause_after": 0.35},'
        '{"type": "dialogue", "text": "你以为逃得掉'
    )
    complete_response = (
        '{"segments": ['
        '{"type": "narration", "text": "陆衍从后窗翻出，守卫一掌拍向后心。", '
        '"speaker": "旁白", "emotion": "tense", "performance_notes": "压低声线，句尾停顿。", "pause_after": 0.35},'
        '{"type": "dialogue", "text": "你以为逃得掉吗？", '
        '"speaker": "守卫", "emotion": "angry", "performance_notes": "加重语气，威胁感。", "pause_after": 0.3},'
        '{"type": "narration", "text": "陆衍翻身落地，借着夜色狂奔。", '
        '"speaker": "旁白", "emotion": "tense", "performance_notes": "节奏加快。", "pause_after": 0.35}'
        ']}'
    )
    llm = SequencedLLM([truncated_response, complete_response])
    engine = make_engine_with_llm(llm)
    segments = [
        ScriptSegment(type="narration", text="陆衍从后窗翻出，守卫一掌拍向后心。", speaker="旁白", emotion="tense"),
        ScriptSegment(type="dialogue", text="你以为逃得掉吗？", speaker="守卫", emotion="angry"),
        ScriptSegment(type="narration", text="陆衍翻身落地，借着夜色狂奔。", speaker="旁白", emotion="tense"),
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

    # 成于重试的完整输出：三个片段全部被修订，无需用原剧本补尾
    assert result["applied"] is True
    assert result["segments_after"] == 3
    assert len(llm.calls) == 2
    assert llm.calls[1]["max_tokens"] > llm.calls[0]["max_tokens"]
    assert segments[1].performance_notes == "加重语气，威胁感。"
    # 旁白片段的 performance_notes 会被 _enrich_narration_delivery 追加演绎提示，只需验证 LLM 修订内容已生效
    assert segments[2].performance_notes.startswith("节奏加快。")


def test_estimate_quality_revision_max_tokens_uses_retry_cap_for_large_payload():
    """大剧本按 2.5 倍估算超过常规上限时，应直接采用重试档预算，
    避免首次调用在 32768 截断后再扩容重试的二次 LLM 调用浪费。"""
    engine = make_engine('{"segments": []}')
    # 约 4 万字的剧本：len(payload) * 2.5 + 1500 远超 32768
    payload_json = json.dumps({"segments": [{"text": "陆衍" * 20000}]})
    estimated = engine._estimate_quality_revision_max_tokens(payload_json)
    assert estimated == QUALITY_REVISION_RETRY_MAX_TOKEN_CAP


def test_estimate_quality_revision_max_tokens_small_payload_stays_in_normal_cap():
    engine = make_engine('{"segments": []}')
    small_payload = json.dumps({"segments": [{"text": "陆衍从后窗翻出。"}]})
    estimated = engine._estimate_quality_revision_max_tokens(small_payload)
    assert estimated <= QUALITY_REVISION_MAX_TOKEN_CAP
    assert estimated >= 2000
