"""
判定器四层校准（设计文档 §3.4 / §14 第 7 步）

用 shadow 阶段积累的已结算实验样本（§14 第 6 步产出），按
全局 → 题材（genre）→ 策略族（strategy_family）→ 挑战者（challenger_id）
四个维度分组聚合 verdict，逐层核对最小样本量与作废率门槛。

某挑战者「四层全过」（全局 + 其题材 + 其策略族 + 其自身分布）→ 判定器在该
挑战者上的误差分布已校准，可从 shadow 推进到 eligible（待人工批准，不参与返回；
eligible → returnable 的开闸属 §14 第 8 步，需人工介入）。

- 逐组 verdict 聚合复用 replay_calibration.compute_replay_consistency（同一作废率口径）；
- 第 4 层是分布一致性检验而非晋升检验：第一版用明确最小样本数 + 同一作废率上限，
  不引入贝叶斯层次模型（§3.4）；
- 状态推进经 experiment_contract.assert_transition 校验合法性，非法转换直接抛错。
"""
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from .challenger_repository import ChallengerRepository
from .experiment_contract import ServingMode
from .experiment_repository import ExperimentRepository
from .replay_calibration import ReplayConsistencyReport, compute_replay_consistency

logger = logging.getLogger(__name__)

# 四层最小样本（§3.4 / §15 配置项默认值：200/50/30/20）
DEFAULT_LAYER1_MIN = 200
DEFAULT_LAYER2_MIN = 50
DEFAULT_LAYER3_MIN = 30
DEFAULT_LAYER4_MIN = 20
DEFAULT_MAX_INVALIDATION_RATE = 0.05


@dataclass(frozen=True)
class CalibrationSample:
    """单条已结算样本的分组键与 verdict"""
    genre: str
    strategy_family: str
    challenger_id: str
    outcome: str


@dataclass(frozen=True)
class CalibrationThresholds:
    layer1_min: int = DEFAULT_LAYER1_MIN
    layer2_min: int = DEFAULT_LAYER2_MIN
    layer3_min: int = DEFAULT_LAYER3_MIN
    layer4_min: int = DEFAULT_LAYER4_MIN
    max_invalidation_rate: float = DEFAULT_MAX_INVALIDATION_RATE

    @classmethod
    def from_env(cls) -> "CalibrationThresholds":
        return cls(
            layer1_min=int(os.getenv("CALIBRATION_MIN_SAMPLES_GLOBAL", str(DEFAULT_LAYER1_MIN))),
            layer2_min=int(os.getenv("CALIBRATION_MIN_SAMPLES_GENRE", str(DEFAULT_LAYER2_MIN))),
            layer3_min=int(os.getenv("CALIBRATION_MIN_SAMPLES_FAMILY", str(DEFAULT_LAYER3_MIN))),
            layer4_min=int(os.getenv("CALIBRATION_MIN_SAMPLES_CHALLENGER", str(DEFAULT_LAYER4_MIN))),
            max_invalidation_rate=float(
                os.getenv("EXPERIMENT_INVALIDATED_RATE_MAX", str(DEFAULT_MAX_INVALIDATION_RATE))
            ),
        )


@dataclass(frozen=True)
class LayerGroupResult:
    key: str                          # 全局为 ""，其余为 genre/strategy_family/challenger_id
    report: ReplayConsistencyReport
    passed: bool


@dataclass(frozen=True)
class LayeredCalibrationReport:
    layer1: LayerGroupResult                    # 全局单组
    layer2: Dict[str, LayerGroupResult]         # genre -> 结果
    layer3: Dict[str, LayerGroupResult]         # strategy_family -> 结果
    layer4: Dict[str, LayerGroupResult]         # challenger_id -> 结果
    challenger_context: Dict[str, Tuple[str, str]]  # challenger_id -> (genre, strategy_family)


def _group_passed(report: ReplayConsistencyReport, min_samples: int, max_rate: float) -> bool:
    """单组是否达标：有效样本充足 且 作废率不越限（与第 1 层同口径）。"""
    return report.effective_total >= min_samples and report.invalidation_rate <= max_rate


def _build_group(key: str, outcomes: Sequence[str], min_samples: int, max_rate: float) -> LayerGroupResult:
    report = compute_replay_consistency(outcomes)
    return LayerGroupResult(key=key, report=report, passed=_group_passed(report, min_samples, max_rate))


