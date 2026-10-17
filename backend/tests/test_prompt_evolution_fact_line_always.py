"""常驻事实底线必须在**所有**路径下生效，不得被定点指令挤掉。

背景（2026-10-16 真实进化轮次 85337c99 取证）：
- 8 样本全部走「真实段落标注」分支（SEGMENT_HINT_ENABLED=true 且有 label==1 段）。
- 因evaluator.py:321 写作 `if not targeted_hint and FACT_HINT_ENABLED`，
  这 8 个样本**一条事实底线都没收到**。
- 而本轮 7/8 失格，归因统计：事实一致 <90 共 5 次、语义保真 <80 共 3 次、
  信息完整 <75 共 1 次 —— 事实一致性是绝对主因，恰好对应缺失的那条约束。

🔴 前提证伪：既有注释称「定点指令自身已含事实条款，故不叠加，避免指令过长」。
实测两者强度差约 5 倍：
- build_detector_segment_hint 收尾只有一句笼统的
  「不得为了改动而改动，更不得改动其中涉及的事实、数字与专有名词」
- FACT_BOTTOM_LINE_HINT 是 5 条逐项核对（数字原样保留 / 专名原样保留 /
  对白不得改写增删 / 因果不得改变 / 禁止新增原文没有的动作物件心理设定）
前者是提醒，后者是可执行核对清单，不构成等价替代。
"""

import pytest
from unittest.mock import AsyncMock

from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.novel_rules import (
    FACT_BOTTOM_LINE_HINT,
    build_detector_segment_hint,
)
from app.services.prompt_evolution.test_samples import TestSample


def _join(*paras):
    return "\n\n".join(paras)


class TestHintStrengthComparison:
    """先锁定前提：段落标注指令的事实条款强度不足以替代事实底线。"""

    def test_segment_hint_has_no_itemized_fact_checklist(self):
        """段落标注指令不含逐项核对清单。"""
        hint = build_detector_segment_hint([
            {"label": 1, "text": "实测判为AI的片段。", "conf": 0.99},
        ])
        assert "检测器实测标注" in hint
        # FACT_BOTTOM_LINE_HINT 逐项核对的关键条款，段落指令里都没有
        for clause in ("专有名词必须原样保留", "百分比", "对白内容不得改写"):
            assert clause not in hint, (
                f"段落标注指令若已含条款「{clause}」，则可替代事实底线；"
                f"实际不含量级差距说明不能替代"
            )

    def test_fact_bottom_line_is_itemized(self):
        """事实底线是逐项可执行核对。"""
        for clause in ("专有名词", "百分比", "对白内容不得改写", "因果关系不得改变"):
            assert clause in FACT_BOTTOM_LINE_HINT


class TestFactBottomLineAlwaysApplied:
    """所有路径下事实底线都必须下发。"""

    def _make_evaluator(self):
        evaluator = PromptEvaluator()
        evaluator.llm_client = AsyncMock()
        evaluator.llm_client.chat = AsyncMock(
            return_value="改写后的正文内容占位，长度足够通过守门。" * 5
        )
        evaluator.ai_detector = AsyncMock()
        evaluator.semantic_judge = AsyncMock()
        evaluator.semantic_judge.evaluate = AsyncMock(return_value={
            "available": True, "hard_fail": False,
            "semantic_fidelity": {"score": 90},
            "fact_consistency": {"score": 95},
            "information_completeness": {"score": 85},
            "readability": {"score": 90},
            "writing_naturalness": {"score": 85},
        })
        return evaluator

    @pytest.mark.asyncio
    async def test_fact_line_applied_alongside_segment_hint(self, monkeypatch):
        """🔴 核心回归：有真实段落标注时，事实底线仍必须一并下发。

        85337c99 实测：8/8 样本走段落标注路径 → 全部未收到事实底线
        → 事实一致 <90 失格 5 次，为本轮首要失格原因。
        """
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95,
             "segment_labels": [{"label": 1, "text": "实测判为AI的片段。", "conf": 0.99}]},
            {"success": True, "ai_score": 70},
        ])
        sample = TestSample(
            sample_id="t", genre="都市",
            text=_join("实测判为AI的片段。", "另一段普通叙述。"),
        )

        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "检测器实测标注" in user_msg, "段落标注指令仍应下发（定点能力不能丢）"
        assert "事实底线" in user_msg, (
            "段落标注指令不含逐项事实核对清单，不能替代常驻事实底线"
        )

    @pytest.mark.asyncio
    async def test_fact_line_applied_alongside_regex_hint(self, monkeypatch):
        """正则预检路径同样不得跳过事实底线。

        构造方式对齐既有 test_real_labels_win_over_regex：用真实命中正则的文本
        （「不是…而是…」）触发预检，不靠 patch locate_high_risk_segments——
        patch 会让被测逻辑变成我们自己的 mock，失去意义。
        """
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            # 无 label==1 段 → 真值指令为空；ai_score 95 ≥ 阈值 90 → 走正则预检
            {"success": True, "ai_score": 95,
             "segment_labels": [{"label": 2, "text": "疑似段落。"}]},
            {"success": True, "ai_score": 70},
        ])
        sample = TestSample(
            sample_id="t2", genre="都市",
            text=_join("这不是恐惧，而是敬畏。", "另一段普通叙述。"),
        )

        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "事实底线" in user_msg, (
            f"正则预检路径同样必须叠加事实底线；实际指令: {user_msg[-400:]}"
        )

    @pytest.mark.asyncio
    async def test_no_duplicate_fact_block(self, monkeypatch):
        """叠加不得产生重复的事实底线块（指令冗余会挤占注意力）。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95,
             "segment_labels": [{"label": 1, "text": "实测判为AI的片段。", "conf": 0.99}]},
            {"success": True, "ai_score": 70},
        ])
        sample = TestSample(
            sample_id="t3", genre="都市",
            text=_join("实测判为AI的片段。", "另一段普通叙述。"),
        )

        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert user_msg.count("【事实底线") <= 1, "事实底线块不得重复下发"

    @pytest.mark.asyncio
    async def test_disabled_switch_still_wins(self, monkeypatch):
        """开关关闭时一律不下发，保持零污染开关语义。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95,
             "segment_labels": [{"label": 1, "text": "实测判为AI的片段。", "conf": 0.99}]},
            {"success": True, "ai_score": 70},
        ])
        sample = TestSample(
            sample_id="t4", genre="都市",
            text=_join("实测判为AI的片段。", "另一段普通叙述。"),
        )

        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "事实底线" not in user_msg

    @pytest.mark.asyncio
    async def test_hint_source_reports_both(self, monkeypatch):
        """日志来源需如实反映叠加情况，便于事后从日志核对。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", True)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = self._make_evaluator()
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95,
             "segment_labels": [{"label": 1, "text": "实测判为AI的片段。", "conf": 0.99}]},
            {"success": True, "ai_score": 70},
        ])
        sample = TestSample(
            sample_id="t5", genre="都市",
            text=_join("实测判为AI的片段。", "另一段普通叙述。"),
        )

        await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        user_msg = evaluator.llm_client.chat.await_args_list[0].kwargs["messages"][1]["content"]
        assert "事实底线" in user_msg
        # 顺序：定点在前、事实底线在后（先定位再约束，注意力分配更合理）
        assert user_msg.index("检测器实测标注") < user_msg.index("事实底线")