from __future__ import annotations

import base64
import hashlib
import math
import struct
import sys
import wave
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.models import SceneRenderPlan
from app.services.audiobook.scene_engine.scene_billing import (
    build_seed_scene_billing_summary,
)
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderService


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


def _plan() -> SceneRenderPlan:
    return SceneRenderPlan(
        scene_id="scene_0001",
        source_segment_indices=(0, 1),
        expected_text="第一句\n第二句",
        expected_duration_s=4.0,
        speaker_names=("旁白",),
        references=({"speaker": "speaker-1"},),
        prompt="旁白清晰地说：\"第一句\"，随后说：\"第二句\"。",
        prompt_hash="prompt-hash",
        reference_hashes=("reference-hash",),
        boundary_before="开场",
        boundary_after="收尾",
    )


class FakeAdapter:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.responses.pop(0)


def _success_response(
    audio_bytes: bytes,
    *,
    subtitles,
    request_id: str = "provider-request-1",
) -> dict:
    return {
        "audio": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_format": "wav",
        "subtitle": subtitles,
        "duration": 1.0,
        "original_duration": 1.25,
        "request_id": request_id,
    }


def test_scene_renderer_persists_audio_runs_quality_gate_and_writes_checkpoint(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}, {"text": "第二句"}],
            )
        ]
    )
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )

    result = service.render(_plan())

    assert result.status == "passed"
    assert result.action == "assemble"
    assert result.quality_report is not None
    assert result.quality_report.passed is True
    assert result.audio_path is not None and result.audio_path.exists()
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["references"] == [{"speaker": "speaker-1"}]
    assert adapter.calls[0]["audio_config"] == {
        "format": "mp3",
        "sample_rate": 48000,
        "pitch_rate": 0,
        "speech_rate": 0,
        "loudness_rate": 0,
        "enable_subtitle": True,
    }
    assert adapter.calls[0]["watermark"] == {}
    assert checkpoints[-1]["status"] == "passed"
    assert checkpoints[-1]["prompt_hash"] == "prompt-hash"
    # P1 提示词透明化：checkpoint 携带 prompt 全文，供场景编辑器投影展示
    assert checkpoints[-1]["prompt"] == '旁白清晰地说："第一句"，随后说："第二句"。'
    # 阶段 1：新产出 checkpoint 使用当前 schema（v2）并携带显式元数据
    assert checkpoints[-1]["schema_version"] == 2
    assert checkpoints[-1]["checkpoint_type"] == "seed_scene_checkpoint"
    assert checkpoints[-1]["signature_contract_version"] == "1.0.0"
    assert checkpoints[-1]["producer_version"] == "scene-render-service-v2"
    assert checkpoints[-1]["created_at"]
    assert checkpoints[-1]["renderer_version"] == "scene-render-service-v2"
    # 阶段 1：新任务默认请求 multilingual
    assert checkpoints[-1]["model"] == "seed-audio-1.0-multilingual"
    assert checkpoints[-1]["audio_config"] == {
        "format": "mp3",
        "sample_rate": 48000,
        "pitch_rate": 0,
        "speech_rate": 0,
        "loudness_rate": 0,
        "enable_subtitle": True,
    }
    assert checkpoints[-1]["source_segment_indices"] == [0, 1]
    assert checkpoints[-1]["source_text_hash"] == hashlib.sha256(
        "第一句\n第二句".encode("utf-8")
    ).hexdigest()
    assert checkpoints[-1]["audio_sha256"] == hashlib.sha256(
        result.audio_path.read_bytes()
    ).hexdigest()
    assert checkpoints[-1]["duration"] == 1.0
    assert checkpoints[-1]["quality_report"]["passed"] is True
    assert checkpoints[-1]["billing_duration_s"] == 1.25
    assert checkpoints[-1]["provider_request_id"] == "provider-request-1"
    assert checkpoints[-1]["provider_request_ids"] == ["provider-request-1"]


