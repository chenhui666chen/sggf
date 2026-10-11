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

from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.novel_rules import (
    build_detector_segment_hint,
    build_targeted_rewrite_hint,
    locate_high_risk_segments,
)


@pytest.fixture(autouse=True)
def _use_plain_rewrite(monkeypatch):
    """评估器深区注入用例断言的是「单次改写请求」携带定点提示。

    去锚定范式下首轮调用为要点抽取、提示落在重写轮，调用序列语义不同，
    故此处固定走常规改写路径。
    """
    monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)


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


class TestBuildDetectorSegmentHint:
    """真实检测段落标注 → 定点指令（取代正则盲猜的核心改动）。

    与 build_targeted_rewrite_hint 的关键差别：后者输出的是正则猜出来的句式类别
    标签（"二元对比句式"等），检测器认不认并不确定；这里引用的是检测器实测判为
    确定AI 的**原文片段**，是真值。
    """

    def test_no_labels_render_empty(self):
        assert build_detector_segment_hint([]) == ""

    def test_only_human_and_suspect_render_empty(self):
        """没有「确定AI」段落时不下发指令——避免对已达标文本做无谓干预。"""
        labels = [{"label": 0, "text": "人写的段落。"}, {"label": 2, "text": "疑似段落。"}]
        assert build_detector_segment_hint(labels) == ""

    def test_ai_segment_snippet_quoted(self):
        labels = [{"label": 1, "text": "他缓缓抬起头，眼中闪过一丝复杂的情绪。", "conf": 0.99}]
        hint = build_detector_segment_hint(labels)
        assert "他缓缓抬起头" in hint
        assert "不要沿用" in hint

    def test_sorted_by_confidence_desc(self):
        """置信度高的排在前面：最确信是 AI 的写法优先展示。"""
        labels = [
            {"label": 1, "text": "低置信片段内容占位。", "conf": 0.51},
            {"label": 1, "text": "高置信片段内容占位。", "conf": 0.98},
        ]
        hint = build_detector_segment_hint(labels)
        assert hint.index("高置信") < hint.index("低置信")

    def test_max_items_and_truncation(self):
        labels = [{"label": 1, "text": f"第{i}段" + "字" * 200, "conf": 0.9} for i in range(9)]
        hint = build_detector_segment_hint(labels, max_items=3, max_chars=20)
        assert hint.count("「") == 3
        assert "…" in hint

    def test_suspect_count_reported(self):
        labels = [
            {"label": 1, "text": "确定AI的段落内容。", "conf": 0.9},
            {"label": 2, "text": "疑似A。"}, {"label": 2, "text": "疑似B。"},
        ]
        hint = build_detector_segment_hint(labels)
        assert "疑似AI" in hint and "2" in hint

    def test_missing_text_skipped(self):
        labels = [{"label": 1, "text": "", "conf": 0.9}]
        assert build_detector_segment_hint(labels) == ""


class TestSampleAiSegmentPersistence:
    """段落级真值必须能跨运行持久化，否则第二次进化走缓存会退回盲猜。"""

    def test_compacted_on_store(self):
        from app.services.prompt_evolution.test_samples import TestSample

        s = TestSample(sample_id="p1", genre="都市", text="正文内容。" * 50)
        s.store_ai_detection(
            {
                "ai_score": 100,
                "segment_labels": [
                    {"label": 0, "text": "人工段。"},
                    {"label": 1, "text": "确定AI段。"},
                    {"label": 2, "text": "疑似段。"},
                ],
            },
            policy_version="v1",
        )
        assert s.ai_detection_ai_segments == ["确定AI段。"]

    def test_roundtrip_keeps_segments(self):
        from app.services.prompt_evolution.test_samples import TestSample

        s = TestSample(sample_id="p2", genre="都市", text="正文内容。" * 50,
                       ai_detection_ai_segments=["段一。", "段二。"])
        restored = TestSample.from_dict(s.to_dict())
        assert restored.ai_detection_ai_segments == ["段一。", "段二。"]

    def test_restored_detection_rebuilds_labels(self):
        from app.services.prompt_evolution.test_samples import TestSample

        s = TestSample(sample_id="p3", genre="都市", text="正文内容。" * 50,
                       ai_detection_ai_segments=["被判AI的段。"])
        s.ai_detection_score = 100
        s.ai_detection_text_hash = s._detection_text_hash()
        s.ai_detection_policy_version = "v1"
        got = s.get_ai_detection("v1")
        assert got["segment_labels"] == [{"label": 1, "text": "被判AI的段。"}]


