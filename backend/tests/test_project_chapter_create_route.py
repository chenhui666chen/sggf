"""项目内创建章节路由测试。

背景（bugfix）：前端通过 `POST /api/v1/projects/{project_id}/chapters` 创建章节，
`project_id` 已经在 URL 路径中携带。若后端复用要求请求体必带 `project_id` 的
`ChapterCreate`，请求会在进入函数体之前被 Pydantic 拦下并返回 422，
导致“生成完成后无法保存章节”。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for path in (ROOT_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import projects as projects_api, chapters as chapters_api
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.project import Chapter, Project
from app.models.user import User

OWNER_ID = 1
PROJECT_ID = 101


def _build_test_app() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Project.__table__, Chapter.__table__],
    )

    app = FastAPI()
    app.include_router(projects_api.router)
    app.include_router(chapters_api.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    auth_user = User(
        id=OWNER_ID,
        username="chapter_owner",
        password_hash="hash",
        is_active=True,
    )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[projects_api.get_db] = override_get_db
    app.dependency_overrides[chapters_api.get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: auth_user

    return TestClient(app), testing_session_local


@pytest.fixture()
def client_and_session():
    client, session_factory = _build_test_app()
    db = session_factory()
    try:
        db.add(
            Project(
                id=PROJECT_ID,
                display_no=1,
                user_id=OWNER_ID,
                title="测试小说",
                status="draft",
                word_count=0,
            )
        )
        db.commit()
    finally:
        db.close()
    return client, session_factory


def test_create_chapter_accepts_body_without_project_id(client_and_session):
    """请求体不含 project_id 时应正常创建（project_id 取自路径参数）。"""
    client, _ = client_and_session

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/chapters",
        json={"title": "第一章 初雪", "content": "他推开门，雪落了满肩。"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project_id"] == PROJECT_ID
    assert payload["title"] == "第一章 初雪"
    assert payload["content"] == "他推开门，雪落了满肩。"


def test_create_chapter_auto_fills_number_title_and_word_count(client_and_session):
    """请求体只剩内容时，章节号、标题、中文字数应由后端兜底生成。"""
    client, session_factory = client_and_session

    db = session_factory()
    try:
        db.add(
            Chapter(
                project_id=PROJECT_ID,
                chapter_number=2,
                title="既有章节",
                content="旧内容",
                word_count=3,
            )
        )
        db.commit()
    finally:
        db.close()

    content = "雪停了。\n\n他转身走进巷子深处。"
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/chapters",
        json={"content": content},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["chapter_number"] == 3
    assert payload["title"].strip() != ""
    # 中文字数：按去空白后的字符数统计，而非按空格分词
    assert payload["word_count"] == len("".join(content.split()))


def test_legacy_chapters_endpoint_keeps_its_contract(client_and_session):
    """重构后旧端点 POST /api/v1/chapters/ 行为不变：仍为 201 + body 携带 project_id。"""
    client, _ = client_and_session

    response = client.post(
        "/api/v1/chapters/",
        json={"project_id": PROJECT_ID, "title": "第一章", "content": "他走进巷子深处。"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["project_id"] == PROJECT_ID
    assert payload["title"] == "第一章"


def _spy_chapter_side_effects(monkeypatch):
    """记录章节创建后的追踪与后台任务调用。"""
    import app.services.auto_tracking as auto_tracking
    import app.services.chapter_post_save as chapter_post_save

    tracking_calls: list[str] = []
    started_tasks: list[dict] = []

    class FakeAutoTrackingService:
        @staticmethod
        def update_character_appearances_smart(**kwargs):
            tracking_calls.append("character_appearances")
            return {"added": 0}

        @staticmethod
        def update_setting_references_smart(**kwargs):
            tracking_calls.append("setting_references")
            return {"added": 0}

        @staticmethod
        def update_character_item_relations(**kwargs):
            tracking_calls.append("character_item_relations")
            return {"techniques": 0, "artifacts": 0, "locations": 0}

    def fake_start_chapter_post_save_task(**kwargs):
        started_tasks.append(kwargs)

    monkeypatch.setattr(auto_tracking, "AutoTrackingService", FakeAutoTrackingService)
    monkeypatch.setattr(
        chapter_post_save, "start_chapter_post_save_task", fake_start_chapter_post_save_task
    )
    return tracking_calls, started_tasks


def test_create_chapter_in_project_runs_entity_tracking(client_and_session, monkeypatch):
    """与 POST /api/v1/chapters/ 保持一致：创建后触发人物/设定追踪。"""
    tracking_calls, _ = _spy_chapter_side_effects(monkeypatch)
    client, _ = client_and_session

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/chapters",
        json={"title": "第一章", "content": "他走进巷子深处。"},
    )

    assert response.status_code == 200, response.text
    assert "character_appearances" in tracking_calls
    assert "setting_references" in tracking_calls
    assert "character_item_relations" in tracking_calls


def test_create_chapter_in_project_starts_summary_task(client_and_session, monkeypatch):
    """与 POST /api/v1/chapters/ 保持一致：创建后启动摘要生成后台任务。"""
    _, started_tasks = _spy_chapter_side_effects(monkeypatch)
    client, _ = client_and_session

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/chapters",
        json={"title": "第一章", "content": "他走进巷子深处。"},
    )

    assert response.status_code == 200, response.text
    assert len(started_tasks) == 1
    assert started_tasks[0]["chapter_id"] == response.json()["id"]
    assert started_tasks[0]["project_id"] == PROJECT_ID
    assert started_tasks[0]["generate_summary"] is True
