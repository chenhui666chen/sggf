import sys
import os
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.user_center_points_events import (
    record_dreamweaver_billing_release,
    record_dreamweaver_billing_settle,
)


CURRENT_DIR = Path(__file__).resolve().parent
HELPERS_PATH = CURRENT_DIR / "test_user_center_routes.py"
HELPERS_SPEC = spec_from_file_location("user_center_test_helpers", HELPERS_PATH)
if HELPERS_SPEC is None or HELPERS_SPEC.loader is None:
    raise RuntimeError("无法加载用户中心测试辅助模块")

HELPERS_MODULE = module_from_spec(HELPERS_SPEC)
sys.modules.setdefault("user_center_test_helpers", HELPERS_MODULE)
HELPERS_SPEC.loader.exec_module(HELPERS_MODULE)

build_test_client = HELPERS_MODULE.build_test_client
build_auth_headers = HELPERS_MODULE.build_auth_headers
create_project = HELPERS_MODULE.create_project
create_dreamweaver_run = HELPERS_MODULE.create_dreamweaver_run
create_points_billing_event = HELPERS_MODULE.create_points_billing_event
create_points_pricing_policy_snapshot = HELPERS_MODULE.create_points_pricing_policy_snapshot
create_user = HELPERS_MODULE.create_user


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
            stored_log = db.query(HELPERS_MODULE.AdminOperationLog).filter(HELPERS_MODULE.AdminOperationLog.id == log.id).first()
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
