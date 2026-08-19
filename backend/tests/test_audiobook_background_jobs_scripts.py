from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import background_jobs_scripts


class DummyVoiceManager:
    def __init__(self):
        self.loaded = []

    def load_from_db(self, mapping):
        self.loaded.append(mapping)

    def apply_project_voice_mapping(self, mapping, *, character_profiles=None):
        self.loaded.append(mapping)


class FailingVoiceManager:
    def load_from_db(self, mapping):
        raise RuntimeError("voice manager rejected mapping")


def build_engine(voice_manager=None):
    return SimpleNamespace(voice_manager=voice_manager or DummyVoiceManager())


def test_load_existing_voice_mapping_ignores_invalid_json_payload(caplog):
    engine = build_engine()
    audiobook_project = SimpleNamespace(voice_mapping="{bad-json")

    with caplog.at_level("WARNING", logger="app.services.audiobook.background_jobs_scripts"):
        background_jobs_scripts._load_existing_voice_mapping(engine, audiobook_project)

    assert engine.voice_manager.loaded == []
    assert "从数据库加载音色分配失败" in caplog.text


def test_load_existing_voice_mapping_does_not_swallow_unexpected_json_errors(monkeypatch):
    engine = build_engine()
    audiobook_project = SimpleNamespace(voice_mapping='{"旁白":{"voice_id":"Neil"}}')

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected json parser failure")

    monkeypatch.setattr(background_jobs_scripts.json, "loads", boom)

    with pytest.raises(RuntimeError, match="unexpected json parser failure"):
        background_jobs_scripts._load_existing_voice_mapping(engine, audiobook_project)


def test_load_existing_voice_mapping_keeps_voice_manager_failures_non_blocking(caplog):
    engine = build_engine(FailingVoiceManager())
    audiobook_project = SimpleNamespace(voice_mapping={"旁白": {"voice_id": "Neil"}})

    with caplog.at_level("WARNING", logger="app.services.audiobook.background_jobs_scripts"):
        background_jobs_scripts._load_existing_voice_mapping(engine, audiobook_project)

    assert "从数据库加载音色分配失败" in caplog.text


def test_script_stage_applies_project_audio_engine_mode(monkeypatch, caplog):
    applied_runtime = []
    engine = build_engine()
    engine.apply_scene_audio_runtime_config = lambda **kwargs: applied_runtime.append(kwargs)
    runtime_config = SimpleNamespace(
        voice_mapping={},
        audio_fx={},
        audio_engine_mode="seed_scene",
        seed_audio_model="seed-audio-1.0-multilingual",
        character_items=[],
    )
    monkeypatch.setattr(
        background_jobs_scripts,
        "resolve_project_audio_runtime_config",
        lambda *args, **kwargs: runtime_config,
    )

    with caplog.at_level("INFO", logger="app.services.audiobook.background_jobs_scripts"):
        background_jobs_scripts._apply_script_stage_project_audio_config(
            engine=engine,
            project=SimpleNamespace(),
            tts_model="qwen3-tts-instruct-flash",
            character_profiles=[],
        )

    assert applied_runtime == [
        {
            "audio_engine_mode": "seed_scene",
            "seed_audio_model": "seed-audio-1.0-multilingual",
            "voice_mapping": {},
        }
    ]
    assert "audio_engine_mode=seed_scene" in caplog.text
    assert "seed_audio_model=seed-audio-1.0-multilingual" in caplog.text
