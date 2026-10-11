from __future__ import annotations

import sys
import asyncio
import base64
import json
import math
import struct
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


EXPECTED_CASE_IDS = (
    "multi_character_pressure",
    "phone_confrontation",
    "three_voice_argument",
    "single_voice_memory",
    "pure_narration",
)


def _wav_bytes() -> bytes:
    sample_rate = 16000
    frames = bytearray()
    for index in range(sample_rate):
        sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        case = get_seed_scene_test_case_from_prompt(prompt)
        return {
            "audio": base64.b64encode(_wav_bytes()).decode("ascii"),
            "audio_format": "wav",
            "subtitle": {"sentences": [{"text": text} for text in case["expected_texts"]]},
            "duration": 1.0,
            "original_duration": 1.0,
            "request_id": "provider-request-1",
        }


def get_seed_scene_test_case_from_prompt(prompt: str) -> dict:
    from app.services.audiobook.seed_scene_test_unit import build_seed_scene_test_catalog

    for case in build_seed_scene_test_catalog():
        if any(variant["prompt"] == prompt for variant in case["variants"]):
            return case
    raise AssertionError("unknown test prompt")


def test_seed_scene_test_catalog_defines_five_traceable_scene_types() -> None:
    from app.services.audiobook.seed_scene_test_unit import build_seed_scene_test_catalog

    catalog = build_seed_scene_test_catalog()

    assert tuple(item["id"] for item in catalog) == EXPECTED_CASE_IDS
    assert {item["category"] for item in catalog} == {
        "多人压迫动作",
        "电话悬疑对话",
        "三参考音色争吵",
        "单人伤感回忆",
        "纯旁白基线",
    }
    for item in catalog:
        assert item["model"] == "seed-audio-1.0"
        assert item["repeat_count"] == 3
        assert 1 <= len(item["expected_texts"])
        assert 1 <= len(item["reference_slots"]) <= 3
        assert [variant["id"] for variant in item["variants"]] == [
            "described_voices",
            "reference_voices",
        ]
        for variant in item["variants"]:
            prompt = variant["prompt"]
            assert len(prompt) <= 3000
            assert "对白始终清晰位于前景" in prompt
            assert "不新增、删减或改写台词" in prompt
            assert all(text in prompt for text in item["expected_texts"])


def test_seed_scene_test_catalog_keeps_blind_labels_and_reference_mapping_distinct() -> None:
    from app.services.audiobook.seed_scene_test_unit import get_seed_scene_test_case

    case = get_seed_scene_test_case("phone_confrontation")
    described, referenced = case["variants"]

    assert described["blind_label"] == "样本 A"
    assert referenced["blind_label"] == "样本 B"
    assert "@音频" not in described["prompt"]
    assert "男子1 的声音参考 @音频1，当前仅表演严肃和质问" in referenced["prompt"]
    assert "男子2 的声音参考 @音频2，当前仅表演平静和无奈" in referenced["prompt"]
    assert "台湾口音" not in referenced["prompt"]
    assert "低沉浑厚" not in referenced["prompt"]


def test_seed_scene_test_plan_requires_every_reference_slot_and_is_deterministic() -> None:
    from app.services.audiobook.seed_scene_test_unit import (
        SeedSceneResolvedReference,
        build_seed_scene_test_plan,
    )

    references = (
        SeedSceneResolvedReference(
            slot_id="male_1",
            reference={"audio_data": "REF_1"},
            sha256="hash-1",
        ),
        SeedSceneResolvedReference(
            slot_id="male_2",
            reference={"audio_data": "REF_2"},
            sha256="hash-2",
        ),
    )

    first = build_seed_scene_test_plan(
        "phone_confrontation",
        "reference_voices",
        references,
    )
    second = build_seed_scene_test_plan(
        "phone_confrontation",
        "reference_voices",
        tuple(reversed(references)),
    )

    assert first == second
    assert first.references == (
        {"audio_data": "REF_1"},
        {"audio_data": "REF_2"},
    )
    assert first.reference_hashes == ("hash-1", "hash-2")
    assert first.speaker_names == ("男子1", "男子2")
    assert first.expected_text.splitlines() == [
        "钟sir，你是什么时候被收买的？",
        "既然你都知道了，我也没有什么好隐瞒的。",
        "你现在说这些，是要我继续相信你？",
        "有些事，不是我能选择的。保护好自己。",
    ]
    assert first.prompt_hash == second.prompt_hash
    assert first.scene_id == "seed-test-phone_confrontation-reference_voices-r1"

    with pytest.raises(ValueError, match="missing reference slots: male_2"):
        build_seed_scene_test_plan(
            "phone_confrontation",
            "reference_voices",
            references[:1],
        )