def test_scene_renderer_passes_declared_vocalizations_to_quality_gate(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句，喘息，第二句"}],
            )
        ]
    )
    service = SceneRenderService(adapter=adapter, output_root=tmp_path)
    plan = replace(_plan(), expected_vocalizations=("喘息",))

    result = service.render(plan)

    assert result.status == "passed"
    assert result.quality_report is not None
    assert result.quality_report.extra_lines == ()


def test_scene_renderer_records_provider_attempt_immediately(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}, {"text": "第二句"}],
                request_id="provider-request-9",
            )
        ]
    )
    attempt_records: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        provider_attempt_recorder=attempt_records.append,
    )

    result = service.render(_plan(), model="seed-audio-1.0-multilingual")

    assert result.status == "passed"
    assert attempt_records == [
        {
            "provider_request_id": "provider-request-9",
            "scene_id": "scene_0001",
            "model": "seed-audio-1.0-multilingual",
            "attempt": 1,
            "original_duration": 1.25,
            "prompt_hash": "prompt-hash",
        }
    ]


def test_scene_renderer_uses_injected_asr_when_subtitles_are_missing(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=None,
            )
        ]
    )
    asr_paths: list[Path] = []

    def transcribe(audio_path: Path) -> str:
        asr_paths.append(audio_path)
        return "第一句 第二句"

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
    )

    result = service.render(_plan())

    assert result.status == "passed"
    assert result.quality_report is not None
    assert result.quality_report.transcript_source == "asr"
    assert len(asr_paths) == 1


def test_scene_renderer_persists_safe_asr_usage_metadata(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=None,
            )
        ]
    )

    def transcribe(_audio_path: Path) -> dict:
        return {
            "transcript": "第一句 第二句",
            "provider": "funasr_flash",
            "model": "fun-asr-flash-2026-06-15",
            "metadata": {
                "request_id": "asr-request-1",
                "usage": {"duration": 3},
                "raw_output": {"must_not_persist": True},
            },
        }

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
    )

    result = service.render(_plan())

    assert result.status == "passed"
    assert result.metadata["asr_provider"] == "funasr_flash"
    assert result.metadata["asr_model"] == "fun-asr-flash-2026-06-15"
    assert result.metadata["asr_request_id"] == "asr-request-1"
    assert result.metadata["asr_usage"] == {"duration": 3}
    assert "raw_output" not in str(result.metadata)


def test_scene_renderer_enriches_text_only_subtitles_with_asr_timeline(
    tmp_path: Path,
) -> None:
    plan = _plan()
    expected_lines = plan.expected_text.splitlines()
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": line} for line in expected_lines],
            )
        ]
    )
    asr_paths: list[Path] = []

    def transcribe(audio_path: Path) -> dict:
        asr_paths.append(audio_path)
        return {
            "provider": "fake-asr",
            "model": "fake-timeline-v1",
            "transcript": " ".join(expected_lines),
            "subtitle_payload": {
                "segments": [
                    {"text": expected_lines[0], "start_ms": 100, "end_ms": 450},
                    {"text": expected_lines[1], "start_ms": 500, "end_ms": 900},
                ]
            },
        }

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
    )

    result = service.render(plan)

    assert result.status == "passed"
    assert len(asr_paths) == 1
    assert result.subtitle_payload == {
        "segments": [
            {"text": expected_lines[0], "start_ms": 100, "end_ms": 450},
            {"text": expected_lines[1], "start_ms": 500, "end_ms": 900},
        ]
    }
    assert result.metadata["subtitle_timeline_source"] == "fake-asr"
    assert result.metadata["subtitle_timeline_model"] == "fake-timeline-v1"


