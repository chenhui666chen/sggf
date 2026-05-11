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
