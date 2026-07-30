"""Append-only provider attempt records for Seed Audio scene runs."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Mapping, Tuple


logger = logging.getLogger(__name__)


class ProviderAttemptLedger:
    """Persist one immutable billing record per provider request ID."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._records_by_id: dict[str, dict[str, Any]] = {}
        self._load()

    def record(self, value: Mapping[str, Any]) -> bool:
        record = self._normalize_record(value)
        request_id = record.get("provider_request_id")
        if not request_id:
            return False
        with self._lock:
            if request_id in self._records_by_id:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as ledger_file:
                ledger_file.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                )
                ledger_file.flush()
                os.fsync(ledger_file.fileno())
            self._records_by_id[request_id] = record
        return True

    def records(self) -> Tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(record) for record in self._records_by_id.values())

    def _load(self) -> None:
        if not self.path.exists() or not self.path.is_file():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("Seed Audio provider attempt ledger 读取失败: %s", exc)
            return
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, Mapping):
                continue
            record = self._normalize_record(value)
            request_id = record.get("provider_request_id")
            if request_id and request_id not in self._records_by_id:
                self._records_by_id[request_id] = record

    @staticmethod
    def _normalize_record(value: Mapping[str, Any]) -> dict[str, Any]:
        request_id = str(
            value.get("provider_request_id") or value.get("request_id") or ""
        ).strip()
        scene_id = str(value.get("scene_id") or "").strip()
        model = str(value.get("model") or "").strip()
        prompt_hash = str(value.get("prompt_hash") or "").strip()
        try:
            attempt = max(0, int(value.get("attempt") or 0))
        except (TypeError, ValueError):
            attempt = 0
        try:
            duration = float(value.get("original_duration"))
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration <= 0:
            duration = 0.0
        record: dict[str, Any] = {
            "provider_request_id": request_id,
            "scene_id": scene_id,
            "model": model,
            "attempt": attempt,
            "original_duration": duration,
        }
        if prompt_hash:
            record["prompt_hash"] = prompt_hash
        return record


__all__ = ["ProviderAttemptLedger"]
