"""§2.5 三维投影状态聚合与幂等完整发布协议测试。

覆盖：
- ``aggregate_scene_render_status``：Seed 四态聚合（rendered_all_seed /
  rendered_with_fallback / manual_review_required / failed）与 detail 字段；
- ``upsert_staged_chapter_output``：run 级输出登记（staged，每 run 一条）；
- ``publish_seed_scene_chapter_output``：§2.4 规则 4 幂等完整发布协议——
  发布谓词 / staged 恰一条 / CAS 镜像列 / 旧输出 supersede / 幂等短路 /
  不可发布状态拒绝（不破坏旧已发布产物）。
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.db.base import Base
from app.models.audiobook import (
    AudiobookProject,
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
    SceneAudioArtifact,
)
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook.chapter_output_publish import (
    publish_seed_scene_chapter_output,
    upsert_staged_chapter_output,
)
from app.services.audiobook.engine_pkg._scene_render_mixin import (
    aggregate_scene_render_status,
)
from app.services.audiobook.scene_edit_revision_service import (
    derive_scene_topology_hash,
)


# ---------- 聚合函数（纯函数，无 DB） ----------


def test_aggregate_all_passed_scenes_is_rendered_all_seed():
    status, detail = aggregate_scene_render_status(
        {
            "scene_checkpoints": {
                "scene_1": {"status": "passed", "source_segment_indices": [0]},
                "scene_2": {"status": "passed", "source_segment_indices": [1]},
            }
        }
    )
    assert status == "rendered_all_seed"
    assert detail["local_fallback_count"] == 0
    assert detail["manual_review_scene_ids"] == []


def test_aggregate_with_fallback_scenes_is_rendered_with_fallback():
    status, detail = aggregate_scene_render_status(
        {
            "scene_checkpoints": {
                "scene_1": {"status": "passed", "source_segment_indices": [0]},
                "scene_2": {"status": "legacy_stems", "fallback_reason": "tts_failed"},
                "scene_3": {"status": "legacy_stems", "fallback_reason": "asr_failed"},
            }
        }
    )
    assert status == "rendered_with_fallback"
    assert detail["local_fallback_count"] == 2
    assert detail["manual_review_scene_ids"] == []


def test_aggregate_manual_review_takes_precedence_over_fallback():
    status, detail = aggregate_scene_render_status(
        {
            "scene_checkpoints": {
                "scene_1": {"status": "passed"},
                "scene_2": {"status": "legacy_stems"},
                "scene_3": {"status": "manual_review"},
            }
        }
    )
    assert status == "manual_review_required"
    assert detail["local_fallback_count"] == 1
    assert detail["manual_review_scene_ids"] == ["scene_3"]


def test_aggregate_empty_checkpoints_is_failed():
    status, detail = aggregate_scene_render_status({})
    assert status == "failed"
    assert detail["local_fallback_count"] == 0
    assert detail["manual_review_scene_ids"] == []


def test_aggregate_keeps_terminal_policy_in_detail():
    _, detail = aggregate_scene_render_status(
        {"scene_checkpoints": {"scene_1": {"status": "passed"}}},
        terminal_policy="manual_review_on_repeated_failure",
    )
    assert detail["terminal_policy"] == "manual_review_on_repeated_failure"


def test_aggregate_tolerates_non_mapping_checkpoints():
    status, detail = aggregate_scene_render_status(
        {"scene_checkpoints": {"scene_1": None, "scene_2": "broken"}}
    )
    assert status == "rendered_all_seed"
    assert detail["local_fallback_count"] == 0


# ---------- 发布协议（SQLite in-memory） ----------


def build_session_factory():
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
        ],
    )
    # SQLite 不识别 postgresql_where 部分唯一索引（退化为全局唯一），
    # 会阻止同章节第二个 run 的输出登记；发布协议测试不依赖数据库级
    # 唯一约束（Postgres 语义由真实库保证），此处显式移除
    with engine.begin() as conn:
        conn.execute(
            text("DROP INDEX IF EXISTS uq_chapter_audio_output_published")
        )
    return session_factory


def seed_context(db):
    user = User(
        username="publish_protocol_user",
        email="publish_protocol@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    project = Project(
        user_id=user.id,
        display_no=1,
        title="Publish Protocol Project",
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
    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="processing",
        total_chapters=1,
        engine_mode="seed_scene",
    )
    db.add(audiobook_project)
    db.flush()
    chapter_audio = ChapterAudio(
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter.id,
        script_status="pending",
    )
    db.add(chapter_audio)
    db.flush()
    return {
        "user": user,
        "project": project,
        "chapter": chapter,
        "audiobook_project": audiobook_project,
        "chapter_audio": chapter_audio,
    }


def create_run(db, context, *, status="completed", input_signature="sig-1"):
    chapter_audio = context["chapter_audio"]
    run = ChapterAudioRun(
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        chapter_audio_id=chapter_audio.id,
        run_type="full",
        status=status,
        engine_mode_snapshot="seed_scene",
        input_signature=input_signature,
    )
    db.add(run)
    db.flush()
    return run


@pytest.fixture()
def publish_env():
    session_factory = build_session_factory()
    db = session_factory()
    context = seed_context(db)
    db.commit()
    try:
        yield db, context
    finally:
        db.close()


def test_publish_protocol_publishes_staged_output(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()

    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audiobooks/project_1/audiobook_1/chapter_001.mp3",
        duration=12.5,
        file_size=2048,
        subtitle_path="audiobooks/project_1/audiobook_1/chapter_001.srt",
        subtitle_format="srt",
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
    assert outcome["reason"] == "published"

    db.refresh(chapter_audio)
    assert chapter_audio.published_run_id == run.id
    assert chapter_audio.published_input_signature == "sig-1"
    assert chapter_audio.render_status == "rendered_all_seed"
    assert chapter_audio.render_status_detail == {"local_fallback_count": 0}
    assert chapter_audio.audio_path == "audiobooks/project_1/audiobook_1/chapter_001.mp3"
    assert chapter_audio.duration == 12.5
    assert chapter_audio.file_size == 2048
    assert chapter_audio.subtitle_format == "srt"
    assert chapter_audio.published_provenance == "published"

    output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run.id)
        .first()
    )
    assert output.status == "published"
    assert output.published_at is not None


def test_publish_protocol_supersedes_previous_output(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]

    run_old = create_run(db, context, input_signature="sig-old")
    chapter_audio.desired_run_id = run_old.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=run_old.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_old.mp3",
        duration=10.0,
        file_size=1000,
    )
    db.flush()
    assert publish_seed_scene_chapter_output(
        db,
        run_id=run_old.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_with_fallback",
        render_status_detail={"local_fallback_count": 1},
    )["published"] is True
    db.refresh(chapter_audio)

    run_new = create_run(db, context, input_signature="sig-new")
    chapter_audio.desired_run_id = run_new.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=run_new.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_new.mp3",
        duration=11.0,
        file_size=1200,
    )
    db.flush()
    assert publish_seed_scene_chapter_output(
        db,
        run_id=run_new.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
        render_status_detail={"local_fallback_count": 0},
    )["published"] is True

    db.refresh(chapter_audio)
    assert chapter_audio.published_run_id == run_new.id
    assert chapter_audio.audio_path == "audio_new.mp3"

    old_output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run_old.id)
        .first()
    )
    assert old_output.status == "superseded"
    new_output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run_new.id)
        .first()
    )
    assert new_output.status == "published"


def test_publish_protocol_idempotent_short_circuit(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(b"fake-audio-bytes")
    try:
        upsert_staged_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            audio_path=tmp_path,
            duration=5.0,
            file_size=16,
        )
        db.flush()
        first = publish_seed_scene_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_all_seed",
        )
        assert first["published"] is True
        db.commit()

        second = publish_seed_scene_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_all_seed",
        )
        assert second["published"] is True
        assert second["reason"] == "idempotent"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_publish_protocol_short_circuit_detects_corrupted_output(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()

    # 物理文件缺失 → 最低一致性检查不通过 → 不短路，按产物损坏处理
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="missing_audio_file.mp3",
        duration=5.0,
        file_size=16,
    )
    db.flush()
    first = publish_seed_scene_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )
    assert first["published"] is True
    db.commit()

    # 手动损坏镜像列（清空 duration），再次发布同 run 同签名 → 不短路
    db.query(ChapterAudio).filter(ChapterAudio.id == chapter_audio.id).update(
        {"duration": None},
        synchronize_session=False,
    )
    db.commit()
    second = publish_seed_scene_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )
    assert second["published"] is False
    assert second["reason"] == "published_output_corrupted"


def test_publish_protocol_rejects_not_publishable_status(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_manual.mp3",
        duration=5.0,
        file_size=100,
    )
    db.flush()

    outcome = publish_seed_scene_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="manual_review_required",
        render_status_detail={"manual_review_scene_ids": ["scene_1"]},
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "not_publishable:manual_review_required"

    db.refresh(chapter_audio)
    assert chapter_audio.published_run_id is None
    assert chapter_audio.render_status is None
    assert chapter_audio.audio_path is None


def test_publish_protocol_keeps_old_published_on_desired_changed(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]

    run_old = create_run(db, context, input_signature="sig-old")
    chapter_audio.desired_run_id = run_old.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=run_old.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_old.mp3",
        duration=10.0,
        file_size=1000,
    )
    db.flush()
    assert publish_seed_scene_chapter_output(
        db,
        run_id=run_old.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )["published"] is True
    db.commit()
    db.refresh(chapter_audio)

    # 新 run 完成但 desired_run_id 仍指向旧 run（模拟 desired 已被更新 run 接管）
    run_stale = create_run(db, context, input_signature="sig-stale")
    upsert_staged_chapter_output(
        db,
        run_id=run_stale.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_stale.mp3",
        duration=8.0,
        file_size=800,
    )
    db.flush()

    outcome = publish_seed_scene_chapter_output(
        db,
        run_id=run_stale.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "desired_run_changed"

    db.refresh(chapter_audio)
    assert chapter_audio.published_run_id == run_old.id
    assert chapter_audio.audio_path == "audio_old.mp3"
    stale_output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run_stale.id)
        .first()
    )
    assert stale_output.status == "staged"


def test_publish_protocol_requires_completed_run(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context, status="running")
    chapter_audio.desired_run_id = run.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio.mp3",
        duration=5.0,
        file_size=100,
    )
    db.flush()

    outcome = publish_seed_scene_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "run_not_completed:running"


def test_publish_protocol_requires_single_staged_output(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()

    outcome = publish_seed_scene_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "staged_output_count:0"


def test_upsert_staged_output_is_idempotent_per_run(publish_env):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()

    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_v1.mp3",
        duration=5.0,
        file_size=100,
    )
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio_v2.mp3",
        duration=6.0,
        file_size=120,
    )
    db.flush()

    outputs = db.query(ChapterAudioOutput).filter(
        ChapterAudioOutput.run_id == run.id
    ).all()
    assert len(outputs) == 1
    assert outputs[0].audio_path == "audio_v2.mp3"
    assert outputs[0].status == "staged"


# ---------- §3.4 场景音频 artifact 登记与发布状态机 ----------


import app.services.audiobook.chapter_output_publish as publish_module
from app.services.audiobook.chapter_output_publish import (
    register_scene_audio_artifacts,
)


def _make_scene_entries(scene_ids, *, source_kinds=None):
    entries = []
    for index, scene_id in enumerate(scene_ids):
        source_kind = (source_kinds or {}).get(scene_id, "seed")
        entries.append(
            {
                "artifact_id": f"art_test_{scene_id}",
                "scene_id": scene_id,
                "source_kind": source_kind,
                "source_run_path": f"/tmp/run/{scene_id}.mp3",
                "stored_rel_path": f"art_test_{scene_id}.mp3",
                "content_digest": f"digest-{index}",
                "segment_keys": [],
                "scene_topology_hash": "topo-hash-1",
                "duration_s": 3.5,
            }
        )
    return entries


def _write_artifact_files(tmp_path, scene_ids):
    for scene_id in scene_ids:
        path = tmp_path / f"art_test_{scene_id}.mp3"
        path.write_bytes(b"audio-bytes-" + scene_id.encode("utf-8"))


def _setup_run_with_checkpoint(db, context, *, scene_ids, checkpoint_status="passed"):
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context, input_signature="sig-scenes")
    chapter_audio.desired_run_id = run.id
    run.checkpoint_json = {
        "scene_checkpoints": {
            scene_id: {
                "scene_id": scene_id,
                "status": checkpoint_status,
                "source_segment_indices": [index],
            }
            for index, scene_id in enumerate(scene_ids)
        }
    }
    db.flush()
    return run


def test_register_scene_audio_artifacts_staged_idempotent(publish_env):
    db, context = publish_env
    run = create_run(db, context)
    db.flush()
    entries = _make_scene_entries(["scene_1", "scene_2"])

    changed = register_scene_audio_artifacts(
        db,
        run_id=run.id,
        chapter_audio_id=context["chapter_audio"].id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        scene_artifacts=entries,
    )
    assert changed == 2
    rows = (
        db.query(SceneAudioArtifact)
        .filter(SceneAudioArtifact.run_id == run.id)
        .all()
    )
    assert {row.scene_id for row in rows} == {"scene_1", "scene_2"}
    assert all(row.status == "staged" for row in rows)
    assert all(row.chapter_audio_id == context["chapter_audio"].id for row in rows)
    assert all(row.scene_topology_hash == "topo-hash-1" for row in rows)

    # 同 run 同场景重试（幂等键重放）：刷新元数据而非新增
    entries[0]["content_digest"] = "digest-updated"
    changed = register_scene_audio_artifacts(
        db,
        run_id=run.id,
        chapter_audio_id=context["chapter_audio"].id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        scene_artifacts=entries,
    )
    assert changed == 2
    rows = (
        db.query(SceneAudioArtifact)
        .filter(SceneAudioArtifact.run_id == run.id)
        .all()
    )
    assert len(rows) == 2
    scene_1 = next(row for row in rows if row.scene_id == "scene_1")
    assert scene_1.content_digest == "digest-updated"


def test_publish_activates_scene_artifacts_and_supersedes_old_run(publish_env, tmp_path):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    scene_ids = ["scene_1", "scene_2"]
    _write_artifact_files(tmp_path, scene_ids)
    # 校验 content_digest 与实际文件一致
    entries = []
    for index, scene_id in enumerate(scene_ids):
        file_path = tmp_path / f"art_test_{scene_id}.mp3"
        entries.append(
            {
                "artifact_id": f"art_test_{scene_id}",
                "scene_id": scene_id,
                "source_kind": "seed",
                "source_run_path": f"/tmp/run/{scene_id}.mp3",
                "stored_rel_path": f"art_test_{scene_id}.mp3",
                "content_digest": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                "segment_keys": [],
                "scene_topology_hash": "topo-hash-1",
                "duration_s": 3.5,
            }
        )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(publish_module, "SCENE_ARTIFACT_ROOT", tmp_path)
    try:
        run_old = _setup_run_with_checkpoint(db, context, scene_ids=scene_ids)
        # scene_topology_hash 必须与发布期推导一致（退化合同：无 segment_key 的 scene_id 集合）
        expected_topo = derive_scene_topology_hash(run_old.checkpoint_json, []) or ""
        # 校验 content_digest 与实际文件一致
        entries = []
        for index, scene_id in enumerate(scene_ids):
            file_path = tmp_path / f"art_test_{scene_id}.mp3"
            entries.append(
                {
                    "artifact_id": f"art_test_{scene_id}",
                    "scene_id": scene_id,
                    "source_kind": "seed",
                    "source_run_path": f"/tmp/run/{scene_id}.mp3",
                    "stored_rel_path": f"art_test_{scene_id}.mp3",
                    "content_digest": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                    "segment_keys": [],
                    "scene_topology_hash": expected_topo,
                    "duration_s": 3.5,
                }
            )
        upsert_staged_chapter_output(
            db,
            run_id=run_old.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            audio_path="audio_old.mp3",
            duration=10.0,
            file_size=1000,
        )
        register_scene_audio_artifacts(
            db,
            run_id=run_old.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            scene_artifacts=entries,
        )
        db.flush()
        assert publish_seed_scene_chapter_output(
            db,
            run_id=run_old.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_all_seed",
        )["published"] is True
        db.commit()

        # 新 run 发布 → 旧 run active artifact 置 superseded + deleted_at
        run_new = _setup_run_with_checkpoint(db, context, scene_ids=scene_ids)
        upsert_staged_chapter_output(
            db,
            run_id=run_new.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            audio_path="audio_new.mp3",
            duration=11.0,
            file_size=1200,
        )
        register_scene_audio_artifacts(
            db,
            run_id=run_new.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            scene_artifacts=entries,
        )
        db.flush()
        assert publish_seed_scene_chapter_output(
            db,
            run_id=run_new.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_all_seed",
        )["published"] is True

        old_artifacts = (
            db.query(SceneAudioArtifact)
            .filter(SceneAudioArtifact.run_id == run_old.id)
            .all()
        )
        assert all(row.status == "superseded" for row in old_artifacts)
        assert all(row.deleted_at is not None for row in old_artifacts)
        new_artifacts = (
            db.query(SceneAudioArtifact)
            .filter(SceneAudioArtifact.run_id == run_new.id)
            .all()
        )
        assert all(row.status == "active" for row in new_artifacts)
        assert all(row.deleted_at is None for row in new_artifacts)
    finally:
        monkeypatch.undo()


def test_publish_rejects_incomplete_scene_artifacts(publish_env, tmp_path):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = _setup_run_with_checkpoint(db, context, scene_ids=["scene_1", "scene_2"])
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio.mp3",
        duration=10.0,
        file_size=1000,
    )
    # 只登记 scene_1 → 键集合不匹配 → 不发布
    register_scene_audio_artifacts(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        scene_artifacts=_make_scene_entries(["scene_1"]),
    )
    db.flush()
    outcome = publish_seed_scene_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="rendered_all_seed",
    )
    assert outcome["published"] is False
    assert outcome["reason"].startswith("scene_artifacts_incomplete:")


def test_publish_rejects_missing_artifact_file(publish_env, tmp_path):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = _setup_run_with_checkpoint(db, context, scene_ids=["scene_1"])
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio.mp3",
        duration=10.0,
        file_size=1000,
    )
    # 登记但物理文件不存在（stored_rel_path 指向 tmp_path 下未创建的文件）
    expected_topo = derive_scene_topology_hash(run.checkpoint_json, []) or ""
    entries = [
        {
            "artifact_id": "art_test_missing",
            "scene_id": "scene_1",
            "source_kind": "seed",
            "source_run_path": "/tmp/run/scene_1.mp3",
            "stored_rel_path": "art_test_missing.mp3",
            "content_digest": "deadbeef",
            "segment_keys": [],
            "scene_topology_hash": expected_topo,
            "duration_s": 3.5,
        }
    ]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(publish_module, "SCENE_ARTIFACT_ROOT", tmp_path)
    try:
        register_scene_audio_artifacts(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            scene_artifacts=entries,
        )
        db.flush()
        outcome = publish_seed_scene_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_all_seed",
        )
        assert outcome["published"] is False
        assert "artifact_file_missing" in outcome["reason"]
    finally:
        monkeypatch.undo()


def test_publish_rejects_fallback_contract_mismatch(publish_env, tmp_path):
    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = _setup_run_with_checkpoint(db, context, scene_ids=["scene_1"])
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audio.mp3",
        duration=10.0,
        file_size=1000,
    )
    file_path = tmp_path / "art_test_fb.mp3"
    file_path.write_bytes(b"fallback-bytes")
    expected_topo = derive_scene_topology_hash(run.checkpoint_json, []) or ""
    entries = [
        {
            "artifact_id": "art_test_fb",
            "scene_id": "scene_1",
            "source_kind": "legacy_fallback",
            "source_run_path": "/tmp/run/scene_1.mp3",
            "stored_rel_path": "art_test_fb.mp3",
            "content_digest": hashlib.sha256(file_path.read_bytes()).hexdigest(),
            "segment_keys": [],
            "scene_topology_hash": expected_topo,
            "duration_s": 3.5,
        }
    ]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(publish_module, "SCENE_ARTIFACT_ROOT", tmp_path)
    try:
        register_scene_audio_artifacts(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            scene_artifacts=entries,
        )
        db.flush()
        # checkpoint 场景状态为 passed（非 legacy_stems）→ fallback 合同失配
        outcome = publish_seed_scene_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            render_status="rendered_with_fallback",
        )
        assert outcome["published"] is False
        assert "fallback_contract_mismatch" in outcome["reason"]
    finally:
        monkeypatch.undo()


# ---------- legacy 引擎发布协议（R9/P0-2：full/audio_from_scripts/chapter_remix） ----------


def test_legacy_publish_rejects_non_completed_render_status(publish_env):
    """发布谓词：legacy 仅 result_render_status='completed' 可发布（R9/P0-2）。"""
    from app.services.audiobook.chapter_output_publish import publish_legacy_chapter_output

    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context)
    chapter_audio.desired_run_id = run.id
    db.flush()

    outcome = publish_legacy_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="failed",
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "not_publishable:failed"


def test_legacy_publish_requires_completed_run(publish_env):
    """run 未终态（非 completed）拒绝发布。"""
    from app.services.audiobook.chapter_output_publish import publish_legacy_chapter_output

    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context, status="running")
    chapter_audio.desired_run_id = run.id
    db.flush()

    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audiobooks/project_1/audiobook_1/run_5/chapter_001.mp3",
        duration=12.5,
        file_size=2048,
    )
    db.flush()

    outcome = publish_legacy_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "run_not_completed:running"


def test_legacy_publish_protocol_publishes_staged_output(publish_env):
    """legacy 正常发布：CAS 镜像列 + supersede 旧输出 + staged → published。"""
    from app.services.audiobook.chapter_output_publish import publish_legacy_chapter_output

    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context, input_signature="legacy-sig-1")
    chapter_audio.desired_run_id = run.id
    db.flush()

    output_path = "audiobooks/project_1/audiobook_1/run_5/chapter_001.mp3"
    upsert_staged_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path=output_path,
        duration=12.5,
        file_size=2048,
        subtitle_path="audiobooks/project_1/audiobook_1/run_5/chapter_001.srt",
        subtitle_format="srt",
    )
    db.flush()

    outcome = publish_legacy_chapter_output(
        db,
        run_id=run.id,
        chapter_audio_id=chapter_audio.id,
        render_status="completed",
    )
    assert outcome["published"] is True
    assert outcome["reason"] == "published"

    db.refresh(chapter_audio)
    assert chapter_audio.published_run_id == run.id
    assert chapter_audio.published_input_signature == "legacy-sig-1"
    assert chapter_audio.audio_path == output_path
    assert chapter_audio.render_status == "completed"
    assert chapter_audio.published_provenance == "published"

    output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run.id)
        .first()
    )
    assert output.status == "published"
    assert output.published_at is not None


def test_legacy_publish_idempotent_short_circuit(publish_env):
    """重复发布命中幂等短路（R8：不二次 supersede、不报错）。"""
    from app.services.audiobook.chapter_output_publish import publish_legacy_chapter_output

    db, context = publish_env
    chapter_audio = context["chapter_audio"]
    run = create_run(db, context, input_signature="legacy-sig-2")
    chapter_audio.desired_run_id = run.id
    db.flush()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(b"fake-audio-bytes")
    try:
        upsert_staged_chapter_output(
            db,
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            audio_path=tmp_path,
            duration=10.0,
            file_size=16,
        )
        db.flush()
        first = publish_legacy_chapter_output(
            db, run_id=run.id, chapter_audio_id=chapter_audio.id,
        )
        assert first["published"] is True
        db.commit()
        second = publish_legacy_chapter_output(
            db, run_id=run.id, chapter_audio_id=chapter_audio.id,
        )
        assert second["published"] is True
        assert second["reason"] == "idempotent"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_legacy_publish_supersedes_previous_output(publish_env):
    """新 run 发布时旧已发布输出 supersede（显式排除本 run）。"""
    from app.services.audiobook.chapter_output_publish import publish_legacy_chapter_output

    db, context = publish_env
    chapter_audio = context["chapter_audio"]

    # 旧 run 发布
    old_run = create_run(db, context, input_signature="legacy-old")
    chapter_audio.desired_run_id = old_run.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=old_run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audiobooks/project_1/audiobook_1/run_old/chapter_001.mp3",
        duration=9.0,
        file_size=900,
    )
    db.flush()
    assert publish_legacy_chapter_output(
        db, run_id=old_run.id, chapter_audio_id=chapter_audio.id,
    )["published"] is True

    # 新 run 发布 → 旧输出 superseded
    new_run = create_run(db, context, input_signature="legacy-new")
    chapter_audio.desired_run_id = new_run.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=new_run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audiobooks/project_1/audiobook_1/run_new/chapter_001.mp3",
        duration=11.0,
        file_size=1100,
    )
    db.flush()
    outcome = publish_legacy_chapter_output(
        db, run_id=new_run.id, chapter_audio_id=chapter_audio.id,
    )
    assert outcome["published"] is True

    old_output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == old_run.id)
        .first()
    )
    assert old_output.status == "superseded"
    new_output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == new_run.id)
        .first()
    )
    assert new_output.status == "published"


def test_legacy_publish_cas_miss_keeps_old_output(publish_env):
    """desired_run_id 未被接管 → CAS 不命中，旧已发布产物不变（R11/P1-4）。"""
    from app.services.audiobook.chapter_output_publish import publish_legacy_chapter_output

    db, context = publish_env
    chapter_audio = context["chapter_audio"]

    old_run = create_run(db, context, input_signature="legacy-keep")
    chapter_audio.desired_run_id = old_run.id
    db.flush()
    upsert_staged_chapter_output(
        db,
        run_id=old_run.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audiobooks/project_1/audiobook_1/run_keep/chapter_001.mp3",
        duration=8.0,
        file_size=800,
    )
    db.flush()
    assert publish_legacy_chapter_output(
        db, run_id=old_run.id, chapter_audio_id=chapter_audio.id,
    )["published"] is True
    db.commit()
    db.refresh(chapter_audio)

    # 新 run 完成但 desired_run_id 仍指向旧 run（迟到任务）：发布 CAS 不命中
    run_stale = create_run(db, context, input_signature="legacy-owner")
    upsert_staged_chapter_output(
        db,
        run_id=run_stale.id,
        chapter_audio_id=chapter_audio.id,
        audiobook_project_id=context["audiobook_project"].id,
        chapter_id=context["chapter"].id,
        audio_path="audiobooks/project_1/audiobook_1/run_keep_v2/chapter_001.mp3",
        duration=7.0,
        file_size=700,
    )
    db.flush()

    outcome = publish_legacy_chapter_output(
        db, run_id=run_stale.id, chapter_audio_id=chapter_audio.id,
    )
    assert outcome["published"] is False
    assert outcome["reason"] == "desired_run_changed"

    db.refresh(chapter_audio)
    assert chapter_audio.published_run_id == old_run.id
    assert chapter_audio.published_input_signature == "legacy-keep"
    # 旧已发布产物未被覆盖
    assert chapter_audio.audio_path.endswith("run_keep/chapter_001.mp3")
    # 迟到 run 的输出保持 staged（不发布）
    stale_output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run_stale.id)
        .first()
    )
    assert stale_output.status == "staged"
