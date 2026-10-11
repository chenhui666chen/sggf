from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai_trace_storage import (
    AtomicJsonStore,
    BackgroundOptimizationCoordinator,
    EvaluationRunGuard,
)
import app.services.ai_trace_storage as ai_trace_storage
from app.services.ai_trace_competition import ModelConfigStorage, SingleModelResult


def test_atomic_store_recovers_corrupt_primary_from_backup(tmp_path):
    path = tmp_path / "state.json"
    store = AtomicJsonStore(path)
    store.write({"value": 1})
    store.write({"value": 2})
    path.write_text("{broken", encoding="utf-8")

    assert store.read() == {"value": 1}


def test_atomic_store_serializes_concurrent_updates(tmp_path):
    store = AtomicJsonStore(tmp_path / "counter.json")
    store.write({"count": 0})

    def increment() -> None:
        store.update(lambda data: {"count": data.get("count", 0) + 1})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: increment(), range(40)))

    assert store.read()["count"] == 40


def test_evaluation_guard_rejects_parallel_and_cooldown_runs():
    guard = EvaluationRunGuard(cooldown_seconds=60)
    lease = guard.try_acquire("玄幻", now=100)

    assert lease is not None
    assert guard.try_acquire("玄幻", now=101) is None
    lease.release(completed_at=110)
    assert guard.try_acquire("玄幻", now=120) is None
    assert guard.try_acquire("玄幻", now=171) is not None
    assert guard.try_acquire("都市", now=120) is not None


def test_model_performance_concurrent_updates_do_not_lose_results(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 20, 1,
        fidelity_similarity=90, improvement=40,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: storage.update_performance(result, "玄幻"), range(40)))

    record = storage.load_performance("玄幻")["qwen-plus"]
    assert record.total_evaluations == 40
    assert record.total_success == 40


def test_evaluation_details_are_append_only_and_produce_metrics(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.record_evaluation_detail({
        "evaluation_id": "e1", "genre": "玄幻", "model_id": "m1",
        "success": True, "fidelity_eligible": True, "latency_seconds": 1.2,
    })
    storage.record_evaluation_detail({
        "evaluation_id": "e2", "genre": "玄幻", "model_id": "m1",
        "success": False, "fidelity_eligible": False, "error_type": "timeout",
        "latency_seconds": 120,
    })

    details = storage.load_evaluation_details("玄幻")
    metrics = storage.get_evaluation_metrics("玄幻")
    assert [item["evaluation_id"] for item in details] == ["e1", "e2"]
    assert metrics["total"] == 2
    assert metrics["success_rate"] == 0.5
    assert metrics["fidelity_rejection_rate"] == 0.5
    assert metrics["timeout_count"] == 1


def test_evaluation_guard_enforces_global_window_budget():
    guard = EvaluationRunGuard(
        cooldown_seconds=0, max_completed_runs=2, budget_window_seconds=86400
    )
    first = guard.try_acquire("玄幻", now=100)
    assert first is not None
    first.release(completed_at=101)
    second = guard.try_acquire("都市", now=102)
    assert second is not None
    second.release(completed_at=103)

    assert guard.try_acquire("科幻", now=104) is None
    assert guard.try_acquire("科幻", now=86502) is not None


def test_persistent_coordinator_is_global_and_preserves_budget_after_reload(tmp_path):
    path = tmp_path / "background_optimization_state.json"
    coordinator = BackgroundOptimizationCoordinator(path, daily_budget=5, cooldown_seconds=60)
    lease = coordinator.try_start("manual_evaluation", "玄幻", now=100)

    assert lease is not None
    assert coordinator.try_start("prompt_evolution", "都市", now=101) is None
    assert coordinator.consume_budget(2, now=102) is True
    coordinator.update_progress(expected_models=9, completed_models=4, success_models=3, failed_models=1)
    lease.finish(now=110)

    reloaded = BackgroundOptimizationCoordinator(path, daily_budget=5, cooldown_seconds=60)
    status = reloaded.get_status(now=120)
    assert status["is_running"] is False
    assert status["budget_used"] == 2
    assert status["budget_remaining"] == 3
    assert status["cooldown_until"] == 170
    assert status["expected_models"] == 9
    assert status["completed_models"] == 4
    assert reloaded.try_start("manual_evaluation", "悬疑", now=150) is None
    assert reloaded.try_start("manual_evaluation", "悬疑", now=171) is not None


def test_persistent_coordinator_rejects_budget_overrun(tmp_path):
    coordinator = BackgroundOptimizationCoordinator(
        tmp_path / "state.json", daily_budget=3, cooldown_seconds=0
    )
    assert coordinator.consume_budget(2, now=100) is True
    assert coordinator.consume_budget(2, now=101) is False
    assert coordinator.get_status(now=101)["budget_remaining"] == 1


def test_evaluation_details_keep_only_the_configured_recent_records(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.EVALUATION_DETAIL_LIMIT = 3
    for index in range(5):
        storage.record_evaluation_detail({
            "evaluation_id": f"e{index}", "genre": "玄幻", "success": True
        })

    assert [item["evaluation_id"] for item in storage.load_evaluation_details()] == [
        "e2", "e3", "e4"
    ]


def test_stale_lock_and_temp_files_do_not_block_store_and_backup_recovery_heals_primary(tmp_path):
    path = tmp_path / "state.json"
    store = AtomicJsonStore(path)
    store.write({"value": 1})
    store.write({"value": 2})
    path.with_suffix(".json.lock").write_text("stale", encoding="utf-8")
    path.with_suffix(".json.stale.tmp").write_text("partial", encoding="utf-8")
    path.write_text("{broken", encoding="utf-8")

    assert store.read() == {"value": 1}
    store.update(lambda data: {"value": data["value"] + 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 3}


def test_coordinator_releases_task_owned_by_previous_process(tmp_path):
    path = tmp_path / "state.json"
    AtomicJsonStore(path).write({
        "is_running": True,
        "task_id": "old-task",
        "task_type": "prompt_evolution",
        "owner_pid": 99999999,
        "budget_date": "1970-01-01",
        "budget_used": 1,
    })

    status = BackgroundOptimizationCoordinator(path).get_status(now=100)

    assert status["is_running"] is False
    assert status["status"] == "interrupted"


def test_windows_pid_probe_never_uses_os_kill(monkeypatch):
    def fail_if_called(pid: int, signal_number: int) -> None:
        raise AssertionError(f"os.kill must not be called on Windows: {pid}, {signal_number}")

    monkeypatch.setattr(ai_trace_storage.os, "name", "nt")
    monkeypatch.setattr(ai_trace_storage.os, "kill", fail_if_called)
    monkeypatch.setattr(
        BackgroundOptimizationCoordinator,
        "_windows_pid_is_alive",
        staticmethod(lambda pid: pid == 12345),
    )

    assert BackgroundOptimizationCoordinator._pid_is_alive(os.getpid()) is True
    assert BackgroundOptimizationCoordinator._pid_is_alive(12345) is True
    assert BackgroundOptimizationCoordinator._pid_is_alive(54321) is False
