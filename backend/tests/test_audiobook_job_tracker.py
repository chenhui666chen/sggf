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
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.audiobook_task import AudiobookTask
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook import job_tracker
from app.services.audiobook.job_tracker import AudiobookJobTracker


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


def seed_tracker_context(db, *, celery_task_id="celery-top-fail"):
    user = User(
        username="job_tracker_user",
        email="job_tracker@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Job Tracker Project",
        audio_config="{}",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapters = []
    for index in range(1, 6):
        chapter = Chapter(
            project_id=project.id,
            chapter_number=index,
            title=f"Chapter {index}",
            content=f"Test chapter content {index}",
            summary="summary",
        )
        db.add(chapter)
        chapters.append(chapter)
    db.flush()

    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="processing",
        total_chapters=len(chapters),
    )
    db.add(audiobook_project)
    db.flush()

    task = AudiobookTask(
        audiobook_project_id=audiobook_project.id,
        chapter_id=None,
        task_type="full",
        celery_task_id=celery_task_id,
        status="running",
        current_stage="initializing",
        progress=0.0,
        total_units=len(chapters),
    )
    db.add(task)
    db.flush()

    runs = {
        "queued": ChapterAudioRun(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapters[0].id,
            run_type="full",
            celery_task_id=celery_task_id,
            status="queued",
            current_stage="queued",
            progress=0.0,
            checkpoint_json={"status": "queued"},
        ),
        "running": ChapterAudioRun(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapters[1].id,
            run_type="full",
            celery_task_id=celery_task_id,
            status="running",
            current_stage="tts_synthesis",
            progress=0.25,
            completed_segment_count=1,
            total_segment_count=4,
            checkpoint_json={
                "status": "running",
                "completed_segment_indices": [0],
                "total_segments": 4,
            },
        ),
        "completed": ChapterAudioRun(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapters[2].id,
            run_type="full",
            celery_task_id=celery_task_id,
            status="completed",
            current_stage="completed",
            progress=1.0,
            error_message=None,
            checkpoint_json={"status": "completed", "last_error": None},
        ),
        "failed_with_diagnostic": ChapterAudioRun(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapters[3].id,
            run_type="full",
            celery_task_id=celery_task_id,
            status="failed",
            current_stage="failed",
            progress=0.5,
            error_message="chapter detail failure",
            checkpoint_json={
                "status": "failed",
                "last_error": "chapter detail failure",
                "failure_diagnostic": {"stage": "tts_synthesis"},
            },
        ),
        "other_task": ChapterAudioRun(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapters[4].id,
            run_type="full",
            celery_task_id="celery-other-task",
            status="running",
            current_stage="tts_synthesis",
            progress=0.5,
            checkpoint_json={"status": "running", "last_error": None},
        ),
    }
    db.add_all(runs.values())
    db.commit()

    return {
        "task_id": task.id,
        "celery_task_id": celery_task_id,
        "run_ids": {name: run.id for name, run in runs.items()},
    }


def get_run(db, run_id):
    return db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).first()