def test_scene_renderer_passes_transient_audio_url_to_timeline_asr(
    tmp_path: Path,
) -> None:
    plan = _plan()
    expected_lines = plan.expected_text.splitlines()
    source_url = "https://provider.example/temporary-scene.wav"
    adapter = FakeAdapter(
        [
            {
                "audio_url": source_url,
                "subtitle": [{"text": line} for line in expected_lines],
                "duration": 1.0,
                "original_duration": 1.25,
                "request_id": "provider-request-url",
            }
        ]
    )
    asr_calls: list[tuple[Path, str | None]] = []

    def transcribe(audio_path: Path, *, audio_url: str | None = None) -> dict:
        asr_calls.append((audio_path, audio_url))
        return {
            "provider": "url-asr",
            "model": "url-asr-v1",
            "transcript": " ".join(expected_lines),
            "subtitle_payload": {
                "segments": [
                    {"text": expected_lines[0], "start_ms": 100, "end_ms": 450},
                    {"text": expected_lines[1], "start_ms": 500, "end_ms": 900},
                ]
            },
        }

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        downloader=lambda url: (_wav_bytes(), "audio/wav"),
        asr_provider=transcribe,
    )

    result = service.render(plan)

    assert result.status == "passed"
    assert len(asr_calls) == 1
    assert asr_calls[0][1] == source_url
    assert source_url not in str(result.metadata)


def test_scene_renderer_retries_interrupted_audio_download_without_recreating_seed(
    tmp_path: Path,
) -> None:
    source_url = "https://provider.example/temporary-scene.wav"
    response = {
        "audio_url": source_url,
        "subtitle": [{"text": "第一句"}, {"text": "第二句"}],
        "duration": 1.0,
        "original_duration": 1.25,
        "request_id": "provider-request-url",
    }
    adapter = FakeAdapter([response, response])
    download_calls: list[str] = []

    def download(url: str) -> tuple[bytes, str]:
        download_calls.append(url)
        if len(download_calls) == 1:
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body"
            )
        return _wav_bytes(), "audio/wav"

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        downloader=download,
        max_retries=1,
        max_download_retries=2,
        download_retry_backoff_s=0,
    )

    result = service.render(_plan())

    assert result.status == "passed"
    assert len(adapter.calls) == 1
    assert download_calls == [source_url, source_url]
    assert result.metadata["billing"]["provider_request_count"] == 1


def test_scene_renderer_does_not_recreate_seed_after_download_retries_are_exhausted(
    tmp_path: Path,
) -> None:
    source_url = "https://provider.example/temporary-scene.wav"
    response = {
        "audio_url": source_url,
        "subtitle": [{"text": "第一句"}, {"text": "第二句"}],
        "duration": 1.0,
        "original_duration": 1.25,
        "request_id": "provider-request-url",
    }
    adapter = FakeAdapter([response, response])
    download_calls: list[str] = []

    def download(url: str) -> bytes:
        download_calls.append(url)
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body"
        )

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        downloader=download,
        max_retries=1,
        max_download_retries=2,
        download_retry_backoff_s=0,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 1
    assert result.fallback_reason == "audio_download_failed:RemoteProtocolError"
    assert len(adapter.calls) == 1
    assert download_calls == [source_url, source_url, source_url]
    assert result.metadata["billing"]["provider_request_count"] == 1


def test_scene_renderer_keeps_valid_provider_text_when_asr_timeline_fails(
    tmp_path: Path,
) -> None:
    plan = _plan()
    expected_lines = plan.expected_text.splitlines()
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": line} for line in expected_lines],
            )
        ]
    )

    def transcribe(_audio_path: Path) -> str:
        raise RuntimeError("timeline provider unavailable")

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
    )

    result = service.render(plan)

    assert result.status == "passed"
    assert result.attempts == 1
    assert result.subtitle_payload == [{"text": line} for line in expected_lines]
    assert result.metadata["subtitle_timeline_status"] == "failed"
    assert result.metadata["subtitle_timeline_error"] == "RuntimeError"
    assert len(adapter.calls) == 1


def test_scene_renderer_skips_transcript_only_asr_for_text_only_subtitles(
    tmp_path: Path,
) -> None:
    plan = _plan()
    expected_lines = plan.expected_text.splitlines()
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": line} for line in expected_lines],
            )
        ]
    )
    asr_calls: list[Path] = []

    def transcribe(audio_path: Path) -> str:
        asr_calls.append(audio_path)
        return " ".join(expected_lines)

    transcribe.supports_timestamps = False
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
    )

    result = service.render(plan)

    assert result.status == "passed"
    assert asr_calls == []


