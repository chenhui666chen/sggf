"""Explicit Seed Audio scene rendering orchestration."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import math
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

from adapters.volcengine.audio_generation import DEFAULT_AUDIO_CONFIG
from app.services.audiobook.atomic_files import write_bytes_atomic
from app.services.audiobook.project_audio_config import DEFAULT_SEED_AUDIO_MODEL

from .checkpoint_contracts import (
    CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION,
    SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION,
    SEED_SCENE_CHECKPOINT_TYPE,
)
from .checkpoint_migration import (
    MIGRATION_STATUS_MIGRATED,
    migrate_seed_scene_checkpoint,
)
from app.services.audiobook.prompt_audio_asr_provider import (
    sanitize_asr_audit_metadata,
)
from app.services.audiobook.prompt_audio_asr_pricing import (
    estimate_prompt_audio_asr_cost_yuan,
    get_prompt_audio_asr_pricing,
)
from app.services.audiobook.timed_subtitles import (
    has_timed_subtitle_payload,
    normalize_timed_subtitle_payload,
)

from .audio_analysis import SceneAudioTechnicalAnalyzer
from .models import DEFERRED_PREVIEW_REFERENCE_FIELD, SceneRenderPlan
from .preview_reference_asset import PreviewReferenceMaterializer
from .quality_gate import SceneAudioQualityGate, SceneAudioQualityReport


logger = logging.getLogger(__name__)

CHECKPOINT_SCHEMA_VERSION = CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION
SCENE_RENDERER_VERSION = "scene-render-service-v2"
RETRY_PROMPT_SUFFIX = "重试约束：严格保留所有原文台词，禁止新增、删减、改写或替换任何可辨识对白。"
RETRYABLE_DOWNLOAD_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class SceneRenderError(RuntimeError):
    """Raised for a scene response that cannot be persisted or evaluated."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class SceneRenderResult:
    scene_id: str
    status: str
    action: str
    attempts: int
    audio_path: Path | None
    subtitle_payload: Any
    quality_report: SceneAudioQualityReport | None
    fallback_reason: str | None = None
    reused_checkpoint: bool = False
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class _AsrTimelineResult:
    attempted: bool = False
    transcript: str | None = None
    subtitle_payload: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None


Downloader = Callable[[str], bytes | tuple[bytes, str | None]]
CheckpointWriter = Callable[[dict[str, Any]], None]
AsrProvider = Callable[..., str | Mapping[str, Any]]
ProviderAttemptRecorder = Callable[[Mapping[str, Any]], Any]


