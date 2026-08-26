# -*- coding: utf-8 -*-
"""重排放行守卫：段落/句子顺序调整合法化，信息不变仍为硬约束。

决策（2026-08-19 用户指令）：允许改变段落与句子的出场顺序，但最终
成品传达的信息不变。此前“事件顺序”在提示词铁律、变体硬约束、元优化器
禁令、经验库预设禁令与语义评审命题层五处被锁死，重排策略全链路无法
生存（安全拦截 + 评审扣分双重阻断）。

守卫内容：
①起点提示词与候选提示词：顺序锁定移除、重排许可条款就位
②反过度改写块：顺序调整不再列为内容层禁止项
③变体硬约束与去精致化铁律同步放行
④安全黑名单：重排类策略不再触发拦截（内容破坏类仍拦截）
⑤语义评审：事件顺序移出命题层硬判据，表达层明示顺序调整零扣分
⑥经验库预设：禁令与无效策略同步清理
"""
import pytest

from app.services.prompt_evolution import meta_optimizer as mo
from app.services.prompt_evolution import novel_rules as nr
from app.services.prompt_evolution.semantic_judge import SemanticJudge


class TestStartingPromptReorderPermission:
    def test_iron_rule_allows_reorder(self):
        prompt = mo.SAFE_INITIAL_PROMPT
        assert "允许调整段落与句子的出场顺序" in prompt
        assert "全部信息点必须保留" in prompt

    def test_event_order_no_longer_locked(self):
        # 事件顺序不再作为锁定项出现在起点提示词任何条款中
        assert "事件顺序" not in mo.SAFE_INITIAL_PROMPT

    def test_anti_overrewrite_allows_order_adjustment(self):
        # 内容层禁止项不再包含顺序；重排但不得删信息点
        assert "禁止改变情节、顺序与篇幅" not in mo.ANTI_OVERREWRITE_BLOCK
        assert "段落与句子的出场顺序允许调整" in mo.ANTI_OVERREWRITE_BLOCK

    def test_still_passes_safety_validation(self):
        assert mo.MetaOptimizer._validate_prompt_safety(mo.SAFE_INITIAL_PROMPT)


class TestConstraintsReorderPermission:
    def test_variant_fidelity_allows_reorder(self):
        c = mo.VARIANT_FIDELITY_CONSTRAINT
        assert "事件顺序" not in c
        assert "允许调整段落与句子的出场顺序" in c
        assert "全部信息点必须保留" in c

    def test_deslop_prompt_allows_reorder(self):
        p = mo.DESLOP_CHALLENGER_PROMPT
        assert "事件顺序" not in p
        assert "允许调整段落与句子的出场顺序" in p

    def test_deslop_still_passes_safety_validation(self):
        assert mo.MetaOptimizer._validate_prompt_safety(mo.DESLOP_CHALLENGER_PROMPT)


class TestSafetyBlacklistUpdated:
    def test_reorder_strategy_passes_safety(self):
        strategy = (
            "调整段落与句子的出场顺序，打破检测器对固定叙事节奏的统计匹配，"
            "全部信息点保留不变"
        )
        assert mo.MetaOptimizer._prompt_safety_reason(strategy) is None

    def test_content_destruction_still_blocked(self):
        assert mo.MetaOptimizer._prompt_safety_reason("替换人物姓名") is not None
        assert mo.MetaOptimizer._prompt_safety_reason("插入不相关联想") is not None


class TestJudgeCriteriaUpdated:
    def test_event_order_removed_from_hard_criteria(self):
        prompt = SemanticJudge._system_prompt()
        assert "事件顺序" not in prompt

    def test_order_adjustment_is_zero_deduction(self):
        prompt = SemanticJudge._system_prompt()
        assert "顺序调整但信息点完整不扣分" in prompt


class TestNovelRulesPresetsUpdated:
    def test_effective_strategies_allow_reorder(self):
        assert not any("事件顺序" in s for s in nr.PRESET_EFFECTIVE_STRATEGIES)

    def test_forbidden_patterns_cleanup(self):
        joined = "".join(nr.PRESET_FORBIDDEN_PATTERNS)
        assert "非线性重排" not in joined
        assert "事件顺序" not in joined

    def test_ineffective_strategies_cleanup(self):
        joined = "".join(nr.PRESET_INEFFECTIVE_STRATEGIES)
        assert "重排事件" not in joined


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
