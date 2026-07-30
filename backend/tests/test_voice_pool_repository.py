from __future__ import annotations

import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.voice_pool_publication import VoicePoolPublication
from app.models.voice_pool_rating import VoicePoolRating
from app.models.voice_asset_billing_ledger import VoiceAssetBillingLedger
from app.models.voice_reference_asset import VoiceReferenceAsset
from app.schemas.voice_pool import VoicePoolPublicationCreate
from app.services.audiobook import voice_pool_repository
from app.services.audiobook.voice_pool_repository import (
    create_voice_pool_publication,
    list_public_voice_pool,
    review_voice_pool_publication,
    submit_voice_pool_rating,
    withdraw_voice_pool_publication,
)
from app.services.audiobook.voice_reference_asset_repository import (
    get_active_voice_reference_asset,
    revoke_voice_reference_asset,
    upsert_voice_reference_asset,
)
from app.api.v1.audiobook_api import routes_tts
from app.api.v1.audiobook_api import routes_voice_pool
from app.schemas.audiobook import VoiceReferenceMaterializeRequest
from app.services.audiobook.project_audio_runtime import validate_project_voice_references


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VoiceReferenceAsset.__table__.create(bind=engine)
    VoiceAssetBillingLedger.__table__.create(bind=engine)
    VoicePoolPublication.__table__.create(bind=engine)
    VoicePoolRating.__table__.create(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _authorized_asset(db, *, owner_user_id: int = 7, sha256: str = "voice-sha"):
    now = datetime.now(timezone.utc)
    asset = upsert_voice_reference_asset(
        db,
        {
            "reference_kind": "user_generated_voice",
            "reference_field": "audio_data",
            "owner_user_id": owner_user_id,
            "authorized_by_user_id": owner_user_id,
            "authorization_scope": "user_generated",
            "authorization_basis": "synthetic_design",
            "authorization_version": "voice-reference-consent-v1",
            "authorized_at": now,
            "source_model": "mimo-v2.5-tts-voicedesign",
            "source_voice_id": "mimo_design:unit",
            "storage_uri": "voice-references/design-unit.wav",
            "sha256": sha256,
        },
    )
    db.flush()
    return asset


def _publication_payload() -> VoicePoolPublicationCreate:
    return VoicePoolPublicationCreate(
        display_name="清冷知性女声",
        description="克制、清晰，适合悬疑与都市对白。",
        gender_presentation="female",
        age_impression="young_adult",
        primary_style="restrained",
        language="zh-CN",
        accent="standard_mandarin",
        timbre_tags=["clear", "slightly_husky"],
        scenario_tags=["audiobook", "suspense"],
        emotion_tags=["calm", "sad"],
        rights_basis="synthetic_design",
        license_version="voice-pool-license-v1",
        consent_at=datetime.now(timezone.utc),
    )


def test_user_generated_assets_require_complete_owner_authorization() -> None:
    db = _build_session()

    with pytest.raises(ValueError, match="owner_user_id"):
        upsert_voice_reference_asset(
            db,
            {
                "reference_kind": "user_generated_voice",
                "sha256": "missing-owner",
                "authorization_scope": "user_generated",
                "authorization_version": "v1",
                "authorized_at": datetime.now(timezone.utc),
            },
        )


def test_user_asset_identity_is_isolated_by_owner() -> None:
    db = _build_session()

    first = _authorized_asset(db, owner_user_id=7, sha256="same-audio")
    second = _authorized_asset(db, owner_user_id=8, sha256="same-audio")

    assert first.asset_id != second.asset_id


def test_revoked_asset_is_not_returned_by_active_lookup() -> None:
    db = _build_session()
    asset = _authorized_asset(db)

    revoked = revoke_voice_reference_asset(
        db,
        asset_id=asset.asset_id,
        owner_user_id=7,
        revoked_by_user_id=7,
        reason="用户撤回声音授权",
    )

    assert revoked is not None
    assert revoked.revoked_at is not None
    assert get_active_voice_reference_asset(
        db,
        asset_id=asset.asset_id,
        owner_user_id=7,
    ) is None


def test_publication_requires_controlled_discovery_tags() -> None:
    with pytest.raises(ValueError):
        VoicePoolPublicationCreate(
            display_name="缺少标签的音色",
            gender_presentation="female",
            age_impression="adult",
            primary_style="natural",
            language="zh-CN",
            timbre_tags=[],
            scenario_tags=[],
            rights_basis="synthetic_design",
            license_version="voice-pool-license-v1",
            consent_at=datetime.now(timezone.utc),
        )


def test_publication_payload_does_not_require_client_audio_locations() -> None:
    payload = _publication_payload()

    assert payload.public_preview_uri == ""
    assert payload.public_reference_uri == ""


def test_publication_is_owner_scoped_and_hidden_until_reviewed() -> None:
    db = _build_session()
    asset = _authorized_asset(db)

    with pytest.raises(PermissionError):
        create_voice_pool_publication(
            db,
            source_asset_id=asset.asset_id,
            owner_user_id=8,
            payload=_publication_payload(),
        )

    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    db.flush()

    assert publication.status == "pending_review"
    assert list_public_voice_pool(db) == []

    reviewed = review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
        review_note="标签和标准试听已核验",
    )
    assert reviewed.status == "published"
    assert [item.publication_id for item in list_public_voice_pool(db)] == [
        publication.publication_id
    ]