def test_scene_renderer_enriches_reused_checkpoint_without_seed_regeneration(
    tmp_path: Path,
) -> None:
    plan = _plan()
    expected_lines = plan.expected_text.splitlines()
    initial_checkpoints: list[dict] = []
    initial_service = SceneRenderService(
        adapter=FakeAdapter(
            [
                _success_response(
                    _wav_bytes(),
                    subtitles=[{"text": line} for line in expected_lines],
                )
            ]
        ),
        output_root=tmp_path,
        checkpoint_writer=initial_checkpoints.append,
    )
    initial_result = initial_service.render(plan)
    assert initial_result.status == "passed"

    adapter = FakeAdapter([])
    enriched_checkpoints: list[dict] = []

    def transcribe(_audio_path: Path) -> dict:
        return {
            "provider": "fake-asr",
            "model": "fake-timeline-v1",
            "transcript": " ".join(expected_lines),
            "subtitle_payload": {
                "segments": [
                    {"text": expected_lines[0], "start_ms": 100, "end_ms": 450},
                    {"text": expected_lines[1], "start_ms": 500, "end_ms": 900},
                ]
            },
        }

    resumed_service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
        checkpoint_writer=enriched_checkpoints.append,
    )

    result = resumed_service.render(plan, checkpoint=initial_checkpoints[-1])

    assert result.status == "passed"
    assert result.reused_checkpoint is True
    assert result.subtitle_payload["segments"][0]["start_ms"] == 100
    assert result.metadata["subtitle_timeline_source"] == "fake-asr"
    assert adapter.calls == []
    assert enriched_checkpoints[-1]["subtitle_payload"] == result.subtitle_payload


def test_scene_renderer_does_not_retry_seed_when_asr_is_unconfigured(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=None,
            )
        ]
    )
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        max_retries=1,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 1
    assert result.fallback_reason == "transcript_unavailable"
    assert len(adapter.calls) == 1


def test_scene_renderer_does_not_retry_seed_when_asr_provider_fails(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=None,
            )
        ]
    )
    asr_calls: list[Path] = []

    def transcribe(audio_path: Path) -> str:
        asr_calls.append(audio_path)
        raise RuntimeError("asr unavailable")

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
        max_retries=1,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 1
    assert result.fallback_reason == "asr_failed:RuntimeError"
    assert len(adapter.calls) == 1
    assert len(asr_calls) == 1


def test_scene_renderer_stops_when_per_scene_asr_call_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        [
            _success_response(_wav_bytes(), subtitles=None, request_id="seed-1"),
            _success_response(_wav_bytes(), subtitles=None, request_id="seed-2"),
        ]
    )
    asr_calls: list[Path] = []

    def transcribe(audio_path: Path) -> dict:
        asr_calls.append(audio_path)
        return {
            "provider": "funasr_flash",
            "model": "fun-asr-flash-2026-06-15",
            "transcript": "完全错误的转写",
            "metadata": {"usage": {"duration": 3}},
        }

    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
        max_retries=1,
        max_asr_attempts_per_scene=1,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 2
    assert result.fallback_reason == "asr_call_budget_exhausted"
    assert len(adapter.calls) == 2
    assert len(asr_calls) == 1


def test_scene_renderer_aggregates_asr_cost_across_seed_retries(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(_wav_bytes(), subtitles=None, request_id="seed-1"),
            _success_response(_wav_bytes(), subtitles=None, request_id="seed-2"),
        ]
    )

    def transcribe(_audio_path: Path) -> dict:
        return {
            "provider": "funasr_flash",
            "model": "fun-asr-flash-2026-06-15",
            "transcript": "完全错误的转写",
            "metadata": {
                "request_id": "asr-request",
                "usage": {"duration": 3},
            },
        }

    transcribe.provider_name = "funasr_flash"
    transcribe.model = "fun-asr-flash-2026-06-15"
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
        max_retries=1,
        max_asr_attempts_per_scene=2,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 2
    assert result.metadata["asr_attempt_count"] == 2
    assert result.metadata["asr_actual_cost_yuan"] == 0.00132
    assert [item["status"] for item in result.metadata["asr_attempts"]] == [
        "succeeded",
        "succeeded",
    ]
    assert all(
        item["pricing_source"] == "aliyun_model_studio_public_price_2026-07-24"
        for item in result.metadata["asr_attempts"]
    )
    assert "raw_output" not in str(result.metadata)


