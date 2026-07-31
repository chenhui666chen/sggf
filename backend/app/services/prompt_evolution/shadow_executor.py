"""
shadow 实验执行器（设计文档 §5.2 / §5.3 / §5.5 / §7.1 / §14 第 6 步子块 B-2）

编排核心：认领（数据库任务表 + 租约为状态权威）→ 载荷读取 → 挑战者生成
→ AI 检测 → 同步轻判（judge_pair）→ 异步复评（SemanticJudge 风格）
→ verdict 六分类 → 结算（record_settlement + 四维预算 settle + 载荷删除）。

returnable 预置分支（§5.4 / 子块 B）：载荷含 preset_challenger 时跳过重复生成/检测/轻判，
复用同步双路结果只补异步复评；returnable 由风险治理（§5.1），结算不占用/回写 shadow 预算。

外部调用（生成/检测/复评）经 ShadowExecutionDeps 依赖注入：
本模块不直接触碰任何供应商 SDK，真实装配在 Celery 薄壳（experiment_tasks.py），
sqlite + 假函数即可测试全状态机。

降级语义（§5.5）：
- 供应商调用抛异常 → 未达 max_attempts 留 pending（租约到期自动重试），达上限转 dead + 释放预留额；
- 检测/复评"正常返回但不可用" → infrastructure_failure 正常结算（不进胜率分母，触发 cooldown 由上层统计）；
- 载荷缺失/过期、挑战者行缺失 → 不可恢复，直接 dead + 释放预留额。
日志纪律：只落结构化字段与异常类型名，禁止落用户原文。
"""
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptExperiment
from app.services.prompt_evolution.budget_ledger import BudgetLedger
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.experiment_contract import ServingMode
from app.services.prompt_evolution.experiment_privacy import PayloadVault
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.light_judge import check_hard_fail, judge_pair
from app.services.prompt_evolution.review_verdict import (
    async_review_confirms_win,
    classify_verdict,
)

logger = logging.getLogger(__name__)

# 预算维度与 shadow_dispatch._reserve_all_budgets 严格对齐（结算必须回到同一批账本行）
def _budget_scopes(row: PromptExperiment, subject_id: Optional[str]) -> list:
    scopes = [
        ("global", ""),
        ("genre", row.genre),
        ("challenger", row.challenger_id),
    ]
    if subject_id:
        scopes.append(("user", subject_id))
    return scopes


def _budget_date(row: PromptExperiment) -> str:
    """结算必须回到 reserve 当天的账本行（预算按日滚动，跨天结算不得开新行）"""
    created = row.created_at or datetime.now(timezone.utc)
    return created.strftime("%Y-%m-%d")


def _is_budgeted(row: PromptExperiment) -> bool:
    """仅 shadow 行占用/结算实验预算；returnable 由风险治理（§5.1），不碰预算账本。"""
    return row.serving_mode == ServingMode.SHADOW.value


@dataclass(frozen=True)
class ShadowExecutionDeps:
    """执行期外部依赖（全部注入，便于测试与替换供应商）

    - rewrite_fn(prompt_text, original_text, model_id) -> challenger_text：
      挑战者生成，model_id 来自实验行冻结契约（resolved_model_id）；
    - detect_fn(text) -> Optional[float]：AI 检测分，None 表示检测不可用（infra 异常）；
    - review_fn(original, rewritten, genre) -> Mapping：SemanticJudge 风格评审输出。
    """

    rewrite_fn: Callable[[str, str, Optional[str]], str]
    detect_fn: Callable[[str], Optional[float]]
    review_fn: Callable[[str, str, str], Mapping]
    vault: PayloadVault
    estimated_cost: float
    ai_threshold: float
    max_attempts: int = 3


def _release_budgets(session: Session, row: PromptExperiment, deps: ShadowExecutionDeps, subject_id: Optional[str]) -> None:
    ledger = BudgetLedger(session)
    date = _budget_date(row)
    for scope, scope_key in _budget_scopes(row, subject_id):
        ledger.release(date, scope, scope_key, reserved_cost=deps.estimated_cost)


def _settle_budgets(session: Session, row: PromptExperiment, deps: ShadowExecutionDeps, subject_id: Optional[str]) -> None:
    # B-2 暂无真实计费口径，实际花费按预估入账；接入供应商计费后由此处替换
    ledger = BudgetLedger(session)
    date = _budget_date(row)
    for scope, scope_key in _budget_scopes(row, subject_id):
        ledger.settle(
            date, scope, scope_key,
            reserved_cost=deps.estimated_cost, actual_cost=deps.estimated_cost,
        )


def _finalize_dead(
    session: Session,
    row: PromptExperiment,
    deps: ShadowExecutionDeps,
    *,
    error_code: str,
    subject_id: Optional[str],
) -> None:
    """不可恢复失败：转 dead + 释放预留额（仅 shadow 行占预算），同事务提交"""
    ExperimentRepository(session).mark_dead(row.experiment_id, last_error_code=error_code)
    if _is_budgeted(row):
        _release_budgets(session, row, deps, subject_id)
    session.commit()


