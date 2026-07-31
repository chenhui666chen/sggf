"""
异步权威评审 verdict 六分类测试（设计文档 §7.1 / §14 第 5 步）

verdict 是对"挑战者这一场"的终态标注：
  provisional_win / confirmed_win / invalidated_win / loss /
  hard_failure / infrastructure_failure
纯映射函数，无 IO / 无外部 API。
"""
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_HARD_FAILURE,
    VERDICT_INFRASTRUCTURE_FAILURE,
    VERDICT_INVALIDATED_WIN,
    VERDICT_LOSS,
    VERDICT_PROVISIONAL_WIN,
    ALL_VERDICTS,
    async_review_confirms_win,
    async_review_hard_fail,
    classify_verdict,
)


# ---------------------------------------------------------------------------
# classify_verdict：优先级 infrastructure > hard_failure > win 分支 > loss
# ---------------------------------------------------------------------------
def _kwargs(**overrides):
    base = dict(
        returned_challenger=True,
        infra_ok=True,
        challenger_hard_fail=False,
        async_reviewed=True,
        async_confirms_win=True,
    )
    base.update(overrides)
    return base


def test_all_verdicts_are_distinct_strings():
    assert len(set(ALL_VERDICTS)) == 6
    assert VERDICT_PROVISIONAL_WIN in ALL_VERDICTS
    assert VERDICT_INFRASTRUCTURE_FAILURE in ALL_VERDICTS


def test_infrastructure_failure_has_highest_priority():
    # 即使同步判胜、异步确认，只要基础设施异常一律记 infrastructure_failure
    result = classify_verdict(**_kwargs(infra_ok=False))
    assert result == VERDICT_INFRASTRUCTURE_FAILURE


def test_infrastructure_failure_overrides_hard_fail():
    result = classify_verdict(**_kwargs(infra_ok=False, challenger_hard_fail=True))
    assert result == VERDICT_INFRASTRUCTURE_FAILURE


def test_hard_failure_when_challenger_hard_fail():
    result = classify_verdict(**_kwargs(challenger_hard_fail=True))
    assert result == VERDICT_HARD_FAILURE


def test_hard_failure_overrides_win():
    # 同步返回挑战者，但异步发现硬失败 → 记质量硬失败
    result = classify_verdict(
        **_kwargs(returned_challenger=True, challenger_hard_fail=True, async_confirms_win=True)
    )
    assert result == VERDICT_HARD_FAILURE


def test_provisional_win_when_not_reviewed():
    result = classify_verdict(**_kwargs(returned_challenger=True, async_reviewed=False))
    assert result == VERDICT_PROVISIONAL_WIN


def test_confirmed_win():
    result = classify_verdict(
        **_kwargs(returned_challenger=True, async_reviewed=True, async_confirms_win=True)
    )
    assert result == VERDICT_CONFIRMED_WIN


def test_invalidated_win():
    # 同步判胜，异步作废 → 判定器误判
    result = classify_verdict(
        **_kwargs(returned_challenger=True, async_reviewed=True, async_confirms_win=False)
    )
    assert result == VERDICT_INVALIDATED_WIN


def test_loss_when_champion_returned():
    # 同步未判挑战者胜（返回冠军），非硬失败 → 挑战者败场
    result = classify_verdict(**_kwargs(returned_challenger=False))
    assert result == VERDICT_LOSS


def test_loss_ignores_async_confirm_flag():
    # 返回冠军时，async_confirms_win 不影响结果（当场就是 loss）
    result = classify_verdict(
        **_kwargs(returned_challenger=False, async_reviewed=True, async_confirms_win=True)
    )
    assert result == VERDICT_LOSS


# ---------------------------------------------------------------------------
# async_review_hard_fail：从 SemanticJudge 风格输出派生硬失败
# ---------------------------------------------------------------------------
def _review(**overrides):
    base = dict(
        available=True,
        hard_fail=False,
        fidelity=91.0,
        fact=95.0,
        completeness=88.0,
        over_rewrite_risk="low",
        confidence=0.8,
    )
    base.update(overrides)
    return base


def test_async_hard_fail_when_review_flags_it():
    assert async_review_hard_fail(_review(hard_fail=True)) is True


def test_async_hard_fail_when_fidelity_below_gate():
    assert async_review_hard_fail(_review(fidelity=70.0)) is True


def test_async_hard_fail_when_fact_below_gate():
    assert async_review_hard_fail(_review(fact=80.0)) is True


def test_async_hard_fail_when_completeness_below_gate():
    assert async_review_hard_fail(_review(completeness=60.0)) is True


def test_async_hard_fail_when_over_rewrite_high():
    assert async_review_hard_fail(_review(over_rewrite_risk="high")) is True


def test_async_hard_fail_when_low_confidence():
    assert async_review_hard_fail(_review(confidence=0.4)) is True


def test_async_hard_fail_false_when_all_pass():
    assert async_review_hard_fail(_review()) is False


def test_async_hard_fail_true_when_unavailable():
    # 评审不可用 → 无法判定，视为需要人工/基础设施问题，不放行
    assert async_review_hard_fail(_review(available=False)) is True


# ---------------------------------------------------------------------------
# async_review_confirms_win：挑战者是否被异步确认优于冠军
# ---------------------------------------------------------------------------
def test_confirms_win_true_when_challenger_scores_higher():
    challenger = _review(fidelity=92.0, fact=96.0, completeness=90.0)
    champion = _review(fidelity=88.0, fact=93.0, completeness=85.0)
    assert async_review_confirms_win(challenger, champion) is True


def test_confirms_win_false_when_challenger_not_better():
    challenger = _review(fidelity=85.0, fact=92.0, completeness=84.0)
    champion = _review(fidelity=90.0, fact=95.0, completeness=88.0)
    assert async_review_confirms_win(challenger, champion) is False


def test_confirms_win_false_when_challenger_hard_fail():
    challenger = _review(hard_fail=True, fidelity=99.0, fact=99.0, completeness=99.0)
    champion = _review(fidelity=88.0, fact=93.0, completeness=85.0)
    assert async_review_confirms_win(challenger, champion) is False
