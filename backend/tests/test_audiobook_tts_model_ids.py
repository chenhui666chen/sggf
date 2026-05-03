import asyncio
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import routes_tts
from app.api.v1.audiobook_api.routes_tts import list_tts_models
from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    SUPPORTED_AUDIOBOOK_TTS_MODELS,
    get_audiobook_tts_runtime_model_id,
    get_audiobook_tts_model_price_per_10k,
    is_supported_audiobook_tts_model,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.narration_styles import get_all_narration_styles
from app.services.audiobook.tts_engine_pkg import TTSEngine
from app.services.audiobook.voice_catalog import load_voice_catalog_for_model
from app.services.audiobook.voice_manager_factory import create_voice_manager, get_model_for_voice, list_supported_models
from app.services.audiobook.voice_manager_minimax import MiniMaxVoiceManager
from core.model_resolution import normalize_model_id


def test_audiobook_tts_model_normalization_keeps_business_model_ids() -> None:
    assert normalize_audiobook_tts_model("MiniMax/speech-2.8-hd") == MINIMAX_SPEECH_28_HD_MODEL
    assert normalize_audiobook_tts_model("MiniMax/speech-2.8-turbo") == MINIMAX_SPEECH_28_TURBO_MODEL
    assert normalize_audiobook_tts_model("minimax-speech-2.8") == MINIMAX_SPEECH_28_HD_MODEL
    assert normalize_audiobook_tts_model("qwen3-tts-flash") == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert normalize_audiobook_tts_model("qwen3-tts-plus") == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert is_supported_audiobook_tts_model("MiniMax/speech-2.8-hd") is True
    assert is_supported_audiobook_tts_model("unknown-tts-model") is False
    assert normalize_model_id("MiniMax/speech-2.8-hd") == "MiniMax/speech-2.8-hd"
    assert get_audiobook_tts_runtime_model_id(MINIMAX_SPEECH_28_HD_MODEL) == "MiniMax/speech-2.8-hd"
    assert get_audiobook_tts_runtime_model_id(MINIMAX_SPEECH_28_TURBO_MODEL) == "MiniMax/speech-2.8-turbo"


def test_minimax_voice_catalog_accepts_registry_model_id_alias() -> None:
    catalog = load_voice_catalog_for_model("MiniMax/speech-2.8-hd")
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == MINIMAX_SPEECH_28_HD_MODEL
    assert "male-qn-qingse" in voice_ids
    assert "Cherry" not in voice_ids


def test_voice_manager_factory_keeps_minimax_manager_after_registry_alias() -> None:
    manager = create_voice_manager("MiniMax/speech-2.8-hd")

    assert isinstance(manager, MiniMaxVoiceManager)
    narrator_params = manager.get_narrator_voice().get_tts_params("calm")
    assigned_params = manager.assign_voice("Alice", {"gender": "female"}).get_tts_params("happy")

    assert narrator_params["speaker"] == "male-qn-qingse"
    assert assigned_params["speaker"].startswith("female-")
    assert get_model_for_voice("male-qn-qingse") == MINIMAX_SPEECH_28_HD_MODEL


def test_supported_tts_models_do_not_advertise_unregistered_qwen_plus() -> None:
    supported = list_supported_models()

    assert "qwen3-tts-plus" not in supported
    assert supported == [
        DEFAULT_AUDIOBOOK_TTS_MODEL,
        "cosyvoice-v3.5-plus",
        MINIMAX_SPEECH_28_HD_MODEL,
        MINIMAX_SPEECH_28_TURBO_MODEL,
    ]


def test_narration_style_supported_models_are_registered() -> None:
    for style in get_all_narration_styles():
        assert set(style["supported_models"]).issubset(SUPPORTED_AUDIOBOOK_TTS_MODELS)


def test_tts_engine_normalizes_legacy_model_on_init() -> None:
    engine = TTSEngine(model="qwen3-tts-plus")

    assert engine.model == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert engine._is_qwen_instruct_model() is True


def test_tts_models_endpoint_uses_catalog_counts_and_supported_models(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", lambda **_: ([], {}))

    payload = asyncio.run(list_tts_models(current_user=object()))
    models = {model["id"]: model for model in payload["models"]}

    assert "qwen3-tts-plus" not in models
    assert MINIMAX_SPEECH_28_HD_MODEL in models
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["price_per_10k"] == get_audiobook_tts_model_price_per_10k(
        MINIMAX_SPEECH_28_HD_MODEL
    )
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_status"] == "ready"
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_model_id"] == "MiniMax/speech-2.8-hd"
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_error"] is None
    assert models["cosyvoice-v3.5-plus"]["capabilities"]["requires_custom_voice"] is True
    assert models["cosyvoice-v3.5-plus"]["capabilities"]["supports_voice_clone"] is True
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["capabilities"]["has_system_voices"] is True
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_status"] == "ready"
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_error"] is None
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_note"]
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["voice_count"] == load_voice_catalog_for_model(
        DEFAULT_AUDIOBOOK_TTS_MODEL
    )["meta"]["voice_count"]
    assert f"{models[DEFAULT_AUDIOBOOK_TTS_MODEL]['voice_count']} 个可用音色" in models[
        DEFAULT_AUDIOBOOK_TTS_MODEL
    ]["description"]
    assert f"{models[MINIMAX_SPEECH_28_HD_MODEL]['voice_count']} 音色" in models[
        MINIMAX_SPEECH_28_HD_MODEL
    ]["features"]


def test_tts_models_endpoint_keeps_model_when_voice_catalog_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", lambda **_: ([], {}))
    original_loader = routes_tts.load_voice_catalog_for_model

    def fail_minimax_catalog(model: str):
        if model == MINIMAX_SPEECH_28_TURBO_MODEL:
            raise RuntimeError("broken catalog")
        return original_loader(model)

    monkeypatch.setattr(routes_tts, "load_voice_catalog_for_model", fail_minimax_catalog)

    payload = asyncio.run(list_tts_models(current_user=object()))
    models = {model["id"]: model for model in payload["models"]}

    assert MINIMAX_SPEECH_28_TURBO_MODEL in models
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["catalog_status"] == "unavailable"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["catalog_error"] == "音色目录加载失败，请检查后端 voice catalog 配置"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["voice_count"] == 0
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_status"] == "ready"


def test_tts_models_endpoint_exposes_runtime_registration_status(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", lambda **_: ([], {}))
    original_runtime = routes_tts.get_media_runtime()

    class RuntimeProxy:
        def select_model(self, **kwargs):
            if kwargs.get("preferred_model") == "MiniMax/speech-2.8-turbo":
                raise ValueError("runtime missing")
            return original_runtime.select_model(**kwargs)

    monkeypatch.setattr(routes_tts, "get_media_runtime", lambda: RuntimeProxy())

    payload = asyncio.run(list_tts_models(current_user=object()))
    models = {model["id"]: model for model in payload["models"]}

    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["runtime_model_id"] == "MiniMax/speech-2.8-turbo"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["runtime_status"] == "unavailable"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["runtime_error"] == "TTS 运行时模型未注册或不可用"
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_status"] == "ready"