def test_seed_scene_test_plan_isolates_three_repeat_slots() -> None:
    from app.services.audiobook.seed_scene_test_unit import build_seed_scene_test_plan

    plans = [
        build_seed_scene_test_plan(
            "pure_narration",
            "described_voices",
            sample_index=sample_index,
        )
        for sample_index in (1, 2, 3)
    ]

    assert [plan.scene_id for plan in plans] == [
        "seed-test-pure_narration-described_voices-r1",
        "seed-test-pure_narration-described_voices-r2",
        "seed-test-pure_narration-described_voices-r3",
    ]
    assert len({plan.prompt_hash for plan in plans}) == 1

    with pytest.raises(ValueError, match="sample_index must be between 1 and 3"):
        build_seed_scene_test_plan(
            "pure_narration",
            "described_voices",
            sample_index=4,
        )


def test_described_voice_plan_rejects_references() -> None:
    from app.services.audiobook.seed_scene_test_unit import (
        SeedSceneResolvedReference,
        build_seed_scene_test_plan,
    )

    with pytest.raises(ValueError, match="does not accept references"):
        build_seed_scene_test_plan(
            "pure_narration",
            "described_voices",
            (
                SeedSceneResolvedReference(
                    slot_id="narrator",
                    reference={"audio_data": "REF"},
                    sha256="hash",
                ),
            ),
        )


def test_seed_scene_preview_service_caches_completed_audio(tmp_path: Path) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)

    first = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )
    second = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )

    assert first["cached"] is False
    assert second["cached"] is True
    assert len(adapter.calls) == 1
    assert first["audio_data_base64"] == second["audio_data_base64"]
    assert first["quality_report"]["passed"] is True
    assert first["request_id"] == "provider-request-1"
    assert Path(first["audio_path"]).exists()


def test_seed_scene_preview_manifest_uses_portable_relative_audio_path(
    tmp_path: Path,
) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    service = SeedSceneTestPreviewService(adapter=_FakeAdapter(), output_root=tmp_path)

    service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )

    manifest_path = next((tmp_path / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative_path = manifest["audio_relative_path"]

    assert manifest["schema_version"] == 3
    assert relative_path.startswith("renders/")
    assert "\\" not in relative_path
    assert "audio_path" not in manifest
    assert (tmp_path / Path(*relative_path.split("/"))).is_file()


@pytest.mark.parametrize("legacy_style", ("docker", "windows"))
def test_seed_scene_preview_reuses_cross_environment_legacy_audio_path(
    tmp_path: Path,
    legacy_style: str,
) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)
    generated = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )
    manifest_path = next((tmp_path / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative_path = manifest.pop("audio_relative_path")
    if legacy_style == "docker":
        manifest["audio_path"] = f"/app/data/seed_scene_tests/{relative_path}"
    else:
        windows_relative_path = relative_path.replace("/", "\\")
        manifest["audio_path"] = (
            "C:\\Users\\example\\novel_writing_agent\\backend\\data"
            f"\\seed_scene_tests\\{windows_relative_path}"
        )
    manifest["schema_version"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reused = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )

    assert len(adapter.calls) == 1
    assert reused["cached"] is True
    assert reused["sample_id"] == generated["sample_id"]
    assert Path(reused["audio_path"]).is_file()


def test_seed_scene_preview_rejects_traversal_in_relative_audio_path(
    tmp_path: Path,
) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)
    service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )
    manifest_path = next((tmp_path / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["audio_relative_path"] = "../outside.wav"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    regenerated = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        references=(),
    )

    assert len(adapter.calls) == 2
    assert regenerated["cached"] is False


def test_seed_scene_preview_service_caches_each_repeat_independently(tmp_path: Path) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)

    first = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        sample_index=1,
    )
    second = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        sample_index=2,
    )
    repeated_second = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        sample_index=2,
    )

    assert len(adapter.calls) == 2
    assert first["sample_index"] == 1
    assert second["sample_index"] == 2
    assert first["sample_id"] != second["sample_id"]
    assert second["cached"] is False
    assert repeated_second["cached"] is True
    assert second["billing"]["billable_duration_s"] == 1.0
    assert second["billing"]["actual_cost_yuan"] == 0.0167
    assert second["generation_latency_s"] >= 0


