"""Create review-only blind batches from existing Seed scene test artifacts."""
from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.audiobook.atomic_files import write_bytes_atomic


class SeedSceneBlindReviewService:
    def __init__(self, *, output_root: str | Path) -> None:
        self.output_root = Path(output_root).resolve()
        self.batch_root = self.output_root / "blind_batches"

    def create_batch(self, *, samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not samples:
            raise ValueError("blind-review batch requires at least one sample")
        resolved = [self._resolve_cached_sample(item) for item in samples]
        identities = {
            (item["case_id"], item["variant"], item["sample_index"])
            for item in resolved
        }
        if len(identities) != len(resolved):
            raise ValueError("blind-review batch contains duplicate samples")

        secrets.SystemRandom().shuffle(resolved)
        batch_id = f"blind_{secrets.token_hex(12)}"
        entries = []
        for index, item in enumerate(resolved):
            entries.append({
                **item,
                "anonymous_id": f"sample_{secrets.token_hex(12)}",
                "blind_label": self._blind_label(index),
            })
        payload = {
            "schema_version": "seed-scene-blind-batch-v1",
            "batch_id": batch_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "locked": True,
            "entries": entries,
        }
        write_bytes_atomic(
            self._batch_path(batch_id),
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return self.get_reviewer_manifest(batch_id)

    def get_reviewer_manifest(self, batch_id: str) -> dict[str, Any]:
        batch = self._read_batch(batch_id)
        return {
            "schema_version": "seed-scene-blind-review-v1",
            "batch_id": batch["batch_id"],
            "locked": True,
            "samples": [
                {
                    "anonymous_id": item["anonymous_id"],
                    "blind_label": item["blind_label"],
                }
                for item in batch["entries"]
            ],
        }

    def get_answer_key(self, batch_id: str) -> dict[str, Any]:
        batch = self._read_batch(batch_id)
        return {
            "schema_version": "seed-scene-blind-answer-key-v1",
            "batch_id": batch["batch_id"],
            "entries": [
                {
                    "anonymous_id": item["anonymous_id"],
                    "case_id": item["case_id"],
                    "variant": item["variant"],
                    "sample_index": item["sample_index"],
                    "sample_id": item["sample_id"],
                }
                for item in batch["entries"]
            ],
        }

    def get_blind_audio(self, batch_id: str, anonymous_id: str) -> dict[str, Any]:
        batch = self._read_batch(batch_id)
        entry = next(
            (item for item in batch["entries"] if item["anonymous_id"] == anonymous_id),
            None,
        )
        if entry is None:
            raise LookupError("blind-review sample not found")
        audio_path = self._safe_relative_path(entry["audio_relative_path"])
        if audio_path is None:
            raise LookupError("blind-review audio is unavailable")
        suffix = audio_path.suffix.lower()
        mime_type = "audio/wav" if suffix == ".wav" else "audio/mpeg"
        return {
            "anonymous_id": entry["anonymous_id"],
            "blind_label": entry["blind_label"],
            "audio_mime_type": mime_type,
            "audio_data_base64": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
        }

    def submit_review(
        self,
        batch_id: str,
        anonymous_id: str,
        *,
        reviewer_user_id: int,
        review: Mapping[str, Any],
    ) -> dict[str, Any]:
        batch = self._read_batch(batch_id)
        if not any(item["anonymous_id"] == anonymous_id for item in batch["entries"]):
            raise LookupError("blind-review sample not found")
        score = float(review.get("score"))
        if not 1 <= score <= 5:
            raise ValueError("blind-review score must be between 1 and 5")
        flags = review.get("flags")
        if not isinstance(flags, Mapping) or not flags:
            raise ValueError("blind-review flags are required")
        if any(not isinstance(value, bool) for value in flags.values()):
            raise ValueError("blind-review flags must be boolean")
        payload = {
            "schema_version": "seed-scene-blind-review-record-v1",
            "batch_id": batch_id,
            "anonymous_id": anonymous_id,
            "reviewer_user_id": int(reviewer_user_id),
            "score": score,
            "flags": dict(flags),
            "notes": str(review.get("notes") or "").strip()[:2000],
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "locked": True,
        }
        path = self._review_path(batch_id, anonymous_id, reviewer_user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ValueError("blind-review sample already submitted") from exc
        return payload

    def get_review(
        self,
        batch_id: str,
        anonymous_id: str,
        *,
        reviewer_user_id: int,
    ) -> dict[str, Any]:
        self._read_batch(batch_id)
        path = self._review_path(batch_id, anonymous_id, reviewer_user_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LookupError("blind-review submission not found") from exc
        if (
            payload.get("batch_id") != batch_id
            or payload.get("anonymous_id") != anonymous_id
            or payload.get("reviewer_user_id") != int(reviewer_user_id)
        ):
            raise LookupError("blind-review submission not found")
        return payload

    def get_review_summary(
        self,
        batch_id: str,
        *,
        reveal_identity: bool = False,
    ) -> dict[str, Any]:
        batch = self._read_batch(batch_id)
        reviews_by_sample: dict[str, list[dict[str, Any]]] = {
            item["anonymous_id"]: [] for item in batch["entries"]
        }
        reviewer_ids: set[int] = set()
        review_root = self.batch_root / "reviews" / batch_id
        if review_root.is_dir():
            for path in review_root.glob("*.json"):
                try:
                    review = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                anonymous_id = str(review.get("anonymous_id") or "")
                if (
                    review.get("batch_id") != batch_id
                    or anonymous_id not in reviews_by_sample
                    or review.get("locked") is not True
                ):
                    continue
                try:
                    reviewer_id = int(review.get("reviewer_user_id"))
                    score = float(review.get("score"))
                except (TypeError, ValueError):
                    continue
                reviewer_ids.add(reviewer_id)
                reviews_by_sample[anonymous_id].append({**review, "score": score})

        samples = []
        for entry in batch["entries"]:
            sample_reviews = reviews_by_sample[entry["anonymous_id"]]
            flag_totals: dict[str, list[bool]] = {}
            for review in sample_reviews:
                flags = review.get("flags")
                if not isinstance(flags, Mapping):
                    continue
                for key, value in flags.items():
                    if isinstance(value, bool):
                        flag_totals.setdefault(str(key), []).append(value)
            sample = {
                "anonymous_id": entry["anonymous_id"],
                "blind_label": entry["blind_label"],
                "review_count": len(sample_reviews),
                "average_score": (
                    round(sum(item["score"] for item in sample_reviews) / len(sample_reviews), 4)
                    if sample_reviews else None
                ),
                "flag_pass_rates": {
                    key: round(sum(values) / len(values), 4)
                    for key, values in sorted(flag_totals.items())
                },
            }
            if reveal_identity:
                sample.update({
                    "case_id": entry["case_id"],
                    "variant": entry["variant"],
                    "sample_index": entry["sample_index"],
                    "sample_id": entry["sample_id"],
                })
            samples.append(sample)
        return {
            "schema_version": "seed-scene-blind-review-summary-v1",
            "batch_id": batch_id,
            "sample_count": len(samples),
            "completed_sample_count": sum(item["review_count"] > 0 for item in samples),
            "review_count": sum(item["review_count"] for item in samples),
            "reviewer_count": len(reviewer_ids),
            "identity_revealed": reveal_identity,
            "samples": samples,
        }

    def _resolve_cached_sample(self, requested: Mapping[str, Any]) -> dict[str, Any]:
        case_id = str(requested.get("case_id") or "").strip()
        variant = str(requested.get("variant") or "").strip()
        try:
            sample_index = int(requested.get("sample_index"))
        except (TypeError, ValueError):
            sample_index = 0
        candidates = []
        manifest_root = self.output_root / "manifests"
        if manifest_root.is_dir():
            candidates = sorted(
                manifest_root.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        for manifest_path in candidates:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                manifest.get("case_id") != case_id
                or manifest.get("variant") != variant
                or int(manifest.get("sample_index") or 1) != sample_index
            ):
                continue
            audio_path = self._manifest_audio_path(manifest)
            if audio_path is None:
                continue
            return {
                "case_id": case_id,
                "variant": variant,
                "sample_index": sample_index,
                "sample_id": str(manifest.get("sample_id") or "").strip(),
                "audio_relative_path": audio_path.relative_to(self.output_root).as_posix(),
            }
        raise LookupError("cached blind-review sample not found")

    def _manifest_audio_path(self, manifest: Mapping[str, Any]) -> Path | None:
        relative_path = str(manifest.get("audio_relative_path") or "").strip()
        if relative_path:
            return self._safe_relative_path(relative_path)
        legacy_path = str(manifest.get("audio_path") or "").strip().replace("\\", "/")
        marker = "/renders/"
        marker_index = legacy_path.find(marker)
        if marker_index < 0:
            return None
        return self._safe_relative_path(legacy_path[marker_index + 1:])

    def _safe_relative_path(self, value: str) -> Path | None:
        if not value:
            return None
        candidate = (self.output_root / Path(*value.replace("\\", "/").split("/"))).resolve()
        if not candidate.is_relative_to(self.output_root):
            return None
        return candidate if candidate.is_file() else None

    def _batch_path(self, batch_id: str) -> Path:
        normalized = str(batch_id or "").strip()
        if not normalized.startswith("blind_") or not normalized[6:].isalnum():
            raise LookupError("blind-review batch not found")
        return self.batch_root / f"{normalized}.json"

    def _review_path(
        self,
        batch_id: str,
        anonymous_id: str,
        reviewer_user_id: int,
    ) -> Path:
        self._batch_path(batch_id)
        normalized_sample = str(anonymous_id or "").strip()
        if not normalized_sample.startswith("sample_") or not normalized_sample[7:].isalnum():
            raise LookupError("blind-review sample not found")
        return (
            self.batch_root
            / "reviews"
            / batch_id
            / f"{normalized_sample}-user-{int(reviewer_user_id)}.json"
        )

    def _read_batch(self, batch_id: str) -> dict[str, Any]:
        path = self._batch_path(batch_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LookupError("blind-review batch not found") from exc
        if payload.get("batch_id") != batch_id or not isinstance(payload.get("entries"), list):
            raise LookupError("blind-review batch not found")
        return payload

    @staticmethod
    def _blind_label(index: int) -> str:
        return f"{chr(65 + index % 26)}{index // 26 + 1}"


__all__ = ["SeedSceneBlindReviewService"]
