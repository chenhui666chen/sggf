import os
import sys
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
    build_dreamweaver_task_points_precheck,
)
from app.services.user_center_points_events import build_audiobook_billing_key


CURRENT_DIR = Path(__file__).resolve().parent
HELPERS_PATH = CURRENT_DIR / "test_user_center_routes.py"
HELPERS_SPEC = spec_from_file_location("user_center_test_helpers_for_precheck", HELPERS_PATH)
if HELPERS_SPEC is None or HELPERS_SPEC.loader is None:
    raise RuntimeError("无法加载积分预检测试辅助模块")

HELPERS_MODULE = module_from_spec(HELPERS_SPEC)
sys.modules.setdefault("user_center_test_helpers_for_precheck", HELPERS_MODULE)
HELPERS_SPEC.loader.exec_module(HELPERS_MODULE)

build_test_client = HELPERS_MODULE.build_test_client
create_audiobook_project = HELPERS_MODULE.create_audiobook_project
create_chapter = HELPERS_MODULE.create_chapter
create_points_billing_event = HELPERS_MODULE.create_points_billing_event
create_points_pricing_policy_snapshot = HELPERS_MODULE.create_points_pricing_policy_snapshot
create_points_rule_snapshot = HELPERS_MODULE.create_points_rule_snapshot
create_project = HELPERS_MODULE.create_project
create_user = HELPERS_MODULE.create_user
create_user_asset = HELPERS_MODULE.create_user_asset


def _seed_points_snapshots(
    session_factory,
    *,
    operator_user_id: int,
    operator_username: str,
    now: datetime,
    reusable_asset_reward: float,
    running_audiobook_frozen: float = 2.0,
    user_price_rate: float = 1.0,
    freeze_buffer_rate: float = 0.1,
    negative_margin_block_enabled: bool = True,
) -> None:
    create_points_rule_snapshot(
        session_factory,
        operator_user_id=operator_user_id,
        operator_username=operator_username,
        payload={
            "reusable_asset_reward": reusable_asset_reward,
            "deliverable_asset_reward": 10.0,
            "audiobook_completion_reward": 8.0,
            "dreamweaver_completion_reward": 5.0,
            "running_audiobook_frozen": running_audiobook_frozen,
            "running_dreamweaver_frozen": 2.0,
            "reward_ttl_days": 30,
            "expiring_notice_days": 7,
        },
        created_at=now - timedelta(minutes=6),
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator_user_id,
        operator_username=operator_username,
        payload={
            "points_per_yuan": 100,
            "user_price_basis": "public_list_price",
            "user_price_rate": user_price_rate,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": freeze_buffer_rate,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": negative_margin_block_enabled,
        },
        created_at=now - timedelta(minutes=5),
    )


def test_audiobook_precheck_blocks_when_available_points_insufficient():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="precheck_low_user", email="precheck_low@example.com")
    operator = create_user(session_factory, username="precheck_low_admin", email="precheck_low_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="余额不足项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="甲" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="低余额资产",
        file_url="https://example.com/asset-low.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=20.0,
    )

    db = session_factory()
    try:
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_ids=[chapter.id],
            tts_provider="aliyun",
        )
    finally:
        db.close()

    assert precheck.allowed is False
    assert precheck.failure_code == "insufficient_available_points"
    assert precheck.required_frozen_points == 110.0
    assert precheck.additional_frozen_points == 110.0
    assert precheck.effective_available_points == 20.0
    assert "当前可用 20.00 积分" in (precheck.failure_message or "")


def test_audiobook_precheck_blocks_when_negative_margin_policy_is_hit():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="precheck_margin_user", email="precheck_margin@example.com")
    operator = create_user(session_factory, username="precheck_margin_admin", email="precheck_margin_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="负毛利项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="乙" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="高余额资产",
        file_url="https://example.com/asset-margin.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=200.0,
        user_price_rate=0.8,
        negative_margin_block_enabled=True,
    )

    db = session_factory()
    try:
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_ids=[chapter.id],
            tts_provider="aliyun",
        )
    finally:
        db.close()

    assert precheck.allowed is False
    assert precheck.failure_code == "negative_margin_blocked"
    assert precheck.operating_snapshot is not None
    assert precheck.operating_snapshot.negative_margin_blocked is True
    assert "预估毛利为负" in (precheck.failure_message or "")


