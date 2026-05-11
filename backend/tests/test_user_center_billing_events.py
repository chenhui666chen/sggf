import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.admin_log import AdminOperationLog
from app.services.user_center_points_events import (
    POINTS_BILLING_MODULE_ASSET_STUDIO,
    build_points_billing_key,
    record_audiobook_billing_freeze,
    record_audiobook_billing_release,
    record_audiobook_billing_settle,
    record_dreamweaver_billing_freeze,
    record_dreamweaver_billing_release,
    record_dreamweaver_billing_settle,
    record_points_billing_freeze,
    record_points_billing_settle,
)
from app.services.points_usage_pricing import (
    build_points_billing_precheck,
    build_points_usage_charge_estimate,
)
from app.services.user_points_read_model import build_user_points_read_model


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from user_center_test_helpers import (
    build_auth_headers,
    build_test_client,
    create_audiobook_project,
    create_chapter,
    create_dreamweaver_run,
    create_points_billing_event,
    create_points_pricing_policy_snapshot,
    create_project,
    create_user,
)


def _create_manual_points_adjustment(
    session_factory,
    *,
    operator_user_id: int,
    operator_username: str,
    target_user_id: int,
    delta: float,
    created_at: datetime,
) -> AdminOperationLog:
    db = session_factory()
    try:
        log = AdminOperationLog(
            user_id=operator_user_id,
            username=operator_username,
            operation_type="POINTS_ADJUST",
            resource_type="USER_POINTS",
            resource_id=target_user_id,
            operation_desc="manual points adjustment",
            request_method="POST",
            request_path="/api/v1/admin/users/points-adjustments",
            request_params={
                "delta": delta,
                "adjustment_type": "manual_grant",
                "reason": "测试充值积分",
                "expires_at": None,
            },
            response_status=201,
            ip_address="127.0.0.1",
            user_agent="pytest",
            duration_ms=0,
            error_message=None,
            created_at=created_at,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
    finally:
        db.close()


def test_generic_asset_studio_billing_precheck_freeze_and_settle_updates_account():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="asset_points_user", email="asset_points@example.com")
    operator = create_user(session_factory, username="asset_points_admin", email="asset_points_admin@example.com")
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 100,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )
    _create_manual_points_adjustment(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        target_user_id=user.id,
        delta=200.0,
        created_at=now - timedelta(minutes=3),
    )

    billing_key = build_points_billing_key(POINTS_BILLING_MODULE_ASSET_STUDIO, "image:test-generic")
    db = session_factory()
    try:
        precheck = build_points_billing_precheck(
            db=db,
            user_id=user.id,
            billing_key=billing_key,
            module_key=POINTS_BILLING_MODULE_ASSET_STUDIO,
            module_label="资产生成",
            basis_yuan=1.0,
            provider_key="test-image-model",
        )
        assert precheck.allowed is True
        assert precheck.estimated_points == 100.0
        assert precheck.required_frozen_points == 110.0

        freeze_log = record_points_billing_freeze(
            db=db,
            actor_user_id=user.id,
            actor_username=user.username,
            target_user_id=user.id,
            billing_key=billing_key,
            module_key=POINTS_BILLING_MODULE_ASSET_STUDIO,
            amount_points=precheck.required_frozen_points,
            amount_yuan=precheck.estimated_yuan,
            title="资产生成：图片",
            summary="资产工作台图片生成已冻结积分。",
            action_path="/asset-studio",
            action_label="打开资产工作台",
            provider_key="test-image-model",
            extra_payload={"asset_kind": "image", "asset_mode": "text_to_image"},
        )
        assert freeze_log is not None

        account_after_freeze = build_user_points_read_model(db=db, user_id=user.id).points_bundle.account
        assert account_after_freeze.balance == 200.0
        assert account_after_freeze.frozen == 110.0

        settle_estimate = build_points_usage_charge_estimate(
            db=db,
            module_key=POINTS_BILLING_MODULE_ASSET_STUDIO,
            basis_yuan=1.0,
            provider_key="test-image-model",
            include_freeze_buffer=False,
        )
        settle_log = record_points_billing_settle(
            db=db,
            actor_user_id=user.id,
            actor_username=user.username,
            target_user_id=user.id,
            billing_key=billing_key,
            module_key=POINTS_BILLING_MODULE_ASSET_STUDIO,
            amount_points=settle_estimate.estimated_points,
            amount_yuan=settle_estimate.basis_yuan,
            title="资产生成：图片",
            summary="资产工作台图片生成已完成。",
            action_path="/asset-studio",
            action_label="打开资产工作台",
            provider_key="test-image-model",
            extra_payload={"asset_kind": "image", "asset_mode": "text_to_image"},
        )
        assert settle_log is not None

        account_after_settle = build_user_points_read_model(db=db, user_id=user.id).points_bundle.account
        assert account_after_settle.balance == 100.0
        assert account_after_settle.frozen == 0.0
        assert "asset_studio" in account_after_settle.connected_source_keys
    finally:
        db.close()


