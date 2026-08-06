"""MiniMax 音色一致性与章节完整性闸门测试。

覆盖两个不变量：
1. 音色一致性：失败重试全程只用原请求音色，绝不切换候选音色。
2. 章节完整性：存在任何 TTS 缺失片段时，章节不得进入混音或标记成功。
"""

import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.tts_engine import TTSEngine
from app.services.audiobook.tts_engine_pkg import _aliyun_mixin as aliyun_mixin


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    """记录每次请求 payload 中的 voice_id，并按脚本返回响应或抛出异常。"""

    instances = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")
        self.calls = []
        self.responses = list(getattr(self, "_script", []))
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append((json or {}).get("input", {}).get("voice_setting", {}).get("voice_id"))
        item = self.responses.pop(0) if self.responses else None
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url):
        return _FakeResponse(status_code=404)


def _install_fake_httpx(monkeypatch, script):
    """把假的 httpx 模块注入，使 _call_dashscope_minimax_http 使用受控客户端。"""

    class ScriptedClient(_FakeAsyncClient):
        _script = script

    fake_httpx = SimpleNamespace(
        AsyncClient=ScriptedClient,
        Timeout=lambda **kwargs: kwargs,
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    # 消除重试退避等待，避免测试耗时。
    monkeypatch.setattr(aliyun_mixin, "MINIMAX_TTS_RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    return fake_httpx


def _success_body() -> dict:
    audio_b64 = base64.b64encode(b"fake-audio").decode()
    return {"output": {"data": {"audio": audio_b64}}}


def _engine() -> TTSEngine:
    return TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)


@pytest.mark.asyncio
async def test_minimax_timeout_retries_keep_same_voice_and_budget(monkeypatch):
    """连续超时：3 次调用全部使用原请求音色 badao_shaoye，绝不换色。"""
    read_timeout = type("ReadTimeout", (Exception,), {})
    _install_fake_httpx(monkeypatch, [read_timeout(), read_timeout(), read_timeout()])
    engine = _engine()

    with pytest.raises(RuntimeError, match="badao_shaoye"):
        await engine._call_dashscope_minimax_http(
            model="MiniMax/speech-2.8-hd",
            api_key="test-key",
            text="这是一段旁白。",
            voice="badao_shaoye",
            voice_params={"speed": 1.0, "volume": 50, "pitch": 0},
        )

    client = _FakeAsyncClient.instances[-1]
    assert len(client.calls) == aliyun_mixin.MINIMAX_TTS_MAX_ATTEMPTS
    assert all(voice == "badao_shaoye" for voice in client.calls)


@pytest.mark.asyncio
async def test_minimax_retries_on_server_error_then_succeeds(monkeypatch):
    """5xx / 429 属于可重试瞬时错误，重试后成功。"""
    _install_fake_httpx(
        monkeypatch,
        [
            _FakeResponse(status_code=500, text="server error"),
            _FakeResponse(status_code=429, text="rate limited"),
            _FakeResponse(status_code=200, json_data=_success_body()),
        ],
    )
    engine = _engine()

    audio = await engine._call_dashscope_minimax_http(
        model="MiniMax/speech-2.8-hd",
        api_key="test-key",
        text="这是一段旁白。",
        voice="badao_shaoye",
        voice_params={"speed": 1.0, "volume": 50, "pitch": 0},
    )

    assert audio == b"fake-audio"
    client = _FakeAsyncClient.instances[-1]
    assert len(client.calls) == 3
    assert all(voice == "badao_shaoye" for voice in client.calls)


@pytest.mark.asyncio
async def test_minimax_auth_error_does_not_retry(monkeypatch):
    """401/403 鉴权等永久性错误立即抛出，不重试。"""
    _install_fake_httpx(
        monkeypatch,
        [_FakeResponse(status_code=401, text="unauthorized")],
    )
    engine = _engine()

    with pytest.raises(RuntimeError, match="401"):
        await engine._call_dashscope_minimax_http(
            model="MiniMax/speech-2.8-hd",
            api_key="bad-key",
            text="这是一段旁白。",
            voice="badao_shaoye",
            voice_params={"speed": 1.0, "volume": 50, "pitch": 0},
        )

    client = _FakeAsyncClient.instances[-1]
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_minimax_empty_audio_response_is_retried(monkeypatch):
    """成功状态但响应体为空：视为临时不可用，重试直到耗尽预算。"""
    _install_fake_httpx(
        monkeypatch,
        [
            _FakeResponse(status_code=200, json_data={"output": {}}),
            _FakeResponse(status_code=200, json_data={"output": {}}),
            _FakeResponse(status_code=200, json_data={"output": {}}),
        ],
    )
    engine = _engine()

    with pytest.raises(RuntimeError):
        await engine._call_dashscope_minimax_http(
            model="MiniMax/speech-2.8-hd",
            api_key="test-key",
            text="这是一段旁白。",
            voice="badao_shaoye",
            voice_params={"speed": 1.0, "volume": 50, "pitch": 0},
        )

    client = _FakeAsyncClient.instances[-1]
    assert len(client.calls) == aliyun_mixin.MINIMAX_TTS_MAX_ATTEMPTS


def test_minimax_voice_candidates_only_returns_requested_voice():
    """音色一致性：候选列表只返回精确请求音色，不做任何推测别名变换。"""
    engine = _engine()
    assert engine._build_minimax_voice_candidates("badao_shaoye") == ["badao_shaoye"]
    assert engine._build_minimax_voice_candidates("female-qn-shaonv") == ["female-qn-shaonv"]
    assert engine._build_minimax_voice_candidates("mmx_0123456789abcdef") == ["mmx_0123456789abcdef"]


def _make_gate_harness(synthesis_result):
    from app.services.audiobook.engine_pkg._audio_from_script_mixin import AudioFromScriptMixin
    from app.services.audiobook.engine_pkg._base import AudiobookEngineBase
    from app.services.audiobook.task_tracker import TaskTracker

    class _RecordingMixer:
        def __init__(self):
            self.mix_calls = 0

        def mix_chapter(self, *args, **kwargs):
            self.mix_calls += 1
            return b"mixed-audio"

    class Harness(AudioFromScriptMixin, AudiobookEngineBase):
        def __init__(self):
            self.task_tracker = TaskTracker()
            self.audio_director = SimpleNamespace(
                formulate_strategy=lambda **kwargs: SimpleNamespace(
                    style=SimpleNamespace(value="cinematic"),
                    sound_effect_density="medium",
                    music_density="medium",
                )
            )
            self.script_adapter = SimpleNamespace(strategy=None)
            self._audio_fx_config = {}
            self._last_effect_timeline = None
            self._last_music_timeline = None
            self.audio_mixer = _RecordingMixer()
            self._synthesis_result = synthesis_result

        async def _parallel_design(self, *args, **kwargs):
            return {}, 0, 0

        def _assign_voices(self, script_segments):
            return None

        def _attach_render_plan_metadata(self, temp_segment_cache, metadata):
            # 真实引擎由 TTSMixin 提供；这里模拟把失败索引/错误拷入缓存。
            cache = temp_segment_cache if isinstance(temp_segment_cache, dict) else {}
            if isinstance(metadata, dict):
                for key in (
                    "render_plan",
                    "failed_segment_indices",
                    "failed_segment_errors",
                    "segment_statuses",
                ):
                    if key in metadata:
                        cache[key] = metadata[key]
            return cache

        async def _synthesize_segments_with_resume(self, *args, **kwargs):
            return self._synthesis_result

    return Harness()


@pytest.mark.asyncio
async def test_segments_missing_blocks_mixing_and_maps_source_indices():
    """存在缺失片段时停止混音，返回 segments_missing 并映射回源剧本索引。"""
    synthesis_result = {
        "audio_list": [b"ok", b""],
        "reused_indices": [],
        "synthesized_count": 1,
        "failed_segment_indices": [1],
        "failed_segment_errors": {
            "1": {"error_type": "ReadTimeout", "error_message": "MiniMax request timed out"}
        },
        "render_plan": [
            {
                "index": 0,
                "source_segment_indices": [0],
                "speaker": "旁白",
                "voice_id": "badao_shaoye",
                "segment_type": "narration",
                "text_preview": "第一段。",
            },
            {
                "index": 1,
                "source_segment_indices": [1],
                "speaker": "旁白",
                "voice_id": "badao_shaoye",
                "segment_type": "narration",
                "text_preview": "第二段。",
            },
        ],
    }
    harness = _make_gate_harness(synthesis_result)

    result = await harness.generate_chapter_audio_from_script(
        script_segments_data=[
            {"type": "narration", "text": "第一段。", "speaker": "旁白", "emotion": "neutral"},
            {"type": "narration", "text": "第二段。", "speaker": "旁白", "emotion": "neutral"},
        ],
        chapter_id=1,
        novel_genre="玄幻",
        enable_quality_review=False,
    )

    assert result["success"] is False
    assert result["error"] == "segments_missing"
    # 章节完整性：缺失片段时绝不调用混音。
    assert harness.audio_mixer.mix_calls == 0
    assert result["failed_segment_indices"] == [1]
    missing = result["missing_segments"]
    assert len(missing) == 1
    assert missing[0]["index"] == 1
    assert missing[0]["source_segment_indices"] == [1]
    assert missing[0]["speaker"] == "旁白"
    assert missing[0]["voice"] == "badao_shaoye"
    assert missing[0]["error_type"] == "ReadTimeout"
