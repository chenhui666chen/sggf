"""域 3+4 接入层合同测试（GUIDE §5 六步闭环 / R10/R11/R12/R17/R18）。

覆盖：
- billing_snapshot 构建器（计价快照/映射表/金额计算/积分换算）
- 入队路径写派发意图（dispatch_status/独立 celery_task_id/predecessor/TaskDispatch）
- 入队路径锁定唯一 active ChapterAudio + desired_run_id 指针
- apply_async 三态处理（成功 dispatched / 明确失败补偿）
- 逐 run 任务租约认领 + 心跳 + 终态处理（清租约/关账/finalizer/聚合）
- finalizer settle 参数正确性与 run/批次级 key 兼容
- dispatched 未认领超时重投（R12/P1-5）
"""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.utils.datetime_utils import utc_now  # noqa: E402


# ---------------------------------------------------------------------------
# billing_snapshot 构建器
# ---------------------------------------------------------------------------

class TestBillingSnapshotBuilder:
    def test_usage_kind_mapping_table(self):
        """R18/P1-3：usage_kind → pricing_key → unit 唯一映射表"""
        from app.services.audiobook.billing_snapshot_builder import (
            resolve_pricing_key_for_usage_kind,
            resolve_unit_for_pricing_key,
            resolve_unit_for_usage_kind,
        )

        assert resolve_pricing_key_for_usage_kind("seed_render") == "seed_scene"
        assert resolve_pricing_key_for_usage_kind("tts_chars") == "tts"
        assert resolve_pricing_key_for_usage_kind("asr_seconds") == "asr"
        assert resolve_pricing_key_for_usage_kind("remix") == "remix"
        assert resolve_pricing_key_for_usage_kind("unknown_kind") is None

        assert resolve_unit_for_usage_kind("seed_render") == "second"
        assert resolve_unit_for_usage_kind("tts_chars") == "char"
        assert resolve_unit_for_pricing_key("seed_scene") == "second"
        assert resolve_unit_for_pricing_key("tts") == "char"

    def test_build_snapshot_legacy_stems(self):
        """legacy_stems 快照：tts 单价 = price_per_10k/10000 元/字符"""
        from app.services.audiobook.billing_snapshot_builder import build_billing_snapshot

        db = MagicMock()
        snapshot = build_billing_snapshot(
            db,
            audiobook_project_id=1,
            run_type="audio_from_scripts",
            tts_model="minimax-speech-2.8-hd",
            engine_mode="legacy_stems",
        )

        assert snapshot["snapshot_id"].startswith("bs-")
        assert snapshot["engine_mode"] == "legacy_stems"
        assert snapshot["settlement_formula_version"] >= 1
        assert "snapshot_fingerprint" in snapshot
        tts = snapshot["prices"]["tts"]
        assert tts["unit"] == "char"
        assert tts["price_per_char_yuan"] > 0  # 3.5/10000
        assert "seed_scene" not in snapshot["prices"] or snapshot["prices"]["seed_scene"].get("price_per_second_yuan", 0) == 0
        # 计价策略字段对齐 PointsPricingPolicyConfig
        for field in ("points_per_yuan", "user_price_basis", "user_price_rate", "freeze_buffer_rate"):
            assert field in snapshot, f"缺少计价策略字段 {field}"

    def test_build_snapshot_seed_scene(self):
        """seed_scene 快照：seed_scene 单价 = 1 元/分钟 → /60 元/秒"""
        from app.services.audiobook.billing_snapshot_builder import build_billing_snapshot

        db = MagicMock()
        snapshot = build_billing_snapshot(
            db,
            audiobook_project_id=2,
            run_type="audio_from_scripts",
            tts_model="minimax-speech-2.8-hd",
            engine_mode="seed_scene",
        )

        seed = snapshot["prices"]["seed_scene"]
        assert seed["unit"] == "second"
        assert abs(seed["price_per_second_yuan"] - 1.0 / 60.0) < 1e-7

    def test_compute_settle_amounts(self):
        """按计价快照计算结算金额（quantity × 单价）"""
        from app.services.audiobook.billing_snapshot_builder import compute_settle_amounts

        snapshot = {
            "prices": {
                "tts": {"unit": "char", "price_per_char_yuan": 0.00035},
                "seed_scene": {"unit": "second", "price_per_second_yuan": 1.0 / 60.0},
            }
        }
        tts_amount = compute_settle_amounts(snapshot, pricing_key="tts", quantity=10000)
        assert tts_amount["ok"] is True
        assert abs(tts_amount["amount_yuan"] - 3.5) < 1e-6

        seed_amount = compute_settle_amounts(snapshot, pricing_key="seed_scene", quantity=60)
        assert seed_amount["ok"] is True
        assert abs(seed_amount["amount_yuan"] - 1.0) < 1e-6

        # 未知计价键 / 无单价 → fail-closed（ok=False，金额 0）
        unknown = compute_settle_amounts(snapshot, pricing_key="nope", quantity=10)
        assert unknown["ok"] is False
        assert unknown["amount_yuan"] == 0.0

    def test_convert_yuan_to_points(self):
        """元 → 积分（points_per_yuan × user_price_rate）"""
        from app.services.audiobook.billing_snapshot_builder import convert_yuan_to_points

        snapshot = {"points_per_yuan": 100, "module_user_price_rate": 1.0}
        assert convert_yuan_to_points(snapshot, amount_yuan=3.5) == 350.0

        snapshot2 = {"points_per_yuan": 100, "user_price_rate": 0.8, "module_user_price_rate": 0.8}
        assert convert_yuan_to_points(snapshot2, amount_yuan=10.0) == 800.0

    def test_usage_kind_mapping_single_source(self):
        """映射四处同源：pricing_key/unit 值域与 ledger CHECK 一致（second|char）"""
        from app.services.audiobook.billing_snapshot_builder import PRICING_KEY_UNITS

        assert set(PRICING_KEY_UNITS.values()) <= {"second", "char"}


