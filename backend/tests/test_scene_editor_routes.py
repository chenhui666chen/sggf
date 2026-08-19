"""GUIDE 阶段 3.2/3.3/3.4/3.5 场景编辑器 API 测试。

覆盖：
- ``GET editor-document``：legacy_stems 拒绝、seed_scene 文档形状（scenes/
  last_revisions/revision_set_hash）、章节从属 404；
- ``PUT editor-document``：三类编辑（dialogue 写回 script_json 且语义变化置
  pending、director_override 不修改原文、voice_binding 双写 audio_config）+
  409 并发冲突 + 非法 edit_type/参数 400；
- ``POST dialogue-review``：reviewed/approved 状态机 + 过期 revision_set_hash 409；
- ``GET /scenes/{id}/stream|audit-stream``：play_token 试听、凭证缺失 401、
  superseded 404、审计头暴露。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for _path in (ROOT_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import router as audiobook_router
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.audiobook import (
    AudiobookProject,
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
    SceneAudioArtifact,
    SceneEditRevision,
    SceneEditRevisionHead,
)
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook.chapter_output_publish import (
    publish_seed_scene_chapter_output,
    register_scene_audio_artifacts,
    upsert_staged_chapter_output,
)
from app.services.audiobook.scene_edit_revision_service import (
    derive_scene_topology_hash,
)


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
        import asyncio

        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def put(self, url: str, **kwargs) -> Response:
        return self.request("PUT", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def build_test_client() -> tuple[CompatTestClient, sessionmaker, FastAPI]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Project.__table__,
            Chapter.__table__,
            AudiobookProject.__table__,
            ChapterAudioRun.__table__,
            ChapterAudio.__table__,
            ChapterAudioOutput.__table__,
            SceneAudioArtifact.__table__,
            SceneEditRevision.__table__,
            SceneEditRevisionHead.__table__,
        ],
    )
    # SQLite 不识别 postgresql_where 部分唯一索引（退化为全局唯一），
    # 会阻止同章节第二个 run 的输出登记；本测试每章节仅发布一次，
    # 但显式移除以避免与后续用例交叉污染。
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("DROP INDEX IF EXISTS uq_chapter_audio_output_published"))

    app = FastAPI()
    app.include_router(audiobook_router)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return CompatTestClient(app), session_factory, app


SEGMENTS = [
    {
        "segment_key": "seg_a",
        "type": "dialogue",
        "text": "第一段台词原文",
        "speaker": "角色甲",
    },
    {
        "segment_key": "seg_b",
        "type": "dialogue",
        "text": "第二段台词原文",
        "speaker": "角色乙",
    },
]


def seed_editor_context(
    session_factory,
    *,
    engine_mode: str = "seed_scene",
    script_status: str = "reviewed",
    prepend_dummy_batch: bool = False,
    with_review_evidence: bool = False,
):
    db = session_factory()
    try:
        user = User(
            username="scene_editor_user",
            email="scene_editor@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            display_no=1,
            title="Scene Editor Project",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()
        chapter = Chapter(
            project_id=project.id,
            chapter_number=1,
            title="Chapter 1",
            content="Test content",
            summary="summary",
        )
        db.add(chapter)
        db.flush()
        if prepend_dummy_batch:
            # 占位批次：让目标批次 id 与 project id 不同，暴露把
            # audiobook_project_id 误当 project_id 的归属校验 bug
            dummy = AudiobookProject(
                project_id=project.id,
                status="processing",
                total_chapters=1,
                engine_mode="seed_scene",
            )
            db.add(dummy)
            db.flush()
        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="processing",
            total_chapters=1,
            engine_mode=engine_mode,
        )
        db.add(audiobook_project)
        db.flush()
        chapter_audio = ChapterAudio(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapter.id,
            script_status=script_status,
            script_json=json.dumps(SEGMENTS, ensure_ascii=False),
        )
        if with_review_evidence:
            chapter_audio.script_review_json = '{"overall_score": 90}'
            chapter_audio.script_review_version = "rev-1"
        db.add(chapter_audio)
        db.commit()
        return {
            "user_id": user.id,
            "project_id": project.id,
            "chapter_id": chapter.id,
            "audiobook_project_id": audiobook_project.id,
            "chapter_audio_id": chapter_audio.id,
        }
    finally:
        db.close()


def _auth_user(user_id: int) -> User:
    return User(
        id=user_id,
        username=f"auth_user_{user_id}",
        email=f"auth_user_{user_id}@example.com",
        password_hash="hash",
        is_active=True,
    )


def _publish_scene_context(session_factory, context, tmp_path, monkeypatch):
    """构造已发布场景批次：completed run + checkpoint + artifact 登记 + 发布。"""
    import app.services.audiobook.chapter_output_publish as publish_module
    from app.api.v1.audiobook_api import routes_scene_editor

    monkeypatch.setattr(publish_module, "SCENE_ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(routes_scene_editor, "SCENE_ARTIFACT_ROOT", tmp_path)

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project_id"],
            chapter_id=context["chapter_id"],
            chapter_audio_id=chapter_audio.id,
            run_type="full",
            status="completed",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-scenes",
        )
        db.add(run)
        db.flush()
        run.checkpoint_json = {
            "scene_checkpoints": {
                "scene_1": {
                    "scene_id": "scene_1",
                    "status": "passed",
                    "source_segment_keys": ["seg_a"],
                    "metadata": {"expected_duration_s": 3.5},
                },
                "scene_2": {
                    "scene_id": "scene_2",
                    "status": "passed",
                    "source_segment_keys": ["seg_b"],
                    "metadata": {"expected_duration_s": 4.0},
                },
            }
        }
        chapter_audio.desired_run_id = run.id
        db.flush()

        topo_hash = derive_scene_topology_hash(
            run.checkpoint_json,
            json.loads(chapter_audio.script_json or "[]"),
        ) or ""
        entries = []
        for index, scene_id in enumerate(["scene_1", "scene_2"]):
            file_path = tmp_path / f"scene_{scene_id}.mp3"
            file_path.write_bytes(f"audio-bytes-{scene_id}".encode("utf-8"))
            entries.append(
                {
                    "artifact_id": f"art_{scene_id}",
                    "scene_id": scene_id,
                    "source_kind": "seed",
                    "source_run_path": f"/tmp/run/{scene_id}.mp3",
                    "stored_rel_path": f"scene_{scene_id}.mp3",
                    "content_digest": hashlib.sha256(
                        file_path.read_bytes()
                    ).hexdigest(),
                    "segment_keys": ["seg_a"] if scene_id == "scene_1" else ["seg_b"],
                    "scene_topology_hash": topo_hash,
                    "duration_s": 3.5 + index * 0.5,
                }
            )
        upsert_staged_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project_id"],
            chapter_id=context["chapter_id"],
            audio_path="audiobooks/scene_editor/chapter_001.mp3",
            duration=7.5,
            file_size=4096,
        )
        register_scene_audio_artifacts(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project_id"],
            chapter_id=context["chapter_id"],
            scene_artifacts=entries,
        )
        db.flush()
        outcome = publish_seed_scene_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_all_seed",
            render_status_detail={"local_fallback_count": 0},
        )
        assert outcome["published"] is True
        db.commit()
        return {"run_id": run.id}
    finally:
        db.close()


# ——— GET editor-document ———


def test_editor_document_rejects_legacy_stems_batch():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory, engine_mode="legacy_stems")
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document"
    )
    assert response.status_code == 400
    assert "seed_scene" in response.json()["detail"]


def test_editor_document_returns_document_shape():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document"
    )
    assert response.status_code == 200
    document = response.json()
    assert document["engine_mode"] == "seed_scene"
    assert document["chapter_id"] == context["chapter_id"]
    assert document["audiobook_project_id"] == context["audiobook_project_id"]
    assert document["script_status"] == "reviewed"
    assert document["chapter_audio_url"] is None
    # 三条链 head 投影（§3.3 last_revisions）
    for edit_type in ("dialogue", "director_override", "voice_binding"):
        assert edit_type in document["last_revisions"]
        assert document["last_revisions"][edit_type] is None
    assert isinstance(document["revision_set_hash"], str)
    # 无 run 时场景列表为空但结构完整
    assert document["scenes"] == []
    assert isinstance(document["editable_overrides"], dict)
    assert isinstance(document["artifact_references"], dict)


def test_editor_document_rejects_foreign_chapter():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        "/chapters/9999/editor-document"
    )
    assert response.status_code == 404


# ——— PUT editor-document：三类编辑 ———


def test_dialogue_edit_persists_script_and_marks_pending():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory, with_review_evidence=True)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    changed_segments = [
        {**SEGMENTS[0], "text": "修改后的第一段台词"},
        {**SEGMENTS[1]},
    ]
    response = client.put(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=dialogue",
        json={
            "script_segments": changed_segments,
            "base_revision_hash": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["semantic_changed"] is True
    assert body["script_status"] == "pending"
    assert body["revision_heads"]["dialogue"] is not None
    assert isinstance(body["revision_set_hash"], str)

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        assert chapter_audio.script_status == "pending"
        # 验收 6/17：语义变化后旧审定结果清空（script_review_json/version），
        # 重新审定前不可直接导出
        assert chapter_audio.script_review_json is None
        assert chapter_audio.script_review_version is None
        persisted = json.loads(chapter_audio.script_json or "[]")
        assert persisted[0]["text"] == "修改后的第一段台词"
        # 台词编辑只更新 script_json，不删除 checkpoint 记录
        revision = db.query(SceneEditRevision).filter(
            SceneEditRevision.edit_type == "dialogue"
        ).first()
        assert revision is not None
        assert revision.affected_anchors is not None
    finally:
        db.close()


def test_dialogue_edit_same_semantics_keeps_script_status():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.put(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=dialogue",
        json={
            "script_segments": SEGMENTS,
            "base_revision_hash": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["semantic_changed"] is False
    assert body["script_status"] == "reviewed"


def test_dialogue_edit_stale_base_revision_conflicts_409():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    url = (
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=dialogue"
    )

    first = client.put(
        url,
        json={"script_segments": SEGMENTS, "base_revision_hash": None},
    )
    assert first.status_code == 200
    current_hash = first.json()["revision_heads"]["dialogue"]["revision_hash"]

    # 旧 base hash 重放 → 409 并发冲突
    stale = client.put(
        url,
        json={
            "script_segments": SEGMENTS,
            "base_revision_hash": "stale-hash-0000000000000000000000000000000000000000000000000000000000000000",
        },
    )
    assert stale.status_code == 409
    assert "文档已被他人修改" in stale.json()["detail"]["message"]
    assert stale.json()["detail"]["current_head_revision_hash"] == current_hash


def test_director_override_keeps_script_untouched():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    url = (
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=director_override"
    )

    response = client.put(
        url,
        json={
            "scene_id": "scene_1",
            "stable_anchors": {
                "source_segment_keys": ["seg_a"],
                "baseline_script_revision_hash": "base-script-hash",
                "baseline_scene_topology_hash": "topo-hash",
            },
            "overrides": [
                {"direction_type": "performance", "content": "语速放慢，语气阴冷"},
            ],
            "base_revision_hash": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["revision_heads"]["director_override"] is not None

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        # 导演覆盖不修改原文（§2.6）
        assert chapter_audio.script_json == json.dumps(SEGMENTS, ensure_ascii=False)
        revision = db.query(SceneEditRevision).filter(
            SceneEditRevision.edit_type == "director_override"
        ).first()
        payload = json.loads(revision.payload)
        assert payload["scene_id"] == "scene_1"
        assert payload["overrides"][0]["content"] == "语速放慢，语气阴冷"
    finally:
        db.close()

    # 文档投影：editable_overrides 出现该场景覆盖（§3.3）
    document = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document"
    ).json()
    assert "scene_1" in document["editable_overrides"]
    assert (
        document["editable_overrides"]["scene_1"]["overrides"][0]["direction_type"]
        == "performance"
    )


def test_director_override_requires_scene_id():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.put(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=director_override",
        json={"overrides": [], "base_revision_hash": None},
    )
    assert response.status_code == 400
    assert "scene_id" in response.json()["detail"]


def test_voice_binding_requires_tts_model():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.put(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=voice_binding",
        json={"characters": [], "base_revision_hash": None},
    )
    assert response.status_code == 400
    assert "tts_model" in response.json()["detail"]


def test_voice_binding_dual_writes_config_and_revision():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.put(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=voice_binding",
        json={
            "tts_model": "seed-audio-1.0-multilingual",
            "characters": [
                {
                    "character_name": "角色甲",
                    "voice_id": "voice_alpha",
                    "reference_source": "voice_pool",
                }
            ],
            "base_revision_hash": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["revision_heads"]["voice_binding"] is not None

    db = session_factory()
    try:
        # 双写：Project.audio_config 未来批次默认值（tts_model 会被服务端归一化）
        project = db.get(Project, context["project_id"])
        config = json.loads(project.audio_config or "{}")
        engines = config["engines"]["seed_scene"]
        tts_models = engines["tts_models"]
        assert len(tts_models) == 1
        model_key = next(iter(tts_models))
        assert (
            tts_models[model_key]["characters"][0]["voice_id"]
            == "voice_alpha"
        )
        # 双写：当前章节局部覆盖 revision
        revision = db.query(SceneEditRevision).filter(
            SceneEditRevision.edit_type == "voice_binding"
        ).first()
        assert revision is not None
    finally:
        db.close()


def test_invalid_edit_type_rejected():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.put(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document?edit_type=remix",
        json={"base_revision_hash": None},
    )
    assert response.status_code == 400
    assert "edit_type" in response.json()["detail"]


# ——— POST dialogue-review ———


def test_dialogue_review_verdict_state_machine():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory, script_status="pending")
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    url = (
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/dialogue-review"
    )

    reviewed = client.post(
        url,
        json={"verdict": "reviewed", "review_json": {"tone": "ok"}, "base_revision_set_hash": None},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["script_status"] == "reviewed"

    approved = client.post(
        url,
        json={"verdict": "approved", "review_json": {"tone": "ok"}, "base_revision_set_hash": None},
    )
    assert approved.status_code == 200
    assert approved.json()["script_status"] == "approved"

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        assert chapter_audio.script_status == "approved"
        assert chapter_audio.script_review_version is not None
    finally:
        db.close()


def test_dialogue_review_stale_set_hash_conflicts_409():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory, script_status="pending")
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    url = (
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/dialogue-review"
    )

    response = client.post(
        url,
        json={
            "verdict": "reviewed",
            "review_json": {"tone": "ok"},
            "base_revision_set_hash": "stale-set-hash-0000000000000000000000000000000000000000000000000000000000000000",
        },
    )
    assert response.status_code == 409
    assert "文档已被他人修改" in response.json()["detail"]["message"]


# ——— 场景音频 stream / audit-stream ———


def test_scene_stream_requires_credentials():
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)

    response = client.get("/api/v1/audiobook/scenes/art_scene_1/stream")
    assert response.status_code == 401


def test_scene_stream_serves_active_artifact_with_play_token(
    tmp_path, monkeypatch
):
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    _publish_scene_context(session_factory, context, tmp_path, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    document = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document"
    ).json()
    scene = next(item for item in document["scenes"] if item["scene_id"] == "scene_1")
    assert scene["status"] == "passed"
    assert "/scenes/art_scene_1/stream?play_token=" in scene["scene_audio_url"]
    assert scene["metadata"]["expected_duration_s"] == 3.5

    response = client.get(scene["scene_audio_url"])
    assert response.status_code == 200
    assert response.content == b"audio-bytes-scene_1"
    assert response.headers["content-type"] == "audio/mpeg"


def test_scene_stream_rejects_superseded_artifact(tmp_path, monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    _publish_scene_context(session_factory, context, tmp_path, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    # 先取有效 play_token（supersede 后 editor-document 不再暴露该场景 URL）
    document = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}"
        f"/chapters/{context['chapter_id']}/editor-document"
    ).json()
    scene_url = next(
        item["scene_audio_url"]
        for item in document["scenes"]
        if item["scene_id"] == "scene_1"
    )

    db = session_factory()
    try:
        artifact = db.query(SceneAudioArtifact).filter(
            SceneAudioArtifact.scene_id == "scene_1"
        ).first()
        artifact.status = "superseded"
        from datetime import datetime, timezone

        artifact.deleted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    response = client.get(scene_url)
    assert response.status_code == 404
    assert response.json()["detail"] == "场景音频不存在"


def test_audit_stream_exposes_artifact_headers(tmp_path, monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    _publish_scene_context(session_factory, context, tmp_path, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.get("/api/v1/audiobook/scenes/art_scene_1/audit-stream")
    assert response.status_code == 200
    assert response.content == b"audio-bytes-scene_1"
    assert response.headers["X-Artifact-Id"] == "art_scene_1"
    assert response.headers["X-Artifact-Status"] == "active"
    assert response.headers["X-Artifact-Scene-Id"] == "scene_1"
    assert response.headers["X-Artifact-Source-Kind"] == "seed"
    assert response.headers["X-Artifact-Topology-Hash"]


def test_audit_stream_owner_check_uses_project_id_not_batch_id(
    tmp_path, monkeypatch
):
    """回归：非管理员分支必须用 project.id（而非 audiobook_project.id）校验归属。"""
    client, session_factory, app = build_test_client()
    context = seed_editor_context(
        session_factory, prepend_dummy_batch=True
    )
    _publish_scene_context(session_factory, context, tmp_path, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    from app.services.audiobook import repository as repo_module

    captured: dict = {}

    def spy_get_user_project(db, user_id, project_id):
        captured["user_id"] = user_id
        captured["project_id"] = project_id
        return db.query(repo_module.Project).filter(
            repo_module.Project.id == project_id,
            repo_module.Project.user_id == user_id,
        ).first()

    monkeypatch.setattr(
        repo_module.ProjectRepository,
        "get_user_project",
        staticmethod(spy_get_user_project),
    )

    response = client.get("/api/v1/audiobook/scenes/art_scene_1/audit-stream")
    assert response.status_code == 200
    assert captured["project_id"] == context["project_id"]
    assert captured["project_id"] != context["audiobook_project_id"]


def test_audit_stream_forbidden_for_other_user(tmp_path, monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_editor_context(session_factory)
    _publish_scene_context(session_factory, context, tmp_path, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"] + 1000
    )

    response = client.get("/api/v1/audiobook/scenes/art_scene_1/audit-stream")
    assert response.status_code == 403
