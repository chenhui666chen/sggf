from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.character import Character
from app.models.project import Project, Chapter
from app.models.user import User
from app.models.dreamweaver import (
    DreamweaverAsset as DreamweaverAssetModel,
    DreamweaverEpisode as DreamweaverEpisodeModel,
    DreamweaverProject as DreamweaverProjectModel,
    DreamweaverRunEvent as DreamweaverRunEventModel,
    DreamweaverShot as DreamweaverShotModel,
)
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from app.utils.datetime_utils import utc_now
from app.services.dreamweaver.library import (
    approve_latest_library_assets,
    build_library_prompt,
    build_library_role,
    build_library_spec,
    build_library_spec_from_script_entities,
    compute_library_review,
    default_library_asset_uri,
    empty_library_spec,
    ensure_required_library_assets,
    enrich_payload_with_library,
    has_any_library_entities,
    load_latest_library_assets,
    parse_library_role,
    runs_root_path,
    required_library_roles,
    resolve_asset_path,
    strip_crowd_characters_from_spec,
)
from app.services.dreamweaver.video_generation import (
    DreamweaverRunPreflight,
    build_dreamweaver_run_preflight,
    resolve_video_generation_controls,
    sync_subject_ref_for_asset as sync_subject_ref_for_asset_service,
)
from app.services.providers.kling import (
    KlingAPIError,
    KlingConfigurationError,
)
from app.services.dreamweaver.config_lock import (
    DreamweaverProjectConfigLockedError,
    apply_locked_generation_config,
    apply_vision_review_qc_config,
    enforce_locked_generation_config_compatible,
    get_project_locked_generation_config,
    serialize_locked_generation_config,
)
from app.services.dreamweaver.library_prompt import suggest_library_prompt
from app.services.points_task_precheck import (
    build_dreamweaver_task_points_precheck,
    build_task_points_precheck_error_detail,
)
from app.services.chapter_adaptation_assets import build_drama_source_text

from pipeline.state_machine import RunContext, State, progress_percent, run_until_done, stage_label
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    infer_dreamweaver_video_engine_from_model_id,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    normalize_dreamweaver_video_engine,
    resolve_frame_size,
)
from pipeline.library_regenerate_roles import (
    build_missing_character_view_regenerate_roles,
    build_missing_character_view_summary,
)
from pipeline.style_presets import normalize_style_preset, style_negative_prompt_for_preset, style_prompt_for_preset
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)

from adapters.adapter_helpers import (
    edit_image as unified_edit_image,
    generate_image as unified_generate_image,
    get_model_info,
    model_supports_capability,
)

from app.api.v1.dreamweaver_api import router
from app.api.v1.dreamweaver_api._schemas import *
from app.api.v1.dreamweaver_api._helpers import *