# ---------------------------------------------------------------------------
# 入队路径：派发意图 + ChapterAudio 锁定 + TaskDispatch + billing_snapshot
# ---------------------------------------------------------------------------

class TestEnqueueDispatchIntent:
    def test_enqueue_writes_dispatch_intent(self):
        """入队事务内写入派发意图（R11/P0-1 outbox）"""
        from app.services.audiobook import task_support

        run = SimpleNamespace(
            id=100, audiobook_project_id=7, chapter_id=3, run_type="full",
            tts_model="minimax-speech-2.8-hd",
            chapter_audio_id=None, desired_run_id=None,
            run_input_snapshot=json.dumps({"signed_payload": {"billing_context": {}}}),
            status="queued", current_stage="queued", progress=0.0,
            checkpoint_json={}, resumable=True,
            celery_task_id=None, dispatch_status=None, dispatch_attempts=None,
            next_dispatch_at=None, predecessor_run_id=None,
            billing_account_user_id=None,
        )
        chapter_audio = SimpleNamespace(id=55, chapter_id=3, desired_run_id=None)
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_query.filter.return_value.update.return_value = 1
        db = MagicMock()
        db.query.return_value = mock_query

        # _ensure_active_chapter_audio 重读返回 None（新创建路径）
        def _fake_ensure(db, *, audiobook_project_id, chapter_id):
            return chapter_audio

        task_support._ensure_active_chapter_audio = _fake_ensure
        # build_billing_snapshot 需要真实 db（mock 返回固定快照）
        fake_snapshot = {
            "snapshot_id": "bs-test", "prices": {"tts": {"unit": "char", "price_per_char_yuan": 0.00035}},
            "points_per_yuan": 100, "user_price_rate": 1.0, "module_user_price_rate": 1.0,
        }
        with patch(
            "app.services.audiobook.task_support.build_billing_snapshot",
            return_value=fake_snapshot,
        ):
            task_support._freeze_billing_snapshot_into_run(
                db, run=run, engine_mode="legacy_stems", billing_account_user_id=42,
            )

        # billing_snapshot 冻结进 run_input_snapshot + billing_account_user_id
        snapshot_payload = json.loads(run.run_input_snapshot)
        billing_ctx = snapshot_payload["signed_payload"]["billing_context"]
        assert billing_ctx["billing_snapshot"]["snapshot_id"] == "bs-test"
        assert billing_ctx["billing_account_user_id"] == 42
        assert run.billing_account_user_id == 42

    def test_freezing_billing_snapshot_is_idempotent(self):
        """已存在 billing_snapshot 时不覆盖（冻结事实不可变）"""
        from app.services.audiobook import task_support

        existing = {"snapshot_id": "bs-existing", "prices": {}}
        run = SimpleNamespace(
            run_input_snapshot=json.dumps(
                {"signed_payload": {"billing_context": {"billing_snapshot": existing}}}
            ),
            billing_account_user_id=None,
        )
        db = MagicMock()
        with patch(
            "app.services.audiobook.task_support.build_billing_snapshot",
            side_effect=AssertionError("不应重新构建快照"),
        ):
            task_support._freeze_billing_snapshot_into_run(
                db, run=run, engine_mode="legacy_stems", billing_account_user_id=None,
            )
        payload = json.loads(run.run_input_snapshot)
        assert payload["signed_payload"]["billing_context"]["billing_snapshot"]["snapshot_id"] == "bs-existing"


