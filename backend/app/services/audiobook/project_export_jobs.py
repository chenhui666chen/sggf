from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject
from app.models.project import Project

PROJECT_EXPORT_STAGE = "project_export"


def build_project_export_download_url(audiobook_project_id: int, export_type: str) -> str:
    export_path = "m4b" if export_type == "m4b" else "audacity"
    return f"/api/v1/audiobook/projects/{int(audiobook_project_id)}/exports/{export_path}/download"


def build_project_export_task_detail(
    *,
    audiobook_project_id: int,
    export_type: str,
    status: str,
    progress: float,
    message: str,
    force: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    stage_payload: Dict[str, Any] = {
        "status": status,
        "progress": max(0.0, min(1.0, float(progress or 0.0))),
        "message": message,
        "metrics": {},
    }
    if result:
        stage_payload["metrics"] = {
            "cached": bool(result.get("cached")),
            "chapter_count": result.get("chapter_count"),
            "duration": result.get("duration"),
            "file_size": result.get("file_size"),
        }
        for key in ("track_count", "label_count", "track_mode"):
            if key in result:
                stage_payload["metrics"][key] = result.get(key)
    if error_message:
        stage_payload["error_message"] = error_message

    detail: Dict[str, Any] = {
        "audiobook_project_id": int(audiobook_project_id),
        "export_type": export_type,
        "download_url": build_project_export_download_url(audiobook_project_id, export_type),
        "force": bool(force),
        "current_stage": PROJECT_EXPORT_STAGE,
        "stages": {
            PROJECT_EXPORT_STAGE: stage_payload,
        },
    }
    if metadata:
        detail["metadata"] = metadata
    if result:
        detail["export_result"] = result
    if error_message:
        detail["error_message"] = error_message
    return detail


def load_project_export_context(
    db: Session,
    *,
    audiobook_project_id: int,
) -> Tuple[AudiobookProject, Project]:
    audiobook_project = (
        db.query(AudiobookProject)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    if not audiobook_project:
        raise ValueError("有声书项目不存在")

    project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
    if not project:
        raise ValueError("项目不存在")

    return audiobook_project, project