def test_seed_scene_preview_service_reuses_legacy_cache_for_first_repeat(
    tmp_path: Path,
) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService
    from app.services.audiobook.seed_scene_test_unit import build_seed_scene_test_plan

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)
    generated = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        sample_index=1,
    )
    plan = build_seed_scene_test_plan("pure_narration", "described_voices")
    current_key = service._cache_key(
        plan.prompt_hash,
        plan.reference_hashes,
        sample_index=1,
    )
    legacy_key = service._legacy_cache_key(plan.prompt_hash, plan.reference_hashes)
    manifests = tmp_path / "manifests"
    current_manifest = manifests / f"{current_key}.json"
    legacy_manifest = manifests / f"{legacy_key}.json"
    payload = json.loads(current_manifest.read_text(encoding="utf-8"))
    payload.pop("sample_id", None)
    payload["schema_version"] = 1
    payload["metadata"].pop("billing", None)
    legacy_manifest.write_text(json.dumps(payload), encoding="utf-8")
    current_manifest.unlink()

    reused = service.render(
        case_id="pure_narration",
        variant_id="described_voices",
        sample_index=1,
    )

    assert len(adapter.calls) == 1
    assert reused["cached"] is True
    assert reused["sample_id"] == generated["sample_id"]
    assert reused["billing"]["billable_duration_s"] == 1.0
    assert reused["billing"]["provider_request_count"] == 1
    assert reused["billing"]["actual_cost_yuan"] == 0.0167


def test_seed_scene_preview_service_materializes_references_in_slot_order(tmp_path: Path) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)
    encoded = base64.b64encode(_wav_bytes()).decode("ascii")

    result = service.render(
        case_id="phone_confrontation",
        variant_id="reference_voices",
        references=(
            {
                "slot_id": "male_2",
                "source_model": "qwen-audio-3.1-tts-flash",
                "source_voice_id": "Cherry",
                "audio_data_base64": encoded,
                "audio_mime_type": "audio/wav",
            },
            {
                "slot_id": "male_1",
                "source_model": "qwen-audio-3.1-tts-flash",
                "source_voice_id": "Vincent",
                "audio_data_base64": encoded,
                "audio_mime_type": "audio/wav",
            },
        ),
    )

    assert result["quality_report"]["passed"] is True
    assert [item["slot_id"] for item in result["references"]] == ["male_1", "male_2"]
    assert [item["source_voice_id"] for item in result["references"]] == ["Vincent", "Cherry"]
    assert len(adapter.calls[0]["references"]) == 2
    assert all(set(item) == {"audio_data"} for item in adapter.calls[0]["references"])


def test_seed_scene_preview_service_uses_seed_tts_voice_as_native_speaker(tmp_path: Path) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    adapter = _FakeAdapter()
    service = SeedSceneTestPreviewService(adapter=adapter, output_root=tmp_path)

    class _UnexpectedMaterializer:
        def materialize(self, _config):
            raise AssertionError("native Seed-TTS speaker must not materialize preview audio")

    service.reference_materializer = _UnexpectedMaterializer()
    result = service.render(
        case_id="pure_narration",
        variant_id="reference_voices",
        references=(
            {
                "slot_id": "narrator",
                "source_model": "seed-tts-2.0-expressive",
                "source_voice_id": "zh_male_taocheng_uranus_bigtts",
                "audio_url": "https://cdn.example.test/ignored-preview.mp3",
            },
        ),
    )

    assert adapter.calls[0]["references"] == [
        {"speaker": "zh_male_taocheng_uranus_bigtts"},
    ]
    assert result["references"] == [
        {
            "slot_id": "narrator",
            "source_model": "seed-tts-2.0-expressive",
            "source_voice_id": "zh_male_taocheng_uranus_bigtts",
            "reference_type": "speaker",
            "sha256": result["references"][0]["sha256"],
            "duration_s": None,
        }
    ]


@pytest.mark.parametrize(
    ("reference_payload", "expected_source"),
    (
        (
            {"audio_url": "https://cdn.example.test/voice-preview.mp3"},
            {"preview_audio_url": "https://cdn.example.test/voice-preview.mp3"},
        ),
        ({}, {}),
    ),
)
def test_seed_scene_preview_service_reuses_url_or_shared_voice_preview_cache(
    tmp_path: Path,
    reference_payload: dict,
    expected_source: dict,
) -> None:
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestPreviewService

    captured_configs: list[dict] = []

    class _FakeReferenceMaterializer:
        def materialize(self, config):
            captured_configs.append(dict(config))
            return SimpleNamespace(
                reference={"audio_data": "REFERENCE_AUDIO"},
                sha256="reference-hash",
                duration_s=1.0,
            )

    service = SeedSceneTestPreviewService(adapter=_FakeAdapter(), output_root=tmp_path)
    service.reference_materializer = _FakeReferenceMaterializer()
    base_reference = {
        "slot_id": "narrator",
        "source_model": "qwen-audio-3.1-tts-flash",
        "source_voice_id": "Vincent",
    }

    service.render(
        case_id="pure_narration",
        variant_id="reference_voices",
        references=({**base_reference, **reference_payload},),
    )

    assert captured_configs == [
        {
            "tts_model": "qwen-audio-3.1-tts-flash",
            "voice_id": "Vincent",
            **expected_source,
        }
    ]


