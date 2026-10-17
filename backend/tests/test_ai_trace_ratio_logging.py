# -*- coding: utf-8 -*-
"""P19 守卫：日志与对外字段不得再用恒零的 improvement 冒充有效信号。

## 取证（2026-10-17 P18 真实轮次，7 个模型）

多模型竞争日志逐条（`p18_run.log` 02:24:48~02:25:14）：
```
  [DeepSeek Flash]        AI分数=100, 降低0分, 耗时=17.3秒
  [MiMo V2.6 Flash]       AI分数=100, 降低0分, 耗时=28.4秒
  [Qwen3.7 Plus]          AI分数=100, 降低0分, 耗时=32.1秒
  [Doubao Seed Character] AI分数=100, 降低0分, 耗时=31.9秒
  [Kimi K2.8 Preview]     AI分数=100, 降低0分, 耗时=35.5秒
  [MiniMax M3]            AI分数=100, 降低0分, 耗时=39.0秒
  [Doubao Seed Evolving]  AI分数=100, 降低0分, 耗时=42.4秒
```
7 个模型**全部**「降低0分」，但同一轮的 ratio 差异很大 —— 最好的
Doubao Seed Evolving 确定AI占比 0.530，而被拦的 DeepSeek Flash 是 1.000。

⇒ 「降低0分」不携带任何信息：它既不能区分模型，也不能解释未入选原因。
   读者（人或后续排查）会误以为「这些模型都没效果」，而真实情况是
   **有的模型确实没降下来（ratio 1.000），有的降得很好（ratio 0.530）**。

## 涉及的三处

1. 单模型评估日志（`ai_trace_competition.py` `_evaluate_single_model`）
2. 最佳模型汇总日志（同文件 `run_...` 内）
3. 对外 API 字段 `performance.avg_improvement`，
   被前端 `PromptEvolutionPage.tsx` 展示为「AI降分」列。

## 为什么日志要换口径（注意：不是「恒为 0」）

`ai_score = ratio_confidence × 100 = (确定AI占比 + 疑似AI占比) × 100`。
它**不是恒 100** —— 出现人工段落（label=0）就会下降。
它的真实缺陷是**口径合并**：LLM 改写的典型效果是「确定AI → 疑似AI」，
这一步 ratio_confidence 不变，于是 `improvement = original_score - ai_score` 不降。
所以旧日志里所有模型都打「降低0分」，**无法区分**下面三种完全不同的情况：
真的降了 / 恒等映射没动 / 改写后检测失败。

## 修法边界

- 只改**日志措辞与对外字段的可读性**，不改任何排序或准入逻辑
  （那部分已由 P17-1 完成并验证）
- `improvement` / `avg_improvement` 字段**保留**（历史存档里有数据，
  删除会破坏既有 JSON 契约），但必须说明其口径缺陷
- 日志改打 ratio 口径（`确定AI占比 X→Y`），这才是有分辨力的信号
"""
import json

from app.services.ai_trace_competition import ModelConfigStorage, SingleModelResult


def make_result(model_id="m", ai_ratio=0.53, original_ai_ratio=0.72, improvement=0):
    return SingleModelResult(
        model_id=model_id, model_name=model_id, provider="p",
        reduced_text="改写文本", ai_score=100, latency_seconds=1.0,
        improvement=improvement, success=True,
        fidelity_similarity=90.0, semantic_review={"available": True},
        hybrid_score=50.0, ai_ratio=ai_ratio, original_ai_ratio=original_ai_ratio,
    )


