from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.task_trace import (  # noqa: E402
    build_audiobook_trace_context,
    merge_audiobook_trace_context,
)


def test_build_audiobook_trace_context_reuses_celery_task_id_and_omits_none():
    context = build_audiobook_trace_context(
        celery_task_id="celery-123",
        task_db_id=45,
        task_type="export_m4b",
        audiobook_project_id=67,
        chapter_id=None,
        stage="project_export",
        status="running",
        progress=0.05,
    )

    assert context == {
        "trace_id": "celery-123",
        "celery_task_id": "celery-123",
        "task_db_id": 45,
        "task_type": "export_m4b",
        "audiobook_project_id": 67,
        "stage": "project_export",
        "status": "running",
        "progress": 0.05,
    }


def test_merge_audiobook_trace_context_preserves_existing_detail_and_input():
    detail = {
        "audiobook_project_id": 34,
        "export_type": "audacity",
        "trace_id": "existing-trace",
    }

    merged = merge_audiobook_trace_context(
        detail,
        {
            "trace_id": "new-trace",
            "audiobook_project_id": 99,
            "celery_task_id": "new-trace",
            "task_db_id": 12,
            "ignored_none": None,
        },
    )

    assert merged == {
        "audiobook_project_id": 34,
        "export_type": "audacity",
        "trace_id": "existing-trace",
        "celery_task_id": "new-trace",
        "task_db_id": 12,
    }
    assert detail == {
        "audiobook_project_id": 34,
        "export_type": "audacity",
        "trace_id": "existing-trace",
    }
