"""Rendering and caching for the independent Seed Audio scene test unit."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from adapters.volcengine.audio_generation import DEFAULT_AUDIO_CONFIG
from app.core.env_loader import get_backend_root
from app.services.audiobook.atomic_files import write_bytes_atomic
from app.services.audiobook.scene_engine.audio_analysis import SceneAudioTechnicalAnalyzer
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceMaterializer,
)
from app.services.audiobook.scene_engine.quality_gate import SceneAudioQualityGate
from app.services.audiobook.scene_engine.scene_billing import (
    build_seed_scene_billing_summary,
)
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderService
from app.services.audiobook.tts_model_ids import (
    SEED_TTS_20_EXPRESSIVE_MODEL,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.seed_scene_test_unit import (
    SEED_SCENE_TEST_MODEL,
    SeedSceneResolvedReference,
    build_seed_scene_test_plan,
    get_seed_scene_test_case,
)


class SeedSceneTestRenderError(RuntimeError):
    """Raised when a test request cannot produce reviewable audio."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        self.retryable = retryable
        super().__init__(message)


class SeedSceneTestPreviewService:
    """Render one independent scene test and reuse its persisted provider output."""

    def __init__(
        self,
        *,
        adapter: Any,
        output_root: str | Path,
        technical_analyzer: SceneAudioTechnicalAnalyzer | None = None,
        quality_gate: SceneAudioQualityGate | None = None,
    ) -> None:
        self.adapter = adapter
        self.output_root = Path(output_root)
        self.technical_analyzer = technical_analyzer or SceneAudioTechnicalAnalyzer()
        self.quality_gate = quality_gate or SceneAudioQualityGate()
        self.reference_materializer = PreviewReferenceMaterializer(
            output_root=self.output_root / "r",
            technical_analyzer=self.technical_analyzer,
        )

    def render(
        self,
        *,
        case_id: str,
        variant_id: str,
        sample_index: int = 1,
        references: Sequence[Mapping[str, Any]] = (),
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        case = get_seed_scene_test_case(case_id)
        variant = next(
            (item for item in case["variants"] if item["id"] == variant_id),
            None,
        )
        if variant is None:
            raise ValueError(f"unknown Seed Audio scene test variant: {variant_id}")
        if variant_id == "described_voices" and references:
            raise ValueError("described_voices does not accept references")
        resolved_references, reference_summaries = self._materialize_references(
            case,
            references,
        )
        plan = build_seed_scene_test_plan(
            case_id,
            variant_id,
            resolved_references,
            sample_index=sample_index,
        )
        cache_key = self._cache_key(
            plan.prompt_hash,
            plan.reference_hashes,
            sample_index=sample_index,
        )
        manifest_path = self.output_root / "manifests" / f"{cache_key}.json"

        if not force_regenerate:
            cached_manifest = self._read_manifest(manifest_path, plan)
            if cached_manifest is None and sample_index == 1:
                legacy_key = self._legacy_cache_key(
                    plan.prompt_hash,
                    plan.reference_hashes,
                )
                cached_manifest = self._read_manifest(
                    self.output_root / "manifests" / f"{legacy_key}.json",
                    plan,
                )
            if cached_manifest is not None:
                cached_audio_path = Path(cached_manifest["audio_path"])
                sample_id = str(cached_manifest.get("sample_id") or "").strip()
                if not sample_id:
                    sample_id = self._sample_id(cache_key, cached_audio_path)
                return self._build_payload(
                    case=case,
                    variant=variant,
                    plan=plan,
                    audio_path=cached_audio_path,
                    subtitle=cached_manifest.get("subtitle"),
                    metadata=cached_manifest.get("metadata") or {},
                    generation_status=str(cached_manifest.get("generation_status") or "passed"),
                    fallback_reason=cached_manifest.get("fallback_reason"),
                    reference_summaries=reference_summaries,
                    sample_index=sample_index,
                    sample_id=sample_id,
                    generation_latency_s=cached_manifest.get("generation_latency_s"),
                    cached=True,
                )

        renderer = SceneRenderService(
            adapter=self.adapter,
            output_root=self.output_root / "renders",
            technical_analyzer=self.technical_analyzer,
            quality_gate=self.quality_gate,
            max_retries=0,
        )
        started = time.perf_counter()
        result = renderer.render(plan, model=SEED_SCENE_TEST_MODEL)
        generation_latency_s = round(time.perf_counter() - started, 4)
        if result.audio_path is None or not result.audio_path.exists():
            reason = result.fallback_reason or "Seed Audio test did not return reviewable audio"
            raise SeedSceneTestRenderError(
                reason,
                retryable=not reason.startswith("audio_download_failed:"),
            )
        sample_id = self._sample_id(cache_key, result.audio_path)

        manifest = {
            "schema_version": 3,
            "case_id": case_id,
            "variant": variant_id,
            "sample_index": sample_index,
            "sample_id": sample_id,
            "prompt_hash": plan.prompt_hash,
            "reference_hashes": list(plan.reference_hashes),
            "audio_relative_path": self._audio_relative_path(result.audio_path),
            "subtitle": result.subtitle_payload,
            "metadata": dict(result.metadata or {}),
            "generation_status": result.status,
            "fallback_reason": result.fallback_reason,
            "generation_latency_s": generation_latency_s,
        }
        write_bytes_atomic(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return self._build_payload(
            case=case,
            variant=variant,
            plan=plan,
            audio_path=result.audio_path,
            subtitle=result.subtitle_payload,
            metadata=dict(result.metadata or {}),
            generation_status=result.status,
            fallback_reason=result.fallback_reason,
            reference_summaries=reference_summaries,
            sample_index=sample_index,
            sample_id=sample_id,
            generation_latency_s=generation_latency_s,
            cached=False,
        )

    def _materialize_references(
        self,
        case: Mapping[str, Any],
        references: Sequence[Mapping[str, Any]],
    ) -> tuple[tuple[SeedSceneResolvedReference, ...], list[dict[str, Any]]]:
        materialized_by_slot: dict[str, tuple[SeedSceneResolvedReference, dict[str, Any]]] = {}
        known_slots = {slot["id"] for slot in case["reference_slots"]}
        for raw_reference in references:
            slot_id = str(raw_reference.get("slot_id") or "").strip()
            if not slot_id:
                raise ValueError("reference slot_id is required")
            if slot_id not in known_slots:
                raise ValueError(f"unknown reference slot: {slot_id}")
            if slot_id in materialized_by_slot:
                raise ValueError(f"duplicate reference slot: {slot_id}")
            encoded_audio = str(raw_reference.get("audio_data_base64") or "").strip()
            audio_url = str(raw_reference.get("audio_url") or "").strip()
            if encoded_audio and audio_url:
                raise ValueError(
                    f"reference audio_data_base64 and audio_url are mutually exclusive: {slot_id}"
                )
            mime_type = str(raw_reference.get("audio_mime_type") or "audio/mpeg").strip()
            source_model = str(raw_reference.get("source_model") or "").strip()
            source_voice_id = str(raw_reference.get("source_voice_id") or "").strip()
            normalized_model = normalize_audiobook_tts_model(source_model, default="")
            if normalized_model == SEED_TTS_20_EXPRESSIVE_MODEL:
                if not source_voice_id:
                    raise ValueError(f"native Seed-TTS speaker is required: {slot_id}")
                speaker_identity = {
                    "schema_version": 1,
                    "model": normalized_model,
                    "speaker": source_voice_id,
                }
                speaker_hash = hashlib.sha256(
                    json.dumps(
                        speaker_identity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                resolved = SeedSceneResolvedReference(
                    slot_id=slot_id,
                    reference={"speaker": source_voice_id},
                    sha256=speaker_hash,
                )
                summary = {
                    "slot_id": slot_id,
                    "source_model": normalized_model,
                    "source_voice_id": source_voice_id,
                    "reference_type": "speaker",
                    "sha256": speaker_hash,
                    "duration_s": None,
                }
                materialized_by_slot[slot_id] = (resolved, summary)
                continue

            materializer_config = {
                "tts_model": source_model,
                "voice_id": source_voice_id,
            }
            if encoded_audio:
                materializer_config["preview_audio_data"] = (
                    f"data:{mime_type};base64,{encoded_audio}"
                )
            elif audio_url:
                materializer_config["preview_audio_url"] = audio_url
            asset = self.reference_materializer.materialize(materializer_config)
            resolved = SeedSceneResolvedReference(
                slot_id=slot_id,
                reference=asset.reference,
                sha256=asset.sha256,
            )
            summary = {
                "slot_id": slot_id,
                "source_model": source_model,
                "source_voice_id": source_voice_id,
                "reference_type": "audio",
                "sha256": asset.sha256,
                "duration_s": asset.duration_s,
            }
            materialized_by_slot[slot_id] = (resolved, summary)

        ordered_resolved = []
        ordered_summaries = []
        for slot in case["reference_slots"]:
            materialized = materialized_by_slot.get(slot["id"])
            if materialized is None:
                continue
            ordered_resolved.append(materialized[0])
            ordered_summaries.append(materialized[1])
        return tuple(ordered_resolved), ordered_summaries

    def _build_payload(
        self,
        *,
        case: Mapping[str, Any],
        variant: Mapping[str, Any],
        plan: Any,
        audio_path: Path,
        subtitle: Any,
        metadata: Mapping[str, Any],
        generation_status: str,
        fallback_reason: Any,
        reference_summaries: list[dict[str, Any]],
        sample_index: int,
        sample_id: str,
        generation_latency_s: Any,
        cached: bool,
    ) -> dict[str, Any]:
        audio_bytes = audio_path.read_bytes()
        audio_format = audio_path.suffix.lower().lstrip(".") or "mp3"
        audio_mime_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"
        technical_report = self.technical_analyzer.analyze(audio_path)
        quality_report = self.quality_gate.evaluate(
            expected_texts=tuple(case["expected_texts"]),
            subtitle_payload=subtitle,
            audio_metadata=technical_report.to_quality_metadata(),
        )
        resolved_fallback_reason = None if quality_report.passed else (
            quality_report.fallback_reason or fallback_reason
        )
        request_id = str(metadata.get("request_id") or "").strip() or None
        duration = technical_report.duration_s
        if duration is None and metadata.get("duration") is not None:
            duration = float(metadata["duration"])
        billing_metadata = (
            metadata.get("billing")
            if isinstance(metadata.get("billing"), Mapping)
            else {}
        )
        billable_duration_s = billing_metadata.get("billable_duration_s")
        if billable_duration_s is None:
            billable_duration_s = metadata.get("original_duration")
        raw_request_ids = billing_metadata.get("provider_request_ids") or ()
        if not raw_request_ids and metadata.get("request_id"):
            raw_request_ids = (metadata.get("request_id"),)
        request_ids = tuple(
            request_id
            for value in raw_request_ids
            if (request_id := str(value or "").strip())
        )
        if request_ids:
            billing = build_seed_scene_billing_summary(
                None,
                provider_attempts=(
                    {
                        "provider_request_id": request_ids[0],
                        "original_duration": billable_duration_s,
                    },
                ),
                model=SEED_SCENE_TEST_MODEL,
            )
        else:
            billing = build_seed_scene_billing_summary(
                {
                    sample_id: {
                        "billing_duration_s": billable_duration_s,
                        "provider_request_ids": (),
                    }
                },
                model=SEED_SCENE_TEST_MODEL,
            )
        return {
            "model": SEED_SCENE_TEST_MODEL,
            "case_id": case["id"],
            "variant": variant["id"],
            "sample_index": sample_index,
            "sample_id": sample_id,
            "blind_label": variant["blind_label"],
            "prompt": plan.prompt,
            "expected_texts": list(case["expected_texts"]),
            "audio_data_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "audio_format": audio_format,
            "audio_mime_type": audio_mime_type,
            "audio_size_bytes": len(audio_bytes),
            "audio_path": str(audio_path.resolve()),
            "duration": duration,
            "subtitle": subtitle,
            "request_id": request_id,
            "generation_latency_s": self._optional_non_negative_float(
                generation_latency_s
            ),
            "billing": billing,
            "generation_status": "passed" if quality_report.passed else generation_status,
            "fallback_reason": resolved_fallback_reason,
            "quality_report": asdict(quality_report),
            "references": reference_summaries,
            "cached": cached,
        }

    def _read_manifest(self, manifest_path: Path, plan: Any) -> dict[str, Any] | None:
        if not manifest_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("prompt_hash") != plan.prompt_hash:
                return None
            if tuple(manifest.get("reference_hashes") or ()) != tuple(plan.reference_hashes):
                return None
            audio_path = self._resolve_manifest_audio_path(manifest)
            if audio_path is None:
                return None
            manifest["audio_path"] = str(audio_path)
            return manifest
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _audio_relative_path(self, audio_path: Path) -> str:
        resolved_path = audio_path.resolve()
        output_root = self.output_root.resolve()
        if not resolved_path.is_relative_to(output_root):
            raise SeedSceneTestRenderError(
                f"Seed Audio test output escaped its storage root: {resolved_path}"
            )
        return resolved_path.relative_to(output_root).as_posix()

    def _resolve_manifest_audio_path(
        self,
        manifest: Mapping[str, Any],
    ) -> Path | None:
        relative_path = manifest.get("audio_relative_path")
        if relative_path is not None:
            return self._resolve_relative_audio_path(relative_path)

        legacy_path_value = str(manifest.get("audio_path") or "").strip()
        if not legacy_path_value:
            return None

        native_path = Path(legacy_path_value).resolve()
        if self._is_reusable_audio_path(native_path):
            return native_path

        normalized_legacy_path = legacy_path_value.replace("\\", "/")
        marker = "/renders/"
        marker_index = normalized_legacy_path.find(marker)
        if marker_index >= 0:
            portable_path = normalized_legacy_path[marker_index + 1 :]
        elif normalized_legacy_path.startswith("renders/"):
            portable_path = normalized_legacy_path
        else:
            return None
        return self._resolve_relative_audio_path(portable_path)

    def _resolve_relative_audio_path(self, value: Any) -> Path | None:
        normalized_path = str(value or "").strip().replace("\\", "/")
        portable_path = PurePosixPath(normalized_path)
        if (
            not normalized_path
            or portable_path.is_absolute()
            or not portable_path.parts
            or portable_path.parts[0] != "renders"
            or ".." in portable_path.parts
        ):
            return None
        candidate = self.output_root.joinpath(*portable_path.parts).resolve()
        return candidate if self._is_reusable_audio_path(candidate) else None

    def _is_reusable_audio_path(self, audio_path: Path) -> bool:
        output_root = self.output_root.resolve()
        return (
            audio_path.is_relative_to(output_root)
            and audio_path.exists()
            and audio_path.is_file()
        )

    @staticmethod
    def _cache_key(
        prompt_hash: str,
        reference_hashes: Sequence[str],
        *,
        sample_index: int,
    ) -> str:
        signature = json.dumps(
            {
                "schema_version": 2,
                "model": SEED_SCENE_TEST_MODEL,
                "sample_index": sample_index,
                "prompt_hash": prompt_hash,
                "reference_hashes": list(reference_hashes),
                "audio_config": DEFAULT_AUDIO_CONFIG,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()

    @staticmethod
    def _legacy_cache_key(prompt_hash: str, reference_hashes: Sequence[str]) -> str:
        signature = json.dumps(
            {
                "schema_version": 1,
                "model": SEED_SCENE_TEST_MODEL,
                "prompt_hash": prompt_hash,
                "reference_hashes": list(reference_hashes),
                "audio_config": DEFAULT_AUDIO_CONFIG,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()

    @staticmethod
    def _sample_id(cache_key: str, audio_path: Path) -> str:
        audio_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        digest = hashlib.sha256(
            f"{cache_key}:{audio_sha256}".encode("ascii")
        ).hexdigest()
        return f"seed-sample-{digest[:16]}"

    @staticmethod
    def _optional_non_negative_float(value: Any) -> float | None:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        return round(normalized, 4) if normalized >= 0 else None


def create_seed_scene_test_preview_service() -> SeedSceneTestPreviewService:
    from adapters.registry import registry

    adapter = registry.get_adapter(SEED_SCENE_TEST_MODEL)
    if adapter is None:
        raise SeedSceneTestRenderError("Seed Audio adapter is unavailable")
    return SeedSceneTestPreviewService(
        adapter=adapter,
        output_root=get_backend_root() / "data" / "seed_scene_tests",
    )


__all__ = [
    "SeedSceneTestPreviewService",
    "SeedSceneTestRenderError",
    "create_seed_scene_test_preview_service",
]