class TestRatioReductionHelper:
    """日志措辞必须基于 ratio 口径，而不是恒零的 improvement。"""

    def test_reduction_text_reports_ratio_not_score(self):
        r = make_result(ai_ratio=0.53, original_ai_ratio=0.72)
        text = ModelConfigStorage.describe_ratio_reduction(r)
        assert "0.720" in text and "0.530" in text, (
            f"应报告 ratio 变化，实际为：{text}"
        )
        assert "分" not in text or "占比" in text, (
            f"不应再以「降N分」表述（ai_score 恒 100），实际为：{text}"
        )

    def test_reduction_text_when_ratio_missing(self):
        """ratio 缺失（检测失败）必须说「不可用」而不是编造降幅。"""
        r = make_result(ai_ratio=None, original_ai_ratio=0.72)
        text = ModelConfigStorage.describe_ratio_reduction(r)
        assert "不可用" in text or "缺失" in text, text

    def test_reduction_text_when_original_missing(self):
        r = make_result(ai_ratio=0.53, original_ai_ratio=None)
        text = ModelConfigStorage.describe_ratio_reduction(r)
        assert "不可用" in text or "缺失" in text, text

    def test_identity_mapping_is_visible(self):
        """恒等映射必须在日志里一眼可见（1.000→1.000），不能只写「0 分」。"""
        r = make_result(ai_ratio=1.0, original_ai_ratio=1.0)
        text = ModelConfigStorage.describe_ratio_reduction(r)
        assert "1.000" in text, text

    def test_real_shape_distinguishes_good_and_bad(self):
        """真实量级：0.72→0.53 与 1.00→1.00 必须产出不同文本。

        这条是本文件的核心 —— 旧措辞对这两个模型输出完全相同的
        「AI分数=100, 降低0分」，无法区分。
        """
        good = ModelConfigStorage.describe_ratio_reduction(
            make_result(model_id="good", ai_ratio=0.53, original_ai_ratio=0.72))
        bad = ModelConfigStorage.describe_ratio_reduction(
            make_result(model_id="bad", ai_ratio=1.0, original_ai_ratio=1.0))
        assert good != bad, "两个真实表现不同的模型不得产出相同日志文本"


class TestImprovementFieldIsMarkedDeprecated:
    """字段保留（历史存档依赖），但必须说明它为何分辨力不足。

    注意措辞：improvement 并非**恒为 0**。ai_score = ratio_confidence × 100，
    只要改写结果出现人工段落（label=0）它就会下降。它的问题是**口径合并** ——
    ai_score 把「确定AI(1)」与「疑似AI(2)」合并计数，而 LLM 改写的典型效果
    正是 AI→疑似，这一步 ratio_confidence 不变 ⇒ improvement 仍为 0。
    人工占比上来后该字段才会有可观非零值。
    """

    def test_field_still_exists(self):
        r = make_result()
        assert hasattr(r, "improvement")
        assert r.improvement == 0

    def test_improvement_is_not_mathematically_forced_to_zero(self):
        """人工段落出现时 improvement 可以为正 —— 锁住这个事实，
        防止后人（或文档）把它误写成「恒为 0 / 数学上不可能有值」。"""
        r = make_result(improvement=7)
        assert r.improvement == 7

    def test_accumulation_site_documents_limitation(self):
        """累加处必须说明该指标的口径缺陷，避免后来者再把它当主要指标。"""
        import inspect
        src = inspect.getsource(ModelConfigStorage)
        assert "avg_improvement" in src
        assert "疑似" in src, (
            "avg_improvement 的累加处必须说明根因：ai_score 合并了"
            "「确定AI」与「疑似AI」，分辨不出 AI→疑似 这类真实改写进步"
        )

    def test_no_source_claims_improvement_is_always_zero(self):
        """禁止再出现「恒为 0」这类绝对断言 —— 它与人工占比上升的事实矛盾。"""
        import inspect
        src = inspect.getsource(ModelConfigStorage)
        for wrong in ("avg_improvement 在 LLM 改写区间恒为 0",
                      "improvement 恒为 0"):
            assert wrong not in src, f"源码仍含错误的绝对断言：{wrong}"


class TestLoggingUsesRatioWording:
    def test_single_model_log_has_no_bare_score_reduction_claim(self):
        import inspect
        from app.services.ai_trace_competition import MultiModelEvaluationService
        src = inspect.getsource(MultiModelEvaluationService)
        assert "降低{improvement}分" not in src, (
            "单模型评估日志不得再打「降低{improvement}分」—— 实测 7 个模型"
            "全部输出「降低0分」，该措辞零信息量且误导"
        )
        assert "describe_ratio_reduction" in src, (
            "单模型评估日志必须改用 ratio 口径"
        )

    def test_best_model_log_uses_ratio_wording(self):
        import inspect
        from app.services.ai_trace_competition import MultiModelEvaluationService
        src = inspect.getsource(MultiModelEvaluationService)
        assert "降低{best.improvement}分" not in src, (
            "最佳模型汇总日志同样不得打「降低N分」"
        )
