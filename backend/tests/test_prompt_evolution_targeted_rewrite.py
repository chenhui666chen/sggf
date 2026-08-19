"""统计预检 → 定点改写 → 复测闭环测试。

背景：外部 skill 基准实验与隔离实验均实证 99 分深区文本对无差别全文改写
不敏感；humanize_mba 的工程闭环（统计预检定位 → 定点改写 → 复测）是对症方向。
本测试覆盖三部分：
1. locate_high_risk_segments：四类结构句式 + 段首模板重复的确定性定位（纯函数）
2. build_targeted_rewrite_hint：定点提示渲染（无命中为空，不污染低分样本）
3. 评估器深区注入：基线 ≥90 时改写请求附带定点提示，低分样本不附加；
   改写前后命中数落入 metrics 供复测对比
"""
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.novel_rules import (
    build_targeted_rewrite_hint,
    locate_high_risk_segments,
)


def _join(*paras):
    return "\n".join(paras)


class TestLocateHighRiskSegments:
    def test_binary_contrast_located(self):
        """二元对比/否定铺垫句式命中并定位到段落序号。"""
        text = _join("第一段正常叙述，没有套路。", "这不是恐惧，而是敬畏。他低下了头。")
        findings = locate_high_risk_segments(text)
        assert any(f["type"] == "binary_contrast" and f["paragraph"] == 2 for f in findings)

    def test_narrator_explanation_located(self):
        """叙述者解释腔/预告腔命中。"""
        text = _join("他推开门。", "他不知道的是，这一切只是开始。")
        findings = locate_high_risk_segments(text)
        assert any(f["type"] == "narrator_explanation" and f["paragraph"] == 2 for f in findings)

    def test_formulaic_dialogue_tags_located(self):
        """公式化对话标签高密度命中（标签≥3 且占比>50%）。"""
        text = _join(
            "“你来了。”他说道。",
            "“嗯。”她问道，“吃饭了吗？”",
            "“吃了。”他笑道。",
        )
        findings = locate_high_risk_segments(text)
        assert any(f["type"] == "dialogue_tags" for f in findings)

    def test_few_dialogue_tags_not_flagged(self):
        """零星一两个对话标签不触发（避免误报）。"""
        text = _join("“你来了。”他说道。", "她点点头，没有说话。")
        findings = locate_high_risk_segments(text)
        assert not any(f["type"] == "dialogue_tags" for f in findings)

    def test_nominalization_located(self):
        """介词引导名词化骨架命中。"""
        text = _join("他通过冥想实现了心境的提升。")
        findings = locate_high_risk_segments(text)
        assert any(f["type"] == "nominalization" for f in findings)

    def test_paragraph_opening_repetition_located(self):
        """连续段首同字重复命中。"""
        text = _join("他走向门口。", "他停下脚步。", "他回头看了一眼。", "他推开门。")
        findings = locate_high_risk_segments(text)
        assert any(f["type"] == "paragraph_opening" for f in findings)

    def test_consecutive_dialogue_openings_not_flagged(self):
        """连续对话段以引号开头不触发段首重复（正常小说结构，防误报）。

        真实样本取证：suspense_001 三段日记（刻意叙事装置）曾被误报为
        paragraph_opening，导致 hint 指示模型重构不该动的文本。
        """
        text = _join(
            "“6月12日，阴，他又来敲门了，说他是邻居。”",
            "“6月15日，雨，他知道我喜欢喝不加糖的豆浆。”",
            "“6月18日，晴，我看到他了，在巷口。”",
        )
        findings = locate_high_risk_segments(text)
        assert not any(f["type"] == "paragraph_opening" for f in findings)

    def test_clean_text_has_no_findings(self):
        """自然文本不误报。"""
        text = _join(
            "雨下了一整夜，屋檐的水声滴答不断。",
            "她翻个身，把被子往上拽了拽。",
            "天亮的时候，巷口传来第一声叫卖。",
        )
        assert locate_high_risk_segments(text) == []

    def test_empty_text_has_no_findings(self):
        assert locate_high_risk_segments("") == []


