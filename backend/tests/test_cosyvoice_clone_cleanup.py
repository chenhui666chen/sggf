from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_string = str(path)
    if path_string not in sys.path:
        sys.path.insert(0, path_string)

from app.services.audiobook import cosyvoice_clone_client


def test_custom_voice_delete_allowlist_excludes_system_and_unknown_ids() -> None:
    assert cosyvoice_clone_client.is_cosyvoice_custom_voice_id(
        "cosyvoice-v3.5-plus-vd-test"
    )
    assert cosyvoice_clone_client.is_cosyvoice_custom_voice_id(
        "cosyvoice-v3-plus-vlegacy-test"
    )
    assert not cosyvoice_clone_client.is_cosyvoice_custom_voice_id("longanyang")
    assert not cosyvoice_clone_client.is_cosyvoice_custom_voice_id("arbitrary-voice-id")


def test_delete_cosyvoice_clone_accepts_known_legacy_custom_id(monkeypatch) -> None:
    calls: list[str] = []

    class FakeVoiceEnrollmentService:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "test-key"

        def delete_voice(self, *, voice_id: str) -> None:
            calls.append(voice_id)

    fake_module = ModuleType("dashscope.audio.tts_v2")
    fake_module.VoiceEnrollmentService = FakeVoiceEnrollmentService
    monkeypatch.setitem(sys.modules, "dashscope.audio.tts_v2", fake_module)
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "_require_dashscope_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "remove_clone_display_name",
        lambda voice_id: calls.append(f"remove:{voice_id}"),
    )
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "invalidate_cosyvoice_clone_cache",
        lambda: calls.append("invalidate"),
    )

    voice_id = "cosyvoice-v3-plus-vlegacy-test"
    result = cosyvoice_clone_client.delete_cosyvoice_clone(voice_id=voice_id)

    assert result == {"voice_id": voice_id, "deleted": True}
    assert calls == [voice_id, f"remove:{voice_id}", "invalidate"]


def test_delete_cosyvoice_clone_rejects_unknown_id_before_sdk_call(monkeypatch) -> None:
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "_require_dashscope_api_key",
        lambda: pytest.fail("SDK must not be reached for an unknown ID"),
    )

    with pytest.raises(cosyvoice_clone_client.CosyVoiceCloneError):
        cosyvoice_clone_client.delete_cosyvoice_clone(voice_id="longanyang")


def test_batch_delete_can_preserve_local_mapping_until_all_cloud_calls_succeed(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FakeVoiceEnrollmentService:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "test-key"

        def delete_voice(self, *, voice_id: str) -> None:
            calls.append(voice_id)

    fake_module = ModuleType("dashscope.audio.tts_v2")
    fake_module.VoiceEnrollmentService = FakeVoiceEnrollmentService
    monkeypatch.setitem(sys.modules, "dashscope.audio.tts_v2", fake_module)
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "_require_dashscope_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "remove_clone_display_name",
        lambda _voice_id: pytest.fail("local mapping must remain during the cloud phase"),
    )
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "invalidate_cosyvoice_clone_cache",
        lambda: calls.append("invalidate"),
    )

    voice_id = "cosyvoice-v3.5-plus-vd-batch-test"
    result = cosyvoice_clone_client.delete_cosyvoice_clone(
        voice_id=voice_id,
        remove_local_mapping=False,
    )

    assert result == {"voice_id": voice_id, "deleted": True}
    assert calls == [voice_id, "invalidate"]


def test_batch_cleanup_can_treat_explicit_resource_not_exist_as_idempotent_success(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FakeVoiceEnrollmentService:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "test-key"

        def delete_voice(self, *, voice_id: str) -> None:
            calls.append(voice_id)
            raise RuntimeError(
                "Code: BadRequest.ResourceNotExist, Error Message: "
                "The Required resource not exist"
            )

    fake_module = ModuleType("dashscope.audio.tts_v2")
    fake_module.VoiceEnrollmentService = FakeVoiceEnrollmentService
    monkeypatch.setitem(sys.modules, "dashscope.audio.tts_v2", fake_module)
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "_require_dashscope_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "remove_clone_display_name",
        lambda _voice_id: pytest.fail("batch cleanup must preserve the local mapping"),
    )
    monkeypatch.setattr(
        cosyvoice_clone_client,
        "invalidate_cosyvoice_clone_cache",
        lambda: calls.append("invalidate"),
    )

    voice_id = "cosyvoice-v3-plus-valready-absent"
    result = cosyvoice_clone_client.delete_cosyvoice_clone(
        voice_id=voice_id,
        remove_local_mapping=False,
        missing_ok=True,
    )

    assert result == {
        "voice_id": voice_id,
        "deleted": False,
        "already_absent": True,
    }
    assert calls == [voice_id, "invalidate"]
