"""LLM 多维度评审器 + 融合评分单测"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

def _make_segments(count=4):
    """构造测试用剧本片段列表（dict 格式）。"""
    segments = []
    for i in range(count):
        segments.append({
            "type": "dialogue" if i % 2 == 0 else "narration",
            "text": f"这是第{i}段测试文本，用于评审。",
            "speaker": "角色A" if i % 2 == 0 else "旁白",
            "emotion": "neutral",
            "performance_notes": "",
        })
    return segments


def _mock_llm_response():
    """模拟 LLM 返回的 JSON 字符串。"""
    import json
    return json.dumps({
        "dimensions": {
            "semantic_coherence": {"score": 8.0, "comment": "连贯性好"},
            "narrative_pacing": {"score": 7.0, "comment": "节奏适中"},
            "atmosphere_imagery": {"score": 6.5, "comment": "氛围一般"},
            "characterization": {"score": 8.5, "comment": "角色鲜明"},
            "dialogue_naturalness": {"score": 7.5, "comment": "对白自然"},
            "emotion_expression": {"score": 8.0, "comment": "情感到位"},
            "audio_cue_relevance": {"score": 7.0, "comment": "音效匹配"},
            "speakability": {"score": 9.0, "comment": "朗读流畅"},
        },
        "issues": [
            {
                "segment_index": 1,
                "dimension": "dialogue_naturalness",
                "severity": "major",
                "description": "对白过于书面化",
                "suggestion": "改为口语表达",
                "fix_type": "llm_rewrite",
                "target_fields": ["text"],
            },
            {
                "segment_index": 2,
                "dimension": "audio_cue_relevance",
                "severity": "minor",
                "description": "音效与场景不匹配",
                "suggestion": "更换为环境音",
                "fix_type": "deterministic",
                "target_fields": ["sound_effects"],
            },
        ],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# LLMQualityReviewer 测试
# ---------------------------------------------------------------------------

class TestLLMQualityReviewer:
    def test_review_prompt_keeps_fixed_voice_identity_out_of_suggestions(self):
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        reviewer = LLMQualityReviewer(llm_client=None)
        prompt = reviewer._build_review_prompt(
            '[]',
            batch_index=1,
            batch_total=1,
        )

        assert "固定音色表演边界" in prompt
        assert "在原音色基础上轻微、短暂表现沙哑" in prompt

    @pytest.mark.asyncio
    async def test_review_returns_dimensions_and_issues(self):
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        mock_client = SimpleNamespace(chat=AsyncMock(return_value=_mock_llm_response()))
        reviewer = LLMQualityReviewer(llm_client=mock_client, batch_size=8)

        report = await reviewer.review(
            _make_segments(4),
            source_text="原文内容",
            novel_genre="玄幻",
        )

        assert report.attempted is True
        assert report.avg_score > 0
        assert len(report.dimensions) == 8
        assert report.dimensions["semantic_coherence"]["score"] == 8.0
        assert len(report.issues) == 2
        assert report.issues[0].dimension == "dialogue_naturalness"
        assert report.issues[0].fix_type == "llm_rewrite"
        assert report.issues[1].fix_type == "deterministic"
        assert report.failed_batches == 0

    @pytest.mark.asyncio
    async def test_review_empty_segments_returns_empty_report(self):
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        reviewer = LLMQualityReviewer(llm_client=None)
        report = await reviewer.review([])

        assert report.attempted is False
        assert report.avg_score == 0.0
        assert report.issues == []

    @pytest.mark.asyncio
    async def test_review_batch_failure_degrades_gracefully(self):
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        mock_client = SimpleNamespace(
            chat=AsyncMock(side_effect=RuntimeError("LLM timeout"))
        )
        reviewer = LLMQualityReviewer(llm_client=mock_client, batch_size=2)

        report = await reviewer.review(_make_segments(4))

        # 所有批次失败，但不抛异常
        assert report.attempted is True
        assert report.failed_batches == 2
        assert report.avg_score == 0.0
        assert report.issues == []

    @pytest.mark.asyncio
    async def test_review_invalid_json_degrades(self):
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        mock_client = SimpleNamespace(
            chat=AsyncMock(return_value="这不是JSON")
        )
        reviewer = LLMQualityReviewer(llm_client=mock_client)

        report = await reviewer.review(_make_segments(2))

        assert report.failed_batches == 1
        assert report.avg_score == 0.0

    @pytest.mark.asyncio
    async def test_review_invalid_dimension_filtered(self):
        """无效维度 key 的 issue 应被过滤。"""
        import json
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        response = json.dumps({
            "dimensions": {"semantic_coherence": {"score": 7.0, "comment": "ok"}},
            "issues": [
                {
                    "segment_index": 0,
                    "dimension": "invalid_dimension_key",
                    "severity": "major",
                    "description": "test",
                    "suggestion": "test",
                    "fix_type": "none",
                    "target_fields": [],
                },
            ],
        })
        mock_client = SimpleNamespace(chat=AsyncMock(return_value=response))
        reviewer = LLMQualityReviewer(llm_client=mock_client)

        report = await reviewer.review(_make_segments(2))

        assert len(report.issues) == 0  # 无效维度被过滤

    @pytest.mark.asyncio
    async def test_review_handles_dataclass_sound_effects_and_music_cue(self):
        """片段含 SoundEffect/MusicCue dataclass 对象时不应报 JSON 序列化错误。"""
        from dataclasses import dataclass
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReviewer

        @dataclass
        class FakeSoundEffect:
            type: str = "action"
            description: str = "拳头击打"
            file: str = ""

        @dataclass
        class FakeMusicCue:
            mood: str = "tense"
            description: str = "紧张背景乐"

        segments = [
            {
                "type": "narration",
                "text": "他猛然挥拳。",
                "speaker": "旁白",
                "emotion": "tense",
                "sound_effects": [FakeSoundEffect()],
                "music_cue": FakeMusicCue(),
                "pause_after": 0.5,
            },
        ]
        mock_client = SimpleNamespace(chat=AsyncMock(return_value=_mock_llm_response()))
        reviewer = LLMQualityReviewer(llm_client=mock_client)

        report = await reviewer.review(segments)

        # 不应有失败批次（序列化成功）
        assert report.failed_batches == 0
        assert report.avg_score > 0


# ---------------------------------------------------------------------------
# merge_llm_review 融合评分测试
# ---------------------------------------------------------------------------

class TestMergeLLMReview:
    def _make_rule_report(self, score=80.0):
        from app.services.audiobook.agents.audio_quality_reviewer import (
            AudioQualityReport,
            AudioQualityReviewer,
        )
        reviewer = AudioQualityReviewer()
        report = AudioQualityReport(
            script_quality={"naturalness_score": 8, "clarity_score": 8, "engagement_score": 8},
            audio_balance={"sound_effects": "正常", "music": "正常", "voice_differentiation": "清晰"},
            pacing={"pacing_issues": []},
            issues=[],
            overall_grade="B+",
            overall_score=score,
            revision_suggestions=[],
        )
        return reviewer, report

    def _make_llm_report(self, avg_score=7.5):
        from app.services.audiobook.agents.llm_quality_reviewer import (
            LLMQualityIssue,
            LLMQualityReport,
        )
        return LLMQualityReport(
            dimensions={
                "semantic_coherence": {"score": 8.0, "label": "语义连贯", "category": "content_narrative", "comment": "好"},
                "dialogue_naturalness": {"score": 7.0, "label": "对白自然", "category": "character_dialogue", "comment": "一般"},
            },
            issues=[
                LLMQualityIssue(
                    segment_index=1,
                    dimension="dialogue_naturalness",
                    severity="major",
                    description="对白生硬",
                    suggestion="口语化",
                    fix_type="llm_rewrite",
                    target_fields=["text"],
                ),
            ],
            avg_score=avg_score,
            failed_batches=0,
            total_batches=1,
            attempted=True,
        )

    def test_merge_fused_score_calculation(self):
        """融合分 = 0.5 * rule_score + 0.5 * (llm_avg * 10)"""
        reviewer, report = self._make_rule_report(score=80.0)
        llm_report = self._make_llm_report(avg_score=7.5)

        merged = reviewer.merge_llm_review(report, llm_report)

        # 0.5 * 80 + 0.5 * 75 = 77.5
        assert merged.overall_score == 77.5
        assert merged.overall_grade == "B"
        assert len(merged.llm_dimensions) == 2
        assert len(merged.issues) == 1
        assert merged.issues[0].category == "llm_quality"
        assert merged.issues[0].dimension == "dialogue_naturalness"
        assert merged.issues[0].fix_type == "llm_rewrite"

    def test_merge_custom_weights(self):
        reviewer, report = self._make_rule_report(score=90.0)
        llm_report = self._make_llm_report(avg_score=6.0)

        merged = reviewer.merge_llm_review(
            report, llm_report, rule_weight=0.7, llm_weight=0.3
        )

        # 0.7 * 90 + 0.3 * 60 = 63 + 18 = 81.0
        assert merged.overall_score == 81.0

    def test_merge_none_llm_report_preserves_rule_score(self):
        reviewer, report = self._make_rule_report(score=85.0)

        merged = reviewer.merge_llm_review(report, None)

        assert merged.overall_score == 85.0
        assert merged.llm_dimensions == {}

    def test_merge_empty_llm_report_preserves_rule_score(self):
        from app.services.audiobook.agents.llm_quality_reviewer import LLMQualityReport

        reviewer, report = self._make_rule_report(score=82.0)
        empty_llm = LLMQualityReport()  # avg_score=0, dimensions={}

        merged = reviewer.merge_llm_review(report, empty_llm)

        assert merged.overall_score == 82.0
        assert merged.llm_dimensions == {}

    def test_merge_adds_revision_suggestion_for_major_issues(self):
        reviewer, report = self._make_rule_report(score=80.0)
        llm_report = self._make_llm_report(avg_score=7.0)

        merged = reviewer.merge_llm_review(report, llm_report)

        assert any("LLM维度" in s for s in merged.revision_suggestions)
