"""Mureka instrumental 契约测试。

依据 2026-10-11 官方文档与真实调用确证：
- /v1/instrumental/generate 只有 model / n / prompt / instrumental_id / stream 五个入参，没有 duration；
- n 缺省为 2 且按生成数量计费，必须显式下发 n=1；
- 终态失败除 failed 外还有 timeouted / cancelled，必须走失败分支而不是白等轮询超时。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from adapters._shared import (
    MUREKA_FAILED_STATUSES,
    MUREKA_INSTRUMENTAL_MODEL,
    MUREKA_INSTRUMENTAL_N,
    MUREKA_PENDING_STATUSES,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _StopAfterCreate(Exception):
    """占位异常：拿到 create 载荷后立即终止流程。"""


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _make_request():
    from app.services.audiobook.ai_music import MusicGenerationRequest, MusicStyle

    return MusicGenerationRequest(
        prompt="tense underscore",
        style=MusicStyle.AMBIENT,
        duration=30,
        tempo="medium",
        mood="tense",
        instruments=[],
        variant=0,
        bucket="underscore:tense",
    )


def _make_client(tmp_path):
    from app.services.audiobook.ai_music import MurekaO1Client

    return MurekaO1Client(api_key="test-key", enable_cache=False, cache_dir=str(tmp_path / "music_cache"))


def test_call_mureka_api_payload_pins_model_and_single_candidate(tmp_path, monkeypatch):
    """载荷只能是 prompt/model/n：不发 n 会出两首并扣双倍，发 duration 上游不认。"""
    import asyncio

    from app.services.audiobook import ai_music as ai_music_module

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse({"id": "task-1", "status": "preparing"})

    def fake_get(url, headers=None, timeout=None):
        raise _StopAfterCreate("stop-after-create")

    monkeypatch.setattr(ai_music_module.requests, "post", fake_post)
    monkeypatch.setattr(ai_music_module.requests, "get", fake_get)

    client = _make_client(tmp_path)
    # _call_mureka_api 把异常统一包成 RuntimeError，这里只关心 create 阶段已经发出的载荷
    with pytest.raises(RuntimeError, match="stop-after-create"):
        asyncio.run(client._call_mureka_api(_make_request()))

    assert captured["url"].endswith("/v1/instrumental/generate")
    assert captured["payload"]["model"] == "mureka-9.5"
    assert captured["payload"]["n"] == 1
    assert "duration" not in captured["payload"]
    assert set(captured["payload"]) == {"prompt", "model", "n"}


@pytest.mark.parametrize("status", ["failed", "timeouted", "cancelled"])
def test_call_mureka_api_fails_fast_on_terminal_status(tmp_path, monkeypatch, status):
    """timeouted/cancelled 是终态，必须立即抛错并带上 failed_reason。"""
    import asyncio

    from app.services.audiobook import ai_music as ai_music_module

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResponse({"id": "task-1", "status": "preparing"})

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse({"status": status, "failed_reason": "上游判定该任务已结束"})

    monkeypatch.setattr(ai_music_module.requests, "post", fake_post)
    monkeypatch.setattr(ai_music_module.requests, "get", fake_get)

    client = _make_client(tmp_path)
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(client._call_mureka_api(_make_request()))

    assert f"任务失败({status})" in str(exc_info.value)
    assert "上游判定该任务已结束" in str(exc_info.value)


def test_shared_status_sets_match_measured_upstream_states():
    """共享状态集合必须覆盖实测枚举，且成功态不得混入失败集合。"""
    assert {"preparing", "queued", "running", "streaming", "reviewing"} <= set(MUREKA_PENDING_STATUSES)
    assert {"failed", "timeouted", "cancelled"} <= set(MUREKA_FAILED_STATUSES)
    assert set(MUREKA_PENDING_STATUSES).isdisjoint(MUREKA_FAILED_STATUSES)
    assert "succeeded" not in MUREKA_PENDING_STATUSES
    assert "succeeded" not in MUREKA_FAILED_STATUSES


def test_adapter_generate_payload_and_terminal_status(monkeypatch):
    """适配器与后端服务共用同一份载荷与终态口径。"""
    from adapters.mureka import instrumental as instrumental_module
    from adapters.mureka.instrumental import MurekaO1InstrumentalAdapter

    monkeypatch.setenv("MUREKA_API_KEY", "test-key")
    monkeypatch.setattr(instrumental_module.time, "sleep", lambda seconds: None)

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse({"id": "task-1", "status": "preparing"})

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse({"status": "timeouted", "failed_reason": "task timeouted by provider"})

    monkeypatch.setattr(instrumental_module.requests, "post", fake_post)
    monkeypatch.setattr(instrumental_module.requests, "get", fake_get)

    result = MurekaO1InstrumentalAdapter(
        MurekaO1InstrumentalAdapter.get_model_spec()
    ).generate(prompt="tense underscore")

    assert captured["payload"]["model"] == "mureka-9.5"
    assert captured["payload"]["n"] == 1
    assert "duration" not in captured["payload"]
    assert result.success is False
    assert "timeouted" in result.error


def _load_card(relative_path: str, model_id: str) -> dict:
    data = yaml.safe_load((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    entries = data["audio_models"] if relative_path.endswith("llm_models.yaml") else data["models"]
    for entry in entries:
        if entry.get("id") == model_id:
            return entry
    raise AssertionError(f"{relative_path} 中缺少模型卡 {model_id}")


def test_model_cards_match_shared_upstream_contract():
    """两张档案卡必须与 adapters/_shared 的上游事实保持一致。"""
    card = _load_card("config/models.yaml", "mureka-o1-instrumental")
    contract = card["detailed_specs"]["music_generation"]["api_contract"]

    assert contract["model_sent"] == MUREKA_INSTRUMENTAL_MODEL
    assert contract["auto_resolves_to"] == MUREKA_INSTRUMENTAL_MODEL
    assert MUREKA_INSTRUMENTAL_MODEL in contract["model_enum"]

    # n 缺省 2，本地必须显式下发更小的值
    assert contract["n_default"] == 2
    low, high = contract["n_range"]
    assert low <= MUREKA_INSTRUMENTAL_N <= high
    assert MUREKA_INSTRUMENTAL_N < contract["n_default"]

    assert contract["has_duration_field"] is False
    assert "duration" not in contract["request_fields"]
    assert card["constraints"]["max_prompt_length"] == contract["max_prompt_chars"] == 1024

    assert set(contract["status_non_terminal"]) <= set(MUREKA_PENDING_STATUSES)
    assert set(contract["status_terminal_failed"]) <= set(MUREKA_FAILED_STATUSES)


def test_hub_card_marks_prompt_composed_controls_as_emulated():
    """统一注册中心档案不得把 style/mood/tempo 说成上游原生入参。"""
    hub_card = _load_card("config/llm_models.yaml", "mureka-o1-instrumental")
    levels = {cap["name"]: cap["level"] for cap in hub_card["capabilities"]}

    assert levels["music_generation"] == "native"
    assert levels["style_control"] == "emulated"
