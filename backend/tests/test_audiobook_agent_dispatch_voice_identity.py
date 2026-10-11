import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for import_root in (PROJECT_ROOT, ROOT_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import app.services.audiobook.agent_dispatch_client as dispatch_module
from app.services.audiobook.agent_dispatch_client import AgentSmartDispatchClient


class _NeverRouter:
    def route_with_fallback_by_strategy(self, **_kwargs):
        raise AssertionError("固定 voice_id 缺少所属模型时不得进入跨模型路由")


class _CapturingEngine:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            metadata={"audio_bytes": b"unit-audio"},
            outputs=[],
            model_id=kwargs["routing_result"].selected_model.id,
            fallback_chain=None,
            latency=0.01,
            error=None,
            trace={},
        )


def test_dispatch_rejects_fixed_voice_without_its_model() -> None:
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()

    result = client.synthesize(text="别回头。", voice_id="fixed-voice")

    assert result.success is False
    assert "固定音色必须绑定所属 TTS 模型" in str(result.error)


def test_dispatch_pins_fixed_voice_model_and_sanitizes_identity_controls(monkeypatch) -> None:
    model_spec = SimpleNamespace(id="seed-tts-2.0-expressive")
    monkeypatch.setattr(
        dispatch_module.model_registry,
        "get_spec",
        lambda model_id: model_spec if model_id == model_spec.id else None,
    )
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()
    client._engine = _CapturingEngine()

    result = client.synthesize(
        text="别回头。",
        voice_id="fixed-voice",
        tts_model="seed-tts-2.0-expressive",
        pitch=0.8,
        pitch_ratio=0.7,
        voice_description="苍老低沉男声",
        instructions="改成老爷爷声，语速缓慢，重读回字。",
        performance_notes="因重伤而声音沙哑，句尾拖长。",
    )

    assert result.success is True
    call = client._engine.calls[0]
    assert call["use_fallback"] is False
    assert call["max_attempts"] == 1
    assert call["routing_result"].selected_model.id == "seed-tts-2.0-expressive"
    assert call["routing_result"].fallback_models == []

    extra = call["task"].extra
    assert extra["voice_id"] == "fixed-voice"
    assert extra["tts_model"] == "seed-tts-2.0-expressive"
    assert "pitch" not in extra
    assert "pitch_ratio" not in extra
    assert "voice_description" not in extra
    assert "老爷爷声" not in extra["instructions"]
    assert "语速缓慢" in extra["instructions"]
    assert "因重伤，仅在原音色基础上轻微、短暂表现沙哑" in extra["performance_notes"]


def test_dispatch_treats_saved_mimo_design_asset_as_fixed_voice(monkeypatch) -> None:
    from app.services.audiobook import mimo_voice_assets

    model_id = "mimo-v2.5-tts-voicedesign"
    model_spec = SimpleNamespace(id=model_id)
    monkeypatch.setattr(
        dispatch_module.model_registry,
        "get_spec",
        lambda requested: model_spec if requested == model_id else None,
    )
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()
    client._engine = _CapturingEngine()
    asset_calls = []

    def fake_resolve_asset(asset_id, *, owner_user_id=None):
        asset_calls.append((asset_id, owner_user_id))
        return {
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "服务端固定青年女性声线",
            "voice_description": "服务端固定青年女性声线",
        }

    monkeypatch.setattr(
        mimo_voice_assets,
        "resolve_mimo_voice_asset_tts_params",
        fake_resolve_asset,
    )

    result = client.synthesize(
        text="别回头。",
        voice_id="mimo_design:asset-1",
        tts_model=model_id,
        owner_user_id=7,
        mimo_voice_asset_id="asset-1",
        voice_design_prompt="客户端伪造的老人声",
        voice_description="客户端伪造的老人声",
        pitch=20,
        instructions="改成老人声，语速缓慢，句尾拖长。",
    )

    assert result.success is True
    extra = client._engine.calls[0]["task"].extra
    assert asset_calls == [("asset-1", 7)]
    assert "pitch" not in extra
    assert "voice_description" not in extra
    assert "owner_user_id" not in extra
    assert extra["voice_design_prompt"] == "服务端固定青年女性声线"
    assert "老人声" not in extra["instructions"]
    assert "语速缓慢" in extra["instructions"]


def test_dispatch_rejects_saved_mimo_design_asset_without_owner_context(monkeypatch) -> None:
    model_id = "mimo-v2.5-tts-voicedesign"
    model_spec = SimpleNamespace(id=model_id)
    monkeypatch.setattr(
        dispatch_module.model_registry,
        "get_spec",
        lambda requested: model_spec if requested == model_id else None,
    )
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()
    client._engine = _CapturingEngine()

    result = client.synthesize(
        text="别回头。",
        voice_id="mimo_design:asset-1",
        tts_model=model_id,
        voice_design_prompt="客户端伪造的老人声",
        instructions="语速缓慢，句尾拖长。",
    )

    assert result.success is False
    assert "所有者上下文" in str(result.error)
    assert client._engine.calls == []


