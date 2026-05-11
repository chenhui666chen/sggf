from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.tasks.audiobook_tasks import (  # noqa: E402
    _build_initial_generation_task_detail,
)


def test_build_initial_generation_task_detail_adds_script_only_trace_context():
    detail = _build_initial_generation_task_detail(
        task_db_id=12,
        celery_task_id="celery-script-123",
        task_type="script_only",
        audiobook_project_id=34,
        chapter_ids=[56, 78],
        tts_model="qwen3-tts-instruct-flash",
        stage="script_adaptation",
        status="running",
        progress=0.0,
    )

    assert detail == {
        "trace_id": "celery-script-123",
        "celery_task_id": "celery-script-123",
        "task_db_id": 12,
        "task_type": "script_only",
        "audiobook_project_id": 34,
        "chapter_ids": [56, 78],
        "chapter_total": 2,
        "stage": "script_adaptation",
        "status": "running",
        "progress": 0.0,
        "tts_model": "qwen3-tts-instruct-flash",
    }


def test_build_initial_generation_task_detail_adds_audio_from_scripts_trace_context():
    detail = _build_initial_generation_task_detail(
        task_db_id=90,
        celery_task_id="celery-audio-456",
        task_type="audio_from_scripts",
        audiobook_project_id=12,
        chapter_ids=[34],
        tts_model="minimax-speech-02-turbo",
        stage="tts_synthesis",
        status="running",
        progress=0.0,
    )

    assert detail["trace_id"] == "celery-audio-456"
    assert detail["celery_task_id"] == "celery-audio-456"
    assert detail["task_db_id"] == 90
    assert detail["task_type"] == "audio_from_scripts"
    assert detail["audiobook_project_id"] == 12
    assert detail["chapter_ids"] == [34]
    assert detail["chapter_total"] == 1
    assert detail["stage"] == "tts_synthesis"
    assert detail["status"] == "running"
    assert detail["progress"] == 0.0
    assert detail["tts_model"] == "minimax-speech-02-turbo"


def test_audio_from_scripts_task_uses_initial_trace_detail():
    task_file = ROOT_DIR / "app/tasks/audiobook_tasks.py"
    content = task_file.read_text(encoding="utf-8")

    assert 'task_type="audio_from_scripts"' in content
    assert 'stage="tts_synthesis"' in content


def test_build_initial_generation_task_detail_adds_full_trace_context():
    detail = _build_initial_generation_task_detail(
        task_db_id=101,
        celery_task_id="celery-full-789",
        task_type="full",
        audiobook_project_id=202,
        chapter_ids=[303, 404, 505],
        tts_model="qwen3-tts-instruct-flash",
        stage="initializing",
        status="running",
        progress=0.0,
    )

    assert detail["trace_id"] == "celery-full-789"
    assert detail["celery_task_id"] == "celery-full-789"
    assert detail["task_db_id"] == 101
    assert detail["task_type"] == "full"
    assert detail["audiobook_project_id"] == 202
    assert detail["chapter_ids"] == [303, 404, 505]
    assert detail["chapter_total"] == 3
    assert detail["stage"] == "initializing"
    assert detail["status"] == "running"
    assert detail["progress"] == 0.0
    assert detail["tts_model"] == "qwen3-tts-instruct-flash"


def test_full_task_uses_initial_trace_detail():
    task_file = ROOT_DIR / "app/tasks/audiobook_tasks.py"
    content = task_file.read_text(encoding="utf-8")

    assert 'task_type="full"' in content
    assert 'stage="initializing"' in content


def test_audiobook_freeze_routes_pass_trace_context():
    route_files = [
        ROOT_DIR / "app/api/v1/audiobook_api/routes_projects.py",
        ROOT_DIR / "app/api/v1/audiobook_api/routes_subtitle.py",
    ]
    content = "\n".join(route_file.read_text(encoding="utf-8") for route_file in route_files)

    assert content.count("build_audiobook_trace_context(") >= 3
    assert content.count("trace_context=build_audiobook_trace_context(") == 3
    assert 'task_type=job_type' in content
    assert 'task_type="audio_from_scripts"' in content
    assert "task_type=resume_task_type" in content
    assert content.count("cost_precheck_id=precheck.cost_precheck_id") == 3