def test_scene_renderer_enforces_known_asr_cost_budget_before_call(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [_success_response(_wav_bytes(), subtitles=None, request_id="seed-1")]
    )
    asr_calls: list[Path] = []

    def transcribe(audio_path: Path) -> dict:
        asr_calls.append(audio_path)
        return {"transcript": "第一句 第二句"}

    transcribe.provider_name = "funasr_flash"
    transcribe.model = "fun-asr-flash-2026-06-15"
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        asr_provider=transcribe,
        max_asr_cost_yuan_per_scene=0.0001,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 1
    assert result.fallback_reason == "asr_cost_budget_exhausted"
    assert asr_calls == []


def test_scene_renderer_retries_one_quality_failure_then_falls_back(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}],
                request_id="provider-request-1",
            ),
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}],
                request_id="provider-request-2",
            ),
        ]
    )
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.action == "legacy_stems"
    assert result.attempts == 2
    assert result.fallback_reason == "transcript_fidelity_failed"
    assert len(adapter.calls) == 2
    assert "重试约束" in adapter.calls[1]["prompt"]
    assert checkpoints[-1]["status"] == "legacy_stems"
    assert checkpoints[-1]["billing_duration_s"] == 2.5
    assert checkpoints[-1]["provider_request_ids"] == [
        "provider-request-1",
        "provider-request-2",
    ]


def test_seed_scene_billing_summary_ignores_legacy_supplier_rate_override(
    monkeypatch,
) -> None:
    checkpoints = {
        "scene_0001": {
            "billing_duration_s": 12.5,
            "provider_request_ids": ["request-1", "request-2"],
        },
        "scene_0002": {
            "billing_duration_s": 7.5,
            "provider_request_ids": ["request-3"],
        },
    }
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN", "0.02")

    summary = build_seed_scene_billing_summary(checkpoints, model="seed-audio-1.0")

    assert summary == {
        "model": "seed-audio-1.0",
        "pricing_status": "configured",
        "pricing_source": "volcengine_public_postpaid",
        "pricing_basis": "public_list_price",
        "price_per_second_yuan": 1 / 60,
        "price_per_minute_yuan": 1.0,
        "billing_increment_s": 0.0,
        "billable_duration_s": 20.0,
        "provider_request_count": 3,
        "actual_cost_yuan": 0.3333,
    }