class TestBuildTargetedRewriteHint:
    def test_empty_findings_render_empty(self):
        """无命中不产生提示，低分/干净样本零污染。"""
        assert build_targeted_rewrite_hint([]) == ""

    def test_findings_render_paragraph_positions(self):
        findings = [
            {"type": "binary_contrast", "paragraph": 2},
            {"type": "paragraph_opening", "paragraph": 1},
        ]
        hint = build_targeted_rewrite_hint(findings)
        assert "第2段" in hint
        assert "第1段" in hint
        assert "定点" in hint or "优先" in hint


class TestEvaluatorDeepZoneInjection:
    def _make_evaluator(self):
        from app.services.prompt_evolution.evaluator import PromptEvaluator

        evaluator = PromptEvaluator()
        evaluator.llm_client = AsyncMock()
        evaluator.llm_client.chat = AsyncMock(return_value="改写后的正文内容占位，长度足够通过守门。" * 5)
        evaluator.ai_detector = AsyncMock()
        evaluator.semantic_judge = AsyncMock()
        evaluator.semantic_judge.evaluate = AsyncMock(
            return_value={
                "available": True,
                "hard_fail": False,
                "semantic_fidelity": {"score": 90},
                "fact_consistency": {"score": 95},
                "information_completeness": {"score": 85},
                "readability": {"score": 90},
                "writing_naturalness": {"score": 85},
            }
        )
        return evaluator

    @pytest.mark.asyncio
    async def test_deep_zone_sample_gets_targeted_hint(self):
        """基线 ≥90 且存在命中：改写请求的 user 消息附带定点提示。"""
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {"success": True, "ai_score": 95, "ai_trace_details": {}},
                {"success": True, "ai_score": 70, "ai_trace_details": {}},
            ]
        )
        original_text = _join(
            "第一段正常叙述。",
            "这不是恐惧，而是敬畏。他低下了头。",
            "通过修炼实现了境界的提升。",
        )
        from app.services.prompt_evolution.test_samples import TestSample

        sample = TestSample(sample_id="t1", genre="都市", text=original_text)
        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        call = evaluator.llm_client.chat.await_args_list[0]
        user_msg = call.kwargs["messages"][1]["content"]
        assert "第2段" in user_msg

    @pytest.mark.asyncio
    async def test_low_score_sample_gets_no_hint(self):
        """基线 <90：不附定点提示，保持普通全文改写。"""
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {"success": True, "ai_score": 60, "ai_trace_details": {}},
                {"success": True, "ai_score": 40, "ai_trace_details": {}},
            ]
        )
        original_text = _join("第一段正常叙述。", "这不是恐惧，而是敬畏。他低下了头。")
        from app.services.prompt_evolution.test_samples import TestSample

        sample = TestSample(sample_id="t2", genre="都市", text=original_text)
        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        call = evaluator.llm_client.chat.await_args_list[0]
        user_msg = call.kwargs["messages"][1]["content"]
        assert "第2段" not in user_msg

    @pytest.mark.asyncio
    async def test_high_risk_hits_recorded_both_sides(self):
        """复测闭环：原文与改写的命中数都落入 metrics。"""
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {"success": True, "ai_score": 95, "ai_trace_details": {}},
                {"success": True, "ai_score": 70, "ai_trace_details": {}},
            ]
        )
        original_text = _join("这不是恐惧，而是敬畏。", "通过修炼实现了境界的提升。")
        from app.services.prompt_evolution.test_samples import TestSample

        sample = TestSample(sample_id="t3", genre="都市", text=original_text)
        result = await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        assert result.original_metrics["high_risk_hits"] == 2
        assert "high_risk_hits" in result.rewritten_metrics