def execute_experiment(
    session: Session, row: PromptExperiment, deps: ShadowExecutionDeps
) -> str:
    """
    执行单个已认领实验，返回结果标签：
    settled:<outcome> / dead:<error_code> / retry_later。
    调用方（run_shadow_batch）已完成认领与租约续期，本函数负责其后全部环节。
    """
    repo = ExperimentRepository(session)

    # 载荷读取（过期/丢失为不可恢复：原文已不可得，无法重试）
    payload_raw = deps.vault.get(row.payload_ref) if row.payload_ref else None
    if payload_raw is None:
        _finalize_dead(session, row, deps, error_code="payload_missing", subject_id=None)
        return "dead:payload_missing"
    payload = json.loads(payload_raw)
    subject_id = payload.get("subject_id")
    original_text = payload.get("original_text", "")
    champion_text = payload.get("champion_text", "")
    champion_ai_score = payload.get("champion_ai_score")
    # returnable 落库会预置同步双路结果（子块 B）：命中则跳过重复生成，只补异步复评
    preset = payload.get("preset_challenger")

    challenger = ChallengerRepository(session).get_by_challenger_id(row.challenger_id)
    if challenger is None:
        _finalize_dead(session, row, deps, error_code="challenger_missing", subject_id=subject_id)
        return "dead:challenger_missing"

    # 供应商调用段：异常走重试/死信，不落原文
    try:
        if preset is not None:
            # 预置分支：复用同步双路结果，不重复调用供应商生成/检测
            challenger_text = preset.get("challenger_text", "")
            challenger_ai_score = preset.get("challenger_ai_score")
        else:
            model_id = row.resolved_model_id if row.resolved_model_id != "default_route" else None
            challenger_text = deps.rewrite_fn(challenger.prompt_text, original_text, model_id)
            challenger_ai_score = deps.detect_fn(challenger_text)
        infra_ok = challenger_ai_score is not None

        challenger_review: Mapping = {}
        champion_review: Mapping = {}
        if infra_ok:
            challenger_review = deps.review_fn(original_text, challenger_text, row.genre)
            champion_review = deps.review_fn(original_text, champion_text, row.genre)
            if not (
                challenger_review.get("available", False)
                and champion_review.get("available", False)
            ):
                infra_ok = False
    except Exception as exc:  # noqa: BLE001 —— 供应商异常：重试或死信
        session.rollback()
        if row.attempt_count >= deps.max_attempts:
            _finalize_dead(
                session, row, deps,
                error_code=f"max_attempts:{type(exc).__name__}", subject_id=subject_id,
            )
            return f"dead:max_attempts:{type(exc).__name__}"
        logger.warning(
            "shadow 实验执行异常，留待重试: experiment_id=%s, attempt=%d, type=%s",
            row.experiment_id, row.attempt_count, type(exc).__name__,
        )
        session.commit()  # 保留认领时的租约与 attempt_count
        return "retry_later"

    # 同步轻判 + 异步复评归类（供应商不可用时跳过判定，直接 infra verdict）
    if infra_ok:
        if preset is not None:
            # 复用同步阶段已计算的轻判结果与择优结论
            light_result = preset.get("light_judge_result") or {}
            returned_variant = preset.get("returned_variant")
            returned_challenger = returned_variant == "challenger"
        else:
            light = judge_pair(
                original_text=original_text,
                champion_text=champion_text,
                challenger_text=challenger_text,
                champion_ai_score=champion_ai_score,
                challenger_ai_score=challenger_ai_score,
                ai_threshold=deps.ai_threshold,
            )
            light_result = asdict(light)
            returned_variant = light.returned_variant
            returned_challenger = light.returned_variant == "challenger"
        chal_hard = check_hard_fail(
            text=challenger_text, reference_text=original_text,
            ai_score=challenger_ai_score, ai_threshold=deps.ai_threshold,
            content_safety_passed=True,
        )
        # challenger_hard_fail 只取同步硬门槛；异步复评不通过由 async_confirms_win=False
        # 归入 invalidated_win（判定器误判，计入作废率监控，§7.1），不与质量硬失败混淆
        verdict = classify_verdict(
            returned_challenger=returned_challenger,
            infra_ok=True,
            challenger_hard_fail=chal_hard.failed,
            async_reviewed=True,
            async_confirms_win=async_review_confirms_win(challenger_review, champion_review),
        )
    else:
        verdict = classify_verdict(returned_challenger=False, infra_ok=False)
        light_result = {}
        returned_variant = None

    repo.record_settlement(
        row.experiment_id,
        light_judge_result=light_result,
        returned_variant=returned_variant,
        async_review_result={
            "challenger": dict(challenger_review),
            "champion": dict(champion_review),
        },
        outcome=verdict,
        champion_ai_score=champion_ai_score,
    )
    if _is_budgeted(row):
        _settle_budgets(session, row, deps, subject_id)
    session.commit()
    # 处理完成立即删除载荷（§10；失败不影响结算，TTL 兜底）
    try:
        deps.vault.delete(row.payload_ref)
    except Exception:  # noqa: BLE001
        logger.warning("载荷删除失败（TTL 兜底）: experiment_id=%s", row.experiment_id)
    return f"settled:{verdict}"


def run_shadow_batch(
    session: Session,
    deps: ShadowExecutionDeps,
    *,
    now: Optional[datetime] = None,
    limit: int = 5,
    lease_seconds: int = 600,
) -> dict:
    """
    批处理入口（beat 轮询调用）：认领至多 limit 个 pending 实验并逐个执行。
    认领（租约续期）先行提交，防止执行中崩溃丢失认领记录；
    单个实验失败不影响批内其它实验。
    """
    now = now or datetime.now(timezone.utc)
    rows = ExperimentRepository(session).claim_next(
        now=now, lease_seconds=lease_seconds, limit=limit
    )
    session.commit()

    stats = {"claimed": len(rows), "settled": 0, "dead": 0, "retry": 0}
    for row in rows:
        outcome = execute_experiment(session, row, deps)
        if outcome.startswith("settled:"):
            stats["settled"] += 1
        elif outcome.startswith("dead:"):
            stats["dead"] += 1
        else:
            stats["retry"] += 1
    logger.info(
        "shadow 批处理完成: claimed=%d, settled=%d, dead=%d, retry=%d",
        stats["claimed"], stats["settled"], stats["dead"], stats["retry"],
    )
    return stats
