"""Seed 场景导演层（指导文档 §4.2）。

窄职责服务包：消费已审定片段与章节上下文，输出结构化 ``SeedSceneDirection[]``，
不得修改台词事实，不得直接调用 Seed Audio 或拼装最终供应商请求。
"""

from .event_mapper import (
    SceneDurationEstimate,
    estimate_scene_duration,
    map_direction_to_events,
)
from .models import (
    ReviewedAnalysisEvidenceRef,
    SegmentEvidenceRef,
    SeedSceneContext,
    SeedSceneDirection,
    SeedSoundDirection,
    SeedSpeechDirection,
    SeedVocalizationDirection,
)
from .parser import DirectionParseError, parse_seed_scene_directions
from .pipeline_integration import (
    DirectorIntegrationDecision,
    SeedSceneDirectorService,
    resolve_director_integration,
)
from .chapter_director_run import ChapterDirectorRun, run_chapter_direction

__all__ = [
    "ChapterDirectorRun",
    "DirectionParseError",
    "DirectorIntegrationDecision",
    "ReviewedAnalysisEvidenceRef",
    "SceneDurationEstimate",
    "SeedSceneDirectorService",
    "SegmentEvidenceRef",
    "SeedSceneContext",
    "SeedSceneDirection",
    "SeedSoundDirection",
    "SeedSpeechDirection",
    "SeedVocalizationDirection",
    "estimate_scene_duration",
    "map_direction_to_events",
    "parse_seed_scene_directions",
    "resolve_director_integration",
    "run_chapter_direction",
]