def test_update_stage_adds_trace_context_to_task_and_chapter_detail(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_tracker_context(db, celery_task_id="celery-stage-trace")
        running_run = get_run(db, context["run_ids"]["running"])
        chapter_id = running_run.chapter_id

    emitted_events = []
    monkeypatch.setattr(
        AudiobookJobTracker,
        "_with_session",
        lambda self: session_factory(),
    )
    monkeypatch.setattr(
        job_tracker.sse_tracker,
        "emit_progress",
        lambda task_id, payload: emitted_events.append((task_id, payload)),
    )

    AudiobookJobTracker(context["task_id"]).update_stage(
        "tts_synthesis",
        2,
        5,
        detail={
            "chapter_id": chapter_id,
            "status": "running",
            "custom_metric": "kept",
            "trace_id": "detail-trace-kept",
        },
    )

    with session_factory() as db:
        task = db.query(AudiobookTask).filter(AudiobookTask.id == context["task_id"]).first()
        run = get_run(db, context["run_ids"]["running"])

        assert task.detail_json["trace_id"] == "detail-trace-kept"
        assert task.detail_json["celery_task_id"] == "celery-stage-trace"
        assert task.detail_json["task_db_id"] == context["task_id"]
        assert task.detail_json["task_type"] == "full"
        assert task.detail_json["audiobook_project_id"] == run.audiobook_project_id
        assert task.detail_json["chapter_id"] == chapter_id
        assert task.detail_json["stage"] == "tts_synthesis"
        assert task.detail_json["progress"] == 0.4
        assert task.detail_json["custom_metric"] == "kept"

        tracker_detail = run.checkpoint_json["tracker_detail"]
        assert tracker_detail == task.detail_json

    assert emitted_events == [
        (
            "celery-stage-trace",
            {
                "stage": "tts_synthesis",
                "progress": 0.4,
                "detail": {
                    "chapter_id": chapter_id,
                    "status": "running",
                    "custom_metric": "kept",
                    "trace_id": "detail-trace-kept",
                    "celery_task_id": "celery-stage-trace",
                    "task_db_id": context["task_id"],
                    "task_type": "full",
                    "audiobook_project_id": run.audiobook_project_id,
                    "stage": "tts_synthesis",
                    "progress": 0.4,
                },
                "status": "running",
                "error_message": None,
            },
        )
    ]


def test_mark_failed_marks_unfinished_runs_for_same_celery_task(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_tracker_context(db)

    emitted_events = []
    monkeypatch.setattr(
        AudiobookJobTracker,
        "_with_session",
        lambda self: session_factory(),
    )
    monkeypatch.setattr(
        job_tracker.sse_tracker,
        "emit_progress",
        lambda task_id, payload: emitted_events.append((task_id, payload)),
    )

    AudiobookJobTracker(context["task_id"]).mark_failed("worker crashed")

    with session_factory() as db:
        task = db.query(AudiobookTask).filter(AudiobookTask.id == context["task_id"]).first()
        queued_run = get_run(db, context["run_ids"]["queued"])
        running_run = get_run(db, context["run_ids"]["running"])
        completed_run = get_run(db, context["run_ids"]["completed"])
        failed_run = get_run(db, context["run_ids"]["failed_with_diagnostic"])
        other_task_run = get_run(db, context["run_ids"]["other_task"])

        assert task.status == "failed"
        assert task.current_stage == "failed"
        assert task.error_message == "worker crashed"

        for run in (queued_run, running_run):
            assert run.status == "failed"
            assert run.current_stage == "failed"
            assert run.error_message == "worker crashed"
            assert run.finished_at is not None
            assert run.expires_at is not None
            assert run.checkpoint_json["status"] == "failed"
            assert run.checkpoint_json["current_stage"] == "failed"
            assert run.checkpoint_json["last_error"] == "worker crashed"
            assert run.checkpoint_json["run_db_id"] == run.id

        assert running_run.completed_segment_count == 1
        assert running_run.total_segment_count == 4
        assert running_run.checkpoint_json["completed_segment_indices"] == [0]

        assert completed_run.status == "completed"
        assert completed_run.current_stage == "completed"
        assert completed_run.error_message is None
        assert completed_run.checkpoint_json["status"] == "completed"

        assert failed_run.status == "failed"
        assert failed_run.error_message == "chapter detail failure"
        assert failed_run.checkpoint_json["last_error"] == "chapter detail failure"
        assert failed_run.checkpoint_json["failure_diagnostic"] == {"stage": "tts_synthesis"}

        assert other_task_run.status == "running"
        assert other_task_run.current_stage == "tts_synthesis"
        assert other_task_run.error_message is None
        assert other_task_run.checkpoint_json["status"] == "running"

    assert emitted_events == [
        (
            context["celery_task_id"],
            {
                "stage": "failed",
                "progress": 1.0,
                "detail": {},
                "status": "failed",
                "error_message": "worker crashed",
            },
        )
    ]


def test_mark_failed_without_celery_task_id_does_not_bulk_fail_project_runs(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_tracker_context(db, celery_task_id=None)
        task = db.query(AudiobookTask).filter(AudiobookTask.id == context["task_id"]).first()
        task.celery_task_id = None
        db.add(task)
        db.commit()

    monkeypatch.setattr(
        AudiobookJobTracker,
        "_with_session",
        lambda self: session_factory(),
    )
    monkeypatch.setattr(job_tracker.sse_tracker, "emit_progress", lambda task_id, payload: None)

    AudiobookJobTracker(context["task_id"]).mark_failed("worker crashed")

    with session_factory() as db:
        task = db.query(AudiobookTask).filter(AudiobookTask.id == context["task_id"]).first()
        queued_run = get_run(db, context["run_ids"]["queued"])
        running_run = get_run(db, context["run_ids"]["running"])

        assert task.status == "failed"
        assert task.error_message == "worker crashed"
        assert queued_run.status == "queued"
        assert queued_run.error_message is None
        assert running_run.status == "running"
        assert running_run.error_message is None
