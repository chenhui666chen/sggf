"""
进化自动启停调度纯逻辑（设计文档 §11 · §14 第 10 步 · 子块 A）

三态（运行中 / 休眠 / 被唤醒）+ 休眠门槛（§11.1）+ 唤醒门槛（§11.2 风险不对称）
+ 滞回与状态转移（§11.3 开关阈值分离防抖动）。纯逻辑测试：全部信号为
dataclass 快照入参，不触 DB、不接 Celery、不接外部 API，确定性验证。
"""
import pytest

from app.services.prompt_evolution.evolution_scheduler import (
    STATE_AWAKE,
    STATE_RUNNING,
    STATE_SLEEPING,
    SchedulerThresholds,
    SleepSignals,
    WakeSignals,
    decide_next_state,
    evaluate_sleep_gate,
    evaluate_wake_gate,
)


# ---------------- SchedulerThresholds ----------------

def test_thresholds_defaults():
    t = SchedulerThresholds()
    assert t.convergence_batches == 3
    assert t.min_batch_improvement == pytest.approx(2.0)
    assert t.max_holdout_score_gap == pytest.approx(5.0)
    assert t.wake_ai_score_rise == pytest.approx(8.0)
    assert t.wake_fidelity_drop == pytest.approx(5.0)
    assert t.wake_challenger_wilson_lower_bound == pytest.approx(0.55)


def test_thresholds_from_env(monkeypatch):
    monkeypatch.setenv("EVOLUTION_CONVERGENCE_BATCHES", "4")
    monkeypatch.setenv("EVOLUTION_MIN_BATCH_IMPROVEMENT", "1.5")
    monkeypatch.setenv("EVOLUTION_MAX_HOLDOUT_SCORE_GAP", "6.0")
    monkeypatch.setenv("EVOLUTION_WAKE_AI_SCORE_RISE", "10.0")
    monkeypatch.setenv("EVOLUTION_WAKE_FIDELITY_DROP", "7.0")
    monkeypatch.setenv("EVOLUTION_WAKE_CHALLENGER_WILSON", "0.60")
    t = SchedulerThresholds.from_env()
    assert t.convergence_batches == 4
    assert t.min_batch_improvement == pytest.approx(1.5)
    assert t.max_holdout_score_gap == pytest.approx(6.0)
    assert t.wake_ai_score_rise == pytest.approx(10.0)
    assert t.wake_fidelity_drop == pytest.approx(7.0)
    assert t.wake_challenger_wilson_lower_bound == pytest.approx(0.60)


# ---------------- evaluate_sleep_gate（§11.1 休眠门槛） ----------------

def _running_signals(**overrides):
    """默认为「不该休眠」的活跃信号，测试按需覆盖。"""
    base = dict(
        converged=False,
        recent_improvements=[5.0, 4.0, 3.0],
        holdout_score_gap=1.0,
        budget_exhausted=False,
    )
    base.update(overrides)
    return SleepSignals(**base)


def test_sleep_gate_all_active_does_not_sleep():
    result = evaluate_sleep_gate(_running_signals())
    assert result.should_sleep is False
    assert result.reasons == []


def test_sleep_gate_budget_exhausted_forces_sleep():
    # 预算触顶独立触发（§11.1 第三行），无视达标与否
    result = evaluate_sleep_gate(_running_signals(budget_exhausted=True))
    assert result.should_sleep is True
    assert "budget_exhausted" in result.reasons


def test_sleep_gate_converged_marginal_exhausted_sleeps():
    # 达标 + 连续 3 批提升 < 2 分 + holdout 分差 < 阈值 → 休眠
    result = evaluate_sleep_gate(
        _running_signals(
            converged=True,
            recent_improvements=[1.8, 1.2, 0.5],
            holdout_score_gap=1.0,
        )
    )
    assert result.should_sleep is True
    assert "marginal_gain_exhausted" in result.reasons


def test_sleep_gate_not_converged_stays_running():
    # 未达标即使提升枯竭也不休眠
    result = evaluate_sleep_gate(
        _running_signals(
            converged=False,
            recent_improvements=[1.0, 0.5, 0.3],
            holdout_score_gap=1.0,
        )
    )
    assert result.should_sleep is False
    assert "marginal_gain_exhausted" not in result.reasons


def test_sleep_gate_improvement_not_exhausted_stays_running():
    # 达标但最近有一批提升 >= 2 分，边际未枯竭
    result = evaluate_sleep_gate(
        _running_signals(
            converged=True,
            recent_improvements=[1.0, 3.0, 0.5],
            holdout_score_gap=1.0,
        )
    )
    assert result.should_sleep is False


def test_sleep_gate_insufficient_batches_stays_running():
    # 批次数不足 convergence_batches，不能判定边际枯竭
    result = evaluate_sleep_gate(
        _running_signals(
            converged=True,
            recent_improvements=[0.5, 0.3],
            holdout_score_gap=1.0,
        )
    )
    assert result.should_sleep is False


def test_sleep_gate_holdout_gap_blocks_overfit_sleep():
    # 达标 + 边际枯竭，但 holdout 分差过大（过拟合假象），阻止带水分入眠（§11.1 第二行）
    result = evaluate_sleep_gate(
        _running_signals(
            converged=True,
            recent_improvements=[1.0, 0.5, 0.3],
            holdout_score_gap=9.0,
        )
    )
    assert result.should_sleep is False
    assert "marginal_gain_exhausted" not in result.reasons


