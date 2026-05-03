import os
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
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


class FakeSignature:
    def __init__(self, *, db, snapshots):
        self.db = db
        self.snapshots = snapshots

    def delay(self):
        raise AssertionError("enqueue_audiobook_task must not dispatch before runs are ready")

    def apply_async(self, *, task_id):
        task = self.db.query(AudiobookTask).one()
        runs = self.db.query(ChapterAudioRun).all()
        self.snapshots.append({
            "event": "apply_async",
            "task_id": task_id,
            "task_celery_task_id": task.celery_task_id,
            "run_count": len(runs),
            "run_celery_task_ids": [run.celery_task_id for run in runs],
            "run_checkpoint_json": [dict(run.checkpoint_json or {}) for run in runs],
        })
        return SimpleNamespace(id=task_id)


def test_enqueue_audiobook_task_prepares_task_runs_and_checkpoint_before_dispatch(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_project(db)
        snapshots = []

        def fake_signature(name, args):
            snapshots.append({
                "event": "signature",
                "name": name,
                "args": args,
            })
            return FakeSignature(db=db, snapshots=snapshots)

        monkeypatch.setattr(task_support, "uuid4", lambda: "fixed-celery-task-id")
        monkeypatch.setattr(task_support.celery_app, "signature", fake_signature)

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
            tts_model="qwen3-tts-instruct-flash",
            output_format="mp3",
            narration_style="professional",
            narration_style_prompt=None,
            generate_subtitle=True,
            before_dispatch=before_dispatch,
        )

        assert async_result.id == "fixed-celery-task-id"
        assert task_record.id
        assert [snapshot["event"] for snapshot in snapshots] == [
            "signature",
            "before_dispatch",
            "apply_async",
        ]
        dispatch_snapshot = snapshots[-1]
        assert dispatch_snapshot["task_id"] == "fixed-celery-task-id"
        assert dispatch_snapshot["task_celery_task_id"] == "fixed-celery-task-id"
        assert dispatch_snapshot["run_count"] == 1
        assert dispatch_snapshot["run_celery_task_ids"] == ["fixed-celery-task-id"]
        assert dispatch_snapshot["run_checkpoint_json"][0]["generate_subtitle"] is True
        assert (
            dispatch_snapshot["run_checkpoint_json"][0]["resume_requested_at"]
            == "2026-05-03T00:00:00+00:00"
        )
