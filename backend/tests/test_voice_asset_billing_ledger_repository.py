"""固定音色生命周期账本仓储 TDD。

账本只登记事件（创建/试听/正式成功/首次使用）+ 幂等键 + 供应商扣费凭证；
在计费口径确定前不自动冻结或结算，仅提供不可重复登记与凭证补录能力。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models.voice_asset_billing_ledger import VoiceAssetBillingLedger
from app.services.audiobook.voice_asset_billing_ledger_repository import (
    build_billing_idempotency_key,
    get_ledger_entry,
    list_voice_billing_events,
    mark_charge_settled,
    normalize_billing_event_type,
    record_voice_billing_event,
)


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VoiceAssetBillingLedger.__table__.create(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def test_record_event_persists_core_fields() -> None:
    db = _build_session()
    entry = record_voice_billing_event(
        db,
        provider="minimax",
        model="minimax-speech-2.8-hd",
        voice_id="mmx_hero",
        event_type="first_official_use",
        owner_user_id=7,
        billable=True,
        fixed_fee_yuan=9.9,
    )
    db.flush()

    assert entry.id is not None
    assert entry.provider == "minimax"
    assert entry.event_type == "first_official_use"
    assert entry.billable is True
    assert entry.fixed_fee_yuan == 9.9
    assert entry.currency == "CNY"
    assert entry.charge_status == "pending"
    assert entry.idempotency_key


def test_record_event_is_idempotent_on_same_lifecycle_event() -> None:
    db = _build_session()
    first = record_voice_billing_event(
        db,
        provider="doubao",
        model="doubao-seed-tts-2.0",
        voice_id="clone_a",
        event_type="clone_succeeded",
        owner_user_id=3,
        billable=True,
        fixed_fee_yuan=138.0,
    )
    db.flush()
    second = record_voice_billing_event(
        db,
        provider="doubao",
        model="doubao-seed-tts-2.0",
        voice_id="clone_a",
        event_type="clone_succeeded",
        owner_user_id=3,
        billable=True,
        fixed_fee_yuan=138.0,
    )
    db.flush()

    assert first.id == second.id
    assert list_voice_billing_events(db, provider="doubao", voice_id="clone_a").__len__() == 1


def test_distinct_events_for_same_voice_are_separate_rows() -> None:
    db = _build_session()
    record_voice_billing_event(
        db,
        provider="stepaudio",
        model="step-audio-2.5",
        voice_id="v1",
        event_type="clone_succeeded",
        owner_user_id=1,
    )
    record_voice_billing_event(
        db,
        provider="stepaudio",
        model="step-audio-2.5",
        voice_id="v1",
        event_type="first_official_use",
        owner_user_id=1,
        billable=True,
        fixed_fee_yuan=9.9,
    )
    db.flush()

    events = list_voice_billing_events(db, provider="stepaudio", voice_id="v1")
    assert {e.event_type for e in events} == {"clone_succeeded", "first_official_use"}


def test_idempotency_key_scopes_by_user() -> None:
    key_a = build_billing_idempotency_key(
        provider="minimax",
        model="minimax-speech-2.8-hd",
        voice_id="v",
        event_type="first_official_use",
        owner_user_id=1,
    )
    key_b = build_billing_idempotency_key(
        provider="minimax",
        model="minimax-speech-2.8-hd",
        voice_id="v",
        event_type="first_official_use",
        owner_user_id=2,
    )
    assert key_a != key_b


def test_mark_charge_settled_records_receipt() -> None:
    db = _build_session()
    entry = record_voice_billing_event(
        db,
        provider="minimax",
        model="minimax-speech-2.8-turbo",
        voice_id="v9",
        event_type="first_official_use",
        owner_user_id=5,
        billable=True,
        fixed_fee_yuan=9.9,
    )
    db.flush()
    charged_at = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    settled = mark_charge_settled(
        db,
        idempotency_key=entry.idempotency_key,
        provider_charge_id="mmx-bill-001",
        provider_charge_receipt="receipt-payload",
        charged_at=charged_at,
    )
    db.flush()

    assert settled is not None
    assert settled.charge_status == "charged"
    assert settled.provider_charge_id == "mmx-bill-001"
    assert settled.provider_charge_receipt == "receipt-payload"
    assert settled.charged_at == charged_at


def test_get_ledger_entry_round_trip() -> None:
    db = _build_session()
    entry = record_voice_billing_event(
        db,
        provider="doubao",
        model="doubao-seed-tts-2.0",
        voice_id="clone_z",
        event_type="voice_created",
        owner_user_id=8,
        voice_asset_id="vc_abcdef",
        metadata={"source": "test"},
    )
    db.flush()

    fetched = get_ledger_entry(db, entry.idempotency_key)
    assert fetched is not None
    assert fetched.voice_asset_id == "vc_abcdef"
    assert fetched.metadata_json == {"source": "test"}
    assert fetched.charge_status == "pending"


def test_invalid_event_type_raises() -> None:
    with pytest.raises(ValueError):
        normalize_billing_event_type("not_a_real_event")