def test_public_voice_pool_route_paginates_and_aggregates_ratings() -> None:
    db = _build_session()
    publications = []
    for index in range(3):
        asset = _authorized_asset(db, sha256=f"page-{index}")
        publication = create_voice_pool_publication(
            db,
            source_asset_id=asset.asset_id,
            owner_user_id=7,
            payload=_publication_payload().model_copy(
                update={"display_name": f"voice-{index}"}
            ),
        )
        review_voice_pool_publication(
            db,
            publication_id=publication.publication_id,
            reviewer_user_id=99,
            approved=True,
        )
        publications.append(publication)
    submit_voice_pool_rating(
        db, publication_id=publications[-1].publication_id, user_id=20, score=4
    )

    first_page = asyncio.run(
        routes_voice_pool.discover_public_voice_pool(limit=2, cursor=None, db=db)
    )

    assert len(first_page["voices"]) == 2
    assert first_page["next_cursor"] == first_page["voices"][-1]["publication_id"]
    assert first_page["voices"][0]["rating_count"] == 1
    second_page = asyncio.run(
        routes_voice_pool.discover_public_voice_pool(
            limit=2, cursor=first_page["next_cursor"], db=db
        )
    )
    assert len(second_page["voices"]) == 1
    assert second_page["next_cursor"] is None


def test_voice_pool_status_transition_table_matches_public_contract() -> None:
    assert voice_pool_repository.VOICE_POOL_STATUS_TRANSITIONS == {
        "pending_review": frozenset({"published", "rejected"}),
        "published": frozenset(
            {"suspended", "community_rejected", "withdrawn", "removed"}
        ),
        "suspended": frozenset({"published", "removed"}),
        "rejected": frozenset({"pending_review"}),
        "community_rejected": frozenset(),
        "withdrawn": frozenset(),
        "removed": frozenset(),
    }


def test_review_rejects_repeated_or_out_of_order_decisions() -> None:
    db = _build_session()
    first_asset = _authorized_asset(db, sha256="first-review")
    first = create_voice_pool_publication(
        db,
        source_asset_id=first_asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=first.publication_id,
        reviewer_user_id=99,
        approved=True,
    )

    with pytest.raises(ValueError, match="published -> published"):
        review_voice_pool_publication(
            db,
            publication_id=first.publication_id,
            reviewer_user_id=99,
            approved=True,
        )

    second_asset = _authorized_asset(db, sha256="second-review")
    second = create_voice_pool_publication(
        db,
        source_asset_id=second_asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=second.publication_id,
        reviewer_user_id=99,
        approved=False,
    )

    with pytest.raises(ValueError, match="rejected -> published"):
        review_voice_pool_publication(
            db,
            publication_id=second.publication_id,
            reviewer_user_id=99,
            approved=True,
        )


def test_only_published_publication_can_be_withdrawn() -> None:
    db = _build_session()
    asset = _authorized_asset(db, sha256="pending-withdraw")
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )

    with pytest.raises(ValueError, match="pending_review -> withdrawn"):
        withdraw_voice_pool_publication(
            db,
            publication_id=publication.publication_id,
            owner_user_id=7,
        )

    assert publication.status == "pending_review"


