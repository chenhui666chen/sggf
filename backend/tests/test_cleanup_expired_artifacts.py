"""GUIDE §8.3：artifact/output 保留期清理与场景 artifact 配额（验收 18/20/21）。

覆盖（§7 测试计划"run 级输出清理（R8）"与"输出墓碑（R9/P2-3）"）：
- SceneAudioArtifact：superseded 超 30 天 → 删物理文件；staged 且 run 终态
  超 30 天 → 置 superseded + deleted_at 并删物理文件；staged 且 run 未终态、
  active 一律不清理；
- ChapterAudioOutput：superseded 超 30 天 → 删文件并置墓碑
  （file_status='purged' + purged_at）；staged 且 run 终态超期 → 同上；
  published 不清理；被 ChapterAudio.published_run_id 镜像列引用的 run 输出
  禁止清理；staged 且 run 未终态不清理；
- 共享物理路径防误删：候选行与仍登记行引用同一路径时该路径不删除；
- dry-run 不产生任何写；--apply 才删除与写墓碑；
- register_scene_audio_artifacts 配额：active 计数达上限拒绝新登记。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
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

import scripts.cleanup_expired_artifacts as cleanup_mod
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
    register_scene_audio_artifacts,
)
from app.utils.datetime_utils import utc_now

OLD = utc_now() - timedelta(days=40)
FRESH = utc_now()


@pytest.fixture
def session_factory():
    """每个测试独立内存库（sqlite StaticPool）。"""
    return build_session()


def build_session() -> sessionmaker:
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
    # 会阻止同 chapter_audio 多个输出登记；本测试需保留多行输出。
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("DROP INDEX IF EXISTS uq_chapter_audio_output_published"))
    return session_factory


def seed_cleanup_data(session_factory, tmp_path: Path) -> dict:
    """构造 §8.3 清理判定所需的全部行，返回候选行 id 与关键文件路径。"""
    db = session_factory()
    try:
        terminal_run = ChapterAudioRun(
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=1,
            run_type="full",
            status="completed",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-terminal",
        )
        db.add(terminal_run)
        db.flush()
        running_run = ChapterAudioRun(
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=1,
            run_type="full",
            status="running",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-running",
        )
        db.add(running_run)
        db.flush()
        protected_run = ChapterAudioRun(
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=1,
            run_type="full",
            status="completed",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-protected",
        )
        db.add(protected_run)
        db.flush()
        # ChapterAudioOutput.run_id 唯一：候选输出行各占独立 run
        terminal_run_b = ChapterAudioRun(
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=1,
            run_type="full",
            status="completed",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-terminal-b",
        )
        db.add(terminal_run_b)
        db.flush()
        terminal_run_c = ChapterAudioRun(
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=1,
            run_type="full",
            status="completed",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-terminal-c",
        )
        db.add(terminal_run_c)
        db.flush()
        # staged + 被 published_run_id 镜像列引用 → 受保护（不清理）
        terminal_run_d = ChapterAudioRun(
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=1,
            run_type="full",
            status="completed",
            engine_mode_snapshot="seed_scene",
            input_signature="sig-terminal-d",
        )
        db.add(terminal_run_d)
        db.flush()
        chapter_audio = ChapterAudio(
            audiobook_project_id=1,
            chapter_id=1,
            script_status="approved",
            script_json=json.dumps([], ensure_ascii=False),
            published_run_id=terminal_run_d.id,
        )
        db.add(chapter_audio)
        db.flush()

        artifact_files = {}
        artifact_rows = {}
        # 1) superseded 超期 → 候选
        artifact_rows["superseded_old"] = SceneAudioArtifact(
            artifact_id="art_superseded_old",
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=chapter_audio.id,
            run_id=terminal_run.id,
            scene_id="scene_superseded_old",
            stored_rel_path="superseded_old.mp3",
            status="superseded",
            deleted_at=OLD,
        )
        # 2) staged + run 终态 + 超期 → 候选
        artifact_rows["staged_terminal_old"] = SceneAudioArtifact(
            artifact_id="art_staged_terminal_old",
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=chapter_audio.id,
            run_id=terminal_run.id,
            scene_id="scene_staged_terminal_old",
            stored_rel_path="staged_terminal_old.mp3",
            status="staged",
            created_at=OLD,
        )
        # 3) staged + run 未终态 → 不候选
        artifact_rows["staged_running"] = SceneAudioArtifact(
            artifact_id="art_staged_running",
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=chapter_audio.id,
            run_id=running_run.id,
            scene_id="scene_staged_running",
            stored_rel_path="staged_running.mp3",
            status="staged",
            created_at=OLD,
        )
        # 4) active → 不候选
        artifact_rows["active"] = SceneAudioArtifact(
            artifact_id="art_active",
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=chapter_audio.id,
            run_id=terminal_run.id,
            scene_id="scene_active",
            stored_rel_path="active.mp3",
            status="active",
        )
        # 5) superseded 超期但与 active 共享路径 → 候选行但路径被保护
        artifact_rows["superseded_shared"] = SceneAudioArtifact(
            artifact_id="art_superseded_shared",
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=chapter_audio.id,
            run_id=terminal_run.id,
            scene_id="scene_superseded_shared",
            stored_rel_path="shared.mp3",
            status="superseded",
            deleted_at=OLD,
        )
        artifact_rows["active_shared"] = SceneAudioArtifact(
            artifact_id="art_active_shared",
            audiobook_project_id=1,
            chapter_id=1,
            chapter_audio_id=chapter_audio.id,
            run_id=terminal_run.id,
            scene_id="scene_active_shared",
            stored_rel_path="shared.mp3",
            status="active",
        )
        for name, row in artifact_rows.items():
            # NOT NULL 列补齐（与 register_scene_audio_artifacts 写入合同一致）
            row.scene_topology_hash = "topo-hash"
            row.content_digest = "digest"
            db.add(row)
        db.flush()
        for name in artifact_rows:
            rel = artifact_rows[name].stored_rel_path
            path = tmp_path / rel
            path.write_bytes(f"audio-{name}".encode("utf-8"))
            artifact_files[name] = path

        output_rows = {}
        output_files = {}
        # 6) output superseded 超期 → 候选（audio + subtitle）
        output_rows["superseded_old"] = ChapterAudioOutput(
            run_id=terminal_run_b.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=1,
            chapter_id=1,
            status="superseded",
            audio_path=str(tmp_path / "out_superseded_old.mp3"),
            subtitle_path=str(tmp_path / "out_superseded_old.srt"),
            created_at=OLD,
        )
        # 7) output staged + 终态 + 超期 → 候选
        output_rows["staged_terminal_old"] = ChapterAudioOutput(
            run_id=terminal_run_c.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=1,
            chapter_id=1,
            status="staged",
            audio_path=str(tmp_path / "out_staged_terminal_old.mp3"),
            created_at=OLD,
        )
        # 8) output published → 不清理
        output_rows["published"] = ChapterAudioOutput(
            run_id=protected_run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=1,
            chapter_id=1,
            status="published",
            file_status="present",
            audio_path=str(tmp_path / "out_published.mp3"),
            duration=3.0,
            file_size=100,
            created_at=OLD,
        )
        # 9) output staged + protected run（published_run_id 镜像列引用）→ 不清理
        output_rows["staged_protected"] = ChapterAudioOutput(
            run_id=terminal_run_d.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=1,
            chapter_id=1,
            status="staged",
            audio_path=str(tmp_path / "out_staged_protected.mp3"),
            created_at=OLD,
        )
        # 10) output staged + run 未终态 → 不清理
        output_rows["staged_running"] = ChapterAudioOutput(
            run_id=running_run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=1,
            chapter_id=1,
            status="staged",
            audio_path=str(tmp_path / "out_staged_running.mp3"),
            created_at=OLD,
        )
        for name, row in output_rows.items():
            db.add(row)
        db.flush()
        for name in output_rows:
            paths = []
            if output_rows[name].audio_path:
                paths.append(output_rows[name].audio_path)
            if output_rows[name].subtitle_path:
                paths.append(output_rows[name].subtitle_path)
            for path_value in paths:
                path = Path(path_value)
                path.write_bytes(f"output-{name}".encode("utf-8"))
                output_files.setdefault(name, []).append(path)

        db.commit()
        return {
            "artifact_files": artifact_files,
            "output_files": output_files,
            "artifact_ids": {
                name: row.id for name, row in artifact_rows.items()
            },
            "output_ids": {name: row.id for name, row in output_rows.items()},
            "terminal_run_id": terminal_run.id,
            "running_run_id": running_run.id,
            "protected_run_id": protected_run.id,
            "chapter_audio_id": chapter_audio.id,
        }
    finally:
        db.close()


def _make_cleanup_env(session_factory, tmp_path, monkeypatch):
    session = session_factory()
    monkeypatch.setattr(cleanup_mod, "SessionLocal", lambda: session)
    monkeypatch.setattr(cleanup_mod, "SCENE_ARTIFACT_ROOT", tmp_path)
    return session


def test_dry_run_reports_candidates_without_writes(session_factory, tmp_path, monkeypatch):
    _make_cleanup_env(session_factory, tmp_path, monkeypatch)
    context = seed_cleanup_data(session_factory, tmp_path)

    result = cleanup_mod.cleanup_expired_artifacts(apply=False)

    # 候选：3 artifact 行（superseded_old + staged_terminal_old + superseded_shared，
    # 其中 shared 路径被 active 登记保护不出现在删除列表）+ 2 output 行
    assert result["artifact_rows"] == 3
    assert result["output_rows"] == 2
    # dry-run 不产生物理删除
    for name, path in context["artifact_files"].items():
        assert path.exists(), f"{name} 不应被 dry-run 删除"
    session = session_factory()
    try:
        assert (
            session.get(SceneAudioArtifact, context["artifact_ids"]["superseded_old"]).status
            == "superseded"
        )
    finally:
        session.close()


def test_apply_purges_files_and_writes_tombstones(session_factory, tmp_path, monkeypatch):
    session = _make_cleanup_env(session_factory, tmp_path, monkeypatch)
    context = seed_cleanup_data(session_factory, tmp_path)

    result = cleanup_mod.cleanup_expired_artifacts(apply=True)

    assert result["deleted_files"] == 5  # 2 artifact 文件 + 3 output 文件（候选 2 行）
    # artifact 候选文件删除
    for name in ("superseded_old", "staged_terminal_old"):
        assert not context["artifact_files"][name].exists()
    # 不候选的保留
    for name in ("staged_running", "active", "active_shared"):
        assert context["artifact_files"][name].exists(), f"{name} 不应被清理"
    # 共享路径被保护：active_shared 仍登记 → shared.mp3 保留
    assert context["artifact_files"]["superseded_shared"].exists()
    # output 候选文件删除
    for name in ("superseded_old", "staged_terminal_old"):
        for path in context["output_files"][name]:
            assert not path.exists(), f"{name} 输出应被清理"
    for name in ("published", "staged_protected", "staged_running"):
        for path in context["output_files"][name]:
            assert path.exists(), f"{name} 输出不应被清理"

    # 墓碑断言
    artifact = session.get(SceneAudioArtifact, context["artifact_ids"]["staged_terminal_old"])
    assert artifact.status == "superseded"
    assert artifact.deleted_at is not None
    for name in ("staged_running", "active", "active_shared"):
        row = session.get(SceneAudioArtifact, context["artifact_ids"][name])
        assert row.status != "superseded" or name == "active_shared" is False
    output = session.get(ChapterAudioOutput, context["output_ids"]["superseded_old"])
    assert output.file_status == "purged"
    assert output.purged_at is not None
    output2 = session.get(ChapterAudioOutput, context["output_ids"]["staged_terminal_old"])
    assert output2.file_status == "purged"
    assert output2.purged_at is not None
    for name in ("published", "staged_protected", "staged_running"):
        row = session.get(ChapterAudioOutput, context["output_ids"][name])
        assert row.file_status != "purged", f"{name} 不应被置墓碑"


# ——— register_scene_audio_artifacts 配额 ———


def test_artifact_registration_respects_quota(session_factory, monkeypatch):
    import app.services.audiobook.chapter_output_publish as publish_mod

    monkeypatch.setattr(publish_mod, "SCENE_ARTIFACT_QUOTA_PER_PROJECT", 2)
    session = session_factory()
    try:
        for index in range(2):
            changed = register_scene_audio_artifacts(
                session,
                run_id=10 + index,
                chapter_audio_id=1,
                audiobook_project_id=1,
                chapter_id=1,
                scene_artifacts=[
                    {
                        "scene_id": f"scene_q{index}",
                        "segment_keys": ["seg_a"],
                        "stored_rel_path": f"quota_{index}.mp3",
                        "content_digest": "d",
                    }
                ],
            )
            assert changed == 1
        # 达到上限后拒绝新登记
        rejected = register_scene_audio_artifacts(
            session,
            run_id=99,
            chapter_audio_id=1,
            audiobook_project_id=1,
            chapter_id=1,
            scene_artifacts=[
                {
                    "scene_id": "scene_overflow",
                    "segment_keys": ["seg_b"],
                    "stored_rel_path": "overflow.mp3",
                }
            ],
        )
        assert rejected == 0
        count = (
            session.query(SceneAudioArtifact)
            .filter(
                SceneAudioArtifact.audiobook_project_id == 1,
                SceneAudioArtifact.deleted_at.is_(None),
            )
            .count()
        )
        assert count == 2
    finally:
        session.close()
