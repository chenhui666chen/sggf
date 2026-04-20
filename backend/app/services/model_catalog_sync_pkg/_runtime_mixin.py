from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import asyncio
import json
import logging
import os
import re

import httpx
import yaml
from sqlalchemy.orm import Session, selectinload

from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource

try:
    from core.unified_llm_client import get_llm_client
    _LLM_CLIENT_AVAILABLE = True
except ImportError:
    _LLM_CLIENT_AVAILABLE = False
    get_llm_client = None

try:
    from core.model_catalog_runtime import get_model_catalog_runtime_index
    _RUNTIME_SIGNAL_AVAILABLE = True
except ImportError:
    _RUNTIME_SIGNAL_AVAILABLE = False
    get_model_catalog_runtime_index = None

logger = logging.getLogger(__name__)

from app.services.model_catalog_sync_pkg._constants import (
    CatalogSeed, SourceVerification, DetailedSpecExtraction,
    _LLM_VERIFICATION_TRIGGER, PRICING_VERIFICATION_CONFIG,
    VERIFIED_PRICING_DATA, _ERROR_PAGE_KEYWORDS,
)

class RuntimeMixin:
    def _build_runtime_snapshot(
        self,
        entries: list[ModelCatalogEntry],
        *,
        generated_at: datetime,
    ) -> dict[str, Any]:
        payload_entries: dict[str, dict[str, Any]] = {}
        for entry in entries:
            payload_entries[entry.model_key] = {
                "model_key": entry.model_key,
                "provider": entry.provider,
                "category": entry.category,
                "modalities": list(entry.modalities or []),
                "verification_status": entry.verification_status,
                "verification_score": entry.verification_score,
                "total_source_count": entry.total_source_count,
                "reachable_source_count": entry.reachable_source_count,
                "verified_source_count": entry.verified_source_count,
                "last_verified_at": entry.last_verified_at.isoformat() if entry.last_verified_at else None,
                "last_synced_at": entry.last_synced_at.isoformat() if entry.last_synced_at else None,
                "capability_hints": self._derive_runtime_capability_hints(entry),
                "task_constraints": self._derive_runtime_task_constraints(entry),
            }

        return {
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "entry_count": len(payload_entries),
            "entries": payload_entries,
        }

    def _write_runtime_snapshot(
        self,
        entries: list[ModelCatalogEntry],
        *,
        generated_at: datetime,
    ) -> None:
        payload = self._build_runtime_snapshot(entries, generated_at=generated_at)
        snapshot_path = self._runtime_snapshot_path
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = snapshot_path.with_suffix(f"{snapshot_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(snapshot_path)

    def _derive_runtime_capability_hints(self, entry: ModelCatalogEntry) -> dict[str, Any]:
        raw = entry.raw_config_json or {}
        detailed_specs = raw.get("detailed_specs") or {}
        video_specs = detailed_specs.get("video_generation") or {}
        image_editing_specs = detailed_specs.get("image_editing") or {}

        reference_input = video_specs.get("reference_input") or {}
        reference_images = reference_input.get("reference_images") or {}
        reference_videos = reference_input.get("reference_videos") or {}
        frame_control = video_specs.get("frame_control") or {}
        multi_image_input = image_editing_specs.get("multi_image_input") or {}

        input_modalities: list[str] = []
        for item in video_specs.get("input_modalities") or []:
            if isinstance(item, dict):
                modality_id = str(item.get("id") or "").strip().lower()
                if modality_id and modality_id not in input_modalities:
                    input_modalities.append(modality_id)

        advanced_feature_ids = {
            str(item.get("id") or "").strip().lower()
            for item in video_specs.get("advanced_features") or []
            if isinstance(item, dict)
        }
        modalities = {str(item).strip().lower() for item in entry.modalities or []}

        def _coerce_int(value: Any) -> Optional[int]:
            try:
                if value is None or value == "":
                    return None
                return int(value)
            except (TypeError, ValueError):
                return None

        max_reference_images = _coerce_int(reference_images.get("max_count"))
        multi_image_max_count = _coerce_int(multi_image_input.get("max_count"))
        if multi_image_max_count is not None:
            max_reference_images = max(max_reference_images or 0, multi_image_max_count)

        max_reference_videos = _coerce_int(reference_videos.get("max_count"))
        supports_reference_images = bool(
            reference_images.get("enabled")
            or multi_image_input.get("enabled")
            or "image" in input_modalities
            or "image_to_video" in modalities
            or "image_to_image_edit" in modalities
        )
        supports_reference_videos = bool(
            reference_videos.get("enabled")
            or "video_to_video" in modalities
            or "reference_to_video" in modalities
        )
        supports_first_frame = bool(frame_control.get("enabled") and frame_control.get("first_frame")) or bool(
            frame_control.get("first_frame")
        )
        supports_last_frame = bool(frame_control.get("enabled") and frame_control.get("last_frame")) or bool(
            frame_control.get("last_frame")
        )
        supports_audio_input = bool("audio" in input_modalities or "audio_sync" in advanced_feature_ids)
        supports_multi_image_edit = bool(multi_image_input.get("enabled") and (multi_image_max_count or 0) > 1)
        supports_camera_control = bool((video_specs.get("camera_control") or {}).get("enabled"))
        supports_motion_control = bool((video_specs.get("motion_control") or {}).get("enabled"))

        return {
            "supports_reference_images": supports_reference_images,
            "max_reference_images": max_reference_images,
            "supports_reference_videos": supports_reference_videos,
            "max_reference_videos": max_reference_videos,
            "supports_first_frame": supports_first_frame,
            "supports_last_frame": supports_last_frame,
            "supports_audio_input": supports_audio_input,
            "supports_multi_image_edit": supports_multi_image_edit,
            "supports_camera_control": supports_camera_control,
            "supports_motion_control": supports_motion_control,
            "declared_input_modalities": input_modalities,
        }

    def _derive_runtime_task_constraints(self, entry: ModelCatalogEntry) -> dict[str, Any]:
        constraints = entry.constraints_json or {}
        raw = entry.raw_config_json or {}
        detailed_specs = raw.get("detailed_specs") or {}

        def _coerce_int(value: Any) -> Optional[int]:
            try:
                if value is None or value == "":
                    return None
                return int(value)
            except (TypeError, ValueError):
                return None

        def _coerce_float(value: Any) -> Optional[float]:
            try:
                if value is None or value == "":
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        def _coerce_float_list(values: Any) -> list[float]:
            if not isinstance(values, list):
                return []
            result: list[float] = []
            for item in values:
                parsed = _coerce_float(item)
                if parsed is None:
                    continue
                if all(abs(existing - parsed) >= 0.001 for existing in result):
                    result.append(parsed)
            return result

        def _coerce_str_list(values: Any) -> list[str]:
            if not isinstance(values, list):
                return []
            result: list[str] = []
            for item in values:
                text = str(item or "").strip()
                if text and text not in result:
                    result.append(text)
            return result

        basic_params: dict[str, Any] = {}
        for section_name in ("video_generation", "image_generation", "image_editing", "audio_generation"):
            section = detailed_specs.get(section_name)
            if isinstance(section, dict) and isinstance(section.get("basic_params"), dict):
                basic_params = section.get("basic_params") or {}
                break

        duration_values = _coerce_float_list(constraints.get("duration"))
        duration_config = basic_params.get("duration") or {}
        if isinstance(duration_config, dict):
            derived_duration_values = _coerce_float_list(duration_config.get("supported_values"))
            if not derived_duration_values:
                min_seconds = _coerce_float(duration_config.get("min_seconds") or duration_config.get("min"))
                max_seconds = _coerce_float(duration_config.get("max_seconds") or duration_config.get("max"))
                step = _coerce_float(duration_config.get("step_seconds") or duration_config.get("step"))
                if (
                    min_seconds is not None
                    and max_seconds is not None
                    and step is not None
                    and step > 0
                    and max_seconds >= min_seconds
                    and (max_seconds - min_seconds) / step <= 60
                ):
                    current = min_seconds
                    generated_values: list[float] = []
                    while current <= max_seconds + 0.001:
                        generated_values.append(round(current, 3))
                        current += step
                    derived_duration_values = generated_values
            if derived_duration_values:
                duration_values = derived_duration_values

        ratio_values = _coerce_str_list(constraints.get("ratios"))
        aspect_ratio_config = basic_params.get("aspect_ratio") or {}
        if isinstance(aspect_ratio_config, dict):
            derived_ratio_values = _coerce_str_list(aspect_ratio_config.get("supported"))
            if derived_ratio_values:
                ratio_values = derived_ratio_values

        resolution_options: list[str] = []
        resolution_specs: list[dict[str, Any]] = []
        resolution_config = basic_params.get("resolution") or {}
        if isinstance(resolution_config, dict):
            resolution_options = _coerce_str_list(
                resolution_config.get("options") or resolution_config.get("supported")
            )
            for item in resolution_config.get("specs") or []:
                if not isinstance(item, dict):
                    continue
                width = _coerce_int(item.get("width"))
                height = _coerce_int(item.get("height"))
                if width is None or height is None:
                    continue
                resolution_specs.append(
                    {
                        "value": str(item.get("value") or item.get("label") or f"{width}x{height}"),
                        "width": width,
                        "height": height,
                    }
                )

        min_width = _coerce_int(constraints.get("min_width"))
        max_width = _coerce_int(constraints.get("max_width"))
        min_height = _coerce_int(constraints.get("min_height"))
        max_height = _coerce_int(constraints.get("max_height"))
        if resolution_specs and min_width is None:
            min_width = min(item["width"] for item in resolution_specs)
        if resolution_specs and max_width is None:
            max_width = max(item["width"] for item in resolution_specs)
        if resolution_specs and min_height is None:
            min_height = min(item["height"] for item in resolution_specs)
        if resolution_specs and max_height is None:
            max_height = max(item["height"] for item in resolution_specs)

        task_constraints = {
            "duration_values": duration_values,
            "ratio_values": ratio_values,
            "min_width": min_width,
            "max_width": max_width,
            "min_height": min_height,
            "max_height": max_height,
            "max_batch_size": _coerce_int(constraints.get("max_batch_size")),
            "resolution_options": resolution_options,
            "resolution_specs": resolution_specs,
        }
        return {
            key: value
            for key, value in task_constraints.items()
            if value not in (None, [], {})
        }