def test_sleep_gate_budget_and_marginal_both_reported():
    result = evaluate_sleep_gate(
        _running_signals(
            converged=True,
            recent_improvements=[1.0, 0.5, 0.3],
            holdout_score_gap=1.0,
            budget_exhausted=True,
        )
    )
    assert result.should_sleep is True
    assert "budget_exhausted" in result.reasons
    assert "marginal_gain_exhausted" in result.reasons


# ---------------- evaluate_wake_gate（§11.2 唤醒门槛，风险不对称 OR） ----------------

def _quiet_signals(**overrides):
    """默认为「无需唤醒」的平静信号，测试按需覆盖。"""
    base = dict(
        champion_ai_score_rise=0.0,
        champion_fidelity_drop=0.0,
        best_challenger_wilson_lower_bound=0.0,
        environment_changed=False,
        sentinel_degraded=False,
    )
    base.update(overrides)
    return WakeSignals(**base)


def test_wake_gate_quiet_does_not_wake():
    result = evaluate_wake_gate(_quiet_signals())
    assert result.should_wake is False
    assert result.reasons == []


def test_wake_gate_champion_ai_degraded():
    result = evaluate_wake_gate(_quiet_signals(champion_ai_score_rise=9.0))
    assert result.should_wake is True
    assert "champion_ai_degraded" in result.reasons


def test_wake_gate_champion_fidelity_drop():
    result = evaluate_wake_gate(_quiet_signals(champion_fidelity_drop=6.0))
    assert result.should_wake is True
    assert "champion_fidelity_drop" in result.reasons


def test_wake_gate_challenger_overtook():
    result = evaluate_wake_gate(_quiet_signals(best_challenger_wilson_lower_bound=0.60))
    assert result.should_wake is True
    assert "challenger_overtook" in result.reasons


def test_wake_gate_environment_changed():
    result = evaluate_wake_gate(_quiet_signals(environment_changed=True))
    assert result.should_wake is True
    assert "environment_changed" in result.reasons


def test_wake_gate_sentinel_degraded():
    result = evaluate_wake_gate(_quiet_signals(sentinel_degraded=True))
    assert result.should_wake is True
    assert "sentinel_degraded" in result.reasons


def test_wake_gate_multiple_signals_all_reported():
    result = evaluate_wake_gate(
        _quiet_signals(
            champion_ai_score_rise=9.0,
            environment_changed=True,
        )
    )
    assert result.should_wake is True
    assert "champion_ai_degraded" in result.reasons
    assert "environment_changed" in result.reasons


def test_wake_gate_hysteresis_buffer_below_threshold():
    # 滞回缓冲带（§11.3）：AI 率回升 5 分 < 8 分、保真降 3 分 < 5 分，均不唤醒
    result = evaluate_wake_gate(
        _quiet_signals(champion_ai_score_rise=5.0, champion_fidelity_drop=3.0)
    )
    assert result.should_wake is False


# ---------------- decide_next_state（§11.3 三态转移 + 滞回） ----------------

def test_running_stays_running_when_no_sleep():
    decision = decide_next_state(
        STATE_RUNNING,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(),
    )
    assert decision.next_state == STATE_RUNNING
    assert decision.changed is False


def test_running_transitions_to_sleeping():
    decision = decide_next_state(
        STATE_RUNNING,
        sleep_signals=_running_signals(budget_exhausted=True),
        wake_signals=_quiet_signals(),
    )
    assert decision.next_state == STATE_SLEEPING
    assert decision.changed is True
    assert "budget_exhausted" in decision.reasons


def test_sleeping_stays_sleeping_when_no_wake():
    decision = decide_next_state(
        STATE_SLEEPING,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(),
    )
    assert decision.next_state == STATE_SLEEPING
    assert decision.changed is False


def test_sleeping_transitions_to_awake():
    decision = decide_next_state(
        STATE_SLEEPING,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(champion_ai_score_rise=9.0),
    )
    assert decision.next_state == STATE_AWAKE
    assert decision.changed is True
    assert "champion_ai_degraded" in decision.reasons


def test_awake_transitions_to_running():
    # 被唤醒态一经消费即重启进化（定向进化），转回运行中
    decision = decide_next_state(
        STATE_AWAKE,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(),
    )
    assert decision.next_state == STATE_RUNNING
    assert decision.changed is True


def test_running_ignores_wake_signals():
    # 运行中只判休眠、不看唤醒（已在进化，唤醒无意义）——滞回隔离
    decision = decide_next_state(
        STATE_RUNNING,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(champion_ai_score_rise=9.0),
    )
    assert decision.next_state == STATE_RUNNING
    assert decision.changed is False


def test_sleeping_hysteresis_minor_fluctuation_stays_asleep():
    # 休眠期小幅波动（AI 率回升 5 分 < 8 分阈值）落在缓冲带内，不唤醒
    decision = decide_next_state(
        STATE_SLEEPING,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(champion_ai_score_rise=5.0),
    )
    assert decision.next_state == STATE_SLEEPING
    assert decision.changed is False


def test_decide_uses_custom_thresholds():
    # 自定义阈值：唤醒 AI 率门槛降到 4 分，则 5 分回升即唤醒
    thresholds = SchedulerThresholds(wake_ai_score_rise=4.0)
    decision = decide_next_state(
        STATE_SLEEPING,
        sleep_signals=_running_signals(),
        wake_signals=_quiet_signals(champion_ai_score_rise=5.0),
        thresholds=thresholds,
    )
    assert decision.next_state == STATE_AWAKE
    assert decision.changed is True