def test_seed_scene_billing_summary_uses_public_postpaid_rate(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN", raising=False)
    monkeypatch.delenv("DOUBAO_SEED_AUDIO_PRICE_PER_MINUTE_YUAN", raising=False)

    summary = build_seed_scene_billing_summary(
        {"scene_0001": {"billing_duration_s": 60.0}}
    )

    assert summary["pricing_status"] == "configured"
    assert summary["pricing_source"] == "volcengine_public_postpaid"
    assert summary["pricing_basis"] == "public_list_price"
    assert math.isclose(summary["price_per_second_yuan"], 1 / 60)
    assert summary["price_per_minute_yuan"] == 1.0
    assert summary["billable_duration_s"] == 60.0
    assert summary["actual_cost_yuan"] == 1.0


def test_seed_scene_billing_summary_ignores_legacy_per_minute_override(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN", raising=False)
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_PRICE_PER_MINUTE_YUAN", "0.95")

    summary = build_seed_scene_billing_summary(
        {"scene_0001": {"billing_duration_s": 120.0}}
    )

    assert summary["pricing_source"] == "volcengine_public_postpaid"
    assert math.isclose(summary["price_per_second_yuan"], 1 / 60)
    assert summary["price_per_minute_yuan"] == 1.0
    assert summary["actual_cost_yuan"] == 2.0


def test_seed_scene_billing_summary_defaults_to_linear_billing_increment(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S", raising=False)

    summary = build_seed_scene_billing_summary(
        {"scene_0001": {"billing_duration_s": 12.3}}
    )

    assert summary["billing_increment_s"] == 0.0
    assert summary["billable_duration_s"] == 12.3


def test_seed_scene_billing_summary_quantizes_each_attempt_to_increment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S", "1.0")
    attempts = (
        {"provider_request_id": "request-1", "original_duration": 12.3},
        {"provider_request_id": "request-2", "original_duration": 7.1},
        {"provider_request_id": "request-3", "original_duration": 0.2},
    )

    summary = build_seed_scene_billing_summary({}, provider_attempts=attempts)

    # 每次调用向上取整到 1s，并保证至少 1 个增量单位：ceil(12.3)+ceil(7.1)+ceil(0.2)=13+8+1=22。
    assert summary["billing_increment_s"] == 1.0
    assert summary["billable_duration_s"] == 22.0
    assert summary["provider_request_count"] == 3
    assert summary["actual_cost_yuan"] == round(22.0 / 60, 4)


def test_seed_scene_billing_summary_quantizes_checkpoint_fallback_per_scene(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S", "5.0")

    summary = build_seed_scene_billing_summary(
        {
            "scene_0001": {"billing_duration_s": 12.0},  # ceil -> 15
            "scene_0002": {"billing_duration_s": 3.0},  # ceil -> 5
        }
    )

    assert summary["billing_increment_s"] == 5.0
    assert summary["billable_duration_s"] == 20.0


def test_seed_scene_billing_summary_ignores_invalid_billing_increment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S", "not-a-number")

    summary = build_seed_scene_billing_summary(
        {"scene_0001": {"billing_duration_s": 12.3}}
    )

    assert summary["billing_increment_s"] == 0.0
    assert summary["billable_duration_s"] == 12.3


def test_scene_renderer_reuses_matching_success_checkpoint(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}, {"text": "第二句"}],
            )
        ]
    )
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )
    first = service.render(_plan())

    reused = service.render(_plan(), checkpoint=checkpoints[-1])

    assert first.status == "passed"
    assert reused.status == "passed"
    assert reused.reused_checkpoint is True
    assert reused.action == "assemble"
    assert len(adapter.calls) == 1


def test_scene_renderer_reuses_terminal_fallback_checkpoint_without_calling_seed(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        [
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}],
                request_id="provider-request-1",
            ),
            _success_response(
                _wav_bytes(),
                subtitles=[{"text": "第一句"}],
                request_id="provider-request-2",
            ),
        ]
    )
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )
    first = service.render(_plan())
    resumed_adapter = FakeAdapter([])
    resumed_service = SceneRenderService(
        adapter=resumed_adapter,
        output_root=tmp_path,
    )

    reused = resumed_service.render(_plan(), checkpoint=checkpoints[-1])

    assert first.status == "legacy_stems"
    assert reused.status == "legacy_stems"
    assert reused.action == "legacy_stems"
    assert reused.reused_checkpoint is True
    assert reused.audio_path is None
    assert reused.fallback_reason == "transcript_fidelity_failed"
    assert resumed_adapter.calls == []


def test_scene_renderer_does_not_reuse_checkpoint_for_different_model(tmp_path: Path) -> None:
    response = _success_response(
        _wav_bytes(),
        subtitles=[{"text": "第一句"}, {"text": "第二句"}],
    )
    adapter = FakeAdapter([response, response])
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )
    service.render(_plan())

    # 默认为 multilingual，改请求普通 1.0 时不得复用 checkpoint。
    rerendered = service.render(
        _plan(),
        model="seed-audio-1.0",
        checkpoint=checkpoints[-1],
    )

    assert rerendered.status == "passed"
    assert rerendered.reused_checkpoint is False
    assert len(adapter.calls) == 2
    assert adapter.calls[-1]["model"] == "seed-audio-1.0"
    assert checkpoints[-1]["model"] == "seed-audio-1.0"


