from __future__ import annotations

import asyncio
import json
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base, get_db
from app.models.dreamweaver import DreamweaverProject
from app.models.project import Project
from app.models.user import User


def load_dreamweaver_module():
    dreamweaver_path = ROOT_DIR / "app" / "api" / "v1" / "dreamweaver.py"
    spec = spec_from_file_location("test_dreamweaver_safety_audit_override_module", dreamweaver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 DreamWeaver 路由模块")

    module = module_from_spec(spec)
    sys.modules.setdefault("test_dreamweaver_safety_audit_override_module", module)
    spec.loader.exec_module(module)
    return module


dreamweaver = load_dreamweaver_module()


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def build_test_client() -> tuple[CompatTestClient, sessionmaker, FastAPI]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Project.__table__,
            DreamweaverProject.__table__,
        ],
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE generation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    task_type VARCHAR(50) NOT NULL,
                    task_id VARCHAR(255) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT,
                    completed_at TEXT
                )
                """
            )
        )

    app = FastAPI()
    app.include_router(dreamweaver.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[dreamweaver.get_db] = override_get_db
    return CompatTestClient(app), testing_session_local, app


def _seed_run(
    session_factory: sessionmaker,
    *,
    run_id: str,
    row_status: str = "failed",
    row_error_type: str | None = "state_machine_failed",
    row_error_message: str | None = "unsafe video",
    history_result: dict | None = None,
) -> tuple[User, Project, DreamweaverProject]:
    db = session_factory()
    try:
        user = User(
            username=f"{run_id}_user",
            email=f"{run_id}_user@example.com",
            full_name=f"{run_id}_user",
            is_active=True,
        )
        db.add(user)
        db.flush()

        project = Project(user_id=int(user.id), display_no=1, title=f"{run_id} project")
        db.add(project)
        db.flush()

        dw_project = DreamweaverProject(
            run_id=run_id,
            source_project_id=int(project.id),
            user_id=int(user.id),
            status=row_status,
            state="FAILED" if row_status == "failed" else "DONE",
            stage="failed" if row_status == "failed" else "done",
            progress=100,
            error_type=row_error_type,
            error_message=row_error_message,
            contract_json={
                "run_id": run_id,
                "runtime_config": {
                    "qc_config": {
                        "enable_safety_audit": True,
                        "safety_fail_policy": "block",
                    }
                },
                "episodes": [],
            },
        )
        db.add(dw_project)
        db.flush()

        if history_result is not None:
            db.execute(
                text(
                    """
                    INSERT INTO generation_history
                    (project_id, task_type, task_id, status, result, error, created_at, completed_at)
                    VALUES (:project_id, :task_type, :task_id, :status, :result, :error, :created_at, :completed_at)
                    """
                ),
                {
                    "project_id": int(project.id),
                    "task_type": "dreamweaver",
                    "task_id": f"task_{run_id}",
                    "status": row_status,
                    "result": json.dumps(history_result, ensure_ascii=False),
                    "error": row_error_message,
                    "created_at": "2026-04-18T00:00:00+00:00",
                    "completed_at": "2026-04-18T00:01:00+00:00",
                },
            )

        db.commit()
        db.refresh(user)
        db.refresh(project)
        db.refresh(dw_project)
        return user, project, dw_project
    finally:
        db.close()


def test_safety_audit_approve_completes_failed_run_and_updates_history() -> None:
    client, session_factory, app = build_test_client()
    history_result = {
        "run_id": "dw_safety_override_ok",
        "state": "FAILED",
        "stage": "failed",
        "progress": 100,
        "source_chapter_count": 1,
        "audit": {
            "safety_audit": {
                "enabled": True,
                "executed": True,
                "unsafe": True,
                "blocked": True,
                "fail_policy": "block",
                "summary": "unsafe video",
                "categories": ["violence"],
            }
        },
        "artifacts": {
            "rework_reason": {
                "type": "safety_audit_failed",
                "safety_audit": {
                    "summary": "unsafe video",
                    "blocked": True,
                },
            }
        },
        "error_type": "state_machine_failed",
        "error_message": "unsafe video",
    }
    user, _project, run = _seed_run(
        session_factory,
        run_id="dw_safety_override_ok",
        history_result=history_result,
    )
    app.dependency_overrides[dreamweaver.get_current_user] = lambda: user

    response = client.post(f"/api/v1/dreamweaver/runs/{run.run_id}/safety-audit/approve")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run.run_id
    assert data["status"] == "completed"
    assert data["state"] == "DONE"
    assert data["stage"] == "done"
    assert data["manual_override"] is True

    db = session_factory()
    try:
        refreshed = db.query(DreamweaverProject).filter(DreamweaverProject.run_id == run.run_id).first()
        assert refreshed is not None
        assert refreshed.status == "completed"
        assert refreshed.state == "DONE"
        assert refreshed.stage == "done"
        assert refreshed.error_type is None
        assert refreshed.error_message is None

        runtime_cfg = dict((refreshed.contract_json or {}).get("runtime_config") or {})
        audit = dict(runtime_cfg.get("audit") or {})
        safety_audit = dict(audit.get("safety_audit") or {})
        assert safety_audit["manual_override"] is True
        assert safety_audit["effective_blocked"] is False
        assert safety_audit["original_error_message"] == "unsafe video"

        rework_reason = dict(runtime_cfg.get("rework_reason") or {})
        assert rework_reason["type"] == "safety_audit_failed"
        assert rework_reason["manual_override"] is True

        gh_row = db.execute(
            text("SELECT status, result, error FROM generation_history WHERE task_id = :task_id"),
            {"task_id": "task_dw_safety_override_ok"},
        ).fetchone()
        assert gh_row is not None
        assert gh_row[0] == "completed"
        assert gh_row[2] is None

        payload = json.loads(gh_row[1])
        assert payload["state"] == "DONE"
        assert payload["stage"] == "done"
        assert payload["audit"]["safety_audit"]["manual_override"] is True
        assert payload["artifacts"]["rework_reason"]["manual_override"] is True
        assert "error_type" not in payload
    finally:
        db.close()


def test_safety_audit_approve_rejects_non_safety_failed_run() -> None:
    client, session_factory, app = build_test_client()
    history_result = {
        "run_id": "dw_autoqc_failed_only",
        "state": "FAILED",
        "stage": "failed",
        "progress": 100,
        "source_chapter_count": 1,
        "autoqc": {"pass": False},
        "artifacts": {
            "rework_reason": {
                "type": "autoqc_failed",
                "failures": [{"type": "video_clip_quality_below_threshold"}],
            }
        },
        "error_type": "state_machine_failed",
        "error_message": "autoqc failed",
    }
    user, _project, run = _seed_run(
        session_factory,
        run_id="dw_autoqc_failed_only",
        row_error_message="autoqc failed",
        history_result=history_result,
    )
    app.dependency_overrides[dreamweaver.get_current_user] = lambda: user

    response = client.post(f"/api/v1/dreamweaver/runs/{run.run_id}/safety-audit/approve")

    assert response.status_code == 400

    db = session_factory()
    try:
        refreshed = db.query(DreamweaverProject).filter(DreamweaverProject.run_id == run.run_id).first()
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.error_message == "autoqc failed"
    finally:
        db.close()


def test_safety_audit_approve_supports_row_error_type_fallback_without_history() -> None:
    client, session_factory, app = build_test_client()
    user, _project, run = _seed_run(
        session_factory,
        run_id="dw_safety_row_fallback",
        row_error_type="SafetyAuditFailed",
        row_error_message="row fallback unsafe",
        history_result=None,
    )
    app.dependency_overrides[dreamweaver.get_current_user] = lambda: user

    response = client.post(f"/api/v1/dreamweaver/runs/{run.run_id}/safety-audit/approve")

    assert response.status_code == 200

    db = session_factory()
    try:
        refreshed = db.query(DreamweaverProject).filter(DreamweaverProject.run_id == run.run_id).first()
        assert refreshed is not None
        runtime_cfg = dict((refreshed.contract_json or {}).get("runtime_config") or {})
        safety_audit = dict(dict(runtime_cfg.get("audit") or {}).get("safety_audit") or {})
        assert safety_audit["manual_override"] is True
        assert safety_audit["original_error_type"] == "SafetyAuditFailed"
        assert safety_audit["original_error_message"] == "row fallback unsafe"
        assert refreshed.status == "completed"
    finally:
        db.close()
