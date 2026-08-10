# -*- coding: utf-8 -*-
"""语义评审四层保真判据守卫：防止提示词回归到单一模糊标准。

同时守卫判侧（SemanticJudge）与写侧（SAFE_INITIAL_PROMPT/变体约束/优化器边界）
的情绪意象操作边界对齐，避免评审豁免而改写模型自我设限或越界。
"""
import pytest

from app.services.prompt_evolution import meta_optimizer as mo
from app.services.prompt_evolution.semantic_judge import SemanticJudge


def test_system_prompt_contains_four_layer_fidelity_rubric():
    prompt = SemanticJudge._system_prompt()
    # 四层判据齐全且映射到正确维度
    assert "事实层" in prompt and "fact_consistency" in prompt
    assert "命题层" in prompt and "semantic_fidelity" in prompt
    assert "情绪方向层" in prompt
    assert "表达层" in prompt and "零扣分" in prompt


def test_system_prompt_exempts_same_domain_imagery_replacement():
    prompt = SemanticJudge._system_prompt()
    # 意象同喻域等义替换（情绪方向一致）不得扣保真
    assert "同喻域" in prompt
    assert "不得扣semantic_fidelity" in prompt
    # 整段删除意象归完整度而非保真
    assert "information_completeness而非保真" in prompt


def test_system_prompt_separates_grammar_noise_from_fact():
    prompt = SemanticJudge._system_prompt()
    # 语病/生造词不计入事实维度，避免维度归类漂移污染 fact<90 门槛
    assert "上个古遗迹" in prompt
    assert "不计入fact_consistency" in prompt


def test_user_prompt_reinforces_expression_zero_penalty():
    prompt = SemanticJudge._user_prompt("原文", "改写", "玄幻")
    assert "表达差异零扣分" in prompt
    assert "同喻域替换不扣保真" in prompt


def test_safe_initial_prompt_allows_same_domain_imagery_replacement():
    # 写侧起点提示词与判侧豁免对齐：意象同喻域替换合法，但情绪方向不可变
    prompt = mo.SAFE_INITIAL_PROMPT
    assert "同喻域的等义表达" in prompt
    assert "情绪方向与强度不得改变" in prompt
    assert "不得换成情绪相反的意象" in prompt


def test_variant_fidelity_constraint_carries_imagery_boundary():
    # 变体与成功候选经 _enforce_fidelity_constraint 确定性携带该边界
    assert "同喻域等义替换" in mo.VARIANT_FIDELITY_CONSTRAINT
    assert "情绪方向不得改变" in mo.VARIANT_FIDELITY_CONSTRAINT


def test_safe_initial_prompt_still_passes_safety_validation():
    # 新增意象条款不得触发安全词表/示例句型误伤
    assert mo.MetaOptimizer._validate_prompt_safety(mo.SAFE_INITIAL_PROMPT)


def test_safe_initial_prompt_requires_full_text_texture_conversion():
    # 反向隔离实验实证：单维度局部改写对高分深区无效，写侧必须要求全文整体执行
    # （v2 起点措辞：作用于全文/不得只在局部段落零星修饰）
    prompt = mo.SAFE_INITIAL_PROMPT
    assert "全文质地转换" in prompt
    assert "作用于全文" in prompt or "局部零星修饰" in prompt


def test_variant_strategy_constraint_requires_global_execution():
    # 确定性追加约束携带全文执行要求，变体与成功候选自动继承
    assert "全文质地转换" in mo.VARIANT_DETECTION_STRATEGY_CONSTRAINT
    assert "单维度局部改写对高分文本无效" in mo.VARIANT_DETECTION_STRATEGY_CONSTRAINT


def test_enforce_constraint_appends_global_execution_clause():
    # 无 marker 的新提示词经确定性追加后携带全文执行条款，重复追加幂等
    prompt = mo.MetaOptimizer._enforce_fidelity_constraint("测试提示词")
    assert "全文质地转换" in prompt
    assert prompt == mo.MetaOptimizer._enforce_fidelity_constraint(prompt)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
