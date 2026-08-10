# -*- coding: utf-8 -*-
"""示例类策略前置约束守卫：优化器三条生成路径必须提前禁止带引号示例。

取证（2026-08-07 批次 430ebd7c）：11 次安全拒绝中 9 次因元优化器在策略/提示词
里嵌引号示例（指令式示例/固定语境整句示例），事后拦截浪费近半生成预算；且
_generate_variant_from_strategy 要求 3 主动鼓励"可以添加新的指令、示例或禁止项"。
修复方向：三条生成路径（optimize_prompt 边界、策略生成、变体生成）提前约束
"不得举示例"，从源头减少带毒产出。
"""
import inspect

import pytest

from app.services.prompt_evolution import meta_optimizer as mo


def test_optimize_boundary_forbids_all_quoted_examples():
    # 边界条款须覆盖短词组引号示例（不止"原句→改句"整句示例）
    src = inspect.getsource(mo.MetaOptimizer.optimize_prompt)
    assert "禁止在改进后的提示词中包含任何带引号的示例" in src


def test_strategy_generation_prompt_forbids_quoted_content():
    # 策略描述本身禁止带引号内容（取证：减少"很""非常"类策略因引号示例被丢弃）
    src = inspect.getsource(mo.MetaOptimizer._generate_random_exploration_strategies)
    assert "不得包含任何带引号内容" in src


def test_variant_generation_prompt_forbids_examples():
    # 变体生成须禁止添加引号示例
    src = inspect.getsource(mo.MetaOptimizer._generate_variant_from_strategy)
    assert "不得添加任何带引号的示例" in src


def test_variant_generation_prompt_no_longer_encourages_examples():
    # 原要求 3"可以添加新的指令、示例或禁止项"是示例产出的直接诱因，必须移除
    src = inspect.getsource(mo.MetaOptimizer._generate_variant_from_strategy)
    assert "可以添加新的指令、示例或禁止项" not in src


def test_preconstraint_clauses_pass_safety_validation():
    # 新增约束条款自身不得触发安全词表/示例模式误伤
    clauses = [
        "不得在策略或提示词中包含任何带引号的示例，只能抽象描述通用手法",
        "策略描述本身不得包含任何带引号内容，只描述抽象规则",
        "不得添加任何带引号的示例，示例会被改写模型机械套用造成事实篡改",
    ]
    for clause in clauses:
        assert mo.MetaOptimizer._prompt_safety_reason(clause) is None, clause


def test_quoted_example_strategy_still_rejected_as_fallback():
    # 前置约束生效后，事后拦截仍保留为兜底：带引号示例的策略依然被识别
    strategy = "减少“很”“非常”“有些”等程度副词，如“温度很高”与“温度略高”"
    reason = mo.MetaOptimizer._prompt_safety_reason(strategy)
    assert reason is not None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