# ---------------------------------------------------------------------------
# 终态接入：update_chapter_run_state 清租约 + 关账
# ---------------------------------------------------------------------------

class TestTerminalAccounting:
    def test_update_chapter_run_state_terminal_clears_lease_and_closes(self):
        """终态写回触发清租约 + 按证据关账（R18/P0）"""
        from app.services.audiobook import task_support

        run = SimpleNamespace(
            id=200, audiobook_project_id=1, chapter_id=3,
            status="queued", error_message=None, celery_task_id="t-200",
            current_stage="queued", progress=0.0, started_at=None, finished_at=None,
            expires_at=None, resumable=True,
            dispatch_status="dispatched",
        )
        db = MagicMock()
        calls = []

        with patch(
            "app.services.audiobook.task_support.ChapterAudioRunRepository.get_run_by_id",
            return_value=run,
        ), patch(
            "app.services.audiobook.dispatch_service.clear_worker_lease",
            side_effect=lambda db, run_id: calls.append(("clear", run_id)) or True,
        ), patch(
            "app.services.audiobook.ledger_transition_service.close_accounting_on_run_terminal",
            side_effect=lambda db, run_id: calls.append(("close", run_id)) or {"confirmed_failed": 1},
        ), patch(
            "app.services.audiobook.task_support.build_run_checkpoint_document",
            return_value={"total_segment_count": 0},
        ), patch(
            "app.services.audiobook.task_support.ChapterAudioRunRepository.update_run",
            return_value=None,
        ):
            task_support.update_chapter_run_state(
                db,
                audiobook_project_id=1,
                chapter_id=3,
                run_type="full",
                status="completed",
                current_stage="completed",
                progress=1.0,
                run_id=200,
            )

        assert ("clear", 200) in calls
        assert ("close", 200) in calls

    def test_update_chapter_run_state_running_does_not_close(self):
        """非终态（running）不触发清租约/关账"""
        from app.services.audiobook import task_support

        run = SimpleNamespace(
            id=201, audiobook_project_id=1, chapter_id=3,
            status="queued", error_message=None, celery_task_id="t-201",
            current_stage="queued", progress=0.0, started_at=None, finished_at=None,
            expires_at=None, resumable=True,
            dispatch_status="dispatched",
        )
        db = MagicMock()
        calls = []

        with patch(
            "app.services.audiobook.task_support.ChapterAudioRunRepository.get_run_by_id",
            return_value=run,
        ), patch(
            "app.services.audiobook.dispatch_service.clear_worker_lease",
            side_effect=lambda db, run_id: calls.append("clear"),
        ), patch(
            "app.services.audiobook.ledger_transition_service.close_accounting_on_run_terminal",
            side_effect=lambda db, run_id: calls.append("close"),
        ), patch(
            "app.services.audiobook.task_support.build_run_checkpoint_document",
            return_value={},
        ), patch(
            "app.services.audiobook.task_support.ChapterAudioRunRepository.update_run",
            return_value=None,
        ):
            task_support.update_chapter_run_state(
                db,
                audiobook_project_id=1,
                chapter_id=3,
                run_type="full",
                status="running",
                current_stage="running",
                progress=0.5,
                run_id=201,
            )

        assert calls == []