def test_audiobook_freeze_event_records_expected_payload():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="ab_freeze_user", email="ab_freeze@example.com")
    operator = create_user(session_factory, username="ab_freeze_admin", email="ab_freeze_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="有声书冻结项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="甲" * 10000,
    )
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="processing",
        total_chapters=1,
        completed_chapters=0,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 100,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )

    db = session_factory()
    try:
        log = record_audiobook_billing_freeze(
            db=db,
            actor_user_id=user.id,
            actor_username=user.username,
            audiobook_project_id=audiobook_project.id,
            chapter_ids=[chapter.id],
            extra_payload={
                "trace_id": "trace-freeze-1",
                "celery_task_id": "trace-freeze-1",
                "task_db_id": 42,
                "task_type": "audio_from_scripts",
                "cost_precheck_id": "audiobook-precheck-abc123",
                "status": "queued",
                "progress": 0.0,
                "audiobook_project_id": 99999,
                "amount_points": 1.0,
                "chapter_ids": [99999],
                "ignored_none": None,
            },
        )
        assert log is not None
        payload = log.request_params or {}
    finally:
        db.close()

    assert log.operation_type == "POINTS_BILLING_FREEZE"
    assert log.request_method == "POST"
    assert log.request_path == f"/api/v1/audiobook/projects/{audiobook_project.id}/billing-freeze"
    assert log.operation_desc == "有声书任务正式冻结积分 110.00"
    assert payload["billing_key"] == f"audiobook:{audiobook_project.id}"
    assert payload["module_key"] == "audiobook"
    assert payload["event_kind"] == "freeze"
    assert payload["target_user_id"] == user.id
    assert payload["amount_points"] == 110.0
    assert payload["amount_yuan"] == 1.0
    assert payload["title"] == "有声书冻结项目"
    assert payload["pricing_status"] == "estimated"
    assert payload["task_status"] == "running"
    assert payload["chapter_ids"] == [chapter.id]
    assert payload["trace_id"] == "trace-freeze-1"
    assert payload["celery_task_id"] == "trace-freeze-1"
    assert payload["task_db_id"] == 42
    assert payload["task_type"] == "audio_from_scripts"
    assert payload["cost_precheck_id"] == "audiobook-precheck-abc123"
    assert payload["status"] == "queued"
    assert payload["progress"] == 0.0
    assert "ignored_none" not in payload
    assert payload["action_path"] == f"/audiobook/{project.id}"
    assert payload["action_label"] == "查看有声书项目"
    assert payload["points_per_yuan"] == 100
    assert payload["freeze_buffer_rate"] == 0.1
    assert payload["operating_snapshot"]["user_billed_yuan"] == 1.0
    assert payload["operating_snapshot"]["negative_margin_blocked"] is False


def test_audiobook_freeze_event_uses_tts_pricing_key_when_provided():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="audio_freeze_model_user", email="audio_freeze_model@example.com")
    operator = create_user(session_factory, username="audio_freeze_model_admin", email="audio_freeze_model_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="有声书模型计价冻结项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="乙" * 10000,
    )
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="processing",
        total_chapters=1,
        completed_chapters=0,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 100,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )

    db = session_factory()
    try:
        log = record_audiobook_billing_freeze(
            db=db,
            actor_user_id=user.id,
            actor_username=user.username,
            audiobook_project_id=audiobook_project.id,
            chapter_ids=[chapter.id],
            tts_pricing_key="minimax-speech-2.8-hd",
        )
        assert log is not None
        payload = log.request_params or {}
    finally:
        db.close()

    assert payload["amount_yuan"] == 6.0
    assert payload["amount_points"] == 660.0
    assert payload["operating_snapshot"]["provider_key"] == "minimax-speech-2.8-hd"
    assert payload["operating_snapshot"]["user_billed_yuan"] == 6.0


