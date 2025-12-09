"""
内容创作提示词进化系统

基于用户生成数据的低频采样进化机制：
- 5%采样率（每20次生成1次使用变体测试）
- 隐式反馈：编辑量35% + 保留率35% + 重生次数30%
- 题材差异化评审权重
- 与AI降率进化器并行独立运行
"""

from .models import (
    GenerationRecord,
    ImplicitFeedback,
    PromptVariant,
    EvolutionSession,
    ContentEvolutionConfig,
    AIQualityScore,
    GenerationStage,
    FeedbackStatus,
)
from .storage import ContentEvolutionStorage, get_storage
from .variant_router import VariantRouter, VariantGenerator, get_router
from .feedback_collector import (
    FeedbackCollector,
    RetentionChecker,
    ScoreAggregator,
    get_collector,
)
from .genre_weights import (
    Genre,
    GenreEvaluationProfile,
    GENRE_EVALUATION_PROFILES,
    get_genre_profile,
    build_evaluation_prompt,
    get_all_genres,
)
from .engine import (
    ContentEvolutionEngine,
    get_engine,
    quick_evaluate,
)

__all__ = [
    # Models
    "GenerationRecord",
    "ImplicitFeedback",
    "PromptVariant",
    "EvolutionSession",
    "ContentEvolutionConfig",
    "AIQualityScore",
    "GenerationStage",
    "FeedbackStatus",
    # Storage
    "ContentEvolutionStorage",
    "get_storage",
    # Router
    "VariantRouter",
    "VariantGenerator",
    "get_router",
    # Feedback
    "FeedbackCollector",
    "RetentionChecker",
    "ScoreAggregator",
    "get_collector",
    # Genre Weights
    "Genre",
    "GenreEvaluationProfile",
    "GENRE_EVALUATION_PROFILES",
    "get_genre_profile",
    "build_evaluation_prompt",
    "get_all_genres",
    # Engine
    "ContentEvolutionEngine",
    "get_engine",
    "quick_evaluate",
]
