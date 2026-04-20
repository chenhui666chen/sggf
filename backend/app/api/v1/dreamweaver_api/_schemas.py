from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.services.dreamweaver.config_lock import serialize_locked_generation_config

class RunRequest(BaseModel):
    project_id: int
    chapter_ids: List[int] = Field(default_factory=list)
    # 质量模式：quality=高质量优先（生图更精细），cost=成本优先（生图更快更省）
    quality_mode: Optional[Literal["quality", "cost"]] = Field(default=None)
    # 智能调参：开启后自动优化提示词和参数，默认true=开启智能调参优化，false=关闭
    smart_tuning: Optional[bool] = Field(default=None)
    # A/B 测试变体标识，用于实验分流
    ab_variant: Optional[str] = Field(default=None)
    # 是否允许质检失败后继续，用于 autoqc/qc_warning 模式
    qc_allow_fail: Optional[bool] = Field(default=None)
    # 风格预设：影响生图提示词风格，可选 cinematic_realistic/anime/ink_wash/cyberpunk
    style_preset: Optional[str] = Field(default=None)
    # 图片比例：影响生图宽高比，ratio 参数控制输出 16:9 / 9:16
    image_ratio: Optional[str] = Field(default=None)
    # 图片分辨率：720p / 1080p 等，最终转换为 width/height
    image_resolution: Optional[str] = Field(default=None)
    image_model: Optional[str] = Field(default=None)
    video_model: Optional[str] = Field(default=None)
    video_edit_model: Optional[str] = Field(default=None)
    vision_model: Optional[str] = Field(default=None)
    enable_video_edit: Optional[bool] = Field(default=None)
    enable_vision_review: Optional[bool] = Field(default=None)
    enable_safety_audit: Optional[bool] = Field(default=None)
    safety_fail_policy: Optional[Literal["warn", "block"]] = Field(default=None)
    # 视频帧率：I2V/FFmpeg 视频生成时使用，范围 1~60
    video_fps: Optional[int] = Field(default=None, ge=1, le=60)
    # 视频生成是否需要确认：默认 VIDEO 模式下自动生成 video_clip_jobs 并等待确认
    video_require_confirmation: Optional[bool] = Field(default=None)
    prompt_review_required: Optional[bool] = Field(default=None)
    # 契约版本号，当前为 0.1.0
    schema_version: Optional[str] = None


class RunResponse(BaseModel):
    run_id: str
    state: str
    stage: Optional[str] = None
    progress: Optional[int] = None
    source_chapter_count: int
    plan: Optional[dict] = None
    storyboard: Optional[list] = None
    camera_tree_generation: Optional[dict] = None
    camera_tree: Optional[list] = None
    camera_states: Optional[list] = None
    camera_scenes: Optional[list] = None
    keyframes: Optional[list] = None
    midframes: Optional[list] = None
    video_clips: Optional[list] = None
    merged_video: Optional[str] = None
    audit: Optional[dict] = None
    autoqc: Optional[dict] = None
    qc_warning: Optional[dict] = None
    preflight: Optional[dict] = None
    video_provider_trace: Optional[dict] = None
    smart_dispatch_trace: Optional[dict] = None


class RunAsyncResponse(BaseModel):
    task_id: str
    run_id: str
    status: str
    preflight: Optional[dict] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    run_id: Optional[str] = None
    queue: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    artifacts: Optional[dict] = None
    error_type: Optional[str] = None
    result: Optional[RunResponse] = None
    error: Optional[str] = None


class DreamweaverRunSummaryResponse(BaseModel):
    run_id: str
    status: str
    state: Optional[str] = None
    stage: Optional[str] = None
    progress: int = 0
    schema_version: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    camera_tree_mode: Optional[str] = None
    camera_count: Optional[int] = None
    camera_states_count: Optional[int] = None
    camera_scenes_count: Optional[int] = None


class DreamweaverRunDeleteResponse(BaseModel):
    run_id: str
    deleted_generation_history: int
    deleted_assets: int
    deleted_shots: int
    deleted_episodes: int
    deleted_project: bool
    deleted_run_dir: bool
    failed_paths: List[str] = Field(default_factory=list)


