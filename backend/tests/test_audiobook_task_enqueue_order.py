import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.admin_log import AdminOperationLog
from app.models.audiobook import AudiobookProject, AudiobookTaskDispatch, ChapterAudio, ChapterAudioRun
from app.models.audiobook_task import AudiobookTask
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook import task_support


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
            ChapterAudio.__table__,
            ChapterAudioRun.__table__,
            AudiobookTask.__table__,
            # enqueue 流程读取积分定价策略审计投影（points_pricing_policy）
            AdminOperationLog.__table__,
            # per-run 派发写入任务-派发父子关系（R12/P1-1）
            AudiobookTaskDispatch.__table__,
        ],
    )
    return session_factory


def seed_project(db):
    user = User(
        username="enqueue_order_user",
        email="enqueue_order@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Enqueue Order Project",
        audio_config="{}",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_number=1,
        title="Chapter 1",
        content="Test chapter content",
        summary="summary",
    )
    db.add(chapter)
    db.flush()

    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="pending",
        total_chapters=1,
    )
    db.add(audiobook_project)
    db.commit()

    return {
        "chapter": chapter,
        "audiobook_project": audiobook_project,
    }


def test_enqueue_audiobook_task_prepares_task_runs_and_checkpoint_before_dispatch(monkeypatch):
    from app.services.audiobook import dispatch_service

    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_project(db)
        snapshots = []

        def fake_try_dispatch_run(db, *, run_id):
            runs = db.query(ChapterAudioRun).all()
            snapshots.append({
                "event": "dispatch",
                "run_id": run_id,
                "run_count": len(runs),
                "run_celery_task_ids": [run.celery_task_id for run in runs],
                "run_checkpoint_json": [dict(run.checkpoint_json or {}) for run in runs],
            })
            return "dispatched"

        monkeypatch.setattr(task_support, "uuid4", lambda: "fixed-celery-task-id")
        monkeypatch.setattr(dispatch_service, "try_dispatch_run", fake_try_dispatch_run)

        def before_dispatch(task_record, celery_task_id):
            db.refresh(task_record)
            runs = db.query(ChapterAudioRun).all()
            assert task_record.celery_task_id == celery_task_id
            assert len(runs) == 1
            assert runs[0].celery_task_id == celery_task_id

            checkpoint_json = dict(runs[0].checkpoint_json or {})
            checkpoint_json["resume_requested_at"] = "2026-05-03T00:00:00+00:00"
            runs[0].checkpoint_json = checkpoint_json
            db.add(runs[0])
            db.commit()
            snapshots.append({"event": "before_dispatch", "task_id": celery_task_id})

        task_record, async_result = task_support.enqueue_audiobook_task(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_ids=[context["chapter"].id],
            job_type="audio_from_scripts",
            tts_model="qwen-audio-3.1-tts-flash",
            output_format="mp3",
            narration_style="professional",
            narration_style_prompt=None,
            generate_subtitle=True,
            timeline_edits_by_chapter={
                context["chapter"].id: {
                    "sfx-0-0": {"startUnit": 12, "durationUnits": 48},
                },
            },
            before_dispatch=before_dispatch,
        )

        assert async_result.id == "fixed-celery-task-id"
        assert task_record.id
        # R11/P0-1（outbox）：enqueue 阶段不派发，仅 before_dispatch 回调；
        # run 即派发意图，由 commit 后的 dispatch_pending_runs 显式投递
        assert [snapshot["event"] for snapshot in snapshots] == ["before_dispatch"]

        runs = db.query(ChapterAudioRun).all()
        summary = task_support.dispatch_pending_runs(db, runs)
        assert summary == {"dispatched": 1, "failed": 0, "unknown": 0}
        dispatch_snapshot = snapshots[-1]
        assert dispatch_snapshot["event"] == "dispatch"
        assert dispatch_snapshot["run_count"] == 1
        assert dispatch_snapshot["run_celery_task_ids"] == ["fixed-celery-task-id"]
        assert dispatch_snapshot["run_checkpoint_json"][0]["generate_subtitle"] is True
        assert dispatch_snapshot["run_checkpoint_json"][0]["timeline_edits"] == {
            "sfx-0-0": {"startUnit": 12, "durationUnits": 48},
        }
        assert (
            dispatch_snapshot["run_checkpoint_json"][0]["resume_requested_at"]
            == "2026-05-03T00:00:00+00:00"
        )
