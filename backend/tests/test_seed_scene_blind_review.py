from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_string = str(path)
    if path_string not in sys.path:
        sys.path.insert(0, path_string)

from app.services.audiobook.seed_scene_blind_review import SeedSceneBlindReviewService


def _cached_sample(root: Path, *, case_id: str, variant: str, sample_index: int) -> None:
    audio_path = root / "renders" / f"{case_id}-{variant}-r{sample_index}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"ID3-blind-audio")
    manifest = {
        "schema_version": 3,
        "case_id": case_id,
        "variant": variant,
        "sample_index": sample_index,
        "sample_id": f"sample-{variant}-{sample_index}",
        "audio_relative_path": audio_path.relative_to(root).as_posix(),
    }
    manifests = root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / f"{variant}-{sample_index}.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_blind_batch_separates_reviewer_manifest_and_answer_key(tmp_path: Path) -> None:
    _cached_sample(tmp_path, case_id="case-a", variant="described_voices", sample_index=1)
    _cached_sample(tmp_path, case_id="case-a", variant="reference_voices", sample_index=1)
    service = SeedSceneBlindReviewService(output_root=tmp_path)

    batch = service.create_batch(
        samples=(
            {"case_id": "case-a", "variant": "described_voices", "sample_index": 1},
            {"case_id": "case-a", "variant": "reference_voices", "sample_index": 1},
        )
    )
    reviewer = service.get_reviewer_manifest(batch["batch_id"])
    answer_key = service.get_answer_key(batch["batch_id"])

    assert reviewer["schema_version"] == "seed-scene-blind-review-v1"
    assert len(reviewer["samples"]) == 2
    assert all("variant" not in item for item in reviewer["samples"])
    assert all("audio_path" not in item for item in reviewer["samples"])
    assert {item["anonymous_id"] for item in reviewer["samples"]} == {
        item["anonymous_id"] for item in answer_key["entries"]
    }
    assert {item["variant"] for item in answer_key["entries"]} == {
        "described_voices", "reference_voices"
    }

    sample = service.get_blind_audio(
        batch["batch_id"], reviewer["samples"][0]["anonymous_id"]
    )
    assert base64.b64decode(sample["audio_data_base64"]) == b"ID3-blind-audio"
    assert set(sample) == {"anonymous_id", "blind_label", "audio_mime_type", "audio_data_base64"}


def test_blind_batch_requires_existing_safe_cached_audio(tmp_path: Path) -> None:
    service = SeedSceneBlindReviewService(output_root=tmp_path)
    with pytest.raises(LookupError, match="cached blind-review sample not found"):
        service.create_batch(samples=(
            {"case_id": "case-a", "variant": "described_voices", "sample_index": 1},
        ))
    _cached_sample(tmp_path, case_id="case-a", variant="described_voices", sample_index=1)
    manifest_path = next((tmp_path / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["audio_relative_path"] = "../outside.mp3"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(LookupError, match="cached blind-review sample not found"):
        service.create_batch(samples=(
            {"case_id": "case-a", "variant": "described_voices", "sample_index": 1},
        ))


def test_blind_review_submission_is_first_write_locked(tmp_path: Path) -> None:
    _cached_sample(tmp_path, case_id="case-a", variant="described_voices", sample_index=1)
    service = SeedSceneBlindReviewService(output_root=tmp_path)
    batch = service.create_batch(samples=(
        {"case_id": "case-a", "variant": "described_voices", "sample_index": 1},
    ))
    anonymous_id = batch["samples"][0]["anonymous_id"]
    first = service.submit_review(
        batch["batch_id"],
        anonymous_id,
        reviewer_user_id=7,
        review={"score": 4.5, "flags": {"usable": True}, "notes": "first"},
    )

    assert first["locked"] is True
    assert first["score"] == 4.5
    with pytest.raises(ValueError, match="already submitted"):
        service.submit_review(
            batch["batch_id"],
            anonymous_id,
            reviewer_user_id=7,
            review={"score": 1, "flags": {"usable": False}, "notes": "overwrite"},
        )
    stored = service.get_review(
        batch["batch_id"], anonymous_id, reviewer_user_id=7
    )
    assert stored["score"] == 4.5
    assert stored["notes"] == "first"


@pytest.mark.parametrize("legacy_root", ("/app/data/seed_scene_tests", "C:/old/seed_scene_tests"))
def test_blind_batch_reuses_safe_legacy_manifest_paths(
    tmp_path: Path, legacy_root: str
) -> None:
    _cached_sample(tmp_path, case_id="case-a", variant="described_voices", sample_index=1)
    manifest_path = next((tmp_path / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative_path = manifest.pop("audio_relative_path")
    manifest.pop("sample_index")
    manifest["audio_path"] = f"{legacy_root}/{relative_path}"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    batch = SeedSceneBlindReviewService(output_root=tmp_path).create_batch(samples=(
        {"case_id": "case-a", "variant": "described_voices", "sample_index": 1},
    ))

    assert len(batch["samples"]) == 1


def test_blind_review_summary_aggregates_reviewers_and_only_admin_view_reveals_identity(
    tmp_path: Path,
) -> None:
    _cached_sample(tmp_path, case_id="case-a", variant="described_voices", sample_index=1)
    service = SeedSceneBlindReviewService(output_root=tmp_path)
    batch = service.create_batch(samples=(
        {"case_id": "case-a", "variant": "described_voices", "sample_index": 1},
    ))
    anonymous_id = batch["samples"][0]["anonymous_id"]
    for reviewer_user_id, score, usable in ((7, 4.0, True), (8, 2.0, False)):
        service.submit_review(
            batch["batch_id"],
            anonymous_id,
            reviewer_user_id=reviewer_user_id,
            review={
                "score": score,
                "flags": {"usable": usable, "mixClear": True},
                "notes": "",
            },
        )

    blind = service.get_review_summary(batch["batch_id"], reveal_identity=False)
    revealed = service.get_review_summary(batch["batch_id"], reveal_identity=True)

    assert blind["review_count"] == 2
    assert blind["reviewer_count"] == 2
    assert blind["completed_sample_count"] == 1
    assert blind["samples"][0]["average_score"] == 3.0
    assert blind["samples"][0]["flag_pass_rates"] == {
        "mixClear": 1.0,
        "usable": 0.5,
    }
    assert "variant" not in blind["samples"][0]
    assert "reviewer_user_id" not in json.dumps(blind)
    assert revealed["samples"][0]["case_id"] == "case-a"
    assert revealed["samples"][0]["variant"] == "described_voices"
    assert revealed["samples"][0]["sample_index"] == 1