def test_dreamweaver_freeze_event_records_expected_payload():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_freeze_user", email="dw_freeze@example.com")
    operator = create_user(session_factory, username="dw_freeze_admin", email="dw_freeze_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧冻结项目")
    run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-freeze-1",
        status="running",
        stage="storyboard",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [
                {
                    "shots": [
                        {"shot_key": "shot-1"},
                        {"shot_key": "shot-2"},
                    ]
                }
            ],
        },
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 120,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )

    db = session_factory()
    try:
        log = record_dreamweaver_billing_freeze(db=db, run_id=run.run_id)
        assert log is not None
        payload = log.request_params or {}
    finally:
        db.close()

    assert log.operation_type == "POINTS_BILLING_FREEZE"
    assert log.request_method == "SYSTEM"
    assert log.request_path == f"/internal/dreamweaver/{run.run_id}/billing-freeze"
    assert log.operation_desc == "短剧任务正式冻结积分 200.64"
    assert payload["billing_key"] == f"dreamweaver:{run.run_id}"
    assert payload["module_key"] == "dreamweaver"
    assert payload["event_kind"] == "freeze"
    assert payload["target_user_id"] == user.id
    assert payload["amount_points"] == 200.64
    assert payload["amount_yuan"] == 1.52
    assert payload["title"] == project.title
    assert payload["pricing_status"] == "estimated"
    assert payload["task_status"] == "running"
    assert payload["run_id"] == run.run_id
    assert payload["stage"] == "storyboard"
    assert payload["action_path"] == f"/drama/{project.id}"
    assert payload["action_label"] == "查看短剧项目"
    assert payload["points_per_yuan"] == 120
    assert payload["freeze_buffer_rate"] == 0.1
    assert payload["operating_snapshot"]["user_billed_yuan"] == 1.52
    assert payload["operating_snapshot"]["negative_margin_blocked"] is False


def test_dreamweaver_freeze_event_is_idempotent():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_freeze_once_user", email="dw_freeze_once@example.com")
    operator = create_user(session_factory, username="dw_freeze_once_admin", email="dw_freeze_once_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧幂等冻结项目")
    run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-freeze-once-1",
        status="running",
        stage="storyboard",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [{"shots": [{"shot_key": "shot-1"}]}],
        },
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 120,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )

    db = session_factory()
    try:
        first_log = record_dreamweaver_billing_freeze(db=db, run_id=run.run_id)
        second_log = record_dreamweaver_billing_freeze(db=db, run_id=run.run_id)
        logs = db.query(AdminOperationLog).all()
    finally:
        db.close()

    assert first_log is not None
    assert second_log is None

    matched_logs = [
        log
        for log in logs
        if (getattr(log, "request_params", None) or {}).get("billing_key") == f"dreamweaver:{run.run_id}"
        and (getattr(log, "request_params", None) or {}).get("event_kind") == "freeze"
    ]
    assert len(matched_logs) == 1


def test_dreamweaver_completed_task_billing_and_settlement_are_visible_in_user_center():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_settle_user", email="dw_settle@example.com")
    operator = create_user(session_factory, username="dw_settle_admin", email="dw_settle_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧结算项目")

    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 120,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )
    run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-settle-1",
        status="completed",
        stage="delivery",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [
                {
                    "shots": [
                        {"shot_key": "shot-1"},
                        {"shot_key": "shot-2"},
                    ]
                }
            ],
        },
        created_at=now,
        updated_at=now,
    )

    db = session_factory()
    try:
        log = record_dreamweaver_billing_settle(db=db, run_id=run.run_id)
        assert log is not None
    finally:
        db.close()

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == -177.4
    assert payload["points_account"]["frozen"] == 0.0

    task_billing = payload["task_billing"]
    assert task_billing["actual_task_count"] == 1
    assert task_billing["actual_spend_yuan"] == 1.52
    assert task_billing["actual_spend_points"] == 182.4

    task_items = {item["key"]: item for item in task_billing["items"]}
    assert task_items["dreamweaver-billing-dw-settle-1"]["pricing_status"] == "actual"
    assert task_items["dreamweaver-billing-dw-settle-1"]["actual_yuan"] == 1.52
    assert task_items["dreamweaver-billing-dw-settle-1"]["actual_points"] == 182.4

    points_entries = {item["key"]: item for item in payload["points_entries"]}
    settle_entry = points_entries[f"points-billing-settle-{log.id}"]
    assert settle_entry["direction"] == "expense"
    assert settle_entry["status"] == "active"
    assert settle_entry["source_label"] == "短剧运行"