def test_concurrent_review_cannot_overwrite_first_decision() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VoiceReferenceAsset.__table__.create(bind=engine)
    VoiceAssetBillingLedger.__table__.create(bind=engine)
    VoicePoolPublication.__table__.create(bind=engine)
    VoicePoolRating.__table__.create(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    first_db = session_factory()
    stale_db = session_factory()
    verify_db = session_factory()
    try:
        asset = _authorized_asset(first_db, sha256="concurrent-review")
        publication = create_voice_pool_publication(
            first_db,
            source_asset_id=asset.asset_id,
            owner_user_id=7,
            payload=_publication_payload(),
        )
        first_db.commit()
        publication_id = publication.publication_id

        stale_publication = (
            stale_db.query(VoicePoolPublication)
            .filter(VoicePoolPublication.publication_id == publication_id)
            .one()
        )
        assert stale_publication.status == "pending_review"

        review_voice_pool_publication(
            first_db,
            publication_id=publication_id,
            reviewer_user_id=99,
            approved=True,
        )
        first_db.commit()

        with pytest.raises(ValueError, match="concurrent review conflict"):
            review_voice_pool_publication(
                stale_db,
                publication_id=publication_id,
                reviewer_user_id=100,
                approved=False,
            )
        stale_db.rollback()

        persisted = (
            verify_db.query(VoicePoolPublication)
            .filter(VoicePoolPublication.publication_id == publication_id)
            .one()
        )
        assert persisted.status == "published"
        assert persisted.reviewed_by_user_id == 99
    finally:
        first_db.close()
        stale_db.close()
        verify_db.close()
        engine.dispose()


def test_withdraw_is_idempotent_and_blocks_future_public_use() -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )

    first = withdraw_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        owner_user_id=7,
    )
    second = withdraw_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        owner_user_id=7,
    )

    assert first.status == second.status == "withdrawn"
    assert list_public_voice_pool(db) == []


def test_low_public_ratings_auto_unpublish_voice() -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )

    summary = None
    for user_id in range(20, 30):
        summary = submit_voice_pool_rating(
            db,
            publication_id=publication.publication_id,
            user_id=user_id,
            score=1,
        )

    assert summary is not None
    assert summary["auto_unpublished"] is True
    assert publication.status == "community_rejected"
    assert list_public_voice_pool(db) == []


def test_owner_cannot_rate_own_publication() -> None:
    db = _build_session()
    asset = _authorized_asset(db, owner_user_id=7)
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )

    with pytest.raises(PermissionError, match="own publication"):
        submit_voice_pool_rating(
            db,
            publication_id=publication.publication_id,
            user_id=7,
            score=5,
        )

    assert db.query(VoicePoolRating).count() == 0


def test_community_rejected_publication_cannot_receive_more_ratings() -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )
    for user_id in range(20, 30):
        submit_voice_pool_rating(
            db,
            publication_id=publication.publication_id,
            user_id=user_id,
            score=1,
        )

    assert publication.status == "community_rejected"
    with pytest.raises(ValueError, match="published voice"):
        submit_voice_pool_rating(
            db,
            publication_id=publication.publication_id,
            user_id=30,
            score=1,
        )

    assert db.query(VoicePoolRating).count() == 10


def test_rating_route_returns_forbidden_for_publication_owner() -> None:
    db = _build_session()
    asset = _authorized_asset(db, owner_user_id=7)
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            routes_voice_pool.rate_public_voice_pool_publication(
                publication_id=publication.publication_id,
                payload=routes_voice_pool.VoicePoolRatingRequest(score=5),
                current_user=SimpleNamespace(id=7),
                db=db,
            )
        )

    assert exc_info.value.status_code == 403
    assert db.query(VoicePoolRating).count() == 0


