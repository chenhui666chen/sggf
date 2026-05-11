import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import task_support


def test_safe_record_audiobook_billing_freeze_forwards_expected_arguments(monkeypatch):
    calls = []
    db = object()
    raw_request = object()
    current_user = SimpleNamespace(id=7, username="billing_user")

    def fake_record_audiobook_billing_freeze(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        task_support,
        "record_audiobook_billing_freeze",
        fake_record_audiobook_billing_freeze,
    )

    task_support.safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=12,
        chapter_ids=[3, 5],
        raw_request=raw_request,
        tts_pricing_key="cosyvoice-v3.5-plus",
    )

    assert calls == [
        {
            "db": db,
            "actor_user_id": 7,
            "actor_username": "billing_user",
            "audiobook_project_id": 12,
            "chapter_ids": [3, 5],
            "request_context": raw_request,
            "tts_pricing_key": "cosyvoice-v3.5-plus",
        }
    ]


def test_safe_record_audiobook_billing_freeze_forwards_trace_context(monkeypatch):
    calls = []
    db = object()
    raw_request = object()
    current_user = SimpleNamespace(id=7, username="billing_user")
    trace_context = {
        "trace_id": "trace-123",
        "celery_task_id": "trace-123",
        "task_type": "audio_from_scripts",
        "status": "queued",
    }

    def fake_record_audiobook_billing_freeze(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        task_support,
        "record_audiobook_billing_freeze",
        fake_record_audiobook_billing_freeze,
    )

    task_support.safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=12,
        chapter_ids=[3, 5],
        raw_request=raw_request,
        tts_pricing_key="cosyvoice-v3.5-plus",
        trace_context=trace_context,
    )

    assert calls == [
        {
            "db": db,
            "actor_user_id": 7,
            "actor_username": "billing_user",
            "audiobook_project_id": 12,
            "chapter_ids": [3, 5],
            "request_context": raw_request,
            "tts_pricing_key": "cosyvoice-v3.5-plus",
            "extra_payload": trace_context,
        }
    ]


def test_safe_record_audiobook_billing_freeze_logs_and_swallows_failures(monkeypatch, caplog):
    current_user = SimpleNamespace(id=7, username="billing_user")

    def fake_record_audiobook_billing_freeze(**_kwargs):
        raise RuntimeError("billing backend unavailable")

    monkeypatch.setattr(
        task_support,
        "record_audiobook_billing_freeze",
        fake_record_audiobook_billing_freeze,
    )

    with caplog.at_level("WARNING", logger="app.services.audiobook.task_support"):
        task_support.safe_record_audiobook_billing_freeze(
            db=object(),
            current_user=current_user,
            audiobook_project_id=12,
            chapter_ids=[3],
            raw_request=object(),
            tts_pricing_key="cosyvoice-v3.5-plus",
        )

    assert "记录有声书积分冻结失败 audiobook_project_id=12 chapter_ids=[3]" in caplog.text
    assert "billing backend unavailable" in caplog.text
