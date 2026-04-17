from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from app.services.providers.kling import (
    KlingElementAPI,
    build_image_element_request_from_library_asset,
)

from .contracts import ProviderSubjectRef


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_provider_name(value: Any, *, default: str = "kling") -> str:
    text = _normalize_text(value).lower()
    return text or default


def _parse_optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def _asset_entity_key(asset: Mapping[str, Any]) -> str:
    entity_type = _normalize_text(asset.get("entity_type"))
    entity_id = _parse_optional_int(asset.get("entity_id"))
    if entity_type and entity_id is not None:
        return f"{entity_type}:{entity_id}"
    entity_name = _normalize_text(asset.get("entity_name"))
    if entity_type and entity_name:
        return f"{entity_type}:{entity_name}"
    role = _normalize_text(asset.get("role"))
    return role


def _extract_provider_ref_payload(asset: Mapping[str, Any], *, provider: str) -> Dict[str, Any]:
    direct = asset.get("provider_refs") if isinstance(asset.get("provider_refs"), Mapping) else {}
    meta = asset.get("meta") if isinstance(asset.get("meta"), Mapping) else {}
    meta_provider_refs = meta.get("provider_refs") if isinstance(meta.get("provider_refs"), Mapping) else {}

    provider_key = _normalize_provider_name(provider)
    candidate = direct.get(provider_key) if isinstance(direct.get(provider_key), Mapping) else None
    if candidate is None:
        candidate = meta_provider_refs.get(provider_key) if isinstance(meta_provider_refs.get(provider_key), Mapping) else None
    return dict(candidate or {})


def _resolve_asset_path(asset: Mapping[str, Any]) -> Optional[Path]:
    candidate = asset.get("path")
    if isinstance(candidate, Path) and candidate.exists():
        return candidate
    uri = _normalize_text(asset.get("uri"))
    if not uri:
        return None
    path = Path(uri)
    if path.exists():
        return path
    return None


def _ensure_mutable_meta(asset: MutableMapping[str, Any]) -> Dict[str, Any]:
    meta = asset.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        asset["meta"] = meta
    return meta


def _apply_provider_ref_to_asset(
    asset: MutableMapping[str, Any],
    *,
    provider: str,
    provider_ref: Mapping[str, Any],
) -> None:
    provider_key = _normalize_provider_name(provider)
    direct = asset.get("provider_refs") if isinstance(asset.get("provider_refs"), dict) else {}
    direct[provider_key] = dict(provider_ref)
    asset["provider_refs"] = direct

    meta = _ensure_mutable_meta(asset)
    meta_provider_refs = meta.get("provider_refs") if isinstance(meta.get("provider_refs"), dict) else {}
    meta_provider_refs[provider_key] = dict(provider_ref)
    meta["provider_refs"] = meta_provider_refs


def build_subject_ref_from_asset(
    asset: Mapping[str, Any],
    *,
    provider: str = "kling",
) -> Optional[ProviderSubjectRef]:
    payload = _extract_provider_ref_payload(asset, provider=provider)
    subject_id = _normalize_text(payload.get("element_id") or payload.get("subject_id"))
    if not subject_id:
        return None

    metadata = dict(payload)
    metadata.pop("element_id", None)
    metadata.pop("subject_id", None)
    metadata.pop("source_asset_uri", None)

    return ProviderSubjectRef(
        provider=_normalize_provider_name(provider),
        subject_id=subject_id,
        role=_normalize_text(asset.get("role")),
        source_asset_uri=_normalize_text(payload.get("source_asset_uri") or asset.get("uri")),
        asset_id=_parse_optional_int(asset.get("asset_id") or asset.get("id")),
        entity_type=_normalize_text(asset.get("entity_type")),
        entity_id=_parse_optional_int(asset.get("entity_id")),
        entity_name=_normalize_text(asset.get("entity_name")),
        view=_normalize_text(asset.get("view")),
        metadata=metadata,
    )


