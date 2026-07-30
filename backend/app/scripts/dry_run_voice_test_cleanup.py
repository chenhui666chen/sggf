"""生成测试音色清理范围报告。

该脚本只读数据库、读取本地索引和文件元数据，不删除数据库记录、文件、OSS 对象或供应商云端音色。
运行方式（在 backend 目录）：
    python -m app.scripts.dry_run_voice_test_cleanup
    python -m app.scripts.dry_run_voice_test_cleanup --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


def _bootstrap_environment() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    project_root = backend_root.parent
    for path in (backend_root, project_root):
        path_string = str(path)
        if path_string not in sys.path:
            sys.path.insert(0, path_string)

    from app.core.env_loader import load_project_env

    load_project_env(override=False)


_bootstrap_environment()

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.voice_asset_billing_ledger import VoiceAssetBillingLedger
from app.models.voice_pool_publication import VoicePoolPublication
from app.models.voice_pool_rating import VoicePoolRating
from app.models.voice_reference_asset import VoiceReferenceAsset


CUSTOM_REFERENCE_KINDS = {
    "user_recording",
    "user_generated_voice",
    "provider_preview",
}
CUSTOM_SOURCE_TYPES = {
    "user_upload",
    "user_generated",
    "provider_preview",
}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def storage_type_for_uri(value: str | None) -> str:
    """只返回存储类型，避免 dry-run 输出可访问地址或对象路径。"""
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    if raw.lower().startswith("oss://"):
        return "oss"
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return "http"
    return "local"


def _safe_relative_path(root: Path, candidate: str | Path) -> Path | None:
    try:
        resolved_root = root.resolve()
        resolved_candidate = (root / candidate).resolve()
    except (OSError, RuntimeError, TypeError):
        return None
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        return None
    return resolved_candidate


def _resolve_workspace_path(value: str | Path, workspace_root: Path) -> Path | None:
    raw_path = Path(value)
    candidate = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
    try:
        root = workspace_root.resolve()
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return None
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_index_records(index_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    for key in ("assets", "clones", "voices"):
        records = payload.get(key)
        if isinstance(records, list):
            return [record for record in records if isinstance(record, dict)]
    if payload and all(isinstance(value, (dict, str)) for value in payload.values()):
        return [
            (
                {"id": str(key), **value}
                if isinstance(value, dict)
                else {"id": str(key), "name": str(value), "asset_type": "clone"}
            )
            for key, value in payload.items()
            if str(key).strip()
        ]
    return []


def _local_file_summary(root: Path) -> dict[str, int]:
    file_count = 0
    audio_file_count = 0
    audio_bytes = 0
    if root.is_file():
        file_count = 1
        if root.suffix.lower() in AUDIO_SUFFIXES:
            audio_file_count = 1
            try:
                audio_bytes = root.stat().st_size
            except OSError:
                audio_bytes = 0
        return {
            "file_count": file_count,
            "audio_file_count": audio_file_count,
            "audio_bytes": audio_bytes,
        }
    if not root.exists() or not root.is_dir():
        return {
            "file_count": 0,
            "audio_file_count": 0,
            "audio_bytes": 0,
        }
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        file_count += 1
        if path.suffix.lower() in AUDIO_SUFFIXES:
            audio_file_count += 1
            try:
                audio_bytes += path.stat().st_size
            except OSError:
                pass
    return {
        "file_count": file_count,
        "audio_file_count": audio_file_count,
        "audio_bytes": audio_bytes,
    }


def scan_local_voice_root(root: Path | str, *, provider: str) -> dict[str, Any]:
    """扫描单个供应商本地音色目录，只输出数量、所有者是否存在和文件大小。"""
    normalized_root = Path(root)
    if normalized_root.is_file():
        index_files = [normalized_root]
    else:
        index_files = sorted(normalized_root.glob("index.json")) if normalized_root.exists() else []
    records: list[dict[str, Any]] = []
    for index_path in index_files:
        records.extend(_read_index_records(index_path))

    summary = _local_file_summary(normalized_root)
    owner_counts: dict[str, int] = {"owned": 0, "unowned": 0}
    asset_type_counts: dict[str, int] = {}
    for record in records:
        owner_key = "owned" if record.get("owner_user_id") not in (None, "") else "unowned"
        owner_counts[owner_key] += 1
        asset_type = str(record.get("asset_type") or record.get("type") or "unknown")
        asset_type_counts[asset_type] = asset_type_counts.get(asset_type, 0) + 1

    local_items = [
        {
            "id": str(record.get("id") or record.get("voice_id") or "")[:160],
            "model": str(record.get("model") or ""),
            "asset_type": str(record.get("asset_type") or record.get("type") or "unknown"),
            "owner_present": record.get("owner_user_id") not in (None, ""),
            "audio_file_declared": bool(record.get("audio_path")),
        }
        for record in records
    ]

    return {
        "provider": str(provider),
        "root_exists": normalized_root.exists(),
        "index_record_count": len(records),
        "items": local_items,
        "owner_counts": owner_counts,
        "asset_type_counts": asset_type_counts,
        **summary,
        "action": "delete test index records and controlled local voice files",
        "provider_cloud_action": "manual review required; no provider API call in dry-run",
    }


def _asset_item(asset: VoiceReferenceAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "database_id": asset.id,
        "reference_kind": asset.reference_kind,
        "source_type": asset.source_type,
        "provider": asset.provider or "",
        "source_model": asset.source_model or "",
        "source_voice_id": asset.source_voice_id or "",
        "owner_present": asset.owner_user_id is not None,
        "storage_type": storage_type_for_uri(asset.storage_uri),
        "has_source_url": bool(asset.source_url),
        "cleanup_status": asset.cleanup_status,
        "deleted": asset.deleted_at is not None,
    }


def _publication_item(publication: VoicePoolPublication) -> dict[str, Any]:
    return {
        "publication_id": publication.publication_id,
        "database_id": publication.id,
        "source_asset_database_id": publication.source_asset_id,
        "status": publication.status,
        "owner_present": publication.owner_user_id is not None,
        "has_public_preview": bool(publication.public_preview_uri),
        "has_public_reference": bool(publication.public_reference_uri),
    }


def _ledger_item(ledger: VoiceAssetBillingLedger) -> dict[str, Any]:
    return {
        "database_id": ledger.id,
        "idempotency_key_present": bool(ledger.idempotency_key),
        "provider": ledger.provider,
        "model": ledger.model or "",
        "voice_id": ledger.voice_id or "",
        "event_type": ledger.event_type,
        "owner_present": ledger.owner_user_id is not None,
        "voice_asset_id_present": bool(ledger.voice_asset_id),
        "charge_status": ledger.charge_status,
    }


def _collection(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(items)
    return {"count": len(materialized), "items": materialized}


def _query_custom_assets(db: Session) -> list[VoiceReferenceAsset]:
    return (
        db.query(VoiceReferenceAsset)
        .filter(
            (VoiceReferenceAsset.reference_kind.in_(CUSTOM_REFERENCE_KINDS))
            | (VoiceReferenceAsset.source_type.in_(CUSTOM_SOURCE_TYPES))
        )
        .order_by(VoiceReferenceAsset.id.asc())
        .all()
    )


def build_dry_run_report(
    db: Session,
    *,
    local_roots: Iterable[tuple[Path | str, str]] = (),
) -> dict[str, Any]:
    """构建只读清理报告，不提交事务，也不读取原始音频内容。"""
    assets = _query_custom_assets(db)
    custom_asset_ids = {asset.id for asset in assets}
    publications = (
        db.query(VoicePoolPublication)
        .filter(VoicePoolPublication.source_asset_id.in_(custom_asset_ids))
        .order_by(VoicePoolPublication.id.asc())
        .all()
        if custom_asset_ids
        else []
    )
    publication_ids = {publication.id for publication in publications}
    ratings = (
        db.query(VoicePoolRating)
        .filter(VoicePoolRating.publication_id.in_(publication_ids))
        .order_by(VoicePoolRating.id.asc())
        .all()
        if publication_ids
        else []
    )
    asset_ids = {asset.asset_id for asset in assets}
    ledgers = (
        db.query(VoiceAssetBillingLedger)
        .filter(VoiceAssetBillingLedger.voice_asset_id.in_(asset_ids))
        .order_by(VoiceAssetBillingLedger.id.asc())
        .all()
        if asset_ids
        else []
    )

    return {
        "report_version": "voice-test-cleanup-dry-run-v1",
        "mode": "dry-run",
        "destructive": False,
        "database": {
            "voice_reference_assets": _collection(_asset_item(asset) for asset in assets),
            "voice_pool_publications": _collection(_publication_item(item) for item in publications),
            "voice_pool_ratings": _collection(
                {
                    "database_id": item.id,
                    "publication_database_id": item.publication_id,
                    "score": item.score,
                }
                for item in ratings
            ),
            "voice_asset_billing_ledger": _collection(_ledger_item(item) for item in ledgers),
        },
        "local_roots": [scan_local_voice_root(root, provider=provider) for root, provider in local_roots],
        "oss": {
            "mode": "registered_uri_metadata_only",
            "object_scan_performed": False,
            "action": "delete only after explicit confirmation and constrained object-prefix review",
        },
        "provider_cloud": {
            "mode": "identifiers_not_discovered_in_dry_run",
            "action": "manual provider-side review and deletion only after explicit confirmation",
        },
        "protected": [
            "official system voices",
            "generated audiobook outputs",
            "test projects and chapters",
            "database sequences",
        ],
    }


def _database_cleanup_operations(
    *,
    assets: list[VoiceReferenceAsset],
    publications: list[VoicePoolPublication],
    ratings: list[VoicePoolRating],
    ledgers: list[VoiceAssetBillingLedger],
) -> list[dict[str, Any]]:
    specs = [
        (1, "voice_pool_ratings", ratings),
        (2, "voice_pool_publications", publications),
        (3, "voice_asset_billing_ledger", ledgers),
        (4, "voice_reference_assets", assets),
    ]
    return [
        {
            "order": order,
            "table": table,
            "action": "delete_rows",
            "primary_keys": [int(item.id) for item in items],
            "count": len(items),
        }
        for order, table, items in specs
    ]


def _index_replacement_shape(provider: str) -> str:
    if provider == "cosyvoice":
        return "{}"
    if provider == "minimax":
        return '{"clones":[]}'
    return '{"assets":[]}'


def _build_local_operation(
    *,
    path: Path,
    action: str,
    reason: str,
    provider: str = "",
    replacement_shape: str = "",
) -> dict[str, Any]:
    suffix = path.suffix.lower()
    size = path.stat().st_size
    return {
        "path": path.as_posix(),
        "action": action,
        "reason": reason,
        "provider": provider,
        "exists": True,
        "size_bytes": size,
        "audio": suffix in AUDIO_SUFFIXES,
        "sha256": _file_sha256(path),
        **({"replacement_shape": replacement_shape} if replacement_shape else {}),
    }


def _append_local_operation(
    operations_by_path: dict[str, dict[str, Any]],
    operation: dict[str, Any],
) -> None:
    path = str(operation["path"])
    existing = operations_by_path.get(path)
    if existing is None:
        operations_by_path[path] = operation
        return
    reasons = {str(existing.get("reason") or ""), str(operation.get("reason") or "")}
    existing["reason"] = "; ".join(sorted(reason for reason in reasons if reason))


def _local_index_records(path: Path) -> list[dict[str, Any]]:
    if path.is_file():
        return _read_index_records(path)
    index_path = path / "index.json"
    return _read_index_records(index_path) if index_path.exists() else []


def _provider_cloud_plan(
    local_roots: Iterable[tuple[Path | str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from app.services.audiobook.cosyvoice_clone_client import (
        is_cosyvoice_custom_voice_id,
    )

    supported: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for root_value, provider in local_roots:
        root = Path(root_value)
        if not root.is_absolute():
            root = Path.cwd() / root
        for record in _local_index_records(root):
            voice_id = str(record.get("id") or record.get("voice_id") or "").strip()
            if not voice_id:
                continue
            if provider == "cosyvoice":
                if is_cosyvoice_custom_voice_id(voice_id):
                    supported.append(
                        {
                            "provider": "cosyvoice",
                            "voice_id": voice_id,
                            "action": "delete_voice",
                            "capability": "supported_by_existing_client",
                        }
                    )
                else:
                    manual.append(
                        {
                            "provider": "cosyvoice",
                            "voice_id": voice_id,
                            "reason": "voice id is outside the known custom-voice allowlist",
                        }
                    )
            elif provider == "minimax":
                manual.append(
                    {
                        "provider": "minimax",
                        "voice_id": voice_id,
                        "reason": "existing client removes only the local registry",
                    }
                )
            elif provider == "stepaudio" and record.get("file_id"):
                manual.append(
                    {
                        "provider": "stepaudio",
                        "voice_id": str(record["file_id"]),
                        "reason": "uploaded provider file has no deletion client",
                    }
                )
    return supported, manual


def build_cleanup_manifest(
    db: Session,
    *,
    workspace_root: Path | str,
    local_roots: Iterable[tuple[Path | str, str]] = (),
) -> dict[str, Any]:
    """生成精确清理清单；该函数始终只读，不执行清理。"""
    approved_root = Path(workspace_root).resolve()
    normalized_local_roots = list(local_roots)
    assets = _query_custom_assets(db)
    publications = db.query(VoicePoolPublication).order_by(VoicePoolPublication.id.asc()).all()
    ratings = db.query(VoicePoolRating).order_by(VoicePoolRating.id.asc()).all()
    ledgers = db.query(VoiceAssetBillingLedger).order_by(VoiceAssetBillingLedger.id.asc()).all()

    blockers: list[dict[str, Any]] = []
    local_operations_by_path: dict[str, dict[str, Any]] = {}
    oss_manual_review: list[dict[str, Any]] = []

    for asset in assets:
        storage_type = storage_type_for_uri(asset.storage_uri)
        if storage_type == "local" and asset.storage_uri:
            path = _resolve_workspace_path(asset.storage_uri, approved_root)
            if path is None:
                blockers.append(
                    {
                        "kind": "unsafe_local_path",
                        "asset_id": asset.asset_id,
                        "reason": "path is outside the approved workspace root",
                    }
                )
            elif path.exists() and path.is_file():
                _append_local_operation(
                    local_operations_by_path,
                    _build_local_operation(
                        path=path,
                        action="delete_file",
                        reason=f"voice_reference_asset:{asset.asset_id}",
                        provider=str(asset.provider or ""),
                    ),
                )
        elif storage_type in {"oss", "http"}:
            raw_uri = str(asset.storage_uri or "")
            oss_manual_review.append(
                {
                    "asset_id": asset.asset_id,
                    "storage_type": storage_type,
                    "uri_sha256": hashlib.sha256(raw_uri.encode("utf-8")).hexdigest(),
                    "reason": "remote object identity requires constrained storage review",
                }
            )

    for root_value, provider in normalized_local_roots:
        root = _resolve_workspace_path(root_value, approved_root)
        if root is None:
            blockers.append(
                {
                    "kind": "unsafe_local_root",
                    "provider": str(provider),
                    "reason": "root is outside the approved workspace root",
                }
            )
            continue
        if root.is_file():
            if root.suffix.lower() != ".json":
                blockers.append(
                    {
                        "kind": "unexpected_local_file",
                        "provider": str(provider),
                        "reason": "single-file voice registry must be JSON",
                    }
                )
                continue
            if _read_index_records(root):
                _append_local_operation(
                    local_operations_by_path,
                    _build_local_operation(
                        path=root,
                        action="rewrite_json_index_empty",
                        reason=f"{provider}_voice_registry",
                        provider=str(provider),
                        replacement_shape=_index_replacement_shape(str(provider)),
                    ),
                )
            continue
        if not root.exists():
            continue

        index_path = root / "index.json"
        if (
            index_path.exists()
            and index_path.is_file()
            and _read_index_records(index_path)
        ):
            _append_local_operation(
                local_operations_by_path,
                _build_local_operation(
                    path=index_path,
                    action="rewrite_json_index_empty",
                    reason=f"{provider}_voice_registry",
                    provider=str(provider),
                    replacement_shape=_index_replacement_shape(str(provider)),
                ),
            )
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path == index_path:
                continue
            if path.suffix.lower() not in AUDIO_SUFFIXES:
                blockers.append(
                    {
                        "kind": "unexpected_local_file",
                        "provider": str(provider),
                        "reason": "non-audio file requires manual review",
                    }
                )
                continue
            _append_local_operation(
                local_operations_by_path,
                _build_local_operation(
                    path=path,
                    action="delete_file",
                    reason=f"{provider}_controlled_voice_audio",
                    provider=str(provider),
                ),
            )

    local_operations = sorted(
        local_operations_by_path.values(),
        key=lambda item: (
            0 if item["action"] == "rewrite_json_index_empty" else 1,
            str(item["path"]),
        ),
    )
    provider_operations, provider_manual_review = _provider_cloud_plan(normalized_local_roots)
    database_operations = _database_cleanup_operations(
        assets=assets,
        publications=publications,
        ratings=ratings,
        ledgers=ledgers,
    )

    fingerprint_payload = {
        "database_operations": database_operations,
        "local_operations": local_operations,
        "oss_manual_review": oss_manual_review,
        "provider_cloud_operations": provider_operations,
        "provider_cloud_manual_review": provider_manual_review,
        "blockers": blockers,
    }
    fingerprint_json = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    manifest_fingerprint = "vctc_" + hashlib.sha256(
        fingerprint_json.encode("utf-8")
    ).hexdigest()[:32]

    return {
        "manifest_version": "voice-test-cleanup-manifest-v1",
        "manifest_fingerprint": manifest_fingerprint,
        "mode": "cleanup-manifest",
        "destructive": False,
        "execution_permitted": False,
        "confirmation_required": True,
        "workspace_root": approved_root.as_posix(),
        "database_operations": database_operations,
        "local_operations": local_operations,
        "oss_manual_review": oss_manual_review,
        "provider_cloud_operations": provider_operations,
        "provider_cloud_manual_review": provider_manual_review,
        "blockers": blockers,
        "summary": {
            "database_row_count": sum(item["count"] for item in database_operations),
            "local_file_count": len(local_operations),
            "local_audio_file_count": sum(bool(item["audio"]) for item in local_operations),
            "local_audio_bytes": sum(
                int(item["size_bytes"]) for item in local_operations if item["audio"]
            ),
            "oss_manual_review_count": len(oss_manual_review),
            "provider_cloud_supported_count": len(provider_operations),
            "provider_cloud_manual_review_count": len(provider_manual_review),
            "blocker_count": len(blockers),
        },
    }


def _default_local_roots() -> list[tuple[Path, str]]:
    from app.services.audiobook.cosyvoice_clone_client import _resolve_clone_name_store_path
    from app.services.audiobook.mimo_voice_assets import DEFAULT_MIMO_VOICE_ASSET_DIR
    from app.services.audiobook.stepaudio_voice_assets import DEFAULT_STEPAUDIO_VOICE_ASSET_DIR
    from app.services.audiobook.minimax_voice_clone_client import DEFAULT_MINIMAX_VOICE_CLONE_DIR

    return [
        (Path(DEFAULT_MIMO_VOICE_ASSET_DIR), "mimo"),
        (Path(DEFAULT_STEPAUDIO_VOICE_ASSET_DIR), "stepaudio"),
        (Path(DEFAULT_MINIMAX_VOICE_CLONE_DIR), "minimax"),
        (Path(_resolve_clone_name_store_path()), "cosyvoice"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成测试音色清理 dry-run 报告")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="只输出脱敏 JSON 报告")
    output_group.add_argument(
        "--manifest",
        action="store_true",
        help="输出包含受控本地路径和供应商 ID 的精确只读清单",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.manifest:
            from app.core.env_loader import get_project_root

            report = build_cleanup_manifest(
                db,
                workspace_root=get_project_root(),
                local_roots=_default_local_roots(),
            )
        else:
            report = build_dry_run_report(db, local_roots=_default_local_roots())
    finally:
        db.close()

    if args.json or args.manifest:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("测试音色清理 dry-run（只读）")
    print(f"数据库参考资产: {report['database']['voice_reference_assets']['count']}")
    print(f"公共发布记录: {report['database']['voice_pool_publications']['count']}")
    print(f"公共评分记录: {report['database']['voice_pool_ratings']['count']}")
    print(f"固定费用/试听账本: {report['database']['voice_asset_billing_ledger']['count']}")
    for root_report in report["local_roots"]:
        print(
            f"本地 {root_report['provider']}: "
            f"索引 {root_report['index_record_count']} 条，音频 {root_report['audio_file_count']} 个，"
            f"{root_report['audio_bytes']} bytes"
        )
    print("未执行数据库、文件、OSS 或供应商云端删除。")


if __name__ == "__main__":
    main()
