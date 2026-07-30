import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@127.0.0.1:5432/test_db",
)

from app.api.v1.audiobook_api import routes_projects


def test_project_chapter_summary_exposes_script_review_metadata(monkeypatch):
    monkeypatch.setattr(
        routes_projects,
        "_load_prompt_audio_quality_for_response",
        lambda _chapter_audio: None,
    )
    chapter_audio = SimpleNamespace(
        id=7,
        chapter_id=11,
        audio_path=None,
        duration=0.0,
        file_size=0,
        script_status="reviewed",
        script_json='[{"text":"第一句"}]',
        script_review_json='{"overall_score": 90}',
        segment_count=18,
        dialogue_count=8,
        narration_count=10,
        character_count=3,
        generation_time=4.5,
        tts_cost=0.0,
    )

    payload = routes_projects._serialize_chapter_audio_summary(
        chapter_audio,
        {11: 1},
    )

    assert payload["segment_count"] == 18
    assert payload["dialogue_count"] == 8
    assert payload["narration_count"] == 10
    assert payload["character_count"] == 3
    assert payload["has_review"] is True
