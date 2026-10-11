"""repair-score 端点持久化测试（epic 卷细纲项目）。

背景缺陷：repair-score 在 total scope 下只写回 project_settings.plot_outline，
而读取链路 load_stage_text_context 会用 epic_volumes_detail 重建 plot_outline，
导致修复结果在下次读取时被旧卷细纲静默覆盖（修复永不生效、可无限重复触发）。

覆盖：
- epic 项目调用 repair-score 后，通过读取链路重新加载大纲，人物承接修复可见；
- 二次调用 repair-score 报告"无需修复"（幂等）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for _path in (ROOT_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.workflow import router as workflow_router
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.project import Project
from app.models.user import User
from app.services.workflow_context_builder import WorkflowContextBuilder


CHARACTERS = """### 【姓名】：顾沉舟
【故事立场】：主角方
【角色定位】：主角
【核心动机】：查清浮尸案真相
【主线绑定】：贯穿全书
---

### 【姓名】：陆文渊
【故事立场】：中立方
【角色定位】：情报角色
【核心动机】：守住戏班秘辛
【主线绑定】：第二卷关键证人
---

### 【姓名】：秦九香
【故事立场】：反派方
【角色定位】：对手
【核心动机】：夺回祖传戏箱
【主线绑定】：第三卷冲突核心
---"""


def _chapter(n: int, title: str, body_chars: str) -> str:
    return (
        f"第{n}章：{title}\n"
        f"- 场景目标：推进主线调查。\n"
        f"- 关键事件：证物出现，线索推进。\n"
        f"- 涉及人物：{body_chars}\n"
        f"- 结尾钩子：留下新的悬念。"
    )


VOLUME_1_DETAIL = "\n\n".join([
    _chapter(1, "浮尸现河", "顾沉舟"),
    _chapter(2, "回响初启", "顾沉舟"),
])

VOLUME_2_DETAIL = "\n\n".join([
    _chapter(3, "戏班旧案", "顾沉舟"),
    _chapter(4, "河底遗物", "顾沉舟"),
])

EPIC_VOLUMES_DETAIL = json.dumps(
    {
        "volumes": {
            "1": {"type": "detail", "summary": "第一卷", "detail": VOLUME_1_DETAIL, "chapters_range": [1, 2]},
            "2": {"type": "detail", "summary": "第二卷", "detail": VOLUME_2_DETAIL, "chapters_range": [3, 4]},
        }
    },
    ensure_ascii=False,
)


def _build_app_with_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Project.__table__])
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE project_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL UNIQUE,
                    concept TEXT,
                    world_setting TEXT,
                    characters TEXT,
                    plot_outline TEXT,
                    chapter_draft TEXT,
                    review_report TEXT,
                    final_version TEXT,
                    stage_one_status VARCHAR(50),
                    stage_two_status VARCHAR(50),
                    stage_three_status VARCHAR(50),
                    stage_four_status VARCHAR(50),
                    stage_five_status VARCHAR(50),
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    epic_framework TEXT,
                    epic_framework_generated_at TIMESTAMP,
                    epic_volumes_detail TEXT,
                    structured_memory TEXT,
                    structured_memory_updated_at TIMESTAMP,
                    review_meta TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (username, email, password_hash, is_active, token_version) "
                "VALUES ('tester', 'tester@example.com', 'x', 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO projects (display_no, title, user_id, status, word_count, created_at, updated_at) "
                "VALUES (1, 'epic修复测试项目', (SELECT id FROM users LIMIT 1), 'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO project_settings (project_id, characters, plot_outline, epic_volumes_detail)
                VALUES (
                    (SELECT id FROM projects LIMIT 1),
                    :characters,
                    :plot_outline,
                    :epic_volumes_detail
                )
                """
            ),
            {
                "characters": CHARACTERS,
                "plot_outline": VOLUME_1_DETAIL + "\n\n" + VOLUME_2_DETAIL,
                "epic_volumes_detail": EPIC_VOLUMES_DETAIL,
            },
        )

    app = FastAPI()
    app.include_router(workflow_router)

    from app.models.user import User as UserModel

    def _override_current_user():
        with session_factory() as session:
            return session.query(UserModel).first()

    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_db] = lambda: session_factory()
    return app, session_factory


def _post_repair(app: FastAPI, project_id: int):
    import asyncio

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/api/v1/workflow/expand-story/repair-score",
                json={"project_id": project_id},
            )

    return asyncio.run(_run())


def test_repair_score_persists_through_epic_volumes_read_path():
    app, session_factory = _build_app_with_db()
    with session_factory() as session:
        project_id = session.execute(text("SELECT id FROM projects LIMIT 1")).scalar_one()

    resp = _post_repair(app, project_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    result = body["result"]
    assert result["validation_after"]["unreferenced_characters"] == []

    # 核心断言：修复必须经得起读取链路重建（epic_volumes_detail 是权威源）
    with session_factory() as session:
        builder = WorkflowContextBuilder(session)
        stage = builder.load_stage_text_context(project_id)
    outline_after = (stage.plot_outline or "").strip()
    assert "陆文渊" in outline_after, "修复后读取链路未见人物『陆文渊』承接（被旧卷细纲回滚）"
    assert "秦九香" in outline_after, "修复后读取链路未见人物『秦九香』承接（被旧卷细纲回滚）"

    # 幂等：二次调用应报告无需修复
    resp2 = _post_repair(app, project_id)
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["result"]["validation_before"]["unreferenced_characters"] == []