class DreamweaverProjectGeneratedDeleteResponse(BaseModel):
    project_id: int
    deleted_runs: List[str] = Field(default_factory=list)
    skipped_runs: List[str] = Field(default_factory=list)
    deleted_library_assets: int = 0
    deleted_library_dir: bool = False
    deleted_library_anchor_projects: int = 0
    library_skipped: bool = False
    library_skip_reason: Optional[str] = None
    failed_paths: List[str] = Field(default_factory=list)
    failed_runs: List[Dict[str, str]] = Field(default_factory=list)


class LibraryApproveRequest(BaseModel):
    approve_all: bool = Field(default=False)
    roles: List[str] = Field(default_factory=list)
    approved: bool = Field(default=True)


class LibraryAssetProviderRefUpdateRequest(BaseModel):
    provider: Literal["kling"] = Field(default="kling")
    subject_id: Optional[str] = Field(default=None, max_length=128)
    source_asset_uri: Optional[str] = Field(default=None, max_length=2000)


class LibraryAssetProviderRefSyncRequest(BaseModel):
    provider: Literal["kling"] = Field(default="kling")
    include_related_views: bool = Field(default=True)
    timeout_s: float = Field(default=90.0, ge=5.0, le=300.0)
    poll_interval_s: float = Field(default=2.0, ge=0.2, le=10.0)


class ResumeAsyncResponse(BaseModel):
    task_id: str
    run_id: str
    status: str


class VideoJobConfirmAsyncResponse(BaseModel):
    run_id: str
    status: Literal["queued", "blocked", "noop"]
    task_id: Optional[str] = None
    message: Optional[str] = None
    video_clip_jobs: Optional[List[Dict[str, Any]]] = None


class VideoJobsRebuildResponse(BaseModel):
    run_id: str
    video_clip_jobs: List[Dict[str, Any]] = Field(default_factory=list)


class RestartAsyncRequest(BaseModel):
    start_state: str = Field(min_length=1)
    reset_policy: Literal["downstream", "none"] = Field(default="downstream")
    qc_allow_fail: Optional[bool] = Field(default=None)
    smart_tuning: Optional[bool] = Field(default=None)
    shot_ids: List[str] = Field(default_factory=list)
    cam_idxs: List[int] = Field(default_factory=list)
    asset_roles: List[str] = Field(default_factory=list)
    auto_asset_roles_from_missing_views: bool = Field(default=False)
    auto_asset_character_ids: List[int] = Field(default_factory=list)


class LibraryRegenerateRequest(BaseModel):
    role: str
    run_id: Optional[str] = None
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    prefer_image_edit: Optional[bool] = None
    prefer_view_chain_edit_base: Optional[bool] = None


class LibraryAutoRegenerateRolesRequest(BaseModel):
    run_id: Optional[str] = None
    character_ids: List[int] = Field(default_factory=list)


class LibraryPromptSuggestRequest(BaseModel):
    role: str
    run_id: Optional[str] = None
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    mode: Literal["template", "ai"] = Field(default="template")
    prefer_view_chain_seed: Optional[bool] = None


class LibraryPromptSuggestResponse(BaseModel):
    role: str
    style_preset: str
    image_ratio: str
    prompt: str
    negative_prompt: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class ShotFramePromptUpdateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


class ProjectLockedGenerationConfigResponse(BaseModel):
    locked: bool
    style_preset: str
    image_ratio: str
    image_resolution: str
    image_model: Optional[str] = None
    video_model: Optional[str] = None
    vision_model: Optional[str] = None
    video_edit_model: Optional[str] = None
    enable_video_edit: Optional[bool] = None
    enable_vision_review: Optional[bool] = None
    enable_safety_audit: Optional[bool] = None
    safety_fail_policy: Optional[str] = None
    source_run_id: Optional[str] = None


class ScriptUpdateRequest(BaseModel):
    script_text: str = Field(min_length=1)


class ScriptApproveRequest(BaseModel):
    approved: bool = Field(default=True)


class PromptReviewApproveRequest(BaseModel):
    approved: bool = Field(default=True)


class SafetyAuditApproveResponse(BaseModel):
    run_id: str
    status: str
    state: Optional[str] = None
    stage: Optional[str] = None
    manual_override: bool = Field(default=True)


class ShotVideoPromptUpdateRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, max_length=2000)