def test_design_reference_cache_miss_requires_confirmation_without_generation(monkeypatch) -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    db.commit()
    calls = []

    monkeypatch.setattr(routes_tts, "check_oss_preview_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes_tts, "_resolve_preview_speaker_id", lambda *_args, **_kwargs: "unit")
    monkeypatch.setattr(routes_tts, "_build_preview_voice_params", lambda *_args, **_kwargs: {"speaker": "unit"})

    async def fail_synthesis(**_kwargs):
        calls.append("synthesis")
        raise AssertionError("confirmation probe must not synthesize audio")

    monkeypatch.setattr(routes_tts, "runtime_synthesize_speech", fail_synthesis)
    result = asyncio.run(
        routes_tts.materialize_voice_reference_preview(
            request=VoiceReferenceMaterializeRequest(source_asset_id=asset.asset_id),
            current_user=SimpleNamespace(id=7),
            db=db,
        )
    )

    assert result["requires_cost_confirmation"] is True
    assert result["generated"] is False
    assert calls == []


def test_confirmed_design_reference_is_generated_and_reused(monkeypatch) -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    db.commit()
    monkeypatch.setattr(routes_tts, "check_oss_preview_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes_tts, "_resolve_preview_speaker_id", lambda *_args, **_kwargs: "unit")
    monkeypatch.setattr(routes_tts, "_build_preview_voice_params", lambda *_args, **_kwargs: {"speaker": "unit"})

    async def synthesize(**_kwargs):
        return b"ID3standard-reference"

    monkeypatch.setattr(routes_tts, "runtime_synthesize_speech", synthesize)
    monkeypatch.setattr(
        routes_tts,
        "upload_preview_to_oss",
        lambda **_kwargs: "https://oss.example.com/private/reference.mp3",
    )
    result = asyncio.run(
        routes_tts.materialize_voice_reference_preview(
            request=VoiceReferenceMaterializeRequest(
                source_asset_id=asset.asset_id,
                confirm_cost=True,
            ),
            current_user=SimpleNamespace(id=7),
            db=db,
        )
    )

    assert result["generated"] is True
    assert result["reference_audio_uri"].startswith("https://oss.example.com/")
    db.refresh(asset)
    assert asset.storage_uri == result["reference_audio_uri"]
    assert asset.source_preview_cache_key
    assert db.query(VoiceAssetBillingLedger).count() == 1


def test_publication_route_overrides_untrusted_client_audio_uri() -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    asset.source_url = "https://oss.example.com/derived/standard.mp3"
    asset.storage_uri = asset.source_url
    asset.metadata_json = {"preview_schema_version": "voice-reference-preview-v1"}
    db.commit()
    payload = _publication_payload().model_copy(
        update={
            "public_preview_uri": "https://attacker.example/spoof.mp3",
            "public_reference_uri": "https://attacker.example/spoof.mp3",
        }
    )

    result = asyncio.run(
        routes_voice_pool.publish_voice_to_pool(
            source_asset_id=asset.asset_id,
            payload=payload,
            current_user=SimpleNamespace(id=7),
            db=db,
        )
    )

    assert result["publication"]["public_preview_uri"] == asset.source_url
    assert result["publication"]["reference_audio_url"] == asset.source_url


def test_runtime_reference_validation_refreshes_private_and_public_urls() -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    asset.source_url = "https://oss.example.com/private/latest.mp3"
    asset.storage_uri = asset.source_url
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )
    mapping = {
        "私有角色": {
            "reference_source": "user_private",
            "voice_reference_asset_id": asset.asset_id,
            "reference_audio_url": "https://client.example/stale.mp3",
        },
        "公共角色": {
            "reference_source": "public_pool",
            "voice_pool_publication_id": publication.publication_id,
            "reference_audio_url": "https://client.example/stale-public.mp3",
        },
    }

    validate_project_voice_references(db, owner_user_id=7, voice_mapping=mapping)

    assert mapping["私有角色"]["reference_audio_url"] == asset.source_url
    assert mapping["私有角色"]["voice_reference_owner_user_id"] == 7
    assert mapping["公共角色"]["reference_audio_url"] == publication.public_reference_uri


def test_runtime_reference_validation_blocks_withdrawn_public_voice() -> None:
    db = _build_session()
    asset = _authorized_asset(db)
    publication = create_voice_pool_publication(
        db,
        source_asset_id=asset.asset_id,
        owner_user_id=7,
        payload=_publication_payload(),
    )
    review_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        reviewer_user_id=99,
        approved=True,
    )
    withdraw_voice_pool_publication(
        db,
        publication_id=publication.publication_id,
        owner_user_id=7,
    )

    with pytest.raises(ValueError, match="不存在或已下架"):
        validate_project_voice_references(
            db,
            owner_user_id=8,
            voice_mapping={
                "公共角色": {
                    "reference_source": "public_pool",
                    "voice_pool_publication_id": publication.publication_id,
                }
            },
        )