def test_scene_renderer_does_not_reuse_checkpoint_for_different_audio_config(tmp_path: Path) -> None:
    response = _success_response(
        _wav_bytes(),
        subtitles=[{"text": "第一句"}, {"text": "第二句"}],
    )
    adapter = FakeAdapter([response, response])
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )
    service.render(_plan())

    rerendered = service.render(
        _plan(),
        audio_config={"sample_rate": 24000},
        checkpoint=checkpoints[-1],
    )

    expected_audio_config = {
        "format": "mp3",
        "sample_rate": 24000,
        "pitch_rate": 0,
        "speech_rate": 0,
        "loudness_rate": 0,
        "enable_subtitle": True,
    }
    assert rerendered.status == "passed"
    assert rerendered.reused_checkpoint is False
    assert len(adapter.calls) == 2
    assert adapter.calls[-1]["audio_config"] == expected_audio_config
    assert checkpoints[-1]["audio_config"] == expected_audio_config


def test_scene_renderer_invalidates_checkpoint_when_quality_policy_changes(
    tmp_path: Path,
) -> None:
    response = _success_response(
        _wav_bytes(),
        subtitles=[{"text": "第一句"}, {"text": "第二句"}],
    )
    adapter = FakeAdapter([response, response])
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )
    first = service.render(_plan())
    changed_plan = replace(
        _plan(),
        quality_policy_hash="changed-quality-policy",
    )

    rerendered = service.render(changed_plan, checkpoint=checkpoints[-1])

    assert first.status == "passed"
    assert checkpoints[0]["quality_policy_hash"] == _plan().quality_policy_hash
    assert rerendered.reused_checkpoint is False
    assert len(adapter.calls) == 2


def test_scene_renderer_does_not_reuse_legacy_checkpoint_without_signature_fields(
    tmp_path: Path,
) -> None:
    response = _success_response(
        _wav_bytes(),
        subtitles=[{"text": "第一句"}, {"text": "第二句"}],
    )
    adapter = FakeAdapter([response, response])
    checkpoints: list[dict] = []
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        checkpoint_writer=checkpoints.append,
    )
    service.render(_plan())
    legacy_checkpoint = {
        key: value
        for key, value in checkpoints[-1].items()
        if key not in {"schema_version", "renderer_version", "model", "audio_config"}
    }

    rerendered = service.render(_plan(), checkpoint=legacy_checkpoint)

    assert rerendered.status == "passed"
    assert rerendered.reused_checkpoint is False
    assert len(adapter.calls) == 2


def test_scene_renderer_does_not_retry_non_retryable_adapter_error(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            {
                "success": False,
                "error": "TTSInvalidText:ReadableTextRatioTooLow",
                "error_code": "invalid_request",
                "trace": {"retryable": False},
            }
        ]
    )
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        max_retries=1,
    )

    result = service.render(_plan())

    assert result.status == "legacy_stems"
    assert result.attempts == 1
    assert result.fallback_reason == "TTSInvalidText:ReadableTextRatioTooLow"
    assert len(adapter.calls) == 1


def test_scene_renderer_rejects_unmaterialized_preview_reference(tmp_path: Path) -> None:
    adapter = FakeAdapter([])
    service = SceneRenderService(
        adapter=adapter,
        output_root=tmp_path,
        max_retries=1,
    )
    plan = replace(
        _plan(),
        references=({"preview_cache": "stable-preview-cache-key"},),
        reference_hashes=("preview-cache-reference-hash",),
    )

    result = service.render(plan)

    assert result.status == "legacy_stems"
    assert result.attempts == 1
    assert result.fallback_reason == "unmaterialized_preview_reference"
    assert adapter.calls == []