def test_dreamweaver_release_event_clears_formal_frozen_points():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_release_user", email="dw_release@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧释放项目")
    run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-release-1",
        status="failed",
        stage="storyboard",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [{"shots": [{"shot_key": "shot-1"}]}],
        },
        created_at=now,
        updated_at=now,
    )

    freeze_log = create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"dreamweaver:{run.run_id}",
        module_key="dreamweaver",
        event_kind="freeze",
        amount_points=2.4,
        amount_yuan=0.02,
        title="短剧释放项目",
        summary="短剧任务已生成正式冻结积分",
        project_id=project.id,
        run_id=run.run_id,
        action_path=f"/drama/{project.id}",
        action_label="查看短剧模块",
        created_at=now - timedelta(minutes=1),
    )

    db = session_factory()
    try:
        release_log = record_dreamweaver_billing_release(
            db=db,
            run_id=run.run_id,
            reason="短剧任务失败，已释放冻结积分。",
        )
        assert release_log is not None
    finally:
        db.close()

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == 0.0
    assert payload["points_account"]["frozen"] == 0.0
    assert payload["points_account"]["connected_source_count"] == 1

    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert f"points-billing-freeze-{freeze_log.id}" in points_entries
    assert points_entries[f"points-billing-freeze-{freeze_log.id}"]["direction"] == "hold"
    assert points_entries[f"points-billing-freeze-{freeze_log.id}"]["status"] == "frozen"


def test_dreamweaver_release_event_falls_back_to_default_action_metadata():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_release_fallback_user", email="dw_release_fallback@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧释放回退项目")
    run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-release-fallback-1",
        status="failed",
        stage="storyboard",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [{"shots": [{"shot_key": "shot-1"}]}],
        },
        created_at=now,
        updated_at=now,
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"dreamweaver:{run.run_id}",
        module_key="dreamweaver",
        event_kind="freeze",
        amount_points=48.0,
        amount_yuan=0.4,
        title="短剧释放回退项目",
        summary="formal freeze created",
        project_id=project.id,
        run_id=run.run_id,
        action_path="",
        action_label="",
        created_at=now - timedelta(minutes=1),
    )

    db = session_factory()
    try:
        release_log = record_dreamweaver_billing_release(
            db=db,
            run_id=run.run_id,
            reason="短剧任务失败，回退默认跳转信息。",
        )
        assert release_log is not None
        payload = release_log.request_params or {}
    finally:
        db.close()

    assert payload["event_kind"] == "release"
    assert payload["action_path"] == f"/drama/{project.id}"
    assert payload["action_label"] == "查看短剧模块"
    assert payload["title"] == project.title
    assert payload["amount_points"] == 48.0
    assert payload["amount_yuan"] == 0.4


def test_dreamweaver_settle_event_is_idempotent():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_settle_once_user", email="dw_settle_once@example.com")
    operator = create_user(session_factory, username="dw_settle_once_admin", email="dw_settle_once_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧幂等结算项目")
    run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-settle-once-1",
        status="completed",
        stage="delivery",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [
                {
                    "shots": [
                        {"shot_key": "shot-1"},
                        {"shot_key": "shot-2"},
                    ]
                }
            ],
        },
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 120,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )

    db = session_factory()
    try:
        first_log = record_dreamweaver_billing_settle(db=db, run_id=run.run_id)
        second_log = record_dreamweaver_billing_settle(db=db, run_id=run.run_id)
        logs = db.query(AdminOperationLog).all()
    finally:
        db.close()

    assert first_log is not None
    assert second_log is None

    matched_logs = [
        log
        for log in logs
        if (getattr(log, "request_params", None) or {}).get("billing_key") == f"dreamweaver:{run.run_id}"
        and (getattr(log, "request_params", None) or {}).get("event_kind") == "settle"
    ]
    assert len(matched_logs) == 1


