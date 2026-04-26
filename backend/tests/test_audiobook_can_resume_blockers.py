"""
固化 `_validate_resume_checkpoint` 的 blockers 判定逻辑。

覆盖 blockers 清单：
- run_marked_non_resumable / run_status_not_resumable / already_completed
- checkpoint_schema_version_mismatch
- {script_hash|voice_config_hash|audio_fx_hash|tts_model|output_format}_mismatch
- checkpoint_expired
- missing_temp_assets
- no_checkpoint_material
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent
for _path in (_BACKEND_DIR, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import task_support
from app.services.audiobook.task_support import (
    CHECKPOINT_SCHEMA_VERSION,
    _validate_resume_checkpoint,
)
from app.utils.datetime_utils import utc_now


@pytest.fixture
def patch_resume_context(monkeypatch):
    """替换 DB 查询依赖，返回当前 hash / 配置上下文。"""

    def _apply(context: Dict[str, Any]):
        monkeypatch.setattr(
            task_support,
            "_build_resume_input_context",
            lambda *args, **kwargs: dict(context),
        )

    return _apply


@pytest.fixture
def patch_path_exists(monkeypatch):
    """默认所有 temp asset 均存在，避免 missing_temp_assets 误触发。"""

    monkeypatch.setattr(task_support, "_checkpoint_path_exists", lambda _p: True)


def _make_run(**overrides: Any) -> SimpleNamespace:
    defaults = dict(resumable=True, status="failed")
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _base_context() -> Dict[str, Any]:
    return {
        "script_hash": "sha-script",
        "voice_config_hash": "sha-voice",
        "audio_fx_hash": "sha-fx",
        "tts_model": "qwen-tts-v1",
        "output_format": "mp3",
    }


def _base_checkpoint(**overrides: Any) -> Dict[str, Any]:
    checkpoint: Dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        **_base_context(),
        "cached_audio_paths": {},
        "segments": {},
    }
    checkpoint.update(overrides)
    return checkpoint


def _invoke(
    *,
    chapter_run: SimpleNamespace,
    checkpoint_data: Dict[str, Any],
    checkpoint_source: str = "chapter_audio_run",
    total_segments: int = 4,
    completed_count: int = 2,
):
    return _validate_resume_checkpoint(
        db=None,  # type: ignore[arg-type]
        audiobook_project_id=1,
        chapter_id=1,
        chapter_run=chapter_run,
        chapter_audio=None,
        checkpoint_source=checkpoint_source,
        checkpoint_data=checkpoint_data,
        total_segments=total_segments,
        completed_count=completed_count,
    )


def test_happy_path_no_blockers(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    result = _invoke(chapter_run=_make_run(), checkpoint_data=_base_checkpoint())
    assert result["blockers"] == []


def test_run_marked_non_resumable(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    result = _invoke(
        chapter_run=_make_run(resumable=False),
        checkpoint_data=_base_checkpoint(),
    )
    assert "run_marked_non_resumable" in result["blockers"]


def test_run_status_not_resumable(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    result = _invoke(
        chapter_run=_make_run(status="running"),
        checkpoint_data=_base_checkpoint(),
    )
    assert "run_status_not_resumable" in result["blockers"]


def test_already_completed(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    result = _invoke(
        chapter_run=_make_run(),
        checkpoint_data=_base_checkpoint(),
        total_segments=4,
        completed_count=4,
    )
    assert "already_completed" in result["blockers"]


def test_schema_version_mismatch(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    result = _invoke(
        chapter_run=_make_run(),
        checkpoint_data=_base_checkpoint(schema_version=CHECKPOINT_SCHEMA_VERSION + 99),
    )
    assert "checkpoint_schema_version_mismatch" in result["blockers"]


@pytest.mark.parametrize(
    "field_name",
    ["script_hash", "voice_config_hash", "audio_fx_hash", "tts_model", "output_format"],
)
def test_hash_and_config_mismatch_blockers(
    field_name, patch_resume_context, patch_path_exists
):
    context = _base_context()
    context[field_name] = "current-value"
    patch_resume_context(context)
    checkpoint = _base_checkpoint()
    checkpoint[field_name] = "checkpoint-value"
    result = _invoke(chapter_run=_make_run(), checkpoint_data=checkpoint)
    assert f"{field_name}_mismatch" in result["blockers"]


def test_checkpoint_expired(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    expired_at = (utc_now() - timedelta(hours=1)).isoformat()
    result = _invoke(
        chapter_run=_make_run(),
        checkpoint_data=_base_checkpoint(expires_at=expired_at),
    )
    assert "checkpoint_expired" in result["blockers"]


def test_missing_temp_assets_from_cached_paths(patch_resume_context, monkeypatch):
    patch_resume_context(_base_context())
    monkeypatch.setattr(task_support, "_checkpoint_path_exists", lambda _p: False)
    checkpoint = _base_checkpoint(
        cached_audio_paths={"0": "storage/audiobook_temp/run/ch1/seg_00000.mp3"},
    )
    result = _invoke(chapter_run=_make_run(), checkpoint_data=checkpoint)
    assert "missing_temp_assets" in result["blockers"]
    assert result["checks"]["missing_temp_assets"], "should list the missing asset ref"


def test_missing_temp_assets_from_segment_temp_object_key(
    patch_resume_context, monkeypatch
):
    patch_resume_context(_base_context())
    monkeypatch.setattr(task_support, "_checkpoint_path_exists", lambda _p: False)
    checkpoint = _base_checkpoint(
        segments={"0": {"temp_object_key": "oss://bucket/run/ch1/seg_00000.mp3"}},
    )
    result = _invoke(chapter_run=_make_run(), checkpoint_data=checkpoint)
    assert "missing_temp_assets" in result["blockers"]


def test_no_checkpoint_material_blocker(patch_resume_context, patch_path_exists):
    patch_resume_context(_base_context())
    result = _invoke(
        chapter_run=_make_run(),
        checkpoint_data={},
        checkpoint_source="none",
    )
    assert "no_checkpoint_material" in result["blockers"]


def test_blockers_are_deduplicated(patch_resume_context, monkeypatch):
    """同一 blocker 只应出现一次（dict.fromkeys 去重）。"""

    patch_resume_context(_base_context())
    monkeypatch.setattr(task_support, "_checkpoint_path_exists", lambda _p: False)
    checkpoint = _base_checkpoint(
        cached_audio_paths={
            "0": "storage/audiobook_temp/run/ch1/seg_00000.mp3",
            "1": "storage/audiobook_temp/run/ch1/seg_00001.mp3",
        },
    )
    result = _invoke(chapter_run=_make_run(), checkpoint_data=checkpoint)
    assert result["blockers"].count("missing_temp_assets") == 1
