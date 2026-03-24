from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.model_resolution import normalize_model_id

logger = logging.getLogger(__name__)

_STATUS_PRIORITY = {
    "verified": 3,
    "partial": 2,
    "pending": 1,
    "failed": -1,
}
_DEFAULT_MAX_SIGNAL_AGE_HOURS = 24.0 * 7
_DEFAULT_FAILURE_BLOCK_HOURS = 24.0 * 3


def _is_truthy_env(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ModelCatalogRoutingSignal:
    model_id: str
    verification_status: Optional[str]
    priority: int
    blocked: bool
    reason: Optional[str] = None
    last_verified_at: Optional[str] = None
    stale: bool = False
    age_hours: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "verification_status": self.verification_status,
            "priority": self.priority,
            "blocked": self.blocked,
            "reason": self.reason,
            "last_verified_at": self.last_verified_at,
            "stale": self.stale,
            "age_hours": self.age_hours,
        }


class ModelCatalogRuntimeIndex:
    """读取模型档案同步后生成的运行时快照，并提供轻量路由信号。"""

    def __init__(self, snapshot_path: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self._default_snapshot_path = snapshot_path or (project_root / "config" / "model_catalog_runtime.json")
        self._lock = threading.Lock()
        self._cached_path: Optional[Path] = None
        self._cached_mtime: Optional[float] = None
        self._entries: dict[str, dict[str, Any]] = {}

    def get_signal(self, model_id: Optional[str]) -> ModelCatalogRoutingSignal:
        normalized = normalize_model_id(model_id)
        if normalized is None:
            return ModelCatalogRoutingSignal(
                model_id=str(model_id or ""),
                verification_status=None,
                priority=0,
                blocked=False,
                reason=None,
                last_verified_at=None,
                stale=False,
                age_hours=None,
            )

        entry = self._load_entries().get(normalized)
        if not isinstance(entry, dict):
            return ModelCatalogRoutingSignal(
                model_id=normalized,
                verification_status=None,
                priority=0,
                blocked=False,
                reason=None,
                last_verified_at=None,
                stale=False,
                age_hours=None,
            )

        status = str(entry.get("verification_status") or "").strip().lower() or None
        last_verified_at = entry.get("last_verified_at")
        parsed_last_verified_at = _parse_timestamp(last_verified_at)
        age_hours: Optional[float] = None
        if parsed_last_verified_at is not None:
            age_hours = max(
                0.0,
                round((datetime.now(timezone.utc) - parsed_last_verified_at).total_seconds() / 3600.0, 3),
            )

        allow_failed = _is_truthy_env("MODEL_CATALOG_ALLOW_FAILED_MODELS")
        max_signal_age_hours = _get_env_float(
            "MODEL_CATALOG_MAX_SIGNAL_AGE_HOURS",
            _DEFAULT_MAX_SIGNAL_AGE_HOURS,
        )
        failure_block_hours = _get_env_float(
            "MODEL_CATALOG_FAILURE_BLOCK_HOURS",
            _DEFAULT_FAILURE_BLOCK_HOURS,
        )

        priority = _STATUS_PRIORITY.get(status or "", 0)
        stale = bool(
            age_hours is not None
            and max_signal_age_hours > 0
            and age_hours > max_signal_age_hours
        )
        if stale:
            priority = 0

        blocked = bool(
            status == "failed"
            and not stale
            and not allow_failed
            and age_hours is not None
            and failure_block_hours > 0
            and age_hours <= failure_block_hours
        )
        if blocked:
            reason = "catalog_verification_failed_recent"
        elif stale:
            reason = "catalog_signal_stale"
        elif status == "failed":
            reason = "catalog_verification_failed_not_recent"
        else:
            reason = None

        return ModelCatalogRoutingSignal(
            model_id=normalized,
            verification_status=status,
            priority=priority,
            blocked=blocked,
            reason=reason,
            last_verified_at=str(last_verified_at) if last_verified_at else None,
            stale=stale,
            age_hours=age_hours,
        )

    def get_capability_hints(self, model_id: Optional[str]) -> dict[str, Any]:
        normalized = normalize_model_id(model_id)
        if normalized is None:
            return {}

        entry = self._load_entries().get(normalized)
        if not isinstance(entry, dict):
            return {}

        capability_hints = entry.get("capability_hints")
        return dict(capability_hints) if isinstance(capability_hints, dict) else {}

    def get_task_constraints(self, model_id: Optional[str]) -> dict[str, Any]:
        normalized = normalize_model_id(model_id)
        if normalized is None:
            return {}

        entry = self._load_entries().get(normalized)
        if not isinstance(entry, dict):
            return {}

        task_constraints = entry.get("task_constraints")
        return dict(task_constraints) if isinstance(task_constraints, dict) else {}

    def _resolve_snapshot_path(self) -> Path:
        env_path = os.getenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH")
        if env_path and env_path.strip():
            return Path(env_path.strip())
        return self._default_snapshot_path

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        path = self._resolve_snapshot_path()

        try:
            stat = path.stat()
        except FileNotFoundError:
            with self._lock:
                self._cached_path = path
                self._cached_mtime = None
                self._entries = {}
                return dict(self._entries)

        with self._lock:
            if self._cached_path == path and self._cached_mtime == stat.st_mtime:
                return dict(self._entries)

            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("读取模型档案运行时快照失败 | path=%s | error=%s", path, exc)
                self._cached_path = path
                self._cached_mtime = stat.st_mtime
                self._entries = {}
                return dict(self._entries)

            raw_entries = payload.get("entries") if isinstance(payload, dict) else {}
            entries = {
                str(model_key): value
                for model_key, value in (raw_entries or {}).items()
                if isinstance(value, dict)
            }
            self._cached_path = path
            self._cached_mtime = stat.st_mtime
            self._entries = entries
            return dict(self._entries)


_runtime_index = ModelCatalogRuntimeIndex()


def get_model_catalog_runtime_index() -> ModelCatalogRuntimeIndex:
    return _runtime_index
