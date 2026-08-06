import asyncio
import os
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for import_root in (PROJECT_ROOT, ROOT_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import app.services.audiobook.engine_pkg._tts_mixin as tts_mixin_module
from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin


class _BoundVoiceEngine(TTSMixin):
    def __init__(self) -> None:
        self._use_tts_dispatch = True
        self.model_bound_calls = 0

    async def _synthesize_segments(self, script_segments, **kwargs):
        self.model_bound_calls += 1
        return [b"model-bound"] * len(script_segments)


def test_fixed_voice_segments_never_enter_cross_model_smart_dispatch(monkeypatch) -> None:
    class FailingDispatchClient:
        def synthesize_batch(self, **_kwargs):
            raise AssertionError("固定 voice_id 不得进入跨模型智能调度")

    monkeypatch.setattr(tts_mixin_module, "tts_dispatch_client", FailingDispatchClient())
    engine = _BoundVoiceEngine()
    segments = [
        {
            "text": "测试。",
            "voice_params": {
                "speaker": "voice-a",
                "tts_model": "seed-tts-2.0-expressive",
            },
        }
    ]

    result = asyncio.run(engine._synthesize_segments_with_dispatch(segments))

    assert result == [b"model-bound"]
    assert engine.model_bound_calls == 1


def test_single_fixed_voice_dispatch_api_rejects_cross_model_routing(monkeypatch) -> None:
    class FailingDispatchClient:
        def synthesize(self, **_kwargs):
            raise AssertionError("固定 voice_id 不得进入跨模型智能调度")

    monkeypatch.setattr(tts_mixin_module, "tts_dispatch_client", FailingDispatchClient())
    engine = _BoundVoiceEngine()

    with pytest.raises(ValueError, match="fixed voice_id"):
        engine.synthesize_with_dispatch("测试。", voice_id="voice-a")