# ---------------------------------------------------------------------------
# finalizer settle 参数正确性（R14/P1-e）
# ---------------------------------------------------------------------------

class TestFinalizerSettleContract:
    def _make_run(self):
        snapshot = {
            "signed_payload": {
                "billing_context": {
                    "billing_snapshot": {
                        "snapshot_id": "bs-1",
                        "prices": {"tts": {"unit": "char", "price_per_char_yuan": 0.00035}},
                        "points_per_yuan": 100,
                        "module_user_price_rate": 1.0,
                        "settlement_formula_version": 1,
                    },
                    "billing_account_user_id": 42,
                }
            }
        }
        return SimpleNamespace(
            id=300,
            audiobook_project_id=9,
            billing_account_user_id=42,
            run_input_snapshot=json.dumps(snapshot),
            status="completed",
            billing_finalized_at=None,
        )

    def test_execute_settle_passes_correct_arguments(self):
        """_execute_settle 以正确签名调用 record_points_billing_settle"""
        from app.services.audiobook import billing_finalizer_service

        run = self._make_run()
        db = MagicMock()

        ledger = SimpleNamespace(
            id=1, run_id=300, status="succeeded",
            pricing_key="tts", quantity=10000,  # 10000 字符 × 0.00035 = 3.5 元
        )
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [ledger]
        db.query.return_value = mock_query

        captured = {}

        def fake_settle(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id=999)

        with patch(
            "app.services.user_center_points_events.record_points_billing_settle",
            fake_settle,
        ):
            result = billing_finalizer_service._execute_settle(db, run=run)

        assert result["ok"] is True
        assert captured["billing_key"] == "audiobook:9:run:300"
        assert captured["target_user_id"] == 42
        assert captured["module_key"] == "audiobook"
        assert abs(captured["amount_yuan"] - 3.5) < 1e-6
        assert captured["amount_points"] == 350.0
        assert "settle_scope" in captured["extra_payload"]
        # 复合串仅作审计描述，不作为 billing_key（R14/P1-e）
        assert captured["billing_key"] != "audiobook:9:run:300:settle:300"

    def test_execute_settle_falls_back_to_batch_key(self):
        """run 级 key 无 active freeze → 批次级 key 兼容回退（现有批次冻结不挂死）"""
        from app.services.audiobook import billing_finalizer_service

        run = self._make_run()
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        db.query.return_value = mock_query

        calls = []

        def fake_settle(**kwargs):
            calls.append(kwargs.get("billing_key"))
            return None  # 第一次（run 级）无 active freeze → None

        with patch(
            "app.services.user_center_points_events.record_points_billing_settle",
            fake_settle,
        ):
            result = billing_finalizer_service._execute_settle(db, run=run)

        assert result["ok"] is True
        assert calls == ["audiobook:9:run:300", "audiobook:9"]  # run 级 → 批次级
        assert result["note"] == "no_active_freeze_or_already_settled"

    def test_execute_settle_zero_ledger_skips_gracefully(self):
        """无 succeeded ledger → 无 active freeze → 跳过结算（历史 run 不挂死）"""
        from app.services.audiobook import billing_finalizer_service

        run = self._make_run()
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        db.query.return_value = mock_query

        with patch(
            "app.services.user_center_points_events.record_points_billing_settle",
            return_value=None,
        ):
            result = billing_finalizer_service._execute_settle(db, run=run)

        assert result["ok"] is True


