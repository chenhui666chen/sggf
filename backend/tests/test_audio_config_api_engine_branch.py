"""Phase 1.3 API 合约测试（真实 PostgreSQL）。

覆盖：
- GET audio-config 返回 engines 字段
- PUT 写入引擎分支（characters + audio_fx）
- GET engine-preferences 端点
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

_env_path = ROOT_DIR / ".env"
# 无条件从 .env 读取（其他测试模块可能已写入无效占位 URL，如 test_auth_routes）
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()
            break

DATABASE_URL = os.environ.get("DATABASE_URL", "")

TEST_SCHEMA = "audiobook_audio_config_api_test"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("API 合约测试必须运行于真实 PostgreSQL")


from app.api.v1 import projects as projects_router  # noqa: E402
from app.core.security import get_current_user, create_access_token  # noqa: E402
from app.db.base import Base, get_db  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402

_TABLES = [
    User.__table__,
    Project.__table__,
]


@pytest.fixture(scope="module")
def engine():
    _require_pg()
    eng = create_engine(DATABASE_URL, poolclass=NullPool)
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
    yield eng.execution_options(schema_translate_map={None: TEST_SCHEMA})
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    Base.metadata.create_all(bind=engine, tables=_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def test_client(session_factory):
    app = FastAPI()
    app.include_router(projects_router.router)

    _test_user = None

    def _get_current_user_override():
        nonlocal _test_user
        return _test_user

    app.dependency_overrides[get_current_user] = _get_current_user_override

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return CompatTestClient(app), session_factory, app


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def put(self, url: str, **kwargs) -> Response:
        return self.request("PUT", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def _seed_project(db: Session, tag: str) -> tuple[User, Project]:
    """创建测试用户和项目。"""
    user = User(
        username=f"api_user_{tag}",
        email=f"{tag}@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    project = Project(
        title=f"api_proj_{tag}",
        user_id=user.id,
        display_no=1,
        audio_config=json.dumps({
            "audio_engine_mode": "legacy_stems",
            "seed_audio_model": "seed-audio-1.0-multilingual",
            "characters": [
                {"character_id": 1, "name": "初始角色", "voice_id": "v1"},
            ],
            "audio_fx": {"enable_sound_effects": True, "bgm_theme": "fantasy"},
            "tts_models": {
                "qwen3-tts-instruct-flash": {
                    "characters": [
                        {"character_id": 1, "name": "初始角色", "voice_id": "v1_tts"},
                    ]
                }
            },
        }),
    )
    db.add(project)
    db.flush()
    db.commit()
    return user, project


# ── GET audio-config ────────────────────────────────────────────────────────


class TestGetAudioConfig:
    def test_returns_engines_field_when_present(self, test_client, db):
        """GET audio-config 返回 engines 字段。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "get_eng")

        # 写入引擎分支数据
        proj = db.query(Project).filter(Project.id == project.id).first()
        data = json.loads(proj.audio_config or "{}")
        data["engines"] = {
            "legacy_stems": {
                "tts_models": {
                    "qwen3-tts-instruct-flash": {
                        "characters": [
                            {"character_id": 1, "name": "分支角色", "voice_id": "branch_v1"},
                        ]
                    }
                },
                "audio_fx": {"enable_sound_effects": True, "bgm_theme": "branch_fantasy"},
            }
        }
        proj.audio_config = json.dumps(data, ensure_ascii=False)
        db.add(proj)
        db.commit()

        # 替换 current_user override
        app.dependency_overrides[get_current_user] = lambda: user

        response = client.get(f"/api/v1/projects/{project.id}/audio-config?tts_model=qwen3-tts-instruct-flash")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "engines" in payload
        assert payload["audio_engine_mode"] == "legacy_stems"
        assert len(payload["characters"]) == 1
        assert payload["characters"][0]["character_id"] == 1

    def test_returns_engine_mode_resolved(self, test_client, db):
        """GET audio-config 的 audio_engine_mode 为解析后的值。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "get_mode")

        proj = db.query(Project).filter(Project.id == project.id).first()
        data = json.loads(proj.audio_config or "{}")
        data["audio_engine_mode"] = "auto"
        data["seed_timeline_mode"] = "fast"  # 触发 seed_scene 判定
        proj.audio_config = json.dumps(data, ensure_ascii=False)
        db.add(proj)
        db.commit()

        app.dependency_overrides[get_current_user] = lambda: user
        response = client.get(f"/api/v1/projects/{project.id}/audio-config")
        assert response.status_code == 200, response.text
        payload = response.json()
        # auto + 旧顶层 seed 键 → seed_scene
        assert payload["audio_engine_mode"] == "seed_scene"


# ── PUT audio-config ────────────────────────────────────────────────────────


class TestPutAudioConfig:
    def test_writes_characters_to_engine_branch(self, test_client, db):
        """PUT 角色写入当前引擎分支。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "put_chars")

        app.dependency_overrides[get_current_user] = lambda: user

        new_chars = [
            {"character_id": 1, "name": "更新角色", "voice_id": "updated_v1", "source": "user"},
        ]
        response = client.put(
            f"/api/v1/projects/{project.id}/audio-config?tts_model=qwen3-tts-instruct-flash",
            json={
                "characters": new_chars,
                "audio_fx": {"enable_sound_effects": True, "bgm_theme": "mystery"},
                "audio_engine_mode": "legacy_stems",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload["characters"]) == 1
        assert payload["characters"][0]["voice_id"] == "updated_v1"

        # 验证持久化：引擎分支写入了数据
        db.commit()
        proj = db.query(Project).filter(Project.id == project.id).first()
        saved = json.loads(proj.audio_config or "{}")
        engines = saved.get("engines", {})
        legacy = engines.get("legacy_stems", {})
        tts_models = legacy.get("tts_models", {})
        flash_chars = tts_models.get("qwen3-tts-instruct-flash", {}).get("characters", [])
        assert len(flash_chars) == 1
        assert flash_chars[0]["voice_id"] == "updated_v1"
        # audio_fx 写入引擎分支
        assert legacy.get("audio_fx", {}).get("bgm_theme") == "mystery"
        # 旧顶层 audio_fx 未被覆盖（因 mode=legacy_stems 写入分支）
        assert saved.get("audio_fx", {}).get("bgm_theme") == "fantasy"

    def test_writes_engines_field(self, test_client, db):
        """PUT 传入 engines 字段时合并写入。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "put_eng")

        app.dependency_overrides[get_current_user] = lambda: user

        response = client.put(
            f"/api/v1/projects/{project.id}/audio-config?tts_model=qwen3-tts-instruct-flash",
            json={
                "characters": [],
                "audio_fx": None,
                "engines": {
                    "seed_scene": {
                        "tts_models": {
                            "seed-audio-1.0-multilingual": {
                                "characters": [{"character_id": 2, "name": "种子角色", "voice_id": "seed_v2"}],
                            }
                        },
                        "audio_fx": {"enable_sound_effects": True},
                        "scene_generation_preferences": {"music_enabled": False},
                    }
                },
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["engines"] is not None
        assert "seed_scene" in payload["engines"]

        # 验证持久化
        db.commit()
        proj = db.query(Project).filter(Project.id == project.id).first()
        saved = json.loads(proj.audio_config or "{}")
        assert "engines" in saved
        assert "seed_scene" in saved["engines"]

    def test_writes_legacy_stems_with_mirror(self, test_client, db):
        """PUT 写入 legacy_stems + 默认模型时镜像顶层 characters。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "put_mirror")

        app.dependency_overrides[get_current_user] = lambda: user

        new_chars = [
            {"character_id": 1, "name": "镜像角色", "voice_id": "mirror_v1", "source": "user"},
        ]
        response = client.put(
            f"/api/v1/projects/{project.id}/audio-config?tts_model=qwen3-tts-instruct-flash",
            json={
                "characters": new_chars,
                "audio_engine_mode": "legacy_stems",
            },
        )
        assert response.status_code == 200, response.text

        # 验证顶层 characters 已镜像
        db.commit()
        proj = db.query(Project).filter(Project.id == project.id).first()
        saved = json.loads(proj.audio_config or "{}")
        assert saved.get("characters", [{}])[0].get("voice_id") == "mirror_v1"

    def test_engines_field_does_not_clear_other_branch(self, test_client, db):
        """PUT 带 engines 时只落分支：不清空其他引擎分支（GUIDE §2.2）。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "put_eng_branch")

        # 预置 legacy_stems 分支绑定
        proj = db.query(Project).filter(Project.id == project.id).first()
        data = json.loads(proj.audio_config or "{}")
        data["engines"] = {
            "legacy_stems": {
                "tts_models": {
                    "qwen3-tts-instruct-flash": {
                        "characters": [
                            {"character_id": 1, "name": "旧绑定", "voice_id": "legacy_v1"},
                        ]
                    }
                }
            }
        }
        proj.audio_config = json.dumps(data, ensure_ascii=False)
        db.add(proj)
        db.commit()

        app.dependency_overrides[get_current_user] = lambda: user
        response = client.put(
            f"/api/v1/projects/{project.id}/audio-config?tts_model=qwen3-tts-instruct-flash",
            json={
                "characters": [],
                "audio_fx": None,
                "audio_engine_mode": "seed_scene",
                "engines": {
                    "seed_scene": {
                        "tts_models": {
                            "qwen3-tts-instruct-flash": {
                                "characters": [
                                    {"character_id": 2, "name": "新绑定", "voice_id": "seed_v2"},
                                ]
                            }
                        }
                    }
                },
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        # audio_engine_mode 先更新，响应反映新引擎
        assert payload["audio_engine_mode"] == "seed_scene"

        db.commit()
        proj = db.query(Project).filter(Project.id == project.id).first()
        saved = json.loads(proj.audio_config or "{}")
        assert saved["audio_engine_mode"] == "seed_scene"
        # legacy_stems 分支不被空顶层 characters 清空
        legacy_chars = (
            saved.get("engines", {})
            .get("legacy_stems", {})
            .get("tts_models", {})
            .get("qwen3-tts-instruct-flash", {})
            .get("characters", [])
        )
        assert len(legacy_chars) == 1
        assert legacy_chars[0]["voice_id"] == "legacy_v1"
        # seed_scene 分支写入新绑定
        seed_chars = (
            saved.get("engines", {})
            .get("seed_scene", {})
            .get("tts_models", {})
            .get("qwen3-tts-instruct-flash", {})
            .get("characters", [])
        )
        assert len(seed_chars) == 1
        assert seed_chars[0]["voice_id"] == "seed_v2"


# ── GET engine-preferences ──────────────────────────────────────────────────


class TestGetEnginePreferences:
    def test_legacy_stems_returns_audio_fx(self, test_client, db):
        """legacy_stems 返回 audio_fx。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "pref_leg")

        app.dependency_overrides[get_current_user] = lambda: user
        response = client.get(f"/api/v1/projects/{project.id}/audio-config/engine-preferences")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["engine_mode"] == "legacy_stems"
        assert payload["audio_fx"] is not None
        assert payload["scene_generation_preferences"] is None

    def test_seed_scene_returns_scene_prefs(self, test_client, db):
        """seed_scene 返回 scene_generation_preferences。"""
        client, session_factory, app = test_client
        user, project = _seed_project(db, "pref_seed")

        proj = db.query(Project).filter(Project.id == project.id).first()
        data = json.loads(proj.audio_config or "{}")
        data["audio_engine_mode"] = "seed_scene"
        data["engines"] = {
            "seed_scene": {
                "scene_generation_preferences": {
                    "music_enabled": True,
                    "soundscape_intensity": "high",
                    "performance_style": "cinematic",
                }
            }
        }
        proj.audio_config = json.dumps(data, ensure_ascii=False)
        db.add(proj)
        db.commit()

        app.dependency_overrides[get_current_user] = lambda: user
        response = client.get(f"/api/v1/projects/{project.id}/audio-config/engine-preferences")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["engine_mode"] == "seed_scene"
        assert payload["scene_generation_preferences"] is not None
        assert payload["scene_generation_preferences"]["soundscape_intensity"] == "high"
        assert payload["audio_fx"] is None