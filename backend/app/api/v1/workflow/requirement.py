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

def _get_workflow_session_columns(db: Session) -> set[str]:
    """获取 workflow_sessions 当前实际存在的列，兼容不同数据库版本。"""
    try:
        inspector = inspect(db.get_bind())
        return {column["name"] for column in inspector.get_columns("workflow_sessions")}
    except Exception as exc:
        logger.warning(f"⚠️  获取 workflow_sessions 列信息失败: {exc}")
        return set()


def _extract_requirement_from_workflow_data(raw_value: Any) -> Optional[str]:
    """从 workflow_sessions.data 或旧版 requirement 字段中提取用户需求。"""
    if raw_value is None:
        return None

    if isinstance(raw_value, str):
        text_value = raw_value.strip()
        if not text_value:
            return None
        try:
            raw_value = json.loads(text_value)
        except json.JSONDecodeError:
            return text_value

    if isinstance(raw_value, dict):
        for key in ("requirement", "description", "user_requirement", "prompt", "initial_idea"):
            value = raw_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(raw_value, ensure_ascii=False)

    if isinstance(raw_value, list):
        return json.dumps(raw_value, ensure_ascii=False)

    value = str(raw_value).strip()
    return value or None


def _save_workflow_requirement(db: Session, project_id: int, user_id: int, requirement: str) -> str:
    """保存最新工作流需求，兼容旧版 requirement 列和新版 data 列。"""
    columns = _get_workflow_session_columns(db)

    db.execute(
        text("DELETE FROM workflow_sessions WHERE project_id = :project_id"),
        {"project_id": project_id},
    )

    timestamp = utc_now().isoformat()

    if {"requirement", "created_at"}.issubset(columns):
        db.execute(
            text(
                """INSERT INTO workflow_sessions
                   (project_id, user_id, requirement, created_at)
                   VALUES (:project_id, :user_id, :requirement, :created_at)"""
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "requirement": requirement,
                "created_at": timestamp,
            },
        )
        return "legacy_requirement"

    payload = json.dumps({"requirement": requirement}, ensure_ascii=False)
    insert_columns = ["project_id", "user_id"]
    insert_values = [":project_id", ":user_id"]
    params: Dict[str, Any] = {
        "project_id": project_id,
        "user_id": user_id,
    }

    if "session_type" in columns:
        insert_columns.append("session_type")
        insert_values.append(":session_type")
        params["session_type"] = "workflow"

    if "status" in columns:
        insert_columns.append("status")
        insert_values.append(":status")
        params["status"] = "active"

    if "current_stage" in columns:
        insert_columns.append("current_stage")
        insert_values.append(":current_stage")
        params["current_stage"] = "concept"

    if "data" in columns:
        insert_columns.append("data")
        insert_values.append(":data")
        params["data"] = payload
    elif "requirement" in columns:
        insert_columns.append("requirement")
        insert_values.append(":requirement")
        params["requirement"] = requirement
    else:
        raise RuntimeError("workflow_sessions 缺少可用于保存需求的字段（data/requirement）")

    if "started_at" in columns:
        insert_columns.append("started_at")
        insert_values.append(":started_at")
        params["started_at"] = timestamp
    elif "created_at" in columns:
        insert_columns.append("created_at")
        insert_values.append(":created_at")
        params["created_at"] = timestamp

    db.execute(
        text(
            f"""INSERT INTO workflow_sessions
               ({", ".join(insert_columns)})
               VALUES ({", ".join(insert_values)})"""
        ),
        params,
    )
    return "data_json" if "data" in columns else "requirement_only"


def _resolve_workflow_requirement(db: Session, project_id: int) -> tuple[str, str]:
    """解析工作流需求，优先 workflow_sessions，其次 projects.description。"""
    columns = _get_workflow_session_columns(db)

    if "requirement" in columns:
        order_column = "created_at" if "created_at" in columns else "id"
        order_clause = f"{order_column} DESC, id DESC" if order_column != "id" else "id DESC"
        result = db.execute(
            text(
                f"""SELECT requirement FROM workflow_sessions
                    WHERE project_id = :project_id
                    ORDER BY {order_clause}
                    LIMIT 1"""
            ),
            {"project_id": project_id},
        ).fetchone()
        requirement = _extract_requirement_from_workflow_data(result[0] if result else None)
        if requirement:
            return requirement, "workflow_sessions.requirement"

    if "data" in columns:
        order_column = "started_at" if "started_at" in columns else ("created_at" if "created_at" in columns else "id")
        order_clause = f"{order_column} DESC, id DESC" if order_column != "id" else "id DESC"
        result = db.execute(
            text(
                f"""SELECT data FROM workflow_sessions
                    WHERE project_id = :project_id
                    ORDER BY {order_clause}
                    LIMIT 1"""
            ),
            {"project_id": project_id},
        ).fetchone()
        requirement = _extract_requirement_from_workflow_data(result[0] if result else None)
        if requirement:
            return requirement, "workflow_sessions.data"

    project_result = db.execute(
        text("SELECT description FROM projects WHERE id = :project_id"),
        {"project_id": project_id},
    ).fetchone()
    if project_result and project_result[0]:
        return project_result[0], "projects.description"

    return "根据项目设定进行创作", "default"

