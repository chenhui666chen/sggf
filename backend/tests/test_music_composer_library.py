from __future__ import annotations

import json
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from app.services.audiobook.agents.music_composer import MusicComposer


def _write_index(index_dir: Path, records: list[dict]) -> Path:
    music_cache = index_dir / "music_cache"
    music_cache.mkdir(parents=True)
    (music_cache / "exists.mp3").write_bytes(b"fake-mp3")

    index_path = index_dir / "music_index.json"
    index_path.write_text(json.dumps(records), encoding="utf-8")
    return index_path


def test_load_external_music_library_skips_missing_files(tmp_path):
    index_path = _write_index(tmp_path / "audio_library", [
        {"id": "good_001", "file_path": "music_cache/exists.mp3", "mood": "peaceful", "style": "classical"},
        {"id": "missing_001", "file_path": "music_cache/gone.mp3", "mood": "tense", "style": "orchestral"},
    ])

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    # 存在文件的条目正常加载，缺失文件条目被跳过且不抛异常
    assert "good_001" in composer.music_library
    assert "missing_001" not in composer.music_library


def test_load_external_music_library_logs_single_summary_for_missing(caplog, tmp_path):
    index_path = _write_index(tmp_path / "audio_library", [
        {"id": "missing_001", "file_path": "music_cache/gone_a.mp3", "mood": "tense"},
        {"id": "missing_002", "file_path": "music_cache/gone_b.mp3", "mood": "sad"},
        {"id": "good_001", "file_path": "music_cache/exists.mp3", "mood": "peaceful"},
    ])

    logger_name = "app.services.audiobook.agents.music_composer"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    missing_warnings = [
        record for record in caplog.records
        if record.name == logger_name and "文件缺失" in record.getMessage()
    ]
    # 缺失条目只汇总为一条警告，避免每次加载重复刷屏
    assert len(missing_warnings) == 1
    assert "music_cache/gone_a.mp3" in missing_warnings[0].getMessage()
    assert "music_cache/gone_b.mp3" in missing_warnings[0].getMessage()
    assert "good_001" in composer.music_library
