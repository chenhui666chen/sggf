"""Workflow API module."""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import json
import re
import uuid
from sqlalchemy import inspect, text

from app.db.base import get_db, SessionLocal
from app.services.agent_coordinator import coordinator, StageType, AgentStatus
from app.core.security import get_current_user
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection
from app.websocket.manager import ws_manager
from app.services.character_runtime_context import build_character_prompt_context_from_text
from app.services.workflow_context_builder import WorkflowContextBuilder
from app.utils.datetime_utils import parse_datetime_utc, utc_now
from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized, resolve_model_for_task
from app.services.prompts.stages.world_building import CharacterDesignPrompts, get_genre_character_fields
from app.services.auto_system_detector import auto_create_system_collections

logger = logging.getLogger(__name__)
class StartWorkflowRequest(BaseModel):
    project_id: int
    requirement: str
    # 🆕 可选的目标章节数配置，用于长篇规划（默认100章）
    target_chapter_count: Optional[int] = 100
    workflow_generation_model: Optional[str] = None
    # 🆕 是否清空现有内容（重新开始时使用）
    clear_existing: bool = False

class ExecuteStageRequest(BaseModel):
    project_id: int
    stage: str
    requirement: Optional[str] = None
    workflow_generation_model: Optional[str] = None
    # 🆕 是否启用流式输出（默认启用）
    enable_streaming: bool = True
    # 🆕 概念阶段评审/重生支持的可选参数
    regenerate: bool = False
    targets: Optional[list[str]] = None
    feedback: Optional[str] = None

class RegenerateStageRequest(BaseModel):
    project_id: int
    stage: str

class SaveStageContentRequest(BaseModel):
    content: str
    continue_workflow: bool = False

class GenerateNextChapterRequest(BaseModel):
    workflow_generation_model: Optional[str] = None

class ExpandStoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    current_outline: str
    world_setting: str
    characters: str
    current_chapter_count: int = 0
    current_character_count: int = 0
    target_total_chapters: Optional[int] = None
    target_total_characters: Optional[int] = None
    strategy: str = "auto"
    intent: str = "auto"
    enable_auto_supplement: bool = True
    expansion_mode: str = "auto"
    total_volumes: Optional[int] = None
    total_chapters_min: Optional[int] = None
    total_chapters_max: Optional[int] = None
    target_volume_index: Optional[int] = None
    volume_chapters_min: Optional[int] = None
    volume_chapters_max: Optional[int] = None
    volume_character_increment: Optional[int] = None
    preserve_written_mode: str = "extract_extend"
    lock_existing_chapters: bool = True
    preserve_existing_characters: bool = True
    reset_epic_framework: bool = False


router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

VALID_STORY_EXPANSION_STRATEGIES = {"auto", "balanced", "plot_first", "character_first"}
VALID_STORY_EXPANSION_INTENTS = {"auto", "outline_led", "character_led", "balanced"}
VALID_STORY_EXPANSION_MODES = {"auto", "total", "epic_framework", "volume_detail"}
VALID_PRESERVE_WRITTEN_MODES = {"extract_extend", "preserve_written", "regenerate_all"}
VOLUME_DETAIL_MIN_CHAPTERS = 20
VOLUME_DETAIL_MAX_CHAPTERS = 120

