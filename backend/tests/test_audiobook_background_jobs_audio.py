from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import background_jobs_audio


def test_audio_background_script_json_parse_uses_narrow_exception_boundary():
    source = Path(background_jobs_audio.__file__).read_text(encoding="utf-8")

    assert "except Exception as parse_err" not in source
    assert "except (json.JSONDecodeError, TypeError) as parse_err" in source


def test_generation_workers_use_deleted_target_guard_before_persisting_results():
    from app.services.audiobook import background_jobs_full, background_jobs_scripts

    for module in (
        background_jobs_audio,
        background_jobs_full,
        background_jobs_scripts,
    ):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "is_chapter_generation_target_active(" in source
        assert "is_audiobook_project_active(" in source

    for module in (background_jobs_audio, background_jobs_full):
        source = Path(module.__file__).read_text(encoding="utf-8")
        compact_source = " ".join(source.split())
        assert "output_path=None" in source
        assert "write_bytes_atomic(output_path, bytes(audio_data))" in source
        assert "cleanup_aborted_chapter_generation_artifacts(" in source
        assert "collect_chapter_segment_asset_refs(" in source
        assert "new_persistent_asset_refs - existing_persistent_asset_refs" in compact_source
        assert "delete_replaced_segment_asset_refs(" in source
