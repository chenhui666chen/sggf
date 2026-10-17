# -*- coding: utf-8 -*-
"""P17-2 守卫：事实层判据必须区分「真失真」与「表达扩展」。

## 取证（本轮 112 个真实评审样本，非构造极值）

事实一致性得分分布：最低 65 / P25 88 / 中位 92 / 最高 100，低于阈值 90 者
38 个（35%），占全部 hard_fail 触发原因的 83%（38/46）。
⇒ 当前阈值 90 切在 P25 与中位之间，系统性判死大量样本。

对这 38 个失格样本的 `issues` + `reason` 做严重度粗分：
- 含明确矛盾/篡改措辞（矛盾、冲突、不一致、错误、张冠李戴）：**3 个（8%）**
- 仅含轻微改写措辞（具体化、新增、扩展、措辞、弱化、简化）：**11 个（29%）**
- 两者都含：18 个（47%）

评审自述免责的样本（原文写着「不构成事实篡改」「轻度保真损失」
却仍被判 <90）：3 个。

真实 issues 样例（逐字取自存档）：
- 「原文『将周围的树木拦腰折断』为泛指，改写为『几棵树木』做了数量具体化。」
- 「改写增加了原文未有的『足尖在狼爪上一点』动作细节，属新增事实。」
- 「原文『双眼闪烁着嗜血的光芒』→『双眼满是嗜血之意』，事实性质一致。」

## 根因

`SemanticJudge._system_prompt` 的事实层判据原文是：
    「1事实层（硬，计入fact_consistency）：专名、数字、时空、因果、物品属性
      （如武器名）、动作姿态，**任何改变都扣分**。」

「任何改变都扣分」没有区分两种性质完全不同的改动：
  A. 真失真：专名被改、数字被改、时空矛盾、因果倒置、物品属性改变
     —— 这是改写破坏了原文承诺，读者会被误导。
  B. 表达扩展：数量由泛指变具体、补充了动作细节、意象同义替换
     —— 这是改写在原文范围内的合法细化，不构成事实矛盾。

B 类被当成 A 类判死，直接后果是：
P16 真实轮次 3/4 个版本失格率 50%（4/8），质量门槛成为唯一瓶颈，
而这些失格里相当部分是 B 类。

## 本文件的守卫

不降低阈值（实测阈值 90→85 会让失格率 35.7%→16.1%、
可入围版本 10→16，质量门槛基本失效），而是修正判据：
让事实层只对 A 类扣分，并明确 B 类应计入 expression/表达层而非事实层。
"""
import pytest

from app.services.prompt_evolution.semantic_judge import SemanticJudge


def _judge():
    return SemanticJudge.__new__(SemanticJudge)

def _result(**overrides):
    base = {
        "semantic_fidelity": {"score": 92, "reason": "", "issues": []},
        "fact_consistency": {"score": 88, "reason": "存在细节偏差", "issues": []},
        "information_completeness": {"score": 88, "reason": "", "issues": []},
        "readability": {"score": 90, "reason": "", "issues": []},
        "writing_naturalness": {"score": 90, "reason": "", "issues": []},
        "genre_consistency": {"score": 92, "reason": "", "issues": []},
        "over_rewrite_risk": "low",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


class TestFactLayerCriteria:
    def test_prompt_distinguishes_real_distortion_from_expression_expansion(self):
        """事实层判据必须出现 A/B 两类的区分表述。"""
        prompt = SemanticJudge._system_prompt()

        # A 类：真失真必须扣分
        assert "专名" in prompt
        # B 类：表达扩展不得当失真处理
        assert "表达扩展" in prompt or "细化" in prompt or "同义替换" in prompt
        # 旧的过宽表述必须消失
        assert "任何改变都扣分" not in prompt, (
            "「任何改变都扣分」是把表达扩展与真失真混为一谈的根因，必须删除"
        )

    def test_prompt_states_expansion_counts_as_expression_not_fact(self):
        """表达扩展应计入表达层/零扣分，不得计入 fact_consistency。"""
        prompt = SemanticJudge._system_prompt()
        assert (
            "不计入fact_consistency" in prompt
            or "不计入 fact_consistency" in prompt
        ), "必须明确表达扩展不计入事实一致性，否则判据仍会自相矛盾"

    def test_number_specificity_is_not_fact_distortion(self):
        """真实 issues：「泛指→几棵树木」属数量具体化，不得算事实矛盾。

        这条以判据文本形式固化 —— 无法在单测里跑 LLM，
        但可以守住「规则是否被写进提示词」这个可回归的要点。
        """
        prompt = SemanticJudge._system_prompt()
        assert "具体化" in prompt or "泛指" in prompt, (
            "必须显式处理「泛指变具体」这一真实高频轻微改写，"
            "否则它会继续被判为事实失真"
        )


class TestFactThresholdUnchanged:
    """阈值本身不动：降阈值会同时放过真实失真。"""

    def test_fact_threshold_stays_at_ninety(self):
        assert SemanticJudge.MIN_FACT_CONSISTENCY == 90

    def test_real_distortion_still_fails(self):
        """真失真（专名/因果矛盾）必须仍然判 hard_fail —— 这是守门的底线。"""
        out = SemanticJudge._normalize(_result(
            fact_consistency={"score": 85, "reason": "专名被改、因果倒置", "issues": ["林渊→林渊峰"]},
        ))
        assert out["hard_fail"] is True
        assert any("事实一致性" in r for r in out["hard_fail_reasons"])

    def test_unrelated_dimension_still_fails(self):
        """保真度不足仍应判失格（确保改动没有削弱其他守门）。"""
        out = SemanticJudge._normalize(_result(
            semantic_fidelity={"score": 75, "reason": "断言不等价", "issues": []},
        ))
        assert out["hard_fail"] is True
        assert any("语义保真" in r for r in out["hard_fail_reasons"])


class TestResultNormalizationUnaffected:
    def test_high_scores_pass(self):
        out = SemanticJudge._normalize(_result(
            fact_consistency={"score": 95, "reason": "一致", "issues": []},
            semantic_fidelity={"score": 95, "reason": "", "issues": []},
            information_completeness={"score": 90, "reason": "", "issues": []},
        ))
        assert out["hard_fail"] is False

    def test_risk_and_confidence_gates_intact(self):
        """过度改写风险高 / 置信度不足仍须判失格。"""
        risky = SemanticJudge._normalize(_result(over_rewrite_risk="high"))
        assert risky["hard_fail"] is True

        unconf = SemanticJudge._normalize(_result(confidence=0.2))
        assert unconf["hard_fail"] is True