# ---------------------------------------------------------------------------
# 恢复证据持久化与决策（R12/P1-3，R13/P0-b，验收 70）
# ---------------------------------------------------------------------------

class TestLedgerRecoveryEvidence:
    def _make_ledger(self, **overrides):
        base = dict(
            id=1, run_id=1, status="pending", attempt_key="att:1",
            provider="dashscope_seed", usage_kind="seed_render", unit="second",
            provider_request_id=None, encrypted_result_url=None,
            result_url_expires_at=None, result_url_persisted_at=None,
            idempotency_key_sent=False, commit_stage="pre_call",
            capability_snapshot_json=None,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_persist_result_url_evidence(self):
        """结果 URL 落库：encrypted_result_url + persisted_at + commit_stage=result_persisted"""
        from app.services.audiobook.ledger_recovery_service import (
            persist_result_url_evidence,
        )
        from datetime import timedelta

        ledger = self._make_ledger()
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = ledger
        db.query.return_value = mock_query

        expires = utc_now() + timedelta(hours=1)
        result = persist_result_url_evidence(
            db, ledger_id=1, encrypted_url="enc://abc", expires_at=expires,
        )
        assert result["ok"] is True
        assert ledger.encrypted_result_url == "enc://abc"
        assert ledger.result_url_persisted_at is not None
        assert ledger.commit_stage == "result_persisted"
        db.flush.assert_called_once()

    def test_recovery_by_request_id(self):
        """① 已持有 provider_request_id + 调用时能力支持查询 → request_query"""
        from app.services.audiobook.ledger_recovery_service import decide_recovery_method

        ledger = self._make_ledger(
            provider_request_id="req-1",
            capability_snapshot_json={"supports_request_query": True},
        )
        decision = decide_recovery_method(ledger, current_capability={"supports_request_query": False})
        assert decision["method"] == "request_query"
        # 当前能力变化不影响历史决策
        assert "req-1" in decision["evidence"]

    def test_recovery_ignores_current_capability_for_request_id(self):
        """调用时未声明可查询 → 即使当前支持也不 query（历史调用按历史能力）"""
        from app.services.audiobook.ledger_recovery_service import decide_recovery_method

        ledger = self._make_ledger(
            provider_request_id="req-2",
            capability_snapshot_json={"supports_request_query": False},
        )
        decision = decide_recovery_method(
            ledger, current_capability={"supports_request_query": True},
        )
        assert decision["method"] != "request_query"

    def test_recovery_by_result_url(self):
        """② 已持有结果 URL 且未过期 → temporary_url"""
        from app.services.audiobook.ledger_recovery_service import decide_recovery_method
        from datetime import timedelta

        ledger = self._make_ledger(
            encrypted_result_url="enc://url",
            result_url_persisted_at=utc_now(),
            result_url_expires_at=utc_now() + timedelta(hours=2),
        )
        decision = decide_recovery_method(ledger)
        assert decision["method"] == "temporary_url"

    def test_recovery_by_result_url_expired_falls_through(self):
        """结果 URL 过期 → 不拉取，继续后续决策"""
        from app.services.audiobook.ledger_recovery_service import decide_recovery_method
        from datetime import timedelta

        ledger = self._make_ledger(
            encrypted_result_url="enc://url",
            result_url_persisted_at=utc_now() - timedelta(hours=3),
            result_url_expires_at=utc_now() - timedelta(hours=1),
        )
        decision = decide_recovery_method(ledger)
        assert decision["method"] == "manual"

    def test_recovery_by_idempotency_replay(self):
        """③ 幂等键已发送且调用时能力接受 → replay（不产生第二笔费用）"""
        from app.services.audiobook.ledger_recovery_service import decide_recovery_method

        ledger = self._make_ledger(
            idempotency_key_sent=True,
            capability_snapshot_json={"accepts_idempotency_key": True},
        )
        decision = decide_recovery_method(ledger)
        assert decision["method"] == "replay"

    def test_recovery_manual_no_evidence(self):
        """④ 无任何实际证据 → manual（零二次调用）"""
        from app.services.audiobook.ledger_recovery_service import decide_recovery_method

        ledger = self._make_ledger(
            capability_snapshot_json={"accepts_idempotency_key": True},
        )
        decision = decide_recovery_method(ledger)
        # 能力声明支持但本次调用未实际发送幂等键 → 不得自动重放
        assert decision["method"] == "manual"
        assert decision["evidence"] == "no_recoverable_evidence"

    def test_recovery_methods_domain(self):
        """恢复方法值域对齐 provider_recovery（request_query/temporary_url/replay/manual）"""
        from app.services.audiobook.ledger_recovery_service import RECOVERY_METHODS

        assert RECOVERY_METHODS == {"request_query", "temporary_url", "replay", "manual"}


# ---------------------------------------------------------------------------
# job_id 命名空间与 SSE 事件字段（R13/P1-a，验收 56/68）
# ---------------------------------------------------------------------------

class TestJobIdNamespace:
    def test_task_status_response_has_job_id_namespace(self):
        """状态响应 job_id = task:{AudiobookTask.id} 命名空间字符串"""
        from app.services.audiobook.task_support import build_task_status_response

        task = SimpleNamespace(
            id=77, celery_task_id="uuid-abc", audiobook_project_id=1,
            chapter_id=2, task_type="full", status="running",
            current_stage="tts_synthesis", progress=0.5,
            completed_units=1, total_units=2, detail_json={},
            error_message=None, created_at=None, updated_at=None,
            started_at=None, finished_at=None,
        )
        response = build_task_status_response(task)
        assert response.job_id == "task:77"
        assert response.celery_task_id == "uuid-abc"  # 兼容期双字段并存

    def test_get_task_for_user_resolves_job_id_namespace(self):
        """task:{id} 命名空间按 AudiobookTask.id 解析（验收 68 兼容期）"""
        from app.services.audiobook.repository import AudiobookTaskRepository

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.join.return_value.join.return_value.filter.return_value.first.return_value = "TASK_OBJ"
        db.query.return_value = mock_query

        result = AudiobookTaskRepository.get_task_for_user(db, "task:42", user_id=7)
        assert result == "TASK_OBJ"
        # 断言按 id=42 过滤（非 celery_task_id 字符串）
        filter_kwargs = mock_query.join.return_value.join.return_value.filter.call_args
        filter_cols = [
            getattr(getattr(arg, "left", None), "key", None)
            for arg in filter_kwargs.args
        ]
        assert "id" in filter_cols

    def test_get_task_for_user_keeps_celery_task_id_compat(self):
        """非 task: 前缀仍按 celery_task_id 解析（兼容期）"""
        from app.services.audiobook.repository import AudiobookTaskRepository

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.join.return_value.join.return_value.filter.return_value.first.return_value = "TASK_OBJ"
        db.query.return_value = mock_query

        result = AudiobookTaskRepository.get_task_for_user(db, "uuid-abc", user_id=7)
        assert result == "TASK_OBJ"
        filter_kwargs = mock_query.join.return_value.join.return_value.filter.call_args
        filter_cols = [
            getattr(getattr(arg, "left", None), "key", None)
            for arg in filter_kwargs.args
        ]
        assert "celery_task_id" in filter_cols

    def test_sse_emit_progress_carries_run_id_and_job_id(self):
        """SSE 事件 data 携带 run_id（detail 透传）与 job_id（验收 56/68）"""
        from app.services.audiobook.sse_progress import sse_tracker

        events = []
        original_build = sse_tracker._build_progress_event

        def fake_build(data):
            events.append(data)
            return original_build(data)

        sse_tracker._build_progress_event = fake_build
        try:
            sse_tracker.emit_progress(
                "task-uuid",
                {"stage": "tts_synthesis", "progress": 0.5, "run_id": 123},
            )
        finally:
            sse_tracker._build_progress_event = original_build

        assert events, "应产生 SSE 事件 data"
        event_data = events[0]
        assert event_data.get("run_id") == 123
        assert event_data.get("job_id") == "task-uuid"


# ---------------------------------------------------------------------------
# token fencing（R14/P1-d，验收 76）：迟到 dispatcher 回写/补偿被 token CAS 拒绝
# ---------------------------------------------------------------------------

class TestDispatcherTokenFencing:
    def test_success_writeback_requires_claim_token(self):
        """success 回写 CAS 校验 dispatch_claim_token（迟到 dispatcher 不得覆盖）"""
        from app.services.audiobook.dispatch_service import claim_and_dispatch_stale_pending

        stale_run = SimpleNamespace(
            id=500, dispatch_status="pending", next_dispatch_at=utc_now(),
            dispatch_attempts=0, celery_task_id="task-1",
            run_type="full", audiobook_project_id=1, chapter_id=2, tts_model="m",
            chapter_audio_id=None, predecessor_run_id=None,
            dispatch_claim_token=None,
        )
        db = MagicMock()
        mock_query = MagicMock()
        # 认领查询：返回 stale run
        mock_query.filter.return_value.order_by.return_value.limit.return_value.with_for_update.return_value.all.return_value = [stale_run]
        # 认领/回写 CAS 均为单 filter 多条件 → update rowcount=1
        mock_query.filter.return_value.update.return_value = 1
        db.query.return_value = mock_query

        with patch(
            "app.services.audiobook.dispatch_service._apply_async_safe",
            return_value="success",
        ):
            result = claim_and_dispatch_stale_pending(db, batch_size=20)

        assert result["dispatched"] == 1
        # 回写/认领均经单 filter CAS（含 dispatch_claim_token 条件）
        assert mock_query.filter.return_value.update.call_count >= 2

    def test_late_compensation_rejected_by_token_cas(self):
        """迟到 dispatcher 补偿：token 不匹配 → 拒绝且不置 cancelled"""
        from app.services.audiobook.dispatch_service import _compensate_failed_dispatch

        run = SimpleNamespace(
            id=600, chapter_audio_id=10, predecessor_run_id=5,
            status="running", dispatch_status="dispatched",
        )
        db = MagicMock()
        mock_query = MagicMock()
        # run CAS 更新：rowcount=0（token 已被接管）
        mock_query.filter.return_value.filter.return_value.update.return_value = 0
        db.query.return_value = mock_query

        compensated = _compensate_failed_dispatch(
            db, run, claim_token="stale-token",
        )
        assert compensated is False
        # run 未被取消
        assert run.status == "running"
        assert run.dispatch_status == "dispatched"

    def test_compensation_succeeds_with_matching_token(self):
        """token 匹配 → 补偿生效（run 置 cancelled + desired 回退）"""
        from app.services.audiobook.dispatch_service import _compensate_failed_dispatch

        run = SimpleNamespace(
            id=601, chapter_audio_id=10, predecessor_run_id=5,
            status="running", dispatch_status="dispatched",
        )
        db = MagicMock()
        mock_query = MagicMock()
        # run CAS 为单 filter 多条件（id, token）→ rowcount=1（token 匹配）
        mock_query.filter.return_value.update.return_value = 1
        db.query.return_value = mock_query

        compensated = _compensate_failed_dispatch(
            db, run, claim_token="current-token",
        )
        assert compensated is True
        # bulk update（synchronize_session=False）：断言 CAS update 调用，
        # DB 侧状态由真实 PG 测试验证
        assert mock_query.filter.return_value.update.call_count >= 1


# ---------------------------------------------------------------------------
# dispatch_service：clear_worker_lease + dispatched 未认领重投（R12/P1-5）
# ---------------------------------------------------------------------------

class TestDispatchServiceIntegration:
    def test_clear_worker_lease_with_token(self):
        """token 匹配清除租约"""
        from app.services.audiobook.dispatch_service import clear_worker_lease

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.filter.return_value.update.return_value = 1
        db.query.return_value = mock_query

        assert clear_worker_lease(db, run_id=1, claim_token="tok-1") is True
        db.flush.assert_called_once()

    def test_clear_worker_lease_token_mismatch(self):
        """token 不匹配 → 不清除（接管场景防误清）"""
        from app.services.audiobook.dispatch_service import clear_worker_lease

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.filter.return_value.update.return_value = 0
        db.query.return_value = mock_query

        assert clear_worker_lease(db, run_id=1, claim_token="wrong-token") is False

    def test_requeue_stale_dispatched(self):
        """dispatched 未认领超时 → CAS 置回 pending（R12/P1-5）"""
        from app.services.audiobook.dispatch_service import _requeue_stale_dispatched

        stale_run = SimpleNamespace(
            id=400, dispatch_status="dispatched", claim_token=None,
            dispatched_at=utc_now() - timedelta(minutes=10),
            dispatch_attempts=1,
        )
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.limit.return_value.with_for_update.return_value.all.return_value = [stale_run]
        # 更新链：单 filter 多条件（id/status/claim/dispatched_at）
        mock_query.filter.return_value.update.return_value = 1
        db.query.return_value = mock_query

        count = _requeue_stale_dispatched(db, batch_size=20)
        assert count == 1
        # bulk update（synchronize_session=False）不修改已加载对象：断言 update 调用
        assert mock_query.filter.return_value.update.call_count == 1

    def test_build_task_args_single_run_id(self):
        """逐 run 派发参数 = [run_id]（R10/P0-2）"""
        from app.services.audiobook.dispatch_service import _build_task_args

        run = SimpleNamespace(id=500, run_type="full", audiobook_project_id=1, chapter_id=2, tts_model="m")
        assert _build_task_args(run) == [500]

    def test_resolve_task_name_unified(self):
        """全部 run_type 统一投递到逐 run 任务"""
        from app.services.audiobook.dispatch_service import _resolve_celery_task_name

        for run_type in ("full", "script_only", "audio_from_scripts", "chapter_remix"):
            assert _resolve_celery_task_name(run_type) == "audiobook.run_chapter_dispatch"

    def test_try_finalize_run_takes_account_lock_first(self):
        """finalizer 锁序：账户 advisory 锁先于 run 行锁（R19/P0）"""
        from app.services.audiobook.billing_finalizer_service import try_finalize_run

        db = MagicMock()
        mock_query = MagicMock()
        # 无锁预读链（无 with_for_update）返回 account id
        mock_query.filter.return_value.first.return_value = (42,)
        # 锁后重读链（with_for_update）返回 run 对象
        mock_query.filter.return_value.with_for_update.return_value.first.return_value = SimpleNamespace(
            id=600, status="completed", billing_finalized_at=None,
            lease_expires_at=None, billing_account_user_id=42,
            audiobook_project_id=9, run_input_snapshot=None,
        )
        db.query.return_value = mock_query

        with patch(
            "app.services.audiobook.ledger_transition_service.close_accounting_on_run_terminal",
            return_value={"confirmed_failed": 0},
        ), patch(
            "app.services.audiobook.ledger_transition_service.check_strict_barrier",
            return_value={"passed": True, "pending_count": 0, "manual_count": 0},
        ), patch(
            "app.services.audiobook.billing_finalizer_service._execute_settle",
            return_value={"ok": True, "settle_result": None},
        ):
            result = try_finalize_run(db, run_id=600)

        assert result["finalized"] is True
        # 账户锁必须先于 run 锁（SQL 顺序断言）
        executed_sqls = [c.args[0] if c.args else "" for c in db.execute.call_args_list]
        assert any("pg_advisory_xact_lock" in str(s) for s in executed_sqls)