def test_seed_scene_reference_request_accepts_url_or_shared_cache_identity() -> None:
    from app.schemas.audiobook import SeedSceneTestReferenceRequest
    from pydantic import ValidationError

    url_reference = SeedSceneTestReferenceRequest(
        slot_id="male_lead",
        source_model="cosyvoice-v3.5-plus",
        source_voice_id="voice-a",
        audio_url="https://cdn.example.test/voice-a.mp3",
    )
    cache_reference = SeedSceneTestReferenceRequest(
        slot_id="partner",
        source_model="qwen-audio-3.1-tts-flash",
        source_voice_id="Vincent",
    )

    assert url_reference.audio_url == "https://cdn.example.test/voice-a.mp3"
    assert url_reference.audio_data_base64 is None
    assert cache_reference.audio_url is None
    assert cache_reference.audio_data_base64 is None

    with pytest.raises(ValidationError, match="只能提供一种"):
        SeedSceneTestReferenceRequest(
            slot_id="partner",
            source_model="qwen-audio-3.1-tts-flash",
            source_voice_id="Vincent",
            audio_data_base64="INLINE_AUDIO",
            audio_url="https://cdn.example.test/voice-a.mp3",
        )


def test_seed_scene_test_preview_endpoint_is_independent_from_projects(monkeypatch) -> None:
    from app.api.v1.audiobook_api import routes_seed_scene_test
    from app.schemas.audiobook import SeedSceneTestPreviewRequest

    captured: dict = {}

    class _FakeService:
        def render(self, **kwargs):
            captured.update(kwargs)
            return {
                "model": "seed-audio-1.0",
                "case_id": kwargs["case_id"],
                "variant": kwargs["variant_id"],
                "sample_index": kwargs["sample_index"],
                "sample_id": "seed-sample-test",
                "blind_label": "样本 A",
                "prompt": "旁白说：\"测试。\"",
                "expected_texts": ["测试。"],
                "audio_data_base64": base64.b64encode(b"ID3-test").decode("ascii"),
                "audio_format": "mp3",
                "audio_mime_type": "audio/mpeg",
                "audio_size_bytes": 8,
                "audio_path": "test.mp3",
                "duration": 1.0,
                "subtitle": {"text": "测试。"},
                "request_id": "request-1",
                "generation_latency_s": 1.25,
                "billing": {
                    "billable_duration_s": 1.0,
                    "actual_cost_yuan": 0.0167,
                },
                "generation_status": "passed",
                "fallback_reason": None,
                "quality_report": {"passed": True},
                "references": [],
                "cached": False,
            }

    monkeypatch.setattr(
        routes_seed_scene_test,
        "create_seed_scene_test_preview_service",
        lambda: _FakeService(),
    )

    response = asyncio.run(
        routes_seed_scene_test.preview_seed_scene_test_case(
            request=SeedSceneTestPreviewRequest(
                case_id="pure_narration",
                variant="described_voices",
                sample_index=3,
            ),
            current_user=SimpleNamespace(id=1),
        )
    )

    assert response.case_id == "pure_narration"
    assert response.quality_report["passed"] is True
    assert captured == {
        "case_id": "pure_narration",
        "variant_id": "described_voices",
        "sample_index": 3,
        "references": (),
        "force_regenerate": False,
    }
    assert not hasattr(response, "project_id")
    assert not hasattr(response, "chapter_id")
    assert not hasattr(response, "audio_path")


def test_seed_scene_test_preview_endpoint_marks_exhausted_audio_download_non_retryable(
    monkeypatch,
) -> None:
    from fastapi import HTTPException

    from app.api.v1.audiobook_api import routes_seed_scene_test
    from app.schemas.audiobook import SeedSceneTestPreviewRequest
    from app.services.audiobook.seed_scene_test_renderer import SeedSceneTestRenderError

    class _FakeService:
        def render(self, **_kwargs):
            raise SeedSceneTestRenderError(
                "audio_download_failed:RemoteProtocolError",
                retryable=False,
            )

    monkeypatch.setattr(
        routes_seed_scene_test,
        "create_seed_scene_test_preview_service",
        lambda: _FakeService(),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            routes_seed_scene_test.preview_seed_scene_test_case(
                request=SeedSceneTestPreviewRequest(
                    case_id="pure_narration",
                    variant="described_voices",
                    sample_index=2,
                ),
                current_user=SimpleNamespace(id=1),
            )
        )

    assert error.value.status_code == 503
    assert error.value.detail == {
        "message": "audio_download_failed:RemoteProtocolError",
        "retryable": False,
    }