__all__ = [
    "copy", "json", "logging", "os", "re", "shutil", "time", "uuid",
    "Path", "Any", "Dict", "List", "Literal", "Optional", "Tuple",
    "APIRouter", "Depends", "File", "HTTPException", "UploadFile", "status",
    "FileResponse", "requests", "text", "Session", "flag_modified",
    "get_current_user", "get_db",
    "Character", "Project", "Chapter", "User",
    "DreamweaverAssetModel", "DreamweaverEpisodeModel", "DreamweaverProjectModel",
    "DreamweaverRunEventModel", "DreamweaverShotModel",
    "DREAMWEAVER_SCHEMA_VERSION", "utc_now",
    "approve_latest_library_assets", "build_library_prompt", "build_library_role",
    "build_library_spec", "build_library_spec_from_script_entities",
    "compute_library_review", "default_library_asset_uri", "empty_library_spec",
    "ensure_required_library_assets", "enrich_payload_with_library",
    "has_any_library_entities", "load_latest_library_assets", "parse_library_role",
    "runs_root_path", "required_library_roles", "resolve_asset_path",
    "strip_crowd_characters_from_spec",
    "DreamweaverRunPreflight", "build_dreamweaver_run_preflight",
    "resolve_video_generation_controls", "sync_subject_ref_for_asset_service",
    "KlingAPIError", "KlingConfigurationError",
    "DreamweaverProjectConfigLockedError", "apply_locked_generation_config",
    "apply_vision_review_qc_config", "enforce_locked_generation_config_compatible",
    "get_project_locked_generation_config", "serialize_locked_generation_config",
    "suggest_library_prompt",
    "build_dreamweaver_task_points_precheck", "build_task_points_precheck_error_detail",
    "build_drama_source_text",
    "RunContext", "State", "progress_percent", "run_until_done", "stage_label",
    "DREAMWEAVER_I2V_ENGINE", "DREAMWEAVER_T2V_ENGINE",
    "infer_dreamweaver_video_engine_from_model_id", "is_dreamweaver_auto_engine",
    "is_dreamweaver_i2v_engine", "normalize_dreamweaver_video_engine", "resolve_frame_size",
    "build_missing_character_view_regenerate_roles", "build_missing_character_view_summary",
    "normalize_style_preset", "style_negative_prompt_for_preset", "style_prompt_for_preset",
    "_augment_library_prompt_for_role",
    "_attach_view_chain_prompt_meta",
    "_build_dreamweaver_runtime_config_from_request",
    "_build_library_asset_provider_sync_payload",
    "_build_project_library_spec",
    "_build_scoped_library_spec_from_run",
    "_build_source_text",
    "_character_role_for_view",
    "_character_view_from_role",
    "_dreamweaver_celery_queue",
    "_download_url_to_path",
    "_ensure_contract_shot_assets",
    "_ensure_dreamweaver_points_precheck_passed",
    "_ensure_dreamweaver_request_preflight_passed",
    "_ensure_path_under_runs",
    "_ensure_run_not_running",
    "_env_float",
    "_env_flag",
    "_env_int",
    "_extract_generation_history_rework_reason",
    "_extract_safety_audit_override_context",
    "_find_contract_shot",
    "_find_latest_generation_history_for_run",
    "_infer_video_engine_from_model_id",
    "_is_mp4",
    "_is_placeholder_entity_name",
    "_is_png",
    "_load_project_chapters",
    "_load_project_for_user",
    "_load_run_for_user",
    "_locked_generation_config_error_detail",
    "_merge_descriptor_texts",
    "_meta_descriptor_text",
    "_meta_prompt_text",
    "_normalize_positive_int_list",
    "_normalize_prompt_for_similarity",
    "_normalize_run_id",
    "_parse_generation_history_result_payload",
    "_persist_library_asset_provider_refs",
    "_prompt_similarity",
    "_quality_mode_to_runtime_config",
    "_read_upload_bytes",
    "_resolve_character_view_missing_regenerate_roles",
    "_resolve_library_entity_info",
    "_resolve_prompt_seed_for_role",
    "_resolve_registered_dreamweaver_model_id",
    "_runs_base_dir",
    "_write_image_from_generation_result",
    "resolve_image_edit_adapter_name", "resolve_image_edit_multi_ref", "resolve_image_edit_ref_max_images",
    "unified_edit_image", "unified_generate_image", "get_model_info", "model_supports_capability",
    "router",
    "RunRequest", "RunResponse", "RunAsyncResponse", "TaskStatusResponse",
    "DreamweaverRunSummaryResponse", "DreamweaverRunDeleteResponse",
    "DreamweaverProjectGeneratedDeleteResponse",
    "LibraryApproveRequest", "LibraryAssetProviderRefUpdateRequest",
    "LibraryAssetProviderRefSyncRequest", "ResumeAsyncResponse",
    "VideoJobConfirmAsyncResponse", "VideoJobsRebuildResponse",
    "RestartAsyncRequest", "LibraryRegenerateRequest",
    "LibraryAutoRegenerateRolesRequest", "LibraryPromptSuggestRequest",
    "LibraryPromptSuggestResponse", "ShotFramePromptUpdateRequest",
    "ProjectLockedGenerationConfigResponse", "ScriptUpdateRequest",
    "ScriptApproveRequest", "PromptReviewApproveRequest",
    "SafetyAuditApproveResponse", "ShotVideoPromptUpdateRequest",
]