def test_audiobook_precheck_reuses_existing_formal_freeze_amount():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="precheck_formal_user", email="precheck_formal@example.com")
    operator = create_user(session_factory, username="precheck_formal_admin", email="precheck_formal_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="正式冻结复用项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="丙" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="正式冻结资产",
        file_url="https://example.com/asset-formal.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=120.0,
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
    create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=build_audiobook_billing_key(audiobook_project.id),
        module_key="audiobook",
        event_kind="freeze",
        amount_points=60.0,
        amount_yuan=0.6,
        title="正式冻结复用项目",
        summary="任务开始时已正式冻结积分",
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
        action_path=f"/audiobook/{project.id}",
        action_label="查看有声书项目",
        created_at=now - timedelta(minutes=1),
    )

    db = session_factory()
    try:
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_ids=[chapter.id],
            tts_provider="aliyun",
            audiobook_project_id=audiobook_project.id,
        )
    finally:
        db.close()

    assert precheck.allowed is True
    assert precheck.required_frozen_points == 110.0
    assert precheck.existing_frozen_points == 60.0
    assert precheck.additional_frozen_points == 50.0
    assert precheck.available_points == 60.0


def test_audiobook_precheck_reclaims_current_running_frozen_points_for_existing_project():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="precheck_running_user", email="precheck_running@example.com")
    operator = create_user(session_factory, username="precheck_running_admin", email="precheck_running_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="在途冻结回收项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="丁" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="在途冻结资产",
        file_url="https://example.com/asset-running.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=120.0,
        running_audiobook_frozen=20.0,
    )
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="pending",
        total_chapters=1,
        completed_chapters=0,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )

    db = session_factory()
    try:
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_ids=[chapter.id],
            tts_provider="aliyun",
            audiobook_project_id=audiobook_project.id,
        )
    finally:
        db.close()

    assert precheck.allowed is True
    assert precheck.required_frozen_points == 110.0
    assert precheck.available_points == 100.0
    assert precheck.reclaimed_running_frozen_points == 20.0
    assert precheck.effective_available_points == 120.0


def test_dreamweaver_precheck_blocks_when_available_points_insufficient():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_precheck_low_user", email="dw_precheck_low@example.com")
    operator = create_user(session_factory, username="dw_precheck_low_admin", email="dw_precheck_low_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧余额不足项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="戊" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="短剧低余额资产",
        file_url="https://example.com/dw-asset-low.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=20.0,
    )

    db = session_factory()
    try:
        precheck = build_dreamweaver_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_rows=[chapter],
            chapter_ids=[chapter.id],
        )
    finally:
        db.close()

    assert precheck.allowed is False
    assert precheck.failure_code == "insufficient_available_points"
    assert precheck.estimated_shot_count == 7
    assert precheck.available_points == 20.0
    assert precheck.required_frozen_points > precheck.available_points
    assert "当前可用 20.00 积分" in (precheck.failure_message or "")


def test_dreamweaver_precheck_blocks_when_negative_margin_policy_is_hit():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_precheck_margin_user", email="dw_precheck_margin@example.com")
    operator = create_user(
        session_factory,
        username="dw_precheck_margin_admin",
        email="dw_precheck_margin_admin@example.com",
    )
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧负毛利项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="己" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="短剧高余额资产",
        file_url="https://example.com/dw-asset-margin.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=200.0,
        user_price_rate=0.8,
        negative_margin_block_enabled=True,
    )

    db = session_factory()
    try:
        precheck = build_dreamweaver_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_rows=[chapter],
            chapter_ids=[chapter.id],
        )
    finally:
        db.close()

    assert precheck.allowed is False
    assert precheck.failure_code == "negative_margin_blocked"
    assert precheck.estimated_shot_count == 7
    assert precheck.operating_snapshot is not None
    assert precheck.operating_snapshot.negative_margin_blocked is True
    assert "预估毛利为负" in (precheck.failure_message or "")


def test_dreamweaver_precheck_passes_when_available_points_are_sufficient():
    _, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="dw_precheck_ok_user", email="dw_precheck_ok@example.com")
    operator = create_user(session_factory, username="dw_precheck_ok_admin", email="dw_precheck_ok_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="短剧可启动项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="庚" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="短剧可启动资产",
        file_url="https://example.com/dw-asset-ok.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=500.0,
    )

    db = session_factory()
    try:
        precheck = build_dreamweaver_task_points_precheck(
            db=db,
            user_id=user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_rows=[chapter],
            chapter_ids=[chapter.id],
        )
    finally:
        db.close()

    assert precheck.allowed is True
    assert precheck.failure_code is None
    assert precheck.estimated_shot_count == 7
    assert precheck.balance_points == 500.0
    assert precheck.available_points == 500.0
    assert precheck.required_frozen_points > 0
    assert precheck.required_frozen_points < precheck.available_points