def build_layered_calibration(
    samples: Sequence[CalibrationSample],
    thresholds: Optional[CalibrationThresholds] = None,
) -> LayeredCalibrationReport:
    """把一批已结算样本聚合为四层校准报告。"""
    thresholds = thresholds or CalibrationThresholds()
    max_rate = thresholds.max_invalidation_rate

    by_genre: Dict[str, List[str]] = {}
    by_family: Dict[str, List[str]] = {}
    by_challenger: Dict[str, List[str]] = {}
    challenger_context: Dict[str, Tuple[str, str]] = {}
    all_outcomes: List[str] = []

    for s in samples:
        all_outcomes.append(s.outcome)
        by_genre.setdefault(s.genre, []).append(s.outcome)
        by_family.setdefault(s.strategy_family, []).append(s.outcome)
        by_challenger.setdefault(s.challenger_id, []).append(s.outcome)
        challenger_context.setdefault(s.challenger_id, (s.genre, s.strategy_family))

    layer1 = _build_group("", all_outcomes, thresholds.layer1_min, max_rate)
    layer2 = {
        genre: _build_group(genre, outcomes, thresholds.layer2_min, max_rate)
        for genre, outcomes in by_genre.items()
    }
    layer3 = {
        family: _build_group(family, outcomes, thresholds.layer3_min, max_rate)
        for family, outcomes in by_family.items()
    }
    layer4 = {
        cid: _build_group(cid, outcomes, thresholds.layer4_min, max_rate)
        for cid, outcomes in by_challenger.items()
    }
    return LayeredCalibrationReport(
        layer1=layer1,
        layer2=layer2,
        layer3=layer3,
        layer4=layer4,
        challenger_context=challenger_context,
    )


def challenger_unlocked(report: LayeredCalibrationReport, challenger_id: str) -> bool:
    """
    某挑战者是否四层全过：全局 + 其所属题材 + 其所属策略族 + 其自身分布均达标。
    未出现在样本中的挑战者（无 context）判定为未解锁。
    """
    context = report.challenger_context.get(challenger_id)
    if context is None:
        return False
    genre, family = context

    if not report.layer1.passed:
        return False
    genre_result = report.layer2.get(genre)
    if genre_result is None or not genre_result.passed:
        return False
    family_result = report.layer3.get(family)
    if family_result is None or not family_result.passed:
        return False
    challenger_result = report.layer4.get(challenger_id)
    if challenger_result is None or not challenger_result.passed:
        return False
    return True


def eligible_challenger_ids(report: LayeredCalibrationReport) -> List[str]:
    """返回四层全过的挑战者 id（按 id 升序，供确定性推进）。"""
    return sorted(cid for cid in report.layer4 if challenger_unlocked(report, cid))


def promote_calibrated_challengers(
    session: Session,
    *,
    thresholds: Optional[CalibrationThresholds] = None,
    evaluation_policy_version: str,
    light_judge_version: Optional[str] = None,
) -> dict:
    """
    编排：取本策略版本窗口的已结算样本 → 构建四层报告 → 把四层全过且当前仍处
    shadow 的挑战者推进到 eligible（待人工批准）。已在其他状态的挑战者跳过（幂等）。
    """
    thresholds = thresholds or CalibrationThresholds()
    exp_repo = ExperimentRepository(session)
    chal_repo = ChallengerRepository(session)

    rows = exp_repo.list_settlement_samples(evaluation_policy_version, light_judge_version)
    samples = [
        CalibrationSample(genre=genre, strategy_family=family, challenger_id=cid, outcome=outcome)
        for (genre, family, cid, outcome) in rows
    ]
    report = build_layered_calibration(samples, thresholds)

    promoted: List[str] = []
    for cid in eligible_challenger_ids(report):
        row = chal_repo.get_by_challenger_id(cid)
        if row is None or row.serving_mode != ServingMode.SHADOW.value:
            continue  # 仅 shadow → eligible；已推进/其他状态跳过
        chal_repo.update_serving_mode(cid, ServingMode.ELIGIBLE.value)
        promoted.append(cid)

    session.commit()
    return {
        "samples": len(samples),
        "layer1_passed": report.layer1.passed,
        "promoted": promoted,
    }