class SceneRenderService:
    """Render one explicit Seed Audio scene with bounded recovery."""

    def __init__(
        self,
        *,
        adapter: Any,
        output_root: str | Path,
        downloader: Downloader | None = None,
        checkpoint_writer: CheckpointWriter | None = None,
        provider_attempt_recorder: ProviderAttemptRecorder | None = None,
        asr_provider: AsrProvider | None = None,
        quality_gate: SceneAudioQualityGate | None = None,
        technical_analyzer: SceneAudioTechnicalAnalyzer | None = None,
        max_retries: int = 1,
        max_asr_attempts_per_scene: int | None = None,
        max_asr_cost_yuan_per_scene: float = 0.2,
        max_audio_bytes: int = 100 * 1024 * 1024,
        download_timeout_s: float = 60.0,
        max_download_retries: int = 2,
        download_retry_backoff_s: float = 0.25,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_asr_attempts_per_scene is not None and max_asr_attempts_per_scene < 0:
            raise ValueError("max_asr_attempts_per_scene must be non-negative")
        if max_asr_cost_yuan_per_scene < 0:
            raise ValueError("max_asr_cost_yuan_per_scene must be non-negative")
        if max_audio_bytes <= 0:
            raise ValueError("max_audio_bytes must be positive")
        if max_download_retries < 0:
            raise ValueError("max_download_retries must be non-negative")
        if download_retry_backoff_s < 0:
            raise ValueError("download_retry_backoff_s must be non-negative")
        self.adapter = adapter
        self.output_root = Path(output_root)
        self.downloader = downloader
        self.checkpoint_writer = checkpoint_writer
        self.provider_attempt_recorder = provider_attempt_recorder
        self.asr_provider = asr_provider
        self.quality_gate = quality_gate or SceneAudioQualityGate()
        self.technical_analyzer = technical_analyzer or SceneAudioTechnicalAnalyzer(
            policy=self.quality_gate.policy
        )
        self.max_attempts = int(max_retries) + 1
        self.max_asr_attempts_per_scene = (
            self.max_attempts
            if max_asr_attempts_per_scene is None
            else int(max_asr_attempts_per_scene)
        )
        self.max_asr_cost_yuan_per_scene = float(max_asr_cost_yuan_per_scene)
        self.max_audio_bytes = int(max_audio_bytes)
        self.download_timeout_s = float(download_timeout_s)
        self.max_download_attempts = int(max_download_retries) + 1
        self.download_retry_backoff_s = float(download_retry_backoff_s)

    def render(
        self,
        plan: SceneRenderPlan,
        *,
        model: str = DEFAULT_SEED_AUDIO_MODEL,
        audio_config: Mapping[str, Any] | None = None,
        checkpoint: Mapping[str, Any] | None = None,
    ) -> SceneRenderResult:
        resolved_audio_config = dict(DEFAULT_AUDIO_CONFIG)
        resolved_audio_config.update(dict(audio_config or {}))
        reused = self._reuse_checkpoint(
            plan,
            checkpoint,
            model=model,
            audio_config=resolved_audio_config,
        )
        if reused is not None:
            return self._enrich_reused_timeline(
                plan,
                reused,
                model=model,
                audio_config=resolved_audio_config,
            )

        if plan.render_mode != "seed_scene":
            return self._fallback(
                plan,
                attempts=0,
                reason=plan.fallback_reason or "plan_render_mode_is_not_seed_scene",
            )

        last_reason = "scene_render_failed"
        last_report: SceneAudioQualityReport | None = None
        last_subtitle: Any = None
        last_audio_path: Path | None = None
        last_metadata: dict[str, Any] = {}
        billing_attempts: list[dict[str, Any]] = []
        asr_attempts: list[dict[str, Any]] = []
        completed_attempts = 0

        for attempt in range(1, self.max_attempts + 1):
            completed_attempts = attempt
            prompt = plan.prompt
            if attempt > 1:
                prompt = f"{prompt}\n{RETRY_PROMPT_SUFFIX}"
            try:
                response = self._generate(
                    prompt,
                    model=model,
                    references=plan.references,
                    audio_config=resolved_audio_config,
                )
                audio_source, subtitle_payload, metadata = self._extract_response(response)
                billing_record = self._billing_record(metadata)
                if billing_record:
                    billing_attempts.append(billing_record)
                    self._record_provider_attempt(
                        plan,
                        model=model,
                        attempt=attempt,
                        billing_record=billing_record,
                    )
                last_subtitle = subtitle_payload
                last_metadata = metadata
                if not audio_source:
                    raise SceneRenderError("provider_response_has_no_audio")

                audio_path = self._persist_audio(
                    plan,
                    audio_source,
                    metadata=metadata,
                )
                last_audio_path = audio_path
                transient_audio_url = (
                    str(audio_source).strip()
                    if isinstance(audio_source, str)
                    and audio_source.startswith(("http://", "https://"))
                    else None
                )
                asr_result = self._run_asr_if_needed(
                    audio_path,
                    subtitle_payload,
                    audio_url=transient_audio_url,
                    estimated_duration_s=self._asr_duration_seconds(metadata),
                    attempt_records=asr_attempts,
                )
                technical_report = self.technical_analyzer.analyze(audio_path)
                quality_metadata = technical_report.to_quality_metadata()
                report = self.quality_gate.evaluate(
                    expected_texts=tuple(
                        line for line in plan.expected_text.splitlines() if line.strip()
                    ),
                    subtitle_payload=subtitle_payload,
                    asr_transcript=asr_result.transcript,
                    expected_vocalizations=plan.expected_vocalizations,
                    audio_metadata=quality_metadata,
                )
                last_report = report
                effective_subtitle, timeline_used = self._select_subtitle_timeline(
                    plan,
                    provider_subtitle=subtitle_payload,
                    asr_result=asr_result,
                    primary_report=report,
                    audio_metadata=quality_metadata,
                )
                last_subtitle = effective_subtitle
                last_metadata = self._with_subtitle_timeline_metadata(
                    metadata,
                    provider_subtitle=subtitle_payload,
                    asr_result=asr_result,
                    timeline_used=timeline_used,
                )
                if report.passed:
                    result = SceneRenderResult(
                        scene_id=plan.scene_id,
                        status="passed",
                        action="assemble",
                        attempts=attempt,
                        audio_path=audio_path,
                        subtitle_payload=effective_subtitle,
                        quality_report=report,
                        metadata=self._with_billing_metadata(
                            self._with_asr_attempt_metadata(
                                last_metadata,
                                asr_attempts,
                            ),
                            billing_attempts,
                        ),
                    )
                    self._write_checkpoint(
                        self._checkpoint_payload(
                            plan,
                            result,
                            model=model,
                            audio_config=resolved_audio_config,
                        ),
                    )
                    return result
                last_reason = report.fallback_reason or "scene_quality_gate_failed"
                if report.status == "needs_asr":
                    break
            except Exception as exc:
                last_reason = self._error_reason(exc)
                logger.warning(
                    "Seed Audio 场景渲染失败: scene=%s attempt=%d error=%s",
                    plan.scene_id,
                    attempt,
                    exc,
                )
                if isinstance(exc, SceneRenderError) and not exc.retryable:
                    break

        result = self._fallback(
            plan,
            attempts=completed_attempts,
            reason=last_reason,
            audio_path=last_audio_path,
            subtitle_payload=last_subtitle,
            quality_report=last_report,
            metadata=self._with_billing_metadata(
                self._with_asr_attempt_metadata(
                    last_metadata,
                    asr_attempts,
                ),
                billing_attempts,
            ),
        )
        self._write_checkpoint(
            self._checkpoint_payload(
                plan,
                result,
                model=model,
                audio_config=resolved_audio_config,
            )
        )
        return result

    def _generate(
        self,
        prompt: str,
        *,
        model: str,
        references: tuple[dict[str, Any], ...],
        audio_config: Mapping[str, Any],
    ) -> Any:
        if any(
            reference.get(DEFERRED_PREVIEW_REFERENCE_FIELD)
            for reference in references
        ):
            raise SceneRenderError(
                "unmaterialized_preview_reference",
                retryable=False,
            )
        generator = getattr(self.adapter, "generate", None)
        if not callable(generator):
            raise SceneRenderError("scene adapter must provide generate()")
        return generator(
            prompt=prompt,
            model=model,
            references=[dict(reference) for reference in references],
            audio_config=dict(audio_config),
            watermark={},
        )

    @classmethod
    def _extract_response(
        cls,
        response: Any,
    ) -> tuple[bytes | str | None, Any, dict[str, Any]]:
        if isinstance(response, Mapping):
            source = dict(response)
            nested = source.get("data")
            if isinstance(nested, Mapping):
                merged = dict(nested)
                merged.update({key: value for key, value in source.items() if key != "data"})
                source = merged
            if source.get("success") is False:
                error_code = str(source.get("error_code") or "").strip().lower()
                trace = source.get("trace") if isinstance(source.get("trace"), Mapping) else {}
                retryable = trace.get("retryable", source.get("retryable"))
                if retryable is None:
                    retryable = error_code not in {"invalid_request", "authentication_error"}
                raise SceneRenderError(
                    str(source.get("error") or source.get("message") or "provider_generation_failed"),
                    retryable=bool(retryable),
                )
            metadata = dict(source.get("metadata") or {}) if isinstance(source.get("metadata"), Mapping) else {}
            audio_source = cls._first_value(
                source,
                "audio_data",
                "audio_base64",
                "audio",
                "audio_url",
                "url",
            )
            subtitle = cls._first_value(source, "subtitles", "subtitle", "utterances")
            for key in ("duration", "original_duration", "request_id", "audio_format"):
                if key in source and key not in metadata:
                    metadata[key] = source[key]
            if isinstance(audio_source, str) and audio_source.startswith(("http://", "https://")):
                return audio_source, subtitle, metadata
            return audio_source, subtitle, metadata

        success = getattr(response, "success", True)
        if success is False:
            error_code = str(getattr(response, "error_code", "") or "").strip().lower()
            trace = getattr(response, "trace", {})
            retryable = trace.get("retryable") if isinstance(trace, Mapping) else None
            if retryable is None:
                retryable = error_code not in {"invalid_request", "authentication_error"}
            raise SceneRenderError(
                str(getattr(response, "error", "provider_generation_failed")),
                retryable=bool(retryable),
            )
        metadata_value = getattr(response, "metadata", {})
        metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
        outputs = getattr(response, "outputs", ()) or ()
        audio_source = next((value for value in outputs if value), None)
        subtitle = metadata.get("subtitles") or metadata.get("subtitle") or metadata.get("utterances")
        return audio_source, subtitle, metadata

    @staticmethod
    def _first_value(source: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
        return None

    def _persist_audio(
        self,
        plan: SceneRenderPlan,
        audio_source: bytes | str,
        *,
        metadata: Mapping[str, Any],
    ) -> Path:
        audio_bytes, content_type, source_url = self._resolve_audio_source(audio_source)
        if not audio_bytes:
            raise SceneRenderError("generated_audio_is_empty")
        if len(audio_bytes) > self.max_audio_bytes:
            raise SceneRenderError("generated_audio_is_too_large")

        extension = PreviewReferenceMaterializer._detect_extension(
            audio_bytes,
            content_type=content_type,
            source_url=source_url,
        )
        self.output_root.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=f".{extension}",
                dir=self.output_root,
                delete=False,
            ) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = Path(temp_file.name)
            report = self.technical_analyzer.analyze(temp_path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        if not report.audio_decodable or not report.duration_s or report.duration_s <= 0:
            raise SceneRenderError("generated_audio_not_decodable")

        digest = hashlib.sha256(audio_bytes).hexdigest()
        scene_id = self._safe_path_component(plan.scene_id)
        target = self.output_root / "scenes" / scene_id / f"{plan.prompt_hash[:16]}-{digest[:16]}.{extension}"
        if not target.exists() or target.stat().st_size != len(audio_bytes):
            write_bytes_atomic(target, audio_bytes)
        return target

    def _resolve_audio_source(
        self,
        audio_source: bytes | str,
    ) -> tuple[bytes, str | None, str | None]:
        if isinstance(audio_source, bytes):
            return audio_source, None, None
        value = str(audio_source or "").strip()
        if value.startswith(("http://", "https://")):
            audio_bytes, content_type = self._download_audio_url(value)
            return audio_bytes, content_type, value
        if value.startswith("data:"):
            header, encoded = value.split(",", 1)
            content_type = header[5:].split(";", 1)[0].strip().lower() or None
        else:
            content_type = None
            encoded = value
        try:
            return base64.b64decode(re.sub(r"\s+", "", encoded), validate=True), content_type, None
        except (binascii.Error, ValueError) as exc:
            raise SceneRenderError("generated_audio_base64_invalid") from exc

    def _download_http(self, url: str) -> tuple[bytes, str | None]:
        response = httpx.get(
            url,
            timeout=self.download_timeout_s,
            follow_redirects=True,
        )
        response.raise_for_status()
        if len(response.content) > self.max_audio_bytes:
            raise SceneRenderError("generated_audio_is_too_large")
        return response.content, response.headers.get("content-type")

    def _download_audio_url(self, url: str) -> tuple[bytes, str | None]:
        for attempt in range(1, self.max_download_attempts + 1):
            try:
                result = (
                    self.downloader(url)
                    if self.downloader is not None
                    else self._download_http(url)
                )
                if isinstance(result, tuple):
                    audio_bytes = bytes(result[0] or b"")
                    content_type = result[1]
                else:
                    audio_bytes = bytes(result or b"")
                    content_type = None
                if len(audio_bytes) > self.max_audio_bytes:
                    raise SceneRenderError(
                        "generated_audio_is_too_large",
                        retryable=False,
                    )
                if attempt > 1:
                    logger.info(
                        "Seed Audio 结果音频下载重试成功: attempt=%d/%d bytes=%d",
                        attempt,
                        self.max_download_attempts,
                        len(audio_bytes),
                    )
                return audio_bytes, content_type
            except Exception as exc:
                if not self._is_retryable_download_error(exc):
                    if isinstance(exc, SceneRenderError):
                        raise
                    raise SceneRenderError(
                        f"audio_download_failed:{exc.__class__.__name__}",
                        retryable=False,
                    ) from exc
                if attempt >= self.max_download_attempts:
                    raise SceneRenderError(
                        f"audio_download_failed:{exc.__class__.__name__}",
                        retryable=False,
                    ) from exc
                logger.warning(
                    "Seed Audio 结果音频下载失败，将重试同一临时地址: "
                    "attempt=%d/%d error=%s",
                    attempt,
                    self.max_download_attempts,
                    self._download_error_summary(exc),
                )
                if self.download_retry_backoff_s > 0:
                    time.sleep(self.download_retry_backoff_s * attempt)

        raise SceneRenderError("audio_download_failed:unknown", retryable=False)

    @staticmethod
    def _is_retryable_download_error(error: Exception) -> bool:
        if isinstance(error, httpx.TransportError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in RETRYABLE_DOWNLOAD_STATUS_CODES
        return isinstance(error, (ConnectionError, TimeoutError))

    @staticmethod
    def _download_error_summary(error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            return f"HTTP_{error.response.status_code}"
        return error.__class__.__name__

    def _run_asr_if_needed(
        self,
        audio_path: Path,
        subtitle_payload: Any,
        *,
        audio_url: str | None = None,
        estimated_duration_s: float = 120.0,
        attempt_records: list[dict[str, Any]] | None = None,
    ) -> _AsrTimelineResult:
        if has_timed_subtitle_payload(subtitle_payload) or self.asr_provider is None:
            return _AsrTimelineResult()
        provider_text_available = bool(
            self.quality_gate._extract_subtitle_lines(subtitle_payload)
        )
        if provider_text_available and not bool(
            getattr(self.asr_provider, "supports_timestamps", True)
        ):
            return _AsrTimelineResult()
        records = attempt_records if attempt_records is not None else []
        provider_hint = str(
            getattr(self.asr_provider, "provider_name", "")
            or getattr(self.asr_provider, "name", "")
            or ""
        ).strip()
        model_hint = str(getattr(self.asr_provider, "model", "") or "").strip()
        budget_error = self._asr_budget_error(
            records,
            provider=provider_hint,
            model=model_hint,
            estimated_duration_s=estimated_duration_s,
        )
        if budget_error:
            if provider_text_available:
                return _AsrTimelineResult(error=budget_error)
            raise SceneRenderError(budget_error, retryable=False)

        attempt_record = self._start_asr_attempt_record(
            records,
            provider=provider_hint,
            model=model_hint,
            estimated_duration_s=estimated_duration_s,
        )
        try:
            result = (
                self.asr_provider(audio_path, audio_url=audio_url)
                if audio_url
                else self.asr_provider(audio_path)
            )
        except Exception as exc:
            code = str(getattr(exc, "code", "") or exc.__class__.__name__).strip()
            attempt_record.update({"status": "failed", "error": code})
            if provider_text_available:
                logger.warning(
                    "ASR subtitle timeline enrichment failed; using provider text: "
                    "audio=%s error=%s",
                    audio_path,
                    code,
                )
                return _AsrTimelineResult(attempted=True, error=code)
            raise SceneRenderError(
                f"asr_failed:{code}",
                retryable=False,
            ) from exc
        if isinstance(result, Mapping):
            transcript = str(
                result.get("transcript")
                or result.get("text")
                or result.get("utterance")
                or ""
            ).strip()
            timeline = normalize_timed_subtitle_payload(result)
            if not transcript and timeline:
                transcript = " ".join(
                    str(item.get("text") or "").strip()
                    for item in timeline.get("segments") or ()
                    if str(item.get("text") or "").strip()
                )
            asr_result = _AsrTimelineResult(
                attempted=True,
                transcript=transcript or None,
                subtitle_payload=timeline,
                provider=str(result.get("provider") or "").strip() or None,
                model=str(result.get("model") or "").strip() or None,
                metadata=sanitize_asr_audit_metadata(result.get("metadata")),
            )
            self._complete_asr_attempt_record(attempt_record, asr_result)
            return asr_result
        asr_result = _AsrTimelineResult(
            attempted=True,
            transcript=str(result or "").strip() or None,
        )
        self._complete_asr_attempt_record(attempt_record, asr_result)
        return asr_result

    def _asr_budget_error(
        self,
        records: list[dict[str, Any]],
        *,
        provider: str,
        model: str,
        estimated_duration_s: float,
    ) -> str | None:
        if len(records) >= self.max_asr_attempts_per_scene:
            return "asr_call_budget_exhausted"
        estimated_cost = estimate_prompt_audio_asr_cost_yuan(
            provider=provider,
            model=model,
            duration_seconds=estimated_duration_s,
        )
        if estimated_cost is None:
            return None
        committed_cost = sum(
            float(record.get("estimated_cost_yuan") or 0.0) for record in records
        )
        if committed_cost + estimated_cost > self.max_asr_cost_yuan_per_scene:
            return "asr_cost_budget_exhausted"
        return None

    @staticmethod
    def _start_asr_attempt_record(
        records: list[dict[str, Any]],
        *,
        provider: str,
        model: str,
        estimated_duration_s: float,
    ) -> dict[str, Any]:
        duration = max(0.0, float(estimated_duration_s or 0.0))
        record: dict[str, Any] = {
            "attempt": len(records) + 1,
            "status": "started",
            "provider": provider or None,
            "model": model or None,
            "estimated_duration_seconds": round(duration, 6),
        }
        pricing = get_prompt_audio_asr_pricing(provider, model)
        if pricing is not None:
            record.update(
                {
                    "estimated_cost_yuan": estimate_prompt_audio_asr_cost_yuan(
                        provider=provider,
                        model=model,
                        duration_seconds=duration,
                    ),
                    "pricing_source": pricing.pricing_source,
                    "pricing_basis": pricing.pricing_basis,
                }
            )
        records.append(record)
        return record

    @staticmethod
    def _complete_asr_attempt_record(
        record: dict[str, Any],
        result: _AsrTimelineResult,
    ) -> None:
        provider = result.provider or str(record.get("provider") or "")
        model = result.model or str(record.get("model") or "")
        record.update(
            {
                "status": "succeeded",
                "provider": provider or None,
                "model": model or None,
            }
        )
        metadata = result.metadata or {}
        request_id = str(
            metadata.get("request_id")
            or metadata.get("task_id")
            or metadata.get("response_id")
            or ""
        ).strip()
        if request_id:
            record["request_id"] = request_id
        usage = metadata.get("usage")
        if not isinstance(usage, Mapping):
            return
        try:
            duration = float(usage.get("duration"))
        except (TypeError, ValueError):
            return
        if duration <= 0:
            return
        record["usage"] = {"duration": duration}
        pricing = get_prompt_audio_asr_pricing(provider, model)
        actual_cost = estimate_prompt_audio_asr_cost_yuan(
            provider=provider,
            model=model,
            duration_seconds=duration,
        )
        if pricing is not None and actual_cost is not None:
            record.update(
                {
                    "actual_cost_yuan": actual_cost,
                    "pricing_source": pricing.pricing_source,
                    "pricing_basis": pricing.pricing_basis,
                }
            )

    @staticmethod
    def _with_asr_attempt_metadata(
        metadata: Mapping[str, Any],
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        resolved = dict(metadata)
        if not records:
            return resolved
        safe_records = [dict(record) for record in records]
        resolved["asr_attempt_count"] = len(safe_records)
        resolved["asr_attempts"] = safe_records
        actual_costs = [
            float(record["actual_cost_yuan"])
            for record in safe_records
            if record.get("actual_cost_yuan") is not None
        ]
        if actual_costs:
            resolved["asr_actual_cost_yuan"] = round(sum(actual_costs), 6)
        return resolved

    @staticmethod
    def _existing_asr_attempt_records(
        metadata: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(metadata, Mapping):
            return []
        records = metadata.get("asr_attempts")
        if not isinstance(records, list):
            return []
        return [dict(record) for record in records if isinstance(record, Mapping)]

    @staticmethod
    def _asr_duration_seconds(metadata: Mapping[str, Any]) -> float:
        for key in ("original_duration", "duration"):
            try:
                duration = float(metadata.get(key))
            except (TypeError, ValueError):
                continue
            if duration > 0:
                return duration
        return 120.0

    def _select_subtitle_timeline(
        self,
        plan: SceneRenderPlan,
        *,
        provider_subtitle: Any,
        asr_result: _AsrTimelineResult,
        primary_report: SceneAudioQualityReport,
        audio_metadata: Mapping[str, Any],
    ) -> tuple[Any, bool]:
        if not asr_result.subtitle_payload or not primary_report.passed:
            return provider_subtitle, False
        if provider_subtitle:
            asr_report = self.quality_gate.evaluate(
                expected_texts=tuple(
                    line for line in plan.expected_text.splitlines() if line.strip()
                ),
                subtitle_payload=None,
                asr_transcript=asr_result.transcript,
                expected_vocalizations=plan.expected_vocalizations,
                audio_metadata=audio_metadata,
            )
            if not asr_report.passed:
                return provider_subtitle, False
        return asr_result.subtitle_payload, True

    @staticmethod
    def _with_subtitle_timeline_metadata(
        metadata: Mapping[str, Any],
        *,
        provider_subtitle: Any,
        asr_result: _AsrTimelineResult,
        timeline_used: bool,
    ) -> dict[str, Any]:
        resolved = dict(metadata)
        if asr_result.provider:
            resolved["asr_provider"] = asr_result.provider
        if asr_result.model:
            resolved["asr_model"] = asr_result.model
        audit_metadata = asr_result.metadata or {}
        request_id = str(
            audit_metadata.get("request_id")
            or audit_metadata.get("task_id")
            or audit_metadata.get("response_id")
            or ""
        ).strip()
        if request_id:
            resolved["asr_request_id"] = request_id
        if isinstance(audit_metadata.get("usage"), Mapping):
            resolved["asr_usage"] = dict(audit_metadata["usage"])
        if timeline_used:
            resolved["subtitle_timeline_status"] = "available"
            resolved["subtitle_timeline_source"] = asr_result.provider or "asr"
            if asr_result.model:
                resolved["subtitle_timeline_model"] = asr_result.model
        elif has_timed_subtitle_payload(provider_subtitle):
            resolved["subtitle_timeline_status"] = "available"
            resolved["subtitle_timeline_source"] = "provider_subtitle"
        elif asr_result.error:
            resolved["subtitle_timeline_status"] = "failed"
            resolved["subtitle_timeline_error"] = asr_result.error
        elif asr_result.subtitle_payload:
            resolved["subtitle_timeline_status"] = "rejected"
        elif asr_result.attempted:
            resolved["subtitle_timeline_status"] = "unavailable"
        return resolved

    def _enrich_reused_timeline(
        self,
        plan: SceneRenderPlan,
        reused: SceneRenderResult,
        *,
        model: str,
        audio_config: Mapping[str, Any],
    ) -> SceneRenderResult:
        if (
            reused.status != "passed"
            or reused.audio_path is None
            or self.asr_provider is None
            or has_timed_subtitle_payload(reused.subtitle_payload)
        ):
            return reused
        try:
            asr_attempts = self._existing_asr_attempt_records(reused.metadata)
            asr_result = self._run_asr_if_needed(
                reused.audio_path,
                reused.subtitle_payload,
                attempt_records=asr_attempts,
            )
            if not asr_result.subtitle_payload:
                return reused
            technical_report = self.technical_analyzer.analyze(reused.audio_path)
            report = self.quality_gate.evaluate(
                expected_texts=tuple(
                    line for line in plan.expected_text.splitlines() if line.strip()
                ),
                subtitle_payload=None,
                asr_transcript=asr_result.transcript,
                expected_vocalizations=plan.expected_vocalizations,
                audio_metadata=technical_report.to_quality_metadata(),
            )
            if not report.passed:
                return reused
        except SceneRenderError:
            return reused

        enriched = SceneRenderResult(
            scene_id=reused.scene_id,
            status=reused.status,
            action=reused.action,
            attempts=reused.attempts,
            audio_path=reused.audio_path,
            subtitle_payload=asr_result.subtitle_payload,
            quality_report=report,
            fallback_reason=reused.fallback_reason,
            reused_checkpoint=True,
            metadata=self._with_asr_attempt_metadata(
                self._with_subtitle_timeline_metadata(
                    reused.metadata or {},
                    provider_subtitle=reused.subtitle_payload,
                    asr_result=asr_result,
                    timeline_used=True,
                ),
                asr_attempts,
            ),
        )
        self._write_checkpoint(
            self._checkpoint_payload(
                plan,
                enriched,
                model=model,
                audio_config=audio_config,
            )
        )
        return enriched

    def _reuse_checkpoint(
        self,
        plan: SceneRenderPlan,
        checkpoint: Mapping[str, Any] | None,
        *,
        model: str,
        audio_config: Mapping[str, Any],
    ) -> SceneRenderResult | None:
        if not checkpoint:
            return None
        resolved = self._resolve_checkpoint_schema(checkpoint)
        if resolved is None:
            return None
        checkpoint = resolved
        status = str(checkpoint.get("status") or "").strip()
        if status not in {"passed", "legacy_stems"}:
            return None
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            return None
        if checkpoint.get("renderer_version") != SCENE_RENDERER_VERSION:
            return None
        if checkpoint.get("model") != model:
            return None
        if checkpoint.get("audio_config") != dict(audio_config):
            return None
        if checkpoint.get("scene_id") != plan.scene_id:
            return None
        if checkpoint.get("prompt_hash") != plan.prompt_hash:
            return None
        if checkpoint.get("quality_policy_hash") != plan.quality_policy_hash:
            return None
        if tuple(checkpoint.get("reference_hashes") or ()) != tuple(plan.reference_hashes):
            return None
        if status == "legacy_stems":
            return SceneRenderResult(
                scene_id=plan.scene_id,
                status="legacy_stems",
                action="legacy_stems",
                attempts=int(checkpoint.get("attempts") or 0),
                audio_path=None,
                subtitle_payload=checkpoint.get("subtitle_payload"),
                quality_report=None,
                fallback_reason=(
                    str(checkpoint.get("fallback_reason") or "").strip()
                    or "scene_quality_gate_failed"
                ),
                reused_checkpoint=True,
                metadata=dict(checkpoint.get("metadata") or {}),
            )
        path = Path(str(checkpoint.get("audio_path") or ""))
        if not path.exists() or not path.is_file():
            return None
        return SceneRenderResult(
            scene_id=plan.scene_id,
            status="passed",
            action="assemble",
            attempts=int(checkpoint.get("attempts") or 0),
            audio_path=path,
            subtitle_payload=checkpoint.get("subtitle_payload"),
            quality_report=None,
            reused_checkpoint=True,
            metadata=dict(checkpoint.get("metadata") or {}),
        )

    def _resolve_checkpoint_schema(
        self,
        checkpoint: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        """把历史 checkpoint 解析到当前 schema：v1 走 append-only 迁移。

        迁移成功后写回新版本（旧签名字段不覆盖）并继续复用流程；
        无法证明兼容（legacy_checkpoint_incompatible）时不复用，
        也不破坏旧 checkpoint，由后续重新生成路径接管。
        """
        if checkpoint.get("schema_version") == CHECKPOINT_SCHEMA_VERSION:
            return checkpoint
        now_iso = datetime.now(timezone.utc).isoformat()
        result = migrate_seed_scene_checkpoint(checkpoint, now_iso=now_iso)
        if result.status != MIGRATION_STATUS_MIGRATED or result.checkpoint is None:
            logger.info(
                "Seed Audio 场景 checkpoint 不可迁移，放弃复用: status=%s reasons=%s",
                result.status,
                ",".join(result.reasons),
            )
            return None
        # append-only：新版本引用旧 checkpoint，旧签名字段只读保留。
        self._write_checkpoint(result.checkpoint)
        return result.checkpoint

    def _fallback(
        self,
        plan: SceneRenderPlan,
        *,
        attempts: int,
        reason: str,
        audio_path: Path | None = None,
        subtitle_payload: Any = None,
        quality_report: SceneAudioQualityReport | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> SceneRenderResult:
        return SceneRenderResult(
            scene_id=plan.scene_id,
            status="legacy_stems",
            action="legacy_stems",
            attempts=attempts,
            audio_path=audio_path,
            subtitle_payload=subtitle_payload,
            quality_report=quality_report,
            fallback_reason=reason,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _error_reason(error: Exception) -> str:
        message = str(error).strip()
        return message or error.__class__.__name__

    def _checkpoint_payload(
        self,
        plan: SceneRenderPlan,
        result: SceneRenderResult,
        *,
        model: str,
        audio_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        audio_sha256 = None
        if result.audio_path and result.audio_path.exists():
            audio_sha256 = hashlib.sha256(result.audio_path.read_bytes()).hexdigest()
        quality_payload = (
            asdict(result.quality_report)
            if result.quality_report is not None
            else None
        )
        duration = (
            result.quality_report.duration_s
            if result.quality_report is not None
            else None
        )
        if duration is None:
            duration = self._finite_positive_number(
                (result.metadata or {}).get("duration")
            )
        metadata = dict(result.metadata or {})
        billing = (
            dict(metadata.get("billing") or {})
            if isinstance(metadata.get("billing"), Mapping)
            else {}
        )
        provider_request_ids = [
            str(value)
            for value in billing.get("provider_request_ids") or ()
            if str(value or "").strip()
        ]
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_type": SEED_SCENE_CHECKPOINT_TYPE,
            "signature_contract_version": (
                SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION
            ),
            "producer_version": SCENE_RENDERER_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "renderer_version": SCENE_RENDERER_VERSION,
            "model": model,
            "audio_config": dict(audio_config),
            "scene_id": plan.scene_id,
            "source_segment_indices": list(plan.source_segment_indices),
            "source_text_hash": hashlib.sha256(
                plan.expected_text.encode("utf-8")
            ).hexdigest(),
            "status": result.status,
            "action": result.action,
            "attempts": result.attempts,
            "audio_path": str(result.audio_path) if result.audio_path else None,
            "audio_sha256": audio_sha256,
            "duration": duration,
            "subtitle_payload": result.subtitle_payload,
            "quality_report": quality_payload,
            "prompt": plan.prompt,
            "prompt_hash": plan.prompt_hash,
            "quality_policy_hash": plan.quality_policy_hash,
            "reference_hashes": list(plan.reference_hashes),
            "fallback_reason": result.fallback_reason,
            "provider_request_id": (
                provider_request_ids[-1]
                if provider_request_ids
                else metadata.get("request_id")
            ),
            "provider_request_ids": provider_request_ids,
            "billing_duration_s": self._finite_positive_number(
                billing.get("billable_duration_s")
            ),
            "metadata": metadata,
        }

    @classmethod
    def _billing_record(cls, metadata: Mapping[str, Any]) -> dict[str, Any] | None:
        duration = cls._finite_positive_number(metadata.get("original_duration"))
        request_id = str(metadata.get("request_id") or "").strip()
        if duration is None and not request_id:
            return None
        return {
            "original_duration": duration,
            "request_id": request_id or None,
        }

    def _record_provider_attempt(
        self,
        plan: SceneRenderPlan,
        *,
        model: str,
        attempt: int,
        billing_record: Mapping[str, Any],
    ) -> None:
        if self.provider_attempt_recorder is None:
            return
        record = {
            "provider_request_id": billing_record.get("request_id"),
            "scene_id": plan.scene_id,
            "model": model,
            "attempt": attempt,
            "original_duration": billing_record.get("original_duration"),
            "prompt_hash": plan.prompt_hash,
        }
        try:
            self.provider_attempt_recorder(record)
        except Exception as exc:  # pragma: no cover - billing metadata remains in checkpoint.
            logger.error(
                "Seed Audio provider attempt ledger 写入失败: scene=%s request=%s error=%s",
                plan.scene_id,
                billing_record.get("request_id"),
                exc,
            )

    @classmethod
    def _with_billing_metadata(
        cls,
        metadata: Mapping[str, Any] | None,
        billing_attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        resolved = dict(metadata or {})
        durations = [
            duration
            for item in billing_attempts
            if (duration := cls._finite_positive_number(item.get("original_duration")))
            is not None
        ]
        request_ids = [
            str(item.get("request_id"))
            for item in billing_attempts
            if str(item.get("request_id") or "").strip()
        ]
        resolved["billing"] = {
            "billable_duration_s": round(sum(durations), 4),
            "provider_request_ids": request_ids,
            "provider_request_count": len(request_ids),
        }
        return resolved

    @staticmethod
    def _finite_positive_number(value: Any) -> float | None:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(normalized) or normalized <= 0:
            return None
        return normalized

    def _write_checkpoint(self, payload: dict[str, Any]) -> None:
        if self.checkpoint_writer is None:
            return
        try:
            self.checkpoint_writer(payload)
        except Exception as exc:  # pragma: no cover - checkpoint failure must not lose audio
            logger.warning("Seed Audio 场景检查点写入失败: %s", exc)

    @staticmethod
    def _safe_path_component(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
        return normalized.strip(".-") or "scene"


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "SCENE_RENDERER_VERSION",
    "SceneRenderError",
    "SceneRenderResult",
    "SceneRenderService",
]
