"""短剧配音链路（DreamWeaver → agents/）的模型与默认声线契约。

配音 TTS 已换代到 qwen-audio-3.1 系列，`agents/audio_sync_manager.py` 这条活链路
（被 `agents/dreamweaver_agent_pkg/` 多处导入）必须显式落在 qwen-audio-3.1-tts-flash 上。
不同代际的音色空间不互通：把上一代的默认声线名发给现役模型，上游会判为一个不存在的
voice，而这条链路的异常被 except 吞成"这一句没有音频"，测试不变红、线上静默丢音。
因此这里同时锁两件事：下发的 model_id，以及落到默认值时声线必须在现行音色目录里。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TTS_MODEL = "qwen-audio-3.1-tts-flash"

_voice_catalog = json.loads(
    (ROOT / "shared" / "qwen_audio_3_1_tts_voices.json").read_text(encoding="utf-8")
)
CATALOG_VOICE_IDS = {voice["id"] for voice in _voice_catalog["voices"]}


class _FakeResult:
    success = True
    data = {"audio_data": "ZmFrZQ==", "format": "mp3"}
    error = None
    metadata: dict = {}
    cost = 0.0


@pytest.fixture()
def captured_tts_call(monkeypatch: pytest.MonkeyPatch) -> dict:
    from adapters import adapter_helpers

    captured: dict[str, object] = {}

    def fake_synthesize_speech_sync(**kwargs):
        captured.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr(adapter_helpers, "synthesize_speech_sync", fake_synthesize_speech_sync)
    return captured


def test_dialogue_audio_uses_active_model_and_catalog_voice(
    tmp_path: Path,
    captured_tts_call: dict,
) -> None:
    from agents.audio_sync_manager import AudioSyncManager

    manager = AudioSyncManager(run_dir=tmp_path)
    manager.generate_audio_for_dialogue(shot_id="shot-1", dialogue="你好，测试。")

    assert captured_tts_call["model_id"] == ACTIVE_TTS_MODEL
    voice_params = captured_tts_call["voice_params"]
    assert isinstance(voice_params, dict)
    assert voice_params["speaker"] in CATALOG_VOICE_IDS


def test_character_profile_fallback_voice_is_in_active_catalog(tmp_path: Path) -> None:
    from agents.character_manager import CharacterManager, CharacterProfile

    manager = CharacterManager(run_dir=tmp_path)
    # 音色档案服务不可用时才会走默认值；显式置 False 复现"没有任何角色档案"的起点。
    manager._voice_manager = False

    profile = CharacterProfile(character_id="char-1", name="林澈")
    assert manager._ensure_voice_profile(profile) is True
    assert profile.voice_id in CATALOG_VOICE_IDS
    assert profile.voice_profile_id == profile.voice_id