def test_dreamweaver_settlement_event_includes_operating_snapshot():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_margin_user", email="dw_margin@example.com")
    operator = create_user(session_factory, username="dw_margin_admin", email="dw_margin_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧经营项目")

    original_discount_env = os.environ.get("POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT")
    os.environ["POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT"] = "0.2"

    try:
        create_points_pricing_policy_snapshot(
            session_factory,
            operator_user_id=operator.id,
            operator_username=operator.username,
            payload={
                "points_per_yuan": 120,
                "user_price_basis": "public_list_price",
                "user_price_rate": 1.0,
                "provider_discount_capture_rate": 1.0,
                "freeze_buffer_rate": 0.1,
                "margin_warning_rate": 0.15,
                "negative_margin_block_enabled": True,
            },
            created_at=now - timedelta(minutes=5),
        )
        run = create_dreamweaver_run(
            session_factory,
            user_id=user.id,
            project_id=project.id,
            run_id="dw-margin-1",
            status="completed",
            stage="delivery",
            contract_json={
                "runtime_config": {"quality_mode": "quality"},
                "episodes": [
                    {
                        "shots": [
                            {"shot_key": "shot-1"},
                            {"shot_key": "shot-2"},
                        ]
                    }
                ],
            },
            created_at=now,
            updated_at=now,
        )

        db = session_factory()
        try:
            log = record_dreamweaver_billing_settle(db=db, run_id=run.run_id)
            assert log is not None
        finally:
            db.close()

        response = client.get(
            "/api/v1/user-center/points-overview",
            headers=build_auth_headers(user.id),
        )
        assert response.status_code == 200

        db = session_factory()
        try:
            stored_log = db.query(AdminOperationLog).filter(AdminOperationLog.id == log.id).first()
            assert stored_log is not None
            payload = stored_log.request_params or {}
        finally:
            db.close()

        operating_snapshot = payload.get("operating_snapshot")
        assert operating_snapshot is not None
        assert operating_snapshot["supplier_discount_rate"] == 0.2
        assert operating_snapshot["supplier_discount_rate_source"] == "env:POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT"
        assert operating_snapshot["user_billed_yuan"] == 1.52
        assert operating_snapshot["supplier_discounted_cost_yuan"] == 1.22
        assert operating_snapshot["platform_gross_profit_yuan"] == 0.3
        assert operating_snapshot["platform_margin_rate"] == 0.2
        assert operating_snapshot["margin_status"] == "healthy"
        assert operating_snapshot["negative_margin_blocked"] is False
    finally:
        if original_discount_env is None:
            os.environ.pop("POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT", None)
        else:
            os.environ["POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT"] = original_discount_env


def test_audiobook_zero_cost_completion_releases_formal_freeze():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="ab_release_user", email="ab_release@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="audiobook-zero-cost")
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="completed",
        total_chapters=1,
        completed_chapters=1,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )
    freeze_log = create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"audiobook:{audiobook_project.id}",
        module_key="audiobook",
        event_kind="freeze",
        amount_points=24.0,
        amount_yuan=0.2,
        title="audiobook-zero-cost",
        summary="formal freeze created",
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
        action_path=f"/audiobook/{project.id}",
        action_label="open audiobook",
        created_at=now - timedelta(minutes=1),
    )

    db = session_factory()
    try:
        release_log = record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project.id)
        assert release_log is not None
        assert (release_log.request_params or {}).get("event_kind") == "release"
    finally:
        db.close()

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == 8.0
    assert payload["points_account"]["frozen"] == 0.0

    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert f"points-billing-freeze-{freeze_log.id}" in points_entries
    assert all(not key.startswith("points-billing-settle-") for key in points_entries)


def test_audiobook_release_event_falls_back_to_default_action_metadata():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="ab_release_fallback_user", email="ab_release_fallback@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="有声书释放回退项目")
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="failed",
        total_chapters=1,
        completed_chapters=0,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"audiobook:{audiobook_project.id}",
        module_key="audiobook",
        event_kind="freeze",
        amount_points=24.0,
        amount_yuan=0.2,
        title="有声书释放回退项目",
        summary="formal freeze created",
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
        action_path="",
        action_label="",
        created_at=now - timedelta(minutes=1),
    )

    db = session_factory()
    try:
        release_log = record_audiobook_billing_release(
            db=db,
            audiobook_project_id=audiobook_project.id,
            reason="有声书任务失败，回退默认跳转信息。",
        )
        assert release_log is not None
        payload = release_log.request_params or {}
    finally:
        db.close()

    assert payload["event_kind"] == "release"
    assert payload["action_path"] == f"/audiobook/{project.id}"
    assert payload["action_label"] == "查看有声书项目"
    assert payload["title"] == project.title
    assert payload["amount_points"] == 24.0
    assert payload["amount_yuan"] == 0.2


def test_audiobook_settle_event_is_idempotent():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="ab_settle_once_user", email="ab_settle_once@example.com")
    operator = create_user(session_factory, username="ab_settle_once_admin", email="ab_settle_once_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="有声书幂等结算项目")
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="completed",
        total_chapters=1,
        completed_chapters=1,
        total_cost=1.0,
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 100,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=5),
    )

    db = session_factory()
    try:
        first_log = record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project.id)
        second_log = record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project.id)
        logs = db.query(AdminOperationLog).all()
    finally:
        db.close()

    assert first_log is not None
    assert second_log is None

    matched_logs = [
        log
        for log in logs
        if (getattr(log, "request_params", None) or {}).get("billing_key") == f"audiobook:{audiobook_project.id}"
        and (getattr(log, "request_params", None) or {}).get("event_kind") == "settle"
    ]
    assert len(matched_logs) == 1