class TestCheckpointSchemaMigrationIntegration:
    """阶段 1：renderer 层历史 checkpoint 的 append-only 迁移集成语义。

    - 历史 v1 checkpoint 自动迁移为 v2 并写回，随后复用且不重烧音频；
    - 迁移幂等：已是 v2 的 checkpoint 不再迁移、不重复写回；
    - 缺字段等不兼容 checkpoint 不复用、不破坏，转重新生成。
    """

    def _v1_checkpoint(self, audio_path: Path) -> dict:
        plan = _plan()
        return {
            "schema_version": 1,
            "renderer_version": "scene-render-service-v2",
            "model": "seed-audio-1.0",
            "audio_config": {
                "format": "mp3",
                "sample_rate": 48000,
                "pitch_rate": 0,
                "speech_rate": 0,
                "loudness_rate": 0,
                "enable_subtitle": True,
            },
            "scene_id": plan.scene_id,
            "source_segment_indices": list(plan.source_segment_indices),
            "source_text_hash": "text-hash",
            "prompt_hash": plan.prompt_hash,
            "quality_policy_hash": plan.quality_policy_hash,
            "reference_hashes": list(plan.reference_hashes),
            "status": "passed",
            "attempts": 1,
            "audio_path": str(audio_path),
            "billing_duration_s": 1.25,
            "provider_request_ids": ["request-legacy-1"],
        }

    def test_renderer_migrates_v1_checkpoint_and_reuses_without_reburn(
        self, tmp_path: Path
    ) -> None:
        audio_path = tmp_path / "scene_0001.wav"
        audio_path.write_bytes(_wav_bytes())
        legacy = self._v1_checkpoint(audio_path)

        checkpoints: list[dict] = []
        adapter = FakeAdapter([])
        service = SceneRenderService(
            adapter=adapter,
            output_root=tmp_path,
            checkpoint_writer=checkpoints.append,
        )

        result = service.render(_plan(), model="seed-audio-1.0", checkpoint=legacy)

        # 迁移后复用既有音频，不重烧 Seed
        assert result.status == "passed"
        assert result.reused_checkpoint is True
        assert result.audio_path == audio_path
        assert adapter.calls == []
        # append-only 迁移写回新版本，旧签名字段逐项保留
        assert len(checkpoints) == 1
        migrated = checkpoints[-1]
        assert migrated["schema_version"] == 2
        assert migrated["migration_status"] == "migrated"
        assert migrated["model"] == "seed-audio-1.0"
        assert migrated["prompt_hash"] == "prompt-hash"
        assert migrated["billing_duration_s"] == 1.25
        assert migrated["provider_request_ids"] == ["request-legacy-1"]

    def test_renderer_does_not_migrate_v2_checkpoint_again(
        self, tmp_path: Path
    ) -> None:
        audio_path = tmp_path / "scene_0001.wav"
        audio_path.write_bytes(_wav_bytes())

        checkpoints: list[dict] = []
        adapter = FakeAdapter([])
        service = SceneRenderService(
            adapter=adapter,
            output_root=tmp_path,
            checkpoint_writer=checkpoints.append,
        )

        # 第一次：v1 → 迁移写回 v2
        first = service.render(
            _plan(), model="seed-audio-1.0", checkpoint=self._v1_checkpoint(audio_path)
        )
        assert first.reused_checkpoint is True
        migrated = checkpoints[-1]

        # 第二次：已是 v2，直接复用，不再迁移、不再写回
        second = service.render(
            _plan(), model="seed-audio-1.0", checkpoint=migrated
        )
        assert second.reused_checkpoint is True
        assert len(checkpoints) == 1
        assert adapter.calls == []

    def test_renderer_preserves_incompatible_checkpoint_and_regenerates(
        self, tmp_path: Path
    ) -> None:
        audio_path = tmp_path / "scene_0001.wav"
        audio_path.write_bytes(_wav_bytes())
        broken = self._v1_checkpoint(audio_path)
        del broken["model"]
        snapshot = dict(broken)

        checkpoints: list[dict] = []
        adapter = FakeAdapter(
            [
                _success_response(
                    _wav_bytes(),
                    subtitles=[{"text": "第一句"}, {"text": "第二句"}],
                )
            ]
        )
        service = SceneRenderService(
            adapter=adapter,
            output_root=tmp_path,
            checkpoint_writer=checkpoints.append,
        )

        result = service.render(_plan(), checkpoint=broken)

        # 缺字段不得静默当作命中：不复用、不破坏旧 checkpoint，转重新生成
        assert result.reused_checkpoint is False
        assert broken == snapshot
        assert len(adapter.calls) == 1
        # 重新生成后写入的是全新 v2 checkpoint
        assert checkpoints[-1]["schema_version"] == 2
        assert "migration_status" not in checkpoints[-1]
