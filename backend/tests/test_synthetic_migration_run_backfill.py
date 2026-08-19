"""synthetic migration run 回填合同测试（GUIDE R9/P1-1，R10/P1-1，验收 38/50）。

覆盖：
- 有匹配 completed run 的历史产物 → 回填 published_run_id + published 输出 +
  legacy_unverified provenance（可导出、不作为 CAS 基线）
- 无匹配 run → 创建 migration_placeholder synthetic run（不可恢复/结算/重试/派发）
- 幂等：重复执行不重复创建 synthetic run/输出登记
"""

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
)
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook.synthetic_migration_run_backfill import (  # noqa: E402
    run_synthetic_migration_backfill,
)

_TABLES = [
    User.__table__,
    Project.__table__,
    Chapter.__table__,
    AudiobookProject.__table__,
    ChapterAudio.__table__,
    ChapterAudioRun.__table__,
    ChapterAudioOutput.__table__,
]


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng, tables=_TABLES)
    yield eng
    eng.dispose()


def _seed_scope(db, tag: str):
    user = User(username=f"user_{tag}", email=f"{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"proj_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()
    batch = AudiobookProject(project_id=project.id)
    db.add(batch)
    db.flush()
    audio = ChapterAudio(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        audio_path=f"audiobooks/project_{project.id}/chapter_001.mp3",
        duration=10.0,
        file_size=1000,
    )
    db.add(audio)
    db.flush()
    return user, project, chapter, batch, audio


def test_backfill_with_owner_run(engine):
    """有匹配 completed run → 回填归属 + published 输出 + legacy_unverified。"""
    db = sessionmaker(bind=engine)()
    _, project, chapter, batch, audio = _seed_scope(db, "owner")
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        chapter_audio_id=audio.id,
        run_type="full",
        status="completed",
        dispatch_status="dispatched",
    )
    db.add(run)
    db.flush()
    run_id = run.id
    audio_id = audio.id
    db.commit()
    db.close()

    report = run_synthetic_migration_backfill(engine)

    assert report["scanned_chapters"] == 1
    assert report["owner_run_backfilled"] == 1
    assert report["synthetic_runs_created"] == 0
    assert report["outputs_registered"] == 1

    db = sessionmaker(bind=engine)()
    try:
        fresh_audio = (
            db.query(ChapterAudio)
            .filter(ChapterAudio.id == audio_id)
            .first()
        )
        assert fresh_audio.published_run_id == run_id
        assert fresh_audio.published_provenance == "legacy_unverified"
        # seed 历史 render_status 不精确回填
        assert fresh_audio.render_status is None
        output = (
            db.query(ChapterAudioOutput)
            .filter(ChapterAudioOutput.run_id == run_id)
            .first()
        )
        assert output is not None
        assert output.status == "published"
        assert output.audio_path == fresh_audio.audio_path
    finally:
        db.close()


def test_backfill_creates_synthetic_migration_run(engine):
    """无匹配 run → 创建 migration_placeholder synthetic run（验收 38/50）。"""
    db = sessionmaker(bind=engine)()
    _, project, chapter, batch, audio = _seed_scope(db, "synth")
    db.flush()
    audio_id = audio.id
    db.commit()
    db.close()

    report = run_synthetic_migration_backfill(engine)

    assert report["scanned_chapters"] == 1
    assert report["owner_run_backfilled"] == 0
    assert report["synthetic_runs_created"] == 1
    assert report["outputs_registered"] == 1

    db = sessionmaker(bind=engine)()
    try:
        fresh_audio = (
            db.query(ChapterAudio)
            .filter(ChapterAudio.id == audio_id)
            .first()
        )
        synthetic = (
            db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.id == fresh_audio.published_run_id)
            .first()
        )
        assert synthetic is not None
        assert synthetic.run_type == "migration_placeholder"
        assert synthetic.status == "completed"
        assert synthetic.dispatch_status == "cancelled"
        assert synthetic.resumable is False
        # 不可结算（billing_finalized_at 保持 null 且无 ledger 写入路径）
        assert synthetic.billing_finalized_at is None
        assert fresh_audio.published_provenance == "legacy_unverified"
    finally:
        db.close()


def test_backfill_is_idempotent(engine):
    """幂等：重复执行不重复创建 synthetic run/输出登记。"""
    db = sessionmaker(bind=engine)()
    _, project, chapter, batch, audio = _seed_scope(db, "idem")
    db.commit()
    db.close()

    first = run_synthetic_migration_backfill(engine)
    second = run_synthetic_migration_backfill(engine)

    assert first["synthetic_runs_created"] == 1
    assert first["outputs_registered"] == 1
    # 二次执行：已回填章节不再扫描（published_run_id 非空）
    assert second["scanned_chapters"] == 0
    assert second["synthetic_runs_created"] == 0
    assert second["outputs_registered"] == 0

    db = sessionmaker(bind=engine)()
    try:
        placeholder_count = (
            db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.run_type == "migration_placeholder")
            .count()
        )
        assert placeholder_count == 1
        output_count = (
            db.query(ChapterAudioOutput)
            .filter(ChapterAudioOutput.status == "published")
            .count()
        )
        assert output_count == 1
    finally:
        db.close()


def test_backfill_skips_chapter_without_audio_path(engine):
    """无 audio_path 的章节不扫描（无产物可回填）。"""
    db = sessionmaker(bind=engine)()
    _, project, chapter, batch, audio = _seed_scope(db, "nopath")
    audio.audio_path = None
    db.commit()
    db.close()

    report = run_synthetic_migration_backfill(engine)
    assert report["scanned_chapters"] == 0
    assert report["synthetic_runs_created"] == 0
