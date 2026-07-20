"""共享音频素材评分、聚合与自动下架策略。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Iterable

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.audio_library_asset import AudioLibraryAsset
from app.models.audio_library_asset_rating import AudioLibraryAssetRating


COMMUNITY_REJECTED_STATUS = "community_rejected"


@dataclass(frozen=True)
class AudioLibraryRatingPolicy:
    min_rating_count: int = 10
    low_score_max: int = 2
    min_low_rating_count: int = 8
    min_low_rating_ratio: float = 0.8
    max_average_score: float = 2.0


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def get_audio_library_rating_policy() -> AudioLibraryRatingPolicy:
    return AudioLibraryRatingPolicy(
        min_rating_count=max(1, _env_int("AUDIO_LIBRARY_MIN_RATING_COUNT", 10)),
        low_score_max=max(1, min(5, _env_int("AUDIO_LIBRARY_LOW_SCORE_MAX", 2))),
        min_low_rating_count=max(1, _env_int("AUDIO_LIBRARY_MIN_LOW_RATING_COUNT", 8)),
        min_low_rating_ratio=max(
            0.0,
            min(1.0, _env_float("AUDIO_LIBRARY_MIN_LOW_RATING_RATIO", 0.8)),
        ),
        max_average_score=max(
            1.0,
            min(5.0, _env_float("AUDIO_LIBRARY_MAX_AVERAGE_SCORE", 2.0)),
        ),
    )


def should_auto_unpublish(
    *,
    rating_count: int,
    low_rating_count: int,
    average_score: float,
    policy: AudioLibraryRatingPolicy,
) -> bool:
    if rating_count < policy.min_rating_count:
        return False
    if low_rating_count < policy.min_low_rating_count:
        return False
    if rating_count <= 0 or low_rating_count / rating_count < policy.min_low_rating_ratio:
        return False
    return average_score <= policy.max_average_score


def _aggregate_asset_rating(
    db: Session,
    *,
    asset_id: int,
    low_score_max: int,
) -> tuple[int, int, float]:
    row = (
        db.query(
            func.count(AudioLibraryAssetRating.id),
            func.coalesce(
                func.sum(
                    case(
                        (AudioLibraryAssetRating.score <= low_score_max, 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.avg(AudioLibraryAssetRating.score), 0.0),
        )
        .filter(AudioLibraryAssetRating.asset_id == asset_id)
        .one()
    )
    return int(row[0] or 0), int(row[1] or 0), float(row[2] or 0.0)


def submit_audio_library_rating(
    db: Session,
    *,
    asset: AudioLibraryAsset,
    user_id: int,
    score: int,
    policy: AudioLibraryRatingPolicy | None = None,
) -> dict:
    normalized_score = int(score)
    if normalized_score < 1 or normalized_score > 5:
        raise ValueError("score must be between 1 and 5")
    if not asset.id:
        db.flush()

    rating = (
        db.query(AudioLibraryAssetRating)
        .filter(
            AudioLibraryAssetRating.asset_id == asset.id,
            AudioLibraryAssetRating.user_id == int(user_id),
        )
        .first()
    )
    if rating is None:
        rating = AudioLibraryAssetRating(
            asset_id=asset.id,
            user_id=int(user_id),
            score=normalized_score,
        )
        db.add(rating)
    else:
        rating.score = normalized_score
    db.flush()

    active_policy = policy or get_audio_library_rating_policy()
    rating_count, low_rating_count, average_score = _aggregate_asset_rating(
        db,
        asset_id=asset.id,
        low_score_max=active_policy.low_score_max,
    )
    auto_unpublished = should_auto_unpublish(
        rating_count=rating_count,
        low_rating_count=low_rating_count,
        average_score=average_score,
        policy=active_policy,
    )
    if auto_unpublished:
        metadata = dict(asset.metadata_json or {})
        metadata["community_moderation"] = {
            "reason": "low_user_ratings",
            "rating_count": rating_count,
            "low_rating_count": low_rating_count,
            "average_score": average_score,
            "unpublished_at": datetime.now(timezone.utc).isoformat(),
        }
        asset.metadata_json = metadata
        asset.quality_status = COMMUNITY_REJECTED_STATUS
        db.add(asset)
        db.flush()

    return {
        "asset_id": asset.asset_key,
        "rating_count": rating_count,
        "low_rating_count": low_rating_count,
        "average_score": average_score,
        "user_score": normalized_score,
        "auto_unpublished": auto_unpublished,
        "quality_status": asset.quality_status or "",
    }


def get_audio_library_rating_summaries(
    db: Session,
    *,
    assets: Iterable[AudioLibraryAsset],
    user_id: int,
    policy: AudioLibraryRatingPolicy | None = None,
) -> dict[str, dict]:
    asset_list = [asset for asset in assets if asset.id]
    if not asset_list:
        return {}
    asset_ids = [asset.id for asset in asset_list]
    active_policy = policy or get_audio_library_rating_policy()

    aggregate_rows = (
        db.query(
            AudioLibraryAssetRating.asset_id,
            func.count(AudioLibraryAssetRating.id),
            func.coalesce(
                func.sum(
                    case(
                        (AudioLibraryAssetRating.score <= active_policy.low_score_max, 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.avg(AudioLibraryAssetRating.score), 0.0),
        )
        .filter(AudioLibraryAssetRating.asset_id.in_(asset_ids))
        .group_by(AudioLibraryAssetRating.asset_id)
        .all()
    )
    aggregate_by_id = {
        int(row[0]): {
            "rating_count": int(row[1] or 0),
            "low_rating_count": int(row[2] or 0),
            "average_score": float(row[3] or 0.0),
        }
        for row in aggregate_rows
    }
    user_scores = {
        int(rating.asset_id): int(rating.score)
        for rating in (
            db.query(AudioLibraryAssetRating)
            .filter(
                AudioLibraryAssetRating.asset_id.in_(asset_ids),
                AudioLibraryAssetRating.user_id == int(user_id),
            )
            .all()
        )
    }

    summaries: dict[str, dict] = {}
    for asset in asset_list:
        aggregate = aggregate_by_id.get(
            asset.id,
            {"rating_count": 0, "low_rating_count": 0, "average_score": 0.0},
        )
        summaries[asset.asset_key] = {
            **aggregate,
            "user_score": user_scores.get(asset.id),
        }
    return summaries


def is_community_rejected_status(value: object) -> bool:
    return str(value or "").strip().lower() == COMMUNITY_REJECTED_STATUS


__all__ = [
    "AudioLibraryRatingPolicy",
    "COMMUNITY_REJECTED_STATUS",
    "get_audio_library_rating_policy",
    "get_audio_library_rating_summaries",
    "is_community_rejected_status",
    "should_auto_unpublish",
    "submit_audio_library_rating",
]