def test_dispatch_recognizes_saved_mimo_asset_from_positional_voice_id(monkeypatch) -> None:
    from app.services.audiobook import mimo_voice_assets

    model_id = "mimo-v2.5-tts-voicedesign"
    model_spec = SimpleNamespace(id=model_id)
    monkeypatch.setattr(
        dispatch_module.model_registry,
        "get_spec",
        lambda requested: model_spec if requested == model_id else None,
    )
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()
    client._engine = _CapturingEngine()
    monkeypatch.setattr(
        mimo_voice_assets,
        "resolve_mimo_voice_asset_tts_params",
        lambda asset_id, *, owner_user_id=None: {
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "服务端固定青年女性声线",
            "voice_description": "服务端固定青年女性声线",
        },
    )

    result = client.synthesize(
        text="别回头。",
        voice_id="mimo_design:asset-1",
        tts_model=model_id,
        owner_user_id=7,
        voice_design_prompt="客户端伪造的老人声",
        voice_description="客户端伪造的老人声",
        pitch=20,
        provider_prompt_snapshot={"delivery_plan": {"pitch": "lower"}},
        instructions="改成老人声，语速缓慢，句尾拖长。",
    )

    assert result.success is True
    extra = client._engine.calls[0]["task"].extra
    assert "pitch" not in extra
    assert "voice_description" not in extra
    assert "provider_prompt_snapshot" not in extra
    assert extra["voice_design_prompt"] == "服务端固定青年女性声线"
    assert "老人声" not in extra["instructions"]
    assert "语速缓慢" in extra["instructions"]


def test_dispatch_uses_nested_mimo_asset_identity_for_all_prompt_layers(monkeypatch) -> None:
    from app.services.audiobook import mimo_voice_assets

    model_id = "mimo-v2.5-tts-voicedesign"
    model_spec = SimpleNamespace(id=model_id)
    monkeypatch.setattr(
        dispatch_module.model_registry,
        "get_spec",
        lambda requested: model_spec if requested == model_id else None,
    )
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()
    client._engine = _CapturingEngine()
    monkeypatch.setattr(
        mimo_voice_assets,
        "resolve_mimo_voice_asset_tts_params",
        lambda asset_id, *, owner_user_id=None: {
            "mimo_voice_asset_id": "asset-2",
            "voice_design_prompt": "服务端固定成年男性声线",
            "voice_description": "服务端固定成年男性声线",
        },
    )

    result = client.synthesize(
        text="别回头。",
        tts_model=model_id,
        owner_user_id=7,
        pitch=20,
        voice_description="顶层伪造的老人声",
        provider_prompt_snapshot={"delivery_plan": {"pitch": "lower"}},
        instructions="改成老人声，语速缓慢。",
        voice_params={
            "mimo_voice_asset_id": "asset-2",
            "pitch_ratio": 0.7,
            "voice_description": "嵌套伪造的儿童声",
            "provider_prompt_snapshot": {"delivery_plan": {"pitch": "higher"}},
            "instructions": "改成儿童声，句尾拖长。",
        },
    )

    assert result.success is True
    extra = client._engine.calls[0]["task"].extra
    assert "pitch" not in extra
    assert "voice_description" not in extra
    assert "provider_prompt_snapshot" not in extra
    assert "老人声" not in extra["instructions"]
    assert "语速缓慢" in extra["instructions"]

    nested = extra["voice_params"]
    assert nested["mimo_voice_asset_id"] == "asset-2"
    assert nested["voice_design_prompt"] == "服务端固定成年男性声线"
    assert "pitch_ratio" not in nested
    assert "voice_description" not in nested
    assert "provider_prompt_snapshot" not in nested
    assert "儿童声" not in nested["instructions"]
    assert "句尾拖长" in nested["instructions"]


def test_dispatch_without_fixed_voice_keeps_generic_routing() -> None:
    selected = SimpleNamespace(id="qwen-audio-3.1-tts-flash")
    routing_result = SimpleNamespace(
        selected_model=selected,
        fallback_models=[SimpleNamespace(id="cosyvoice-v3.5-plus")],
        to_dict=lambda: {},
    )

    class _Router:
        def route_with_fallback_by_strategy(self, **_kwargs):
            return routing_result

    client = AgentSmartDispatchClient()
    client._router = _Router()
    client._engine = _CapturingEngine()

    result = client.synthesize(text="系统测试。")

    assert result.success is True
    call = client._engine.calls[0]
    assert call["use_fallback"] is True
    assert call["max_attempts"] == 3


def test_batch_dispatch_binds_each_fixed_voice_to_its_own_model(monkeypatch) -> None:
    specs = {
        model_id: SimpleNamespace(id=model_id)
        for model_id in (
            "seed-tts-2.0-expressive",
            "qwen-audio-3.1-tts-flash",
        )
    }
    monkeypatch.setattr(
        dispatch_module.model_registry,
        "get_spec",
        lambda model_id: specs.get(model_id),
    )
    client = AgentSmartDispatchClient()
    client._router = _NeverRouter()
    client._engine = _CapturingEngine()

    results = client.synthesize_batch(
        texts=["第一句。", "第二句。"],
        voice_ids=["seed-voice", "qwen-voice"],
        tts_models=["seed-tts-2.0-expressive", "qwen-audio-3.1-tts-flash"],
        max_concurrent=1,
        instructions="语速缓慢，重读关键词。",
    )

    assert all(result.success for result in results)
    assert [
        call["routing_result"].selected_model.id
        for call in client._engine.calls
    ] == ["seed-tts-2.0-expressive", "qwen-audio-3.1-tts-flash"]
    assert all(call["use_fallback"] is False for call in client._engine.calls)
