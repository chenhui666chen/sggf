"""
提示词自动优化系统 (Prompt Evolution Engine)

这是一个独立的实验性模块，用于自动化优化"降低AI痕迹"的提示词。
不会自动应用到生产环境，所有优化结果需要人工审核确认。

主要组件：
- PromptEvolutionEngine: 核心进化引擎
- PromptEvaluator: 评估器（调用AI检测）
- MetaOptimizer: 元优化器（分析并改进提示词）
- EvolutionStorage: 存储管理
- TestSampleManager: 测试样本管理
"""

from .engine import PromptEvolutionEngine, run_evolution
from .models import (
    PromptVersion,
    EvaluationResult,
    EvolutionHistory,
    EvolutionConfig,
    ApprovalStatus
)
from .storage import EvolutionStorage
from .evaluator import PromptEvaluator
from .meta_optimizer import MetaOptimizer
from .test_samples import TestSampleManager, DEFAULT_TEST_SAMPLES

__all__ = [
    # 核心引擎
    "PromptEvolutionEngine",
    "run_evolution",
    # 数据模型
    "PromptVersion",
    "EvaluationResult", 
    "EvolutionHistory",
    "EvolutionConfig",
    "ApprovalStatus",
    # 组件
    "EvolutionStorage",
    "PromptEvaluator",
    "MetaOptimizer",
    "TestSampleManager",
    "DEFAULT_TEST_SAMPLES",
]

