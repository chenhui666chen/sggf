"""fallback_assets：延迟回退资产与生产收敛合同（指导文档阶段 7）。"""

from .chapter_convergence import (
    ChapterProductionConvergence,
    LEGACY_FALLBACK_ASSET_KINDS,
    converge_chapter_production,
)
from .fallback_plan import (
    FALLBACK_ASSET_KINDS,
    FallbackAssetPlan,
    FallbackAssetRequirement,
    SCENE_FALLBACK_STATUSES,
    SceneFallbackInput,
    build_fallback_plan,
)
from .fallback_policy import (
    DEFAULT_FALLBACK_ASSET_POLICY,
    FallbackAssetPolicy,
)
from .production_state import (
    DISPOSITION_REASON_CODES,
    PRODUCTION_STATES,
    SceneProductionDisposition,
    chapter_production_summary,
    resolve_scene_disposition,
)

__all__ = [
    "ChapterProductionConvergence",
    "DEFAULT_FALLBACK_ASSET_POLICY",
    "DISPOSITION_REASON_CODES",
    "FALLBACK_ASSET_KINDS",
    "FallbackAssetPlan",
    "FallbackAssetPolicy",
    "FallbackAssetRequirement",
    "LEGACY_FALLBACK_ASSET_KINDS",
    "PRODUCTION_STATES",
    "SCENE_FALLBACK_STATUSES",
    "SceneFallbackInput",
    "SceneProductionDisposition",
    "build_fallback_plan",
    "chapter_production_summary",
    "converge_chapter_production",
    "resolve_scene_disposition",
]
