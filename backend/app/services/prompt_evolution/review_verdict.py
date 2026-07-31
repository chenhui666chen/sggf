"""
异步权威评审 verdict 六分类（设计文档 §7.1 / §14 第 5 步）

纯映射逻辑：把同步判定结果 + 异步权威评审输出，归约为对挑战者这一场的终态标注，
供晋升统计（只用 confirmed_win）与作废率监控（invalidated_win）使用。

不接外部 API：异步评审的原始分数由上游（复用 SemanticJudge）产出后传入，
本模块只做确定性归类，便于离线回放验证一致率。
"""
from typing import Mapping

# 六分类（§7.1）
VERDICT_PROVISIONAL_WIN = "provisional_win"          # 同步判胜，待异步确认
VERDICT_CONFIRMED_WIN = "confirmed_win"              # 异步确认的胜场（晋升唯一口径）
VERDICT_INVALIDATED_WIN = "invalidated_win"          # 同步判胜被异步作废（判定器误判）
VERDICT_LOSS = "loss"                                # 确认败场
VERDICT_HARD_FAILURE = "hard_failure"                # 质量硬失败
VERDICT_INFRASTRUCTURE_FAILURE = "infrastructure_failure"  # 供应商超时/检测异常

ALL_VERDICTS = (
    VERDICT_PROVISIONAL_WIN,
    VERDICT_CONFIRMED_WIN,
    VERDICT_INVALIDATED_WIN,
    VERDICT_LOSS,
    VERDICT_HARD_FAILURE,
    VERDICT_INFRASTRUCTURE_FAILURE,
)

# 异步权威评审硬门槛（与 SemanticJudge 内置门槛一致）
_REVIEW_FIDELITY_GATE = 80.0
_REVIEW_FACT_GATE = 90.0
_REVIEW_COMPLETENESS_GATE = 75.0
_REVIEW_CONFIDENCE_GATE = 0.6


def classify_verdict(
    *,
    returned_challenger: bool,
    infra_ok: bool = True,
    challenger_hard_fail: bool = False,
    async_reviewed: bool = False,
    async_confirms_win: bool = False,
) -> str:
    """
    归类挑战者这一场的终态。优先级（高到低）：
      基础设施异常 > 质量硬失败 > 同步判胜分支 > 败场
    """
    # 1. 基础设施异常最高优先：不进胜率分母，触发 cooldown（§5.5）
    if not infra_ok:
        return VERDICT_INFRASTRUCTURE_FAILURE

    # 2. 质量硬失败（同步或异步任一命中）
    if challenger_hard_fail:
        return VERDICT_HARD_FAILURE

    # 3. 同步判挑战者胜
    if returned_challenger:
        if not async_reviewed:
            return VERDICT_PROVISIONAL_WIN
        return VERDICT_CONFIRMED_WIN if async_confirms_win else VERDICT_INVALIDATED_WIN

    # 4. 同步返回冠军（挑战者当场未胜）→ 败场
    return VERDICT_LOSS


def async_review_hard_fail(review: Mapping) -> bool:
    """
    从 SemanticJudge 风格输出派生异步硬失败。
    评审不可用（available=False）视为无法判定，不予放行。
    """
    if not review.get("available", False):
        return True
    if review.get("hard_fail", False):
        return True
    if float(review.get("fidelity", 0.0)) < _REVIEW_FIDELITY_GATE:
        return True
    if float(review.get("fact", 0.0)) < _REVIEW_FACT_GATE:
        return True
    if float(review.get("completeness", 0.0)) < _REVIEW_COMPLETENESS_GATE:
        return True
    if str(review.get("over_rewrite_risk", "low")).lower() == "high":
        return True
    if float(review.get("confidence", 1.0)) < _REVIEW_CONFIDENCE_GATE:
        return True
    return False


def _review_aggregate(review: Mapping) -> float:
    """三大保真类维度求和，作为挑战者相对冠军的整体质量代理。"""
    return (
        float(review.get("fidelity", 0.0))
        + float(review.get("fact", 0.0))
        + float(review.get("completeness", 0.0))
    )


def async_review_confirms_win(challenger_review: Mapping, champion_review: Mapping) -> bool:
    """
    异步是否确认挑战者优于冠军：挑战者不得硬失败，且整体质量严格高于冠军。
    """
    if async_review_hard_fail(challenger_review):
        return False
    return _review_aggregate(challenger_review) > _review_aggregate(champion_review)