def sync_subject_ref_for_asset(
    asset: MutableMapping[str, Any],
    *,
    provider: str = "kling",
    related_assets: Iterable[Mapping[str, Any]] = (),
    include_related_views: bool = True,
    timeout_s: float = 90.0,
    poll_interval_s: float = 2.0,
    element_api: Optional[KlingElementAPI] = None,
) -> Dict[str, Any]:
    provider_key = _normalize_provider_name(provider)
    if provider_key != "kling":
        raise ValueError(f"暂不支持自动同步 provider={provider_key!r}")

    path = _resolve_asset_path(asset)
    if path is None or not path.exists():
        raise ValueError("素材文件不存在，无法同步 provider subject ref。")

    name = _normalize_text(asset.get("entity_name") or asset.get("role"))
    description = _normalize_text(asset.get("descriptor")) or f"{_normalize_text(asset.get('entity_type'))}:{name}"

    refer_images: list[str] = []
    related_targets: list[MutableMapping[str, Any]] = []
    current_entity_key = _asset_entity_key(asset)
    if include_related_views and current_entity_key:
        for item in related_assets:
            if not isinstance(item, Mapping) or item is asset:
                continue
            if _asset_entity_key(item) != current_entity_key:
                continue
            if isinstance(item, MutableMapping):
                related_targets.append(item)
            extra_path = _resolve_asset_path(item)
            if extra_path is None or not extra_path.exists():
                continue
            text = str(extra_path)
            if text == str(path) or text in refer_images:
                continue
            refer_images.append(text)
            if len(refer_images) >= 3:
                break

    request = build_image_element_request_from_library_asset(
        name=name,
        description=description,
        frontal_image=str(path),
        refer_images=refer_images,
    )
    api = element_api or KlingElementAPI()
    elements = api.create_and_wait(
        request,
        timeout_s=float(timeout_s),
        poll_interval_s=float(poll_interval_s),
    )
    if not elements:
        raise RuntimeError("provider 同步未返回 subject_id。")

    element = elements[0]
    provider_ref = {
        "subject_id": element.element_id,
        "element_id": element.element_id,
        "source_asset_uri": _normalize_text(asset.get("uri")) or str(path),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source": "provider_sync",
        "element_name": element.element_name or name,
        "element_description": element.element_description or description,
        "reference_type": element.reference_type or "image_refer",
    }
    _apply_provider_ref_to_asset(asset, provider=provider_key, provider_ref=provider_ref)
    for related_asset in related_targets:
        _apply_provider_ref_to_asset(related_asset, provider=provider_key, provider_ref=provider_ref)
    return provider_ref


def build_subject_refs_from_character_assets(
    character_assets: Iterable[Mapping[str, Any]],
    *,
    provider: str = "kling",
    max_subject_refs: int = 3,
) -> list[Dict[str, Any]]:
    if max_subject_refs <= 0:
        return []

    refs: list[Dict[str, Any]] = []
    seen_subject_ids: set[str] = set()
    seen_entity_keys: set[str] = set()

    for asset in character_assets:
        if not isinstance(asset, Mapping):
            continue
        subject_ref = build_subject_ref_from_asset(asset, provider=provider)
        if subject_ref is None:
            continue

        entity_key = ""
        if subject_ref.entity_id is not None:
            entity_key = f"{subject_ref.entity_type}:{subject_ref.entity_id}"
        elif subject_ref.entity_name:
            entity_key = f"{subject_ref.entity_type}:{subject_ref.entity_name}"

        if subject_ref.subject_id in seen_subject_ids:
            continue
        if entity_key and entity_key in seen_entity_keys:
            continue

        refs.append(subject_ref.to_dict())
        seen_subject_ids.add(subject_ref.subject_id)
        if entity_key:
            seen_entity_keys.add(entity_key)

        if len(refs) >= int(max_subject_refs):
            break

    return refs


def ensure_subject_refs_for_character_assets(
    character_assets: Iterable[MutableMapping[str, Any]],
    *,
    provider: str = "kling",
    max_subject_refs: int = 3,
    auto_sync: bool = False,
    timeout_s: float = 90.0,
    poll_interval_s: float = 2.0,
    element_api: Optional[KlingElementAPI] = None,
) -> list[Dict[str, Any]]:
    assets = [item for item in character_assets if isinstance(item, MutableMapping)]
    if auto_sync:
        for asset in assets:
            existing = build_subject_ref_from_asset(asset, provider=provider)
            if existing is not None:
                asset.pop("provider_ref_sync_error", None)
                continue
            try:
                sync_subject_ref_for_asset(
                    asset,
                    provider=provider,
                    related_assets=assets,
                    include_related_views=True,
                    timeout_s=timeout_s,
                    poll_interval_s=poll_interval_s,
                    element_api=element_api,
                )
                asset.pop("provider_ref_sync_error", None)
            except Exception as exc:  # noqa: BLE001
                asset["provider_ref_sync_error"] = str(exc)

    return build_subject_refs_from_character_assets(
        assets,
        provider=provider,
        max_subject_refs=max_subject_refs,
    )
