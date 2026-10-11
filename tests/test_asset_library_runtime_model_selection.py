from __future__ import annotations

import pytest


def test_resolve_registered_runtime_model_id_prefers_payload_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import asset_library

    monkeypatch.setenv("DREAMWEAVER_T2I_MODEL", "env-image-model")
    monkeypatch.setattr(
        asset_library,
        "get_model_info",
        lambda model_id: {"id": model_id} if model_id in {"runtime-image-model", "env-image-model", "qwen-image-3.0-pro"} else None,
    )

    resolved = asset_library._resolve_registered_runtime_model_id(
        {"adapter": "runtime-image-model"},
        key="adapter",
        env_name="DREAMWEAVER_T2I_MODEL",
        default="qwen-image-3.0-pro",
    )

    assert resolved == "runtime-image-model"


def test_resolve_registered_runtime_model_id_skips_unregistered_payload_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import asset_library

    monkeypatch.setenv("DREAMWEAVER_VLM_ADAPTER", "env-vlm-model")
    monkeypatch.setattr(
        asset_library,
        "get_model_info",
        lambda model_id: {"id": model_id} if model_id in {"env-vlm-model", "qwen3_vl_plus"} else None,
    )

    resolved = asset_library._resolve_registered_runtime_model_id(
        {"vlm_adapter": "missing-vlm-model"},
        key="vlm_adapter",
        env_name="DREAMWEAVER_VLM_ADAPTER",
        default="qwen3_vl_plus",
    )

    assert resolved == "env-vlm-model"
