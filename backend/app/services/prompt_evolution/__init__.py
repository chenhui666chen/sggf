"""
提示词自动优化系统 (Prompt Evolution Engine)

这里使用懒加载，避免导入样本模块时连带拉起 AI 检测、LLM 客户端等重依赖。
"""

from __future__ import annotations

from importlib import import_module


__all__ = [
    "PromptEvolutionEngine",
    "run_evolution",
    "PromptVersion",
    "EvaluationResult",
    "EvolutionHistory",
    "EvolutionConfig",
    "ApprovalStatus",
    "EvolutionStorage",
    "PromptEvaluator",
    "MetaOptimizer",
    "TestSampleManager",
    "DEFAULT_TEST_SAMPLES",
]

_ATTRIBUTE_TO_MODULE = {
    "PromptEvolutionEngine": ".engine",
    "run_evolution": ".engine",
    "PromptVersion": ".models",
    "EvaluationResult": ".models",
    "EvolutionHistory": ".models",
    "EvolutionConfig": ".models",
    "ApprovalStatus": ".models",
    "EvolutionStorage": ".storage",
    "PromptEvaluator": ".evaluator",
    "MetaOptimizer": ".meta_optimizer",
    "TestSampleManager": ".test_samples",
    "DEFAULT_TEST_SAMPLES": ".test_samples",
}


def __getattr__(name: str):
    target_module = _ATTRIBUTE_TO_MODULE.get(name)
    if not target_module:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(target_module, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
