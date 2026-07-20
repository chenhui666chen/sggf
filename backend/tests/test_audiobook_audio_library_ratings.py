import sys
import importlib
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_audio_library_rating_table_enforces_one_rating_per_user_and_asset():
    import app.models  # noqa: F401
    from app.db.base import Base

    table = Base.metadata.tables.get("audio_library_asset_ratings")

    assert table is not None
    assert table.c.asset_id.foreign_keys
    assert table.c.user_id.foreign_keys
    assert table.c.score.type.python_type is int
    assert any(
        constraint.name == "uq_audio_library_asset_ratings_asset_user"
        for constraint in table.constraints
    )
    assert any(
        constraint.name == "ck_audio_library_asset_ratings_score"
        for constraint in table.constraints
    )


def _load_rating_service():
    module_name = "app.services.audiobook.audio_library_rating_service"
    spec = importlib.util.find_spec(module_name)
    assert spec is not None
    return importlib.import_module(module_name)


def test_audio_library_rating_policy_requires_volume_ratio_and_low_average():
    service = _load_rating_service()
    policy = service.AudioLibraryRatingPolicy(
        min_rating_count=10,
        low_score_max=2,
        min_low_rating_count=8,
        min_low_rating_ratio=0.8,
        max_average_score=2.0,
    )

    assert service.should_auto_unpublish(
        rating_count=10,
        low_rating_count=8,
        average_score=2.0,
        policy=policy,
    ) is True
    assert service.should_auto_unpublish(
        rating_count=9,
        low_rating_count=8,
        average_score=1.5,
        policy=policy,
    ) is False
    assert service.should_auto_unpublish(
        rating_count=10,
        low_rating_count=7,
        average_score=1.5,
        policy=policy,
    ) is False
    assert service.should_auto_unpublish(
        rating_count=10,
        low_rating_count=8,
        average_score=2.1,
        policy=policy,
    ) is False


def test_audio_library_rating_upserts_user_score_and_auto_unpublishes_asset():
    from app.models.audio_library_asset import AudioLibraryAsset
    from app.models.audio_library_asset_rating import AudioLibraryAssetRating

    service = _load_rating_service()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AudioLibraryAsset.__table__.create(engine)
    AudioLibraryAssetRating.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    asset = AudioLibraryAsset(
        library_type="sfx",
        asset_key="sfx-rating-test",
        name="测试音效",
        file_path="sound_effects/test.wav",
        source="user_upload",
    )
    db.add(asset)
    db.commit()

    policy = service.AudioLibraryRatingPolicy(
        min_rating_count=3,
        low_score_max=2,
        min_low_rating_count=3,
        min_low_rating_ratio=1.0,
        max_average_score=2.0,
    )
    service.submit_audio_library_rating(db, asset=asset, user_id=1, score=2, policy=policy)
    service.submit_audio_library_rating(db, asset=asset, user_id=1, score=1, policy=policy)
    service.submit_audio_library_rating(db, asset=asset, user_id=2, score=2, policy=policy)
    result = service.submit_audio_library_rating(
        db,
        asset=asset,
        user_id=3,
        score=2,
        policy=policy,
    )
    db.commit()

    assert db.query(AudioLibraryAssetRating).count() == 3
    assert result["rating_count"] == 3
    assert result["low_rating_count"] == 3
    assert result["average_score"] == 5 / 3
    assert result["user_score"] == 2
    assert result["auto_unpublished"] is True
    assert asset.quality_status == service.COMMUNITY_REJECTED_STATUS
    assert asset.metadata_json["community_moderation"]["reason"] == "low_user_ratings"

    summaries = service.get_audio_library_rating_summaries(
        db,
        assets=[asset],
        user_id=1,
    )
    assert summaries[asset.asset_key]["user_score"] == 1
    assert summaries[asset.asset_key]["rating_count"] == 3

    db.close()
