from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


DREAMWEAVER_SCHEMA_VERSION = "0.1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedModel(StrictModel):
    schema_version: str = Field(default=DREAMWEAVER_SCHEMA_VERSION)


class SubjectPos(StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class FrameSpec(VersionedModel):
    prompt: str
    ratio: str = Field(pattern=r"^\d+:\d+$")
    subject_pos: SubjectPos
    seed: Optional[int] = None


class FrameAnchorConstraints(VersionedModel):
    """
    首尾帧锚定约束（契约层，指标/判定逻辑后续在 AutoQC 落地）。
    """

    similarity_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    lock_identity: bool = True
    lock_style: bool = True
    lock_lighting: bool = True


class ContinuityConstraints(VersionedModel):
    """
    镜头连续性约束（契约层）。
    """

    max_subject_pos_delta: float = Field(default=0.1, ge=0.0, le=1.0)
    enforce_screen_direction: bool = True
    enforce_axis_rule: bool = False


class CostBudget(VersionedModel):
    max_calls: int = Field(default=10, ge=0)
    max_retries: int = Field(default=2, ge=0)


class ShotConstraints(VersionedModel):
    frame_anchor: FrameAnchorConstraints = Field(default_factory=FrameAnchorConstraints)
    continuity: ContinuityConstraints = Field(default_factory=ContinuityConstraints)
    cost_budget: CostBudget = Field(default_factory=CostBudget)


class AutoQCRoute(VersionedModel):
    target_state: str
    action: str
    reason: str
    failure_types: List[str] = Field(default_factory=list)


class AutoQCFailure(VersionedModel):
    failure_type: str
    severity: str
    message: str
    shot_key: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class AutoQCScores(VersionedModel):
    identity: float = Field(ge=0.0, le=1.0)
    structure: float = Field(ge=0.0, le=1.0)
    style: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)
    weights: Dict[str, float] = Field(default_factory=dict)


class AutoQCShotReport(VersionedModel):
    shot_key: str
    passed: bool
    scores: AutoQCScores
    failures: List[AutoQCFailure] = Field(default_factory=list)


class AutoQCReport(VersionedModel):
    passed: bool
    overall_score: float = Field(ge=0.0, le=1.0)
    shots: Dict[str, AutoQCShotReport] = Field(default_factory=dict)
    failures: List[AutoQCFailure] = Field(default_factory=list)
    route: Optional[AutoQCRoute] = None
    config: Dict[str, Any] = Field(default_factory=dict)


AssetType = Literal[
    "image",
    "video",
    "audio",
    "qc_report",
    "anchor",
]


class AssetRef(VersionedModel):
    asset_type: AssetType
    role: str
    uri: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class Shot(VersionedModel):
    shot_index: int = Field(ge=1)
    scene_id: str
    shot_key: str
    desc: str
    duration_s: float = Field(gt=0.0)

    class ShotSchemaV2(VersionedModel):
        """
        可选增强结构（向后兼容），用于承载更细粒度的镜头描述：
        - cam_idx / visual_desc / ff_desc / lf_desc / motion_desc / audio_desc
        - 角色可见性先用 string id（后续可再对齐到 Character/AnchorSet）
        """

        cam_idx: int = Field(default=0, ge=0)
        visual_desc: str = ""
        variation_type: Literal["large", "medium", "small"] = "medium"
        variation_reason: str = ""
        ff_desc: str = ""
        lf_desc: str = ""
        motion_desc: str = ""
        audio_desc: str = ""
        state_before: str = ""
        state_after: str = ""
        ff_vis_char_ids: List[str] = Field(default_factory=list)
        lf_vis_char_ids: List[str] = Field(default_factory=list)
        meta: Dict[str, Any] = Field(default_factory=dict)

    head_frame: FrameSpec
    tail_frame: FrameSpec
    constraints: ShotConstraints = Field(default_factory=ShotConstraints)
    autoqc: Optional[AutoQCShotReport] = None

    shot_schema_v2: Optional[ShotSchemaV2] = None
    assets: List[AssetRef] = Field(default_factory=list)


class Episode(VersionedModel):
    episode_index: int = Field(ge=1)
    title: str = "Episode 1"
    shots: List[Shot]


class Project(VersionedModel):
    """
    DreamWeaver 生产项目（注意：与主站 Project 表区分，这里是“短剧/漫剧生产项目”的契约模型）。
    """

    run_id: str
    source_project_id: int
    user_id: int

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    episodes: List[Episode]

    # project-level assets（如：角色/场景/道具素材库、风格基准图等）
    assets: List[AssetRef] = Field(default_factory=list)

    # 运行期配置快照（便于复现/继续执行）
    runtime_config: Dict[str, Any] = Field(default_factory=dict)

    # 版本化约束/风格/锚点占位字段（后续接入 Style Bible / AnchorSet）
    style_bible_ref: Optional[Dict[str, Any]] = None
    anchor_sets_ref: Optional[Dict[str, Any]] = None
    autoqc: Optional[AutoQCReport] = None