class TestEvaluatorSegmentHintPriority:
    """开关打开时优先用真值指令，且不与正则指令叠加（避免指令过长挤占事实约束）。"""

    def _make_evaluator(self):
        evaluator = PromptEvaluator()
        evaluator.llm_client = AsyncMock()
        evaluator.llm_client.chat = AsyncMock(return_value="改写后的正文内容占位，长度足够通过守门。" * 5)
        evaluator.ai_detector = AsyncMock()
        evaluator.semantic_judge = AsyncMock()
        evaluator.semantic_judge.evaluate = AsyncMock(
            return_value={
                "available": True, "hard_fail": False,
                "semantic_fidelity": {"score": 90},
                "fact_consistency": {"score": 95},
                "information_completeness": {"score": 85},
                "readability": {"score": 90},
                "writing_naturalness": {"score": 85},
            }
        )
        return evaluator

    @pytest.mark.asyncio
    async def test_real_labels_win_over_regex(self, monkeypatch):
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {
                    "success": True, "ai_score": 95, "ai_trace_details": {},
                    "segment_labels": [
                        {"label": 1, "text": "检测器实测判为AI的原文片段。", "conf": 0.99},
                    ],
                },
                {"success": True, "ai_score": 70, "ai_trace_details": {}},
            ]
        )
        from app.services.prompt_evolution.test_samples import TestSample

        # 文本同时命中正则预检（"不是…而是…"），用于验证真值指令优先且未叠加
        sample = TestSample(
            sample_id="t4", genre="都市",
            text=_join("这不是恐惧，而是敬畏。", "检测器实测判为AI的原文片段。"),
        )
        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "检测器实测标注" in user_msg
        assert "第1段" not in user_msg      # 正则指令未叠加


class TestEvaluatorFactBottomLineHint:
    """常驻事实底线：无定点命中时的兜底约束。

    依据实验16：无指令组质量合格率 25%（事实一致性均值 85），有指令组 75%（均值 90）。
    差异来自指令中的事实条款，与"定位"无关，故干净样本也该拿到这条约束。
    """

    def _make_evaluator(self):
        evaluator = PromptEvaluator()
        evaluator.llm_client = AsyncMock()
        evaluator.llm_client.chat = AsyncMock(return_value="改写后的正文内容占位，长度足够通过守门。" * 5)
        evaluator.ai_detector = AsyncMock()
        evaluator.semantic_judge = AsyncMock()
        evaluator.semantic_judge.evaluate = AsyncMock(
            return_value={
                "available": True, "hard_fail": False,
                "semantic_fidelity": {"score": 90},
                "fact_consistency": {"score": 95},
                "information_completeness": {"score": 85},
                "readability": {"score": 90},
                "writing_naturalness": {"score": 85},
            }
        )
        return evaluator

    @pytest.mark.asyncio
    async def test_fact_hint_used_when_nothing_targeted(self, monkeypatch):
        """既无确定AI段落、也未命中正则：下发常驻事实底线，不裸奔。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {   # 只有疑似段，没有「确定AI」段 → 真值指令为空
                    "success": True, "ai_score": 95, "ai_trace_details": {},
                    "segment_labels": [{"label": 2, "text": "疑似段落。"}],
                },
                {"success": True, "ai_score": 70, "ai_trace_details": {}},
            ]
        )
        from app.services.prompt_evolution.test_samples import TestSample

        # 干净文本：不会命中任何正则句式
        sample = TestSample(
            sample_id="t5", genre="都市",
            text=_join("雨下了一整夜，屋檐的水声滴答不断。", "她翻个身，把被子往上拽了拽。"),
        )
        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "事实底线" in user_msg
        assert "专有名词" in user_msg

    @pytest.mark.asyncio
    async def test_no_fact_hint_when_disabled(self, monkeypatch):
        """开关关闭时不下发，保持原有零污染行为。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {"success": True, "ai_score": 95, "ai_trace_details": {},
                 "segment_labels": [{"label": 2, "text": "疑似段落。"}]},
                {"success": True, "ai_score": 70, "ai_trace_details": {}},
            ]
        )
        from app.services.prompt_evolution.test_samples import TestSample

        sample = TestSample(sample_id="t6", genre="都市",
                            text=_join("雨下了一整夜。", "她翻了个身。"))
        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "事实底线" not in user_msg

    @pytest.mark.asyncio
    async def test_fact_hint_not_stacked_on_targeted_hint(self, monkeypatch):
        """已有定点指令时不再叠加事实底线——定点指令本身已含该条款，叠加会拉长指令。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(
            side_effect=[
                {"success": True, "ai_score": 95, "ai_trace_details": {},
                 "segment_labels": [{"label": 1, "text": "实测判为AI的片段。", "conf": 0.99}]},
                {"success": True, "ai_score": 70, "ai_trace_details": {}},
            ]
        )
        from app.services.prompt_evolution.test_samples import TestSample

        sample = TestSample(sample_id="t7", genre="都市",
                            text=_join("实测判为AI的片段。", "另一段普通叙述。"))
        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "检测器实测标注" in user_msg
        # 只允许出现一次事实底线标题
        assert user_msg.count("【事实底线") <= 1


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
