"""
实验任务仓储（设计文档 §5.2 / §6.2 / §14 第 6 步）

prompt_experiments 表的持久化与状态机推进。数据库任务表 + 租约为状态权威，
Celery 仅作无状态执行器（认领 → 执行 → 写回）。

一致性契约（§6.2）：
- 幂等靠唯一约束 (request_id, challenger_id, evaluation_policy_version)，防复评晚到重复结算；
- 状态转换可重入（advance_status 仅当处于期望前态才推进，重复调用为幂等空操作）；
- 事务边界由调用方（Celery 任务体 / 路由）掌控，本层只 flush 不 commit。

纯持久化层：不接 Celery、不调外部 API、不碰 /ai-trace 请求路径。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptChallenger, PromptExperiment

logger = logging.getLogger(__name__)

# 状态机（§5.2）：pending → generating → detecting → light_judging → reviewing → settled；异常终态 dead
STATUS_PENDING = "pending"
STATUS_SETTLED = "settled"
STATUS_DEAD = "dead"

# 终态不可覆写：晚到的重试/复评对终态行一律幂等空操作
_TERMINAL_STATUSES = (STATUS_SETTLED, STATUS_DEAD)


class ExperimentRepository:
    """实验任务仓储（prompt_experiments 表）"""

    def __init__(self, session: Session):
        self.session = session

    def get_by_experiment_id(self, experiment_id: str) -> Optional[PromptExperiment]:
        return (
            self.session.query(PromptExperiment)
            .filter(PromptExperiment.experiment_id == experiment_id)
            .one_or_none()
        )

    def find_settlement(
        self, request_id: str, challenger_id: str, evaluation_policy_version: str
    ) -> Optional[PromptExperiment]:
        """按结算幂等键查询既有行（唯一约束三元组）"""
        return (
            self.session.query(PromptExperiment)
            .filter(
                PromptExperiment.request_id == request_id,
                PromptExperiment.challenger_id == challenger_id,
                PromptExperiment.evaluation_policy_version == evaluation_policy_version,
            )
            .one_or_none()
        )

    def create_experiment(
        self,
        *,
        experiment_id: str,
        request_id: str,
        challenger_id: str,
        genre: str,
        champion_id: str,
        assignment_bucket: int,
        serving_mode: str,
        resolved_model_id: str,
        model_selection_source: str,
        prompt_version_id: str,
        provider_parameters_hash: str,
        light_judge_version: str,
        evaluation_policy_version: str,
        champion_prompt_hash: str,
        challenger_prompt_hash: str,
        payload_ref: Optional[str] = None,
        payload_expires_at: Optional[datetime] = None,
        model_config_version: Optional[str] = None,
        async_review_prompt_version: Optional[str] = None,
        async_review_model_id: Optional[str] = None,
        detector_provider: Optional[str] = None,
        detector_version: Optional[str] = None,
        model_catalog_version: Optional[str] = None,
    ) -> PromptExperiment:
        """
        创建 pending 实验行，幂等 on (request_id, challenger_id, evaluation_policy_version)。
        重复创建（复评晚到 / 批次重跑）返回既有行，不产生第二条。

        并发说明：check-then-insert 存在竞态窗口，数据正确性由唯一约束
        uq_prompt_experiments_settlement 兜底；并发双插时后提交方会收到
        IntegrityError，调用方应回滚后重查（按结算键必得既有行）。
        """
        existing = self.find_settlement(request_id, challenger_id, evaluation_policy_version)
        if existing is not None:
            return existing

        row = PromptExperiment(
            experiment_id=experiment_id,
            request_id=request_id,
            challenger_id=challenger_id,
            genre=genre,
            status=STATUS_PENDING,
            attempt_count=0,
            payload_ref=payload_ref,
            payload_expires_at=payload_expires_at,
            champion_id=champion_id,
            assignment_bucket=assignment_bucket,
            serving_mode=serving_mode,
            resolved_model_id=resolved_model_id,
            model_selection_source=model_selection_source,
            model_config_version=model_config_version,
            prompt_version_id=prompt_version_id,
            provider_parameters_hash=provider_parameters_hash,
            light_judge_version=light_judge_version,
            evaluation_policy_version=evaluation_policy_version,
            async_review_prompt_version=async_review_prompt_version,
            async_review_model_id=async_review_model_id,
            detector_provider=detector_provider,
            detector_version=detector_version,
            champion_prompt_hash=champion_prompt_hash,
            challenger_prompt_hash=challenger_prompt_hash,
            model_catalog_version=model_catalog_version,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def claim_next(
        self,
        *,
        now: datetime,
        lease_seconds: int,
        statuses: tuple = (STATUS_PENDING,),
        limit: int = 1,
    ) -> List[PromptExperiment]:
        """
        认领待处理任务：status ∈ statuses 且租约为空或已过期（now 之前）。
        为认领行续租（lease_until = now + lease_seconds）并递增 attempt_count。
        行级锁 FOR UPDATE SKIP LOCKED 保证多 worker 并发认领互斥
        （sqlite 方言忽略该子句，不影响单测）。
        调用方应统一传时区感知的 UTC now，避免与 timestamptz 列混用 naive 时间。
        """
        rows = (
            self.session.query(PromptExperiment)
            .filter(
                PromptExperiment.status.in_(statuses),
                or_(
                    PromptExperiment.lease_until.is_(None),
                    PromptExperiment.lease_until < now,
                ),
            )
            .order_by(PromptExperiment.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        for row in rows:
            row.lease_until = now + timedelta(seconds=lease_seconds)
            row.attempt_count += 1
            if row.started_at is None:
                row.started_at = now
        self.session.flush()
        return rows

    def advance_status(
        self, experiment_id: str, *, expected_status: str, new_status: str
    ) -> bool:
        """
        可重入状态转换：仅当当前 status == expected_status 才推进。
        返回是否发生转换（已越过前态 → False 幂等空操作）。
        """
        row = self.get_by_experiment_id(experiment_id)
        if row is None or row.status != expected_status:
            return False
        row.status = new_status
        self.session.flush()
        return True

    def record_settlement(
        self,
        experiment_id: str,
        *,
        light_judge_result: dict,
        returned_variant: Optional[str],
        async_review_result: dict,
        outcome: str,
        latency_ms: Optional[dict] = None,
        cost: Optional[dict] = None,
        finished_at: Optional[datetime] = None,
        champion_ai_score: Optional[float] = None,
    ) -> PromptExperiment:
        """写回四段结果并转终态 settled。终态行（settled/dead）幂等空操作，防晚到重复结算覆盖 outcome。"""
        row = self.get_by_experiment_id(experiment_id)
        if row is None:
            raise ValueError(f"实验不存在: {experiment_id}")
        if row.status in _TERMINAL_STATUSES:
            return row
        row.light_judge_result = light_judge_result or {}
        row.returned_variant = returned_variant
        row.async_review_result = async_review_result or {}
        row.outcome = outcome
        if latency_ms is not None:
            row.latency_ms = latency_ms
        if cost is not None:
            row.cost = cost
        if champion_ai_score is not None:
            row.champion_ai_score = champion_ai_score
        row.status = STATUS_SETTLED
        row.lease_until = None
        row.finished_at = finished_at or datetime.now(timezone.utc)
        self.session.flush()
        return row

    def list_settlement_samples(
        self, evaluation_policy_version: str, light_judge_version: Optional[str] = None
    ) -> List[tuple]:
        """
        取某评审策略版本窗口内的已结算样本，供四层校准（§3.4 / §14 第 7 步）分组聚合。

        联 prompt_challengers 取 strategy_family（策略族只存在挑战者行），返回
        (genre, strategy_family, challenger_id, outcome) 四元组列表。
        仅取 status=settled 且 outcome 非空的行；不跨 evaluation_policy_version 聚合（§8.1 硬闸门 #4）。
        """
        query = (
            self.session.query(
                PromptExperiment.genre,
                PromptChallenger.strategy_family,
                PromptExperiment.challenger_id,
                PromptExperiment.outcome,
            )
            .join(
                PromptChallenger,
                PromptChallenger.challenger_id == PromptExperiment.challenger_id,
            )
            .filter(
                PromptExperiment.status == STATUS_SETTLED,
                PromptExperiment.evaluation_policy_version == evaluation_policy_version,
                PromptExperiment.outcome.isnot(None),
            )
        )
        if light_judge_version is not None:
            query = query.filter(PromptExperiment.light_judge_version == light_judge_version)
        return query.all()

    def list_recent_returnable_outcomes(
        self, evaluation_policy_version: str, since: datetime
    ) -> List[str]:
        """
        运行期熔断窗口样本（§5.4）：仅 returnable 场景 + finished_at >= since 的
        已结算 outcome 列表。

        与 list_settlement_samples（四层校准用，全生命周期、含 shadow）刻意分开：
        熔断监控的是"当下 returnable 链路的判定器可靠性"，shadow 样本（ε 量级碾压）
        会稀释信号，历史样本会淹没近期退化。finished_at 为空的行自动排除。
        """
        query = self.session.query(PromptExperiment.outcome).filter(
            PromptExperiment.status == STATUS_SETTLED,
            PromptExperiment.evaluation_policy_version == evaluation_policy_version,
            PromptExperiment.outcome.isnot(None),
            PromptExperiment.serving_mode == "returnable",
            PromptExperiment.finished_at >= since,
        )
        return [row[0] for row in query.all()]

    def list_outcomes_for_challenger(
        self,
        challenger_id: str,
        evaluation_policy_version: str,
        light_judge_version: Optional[str] = None,
    ) -> List[str]:
        """
        取某挑战者在指定评审策略版本窗口内的已结算 verdict 序列，供晋升统计
        （§8 · promotion.aggregate_challenger_stats）聚合。

        仅取 status=settled 且 outcome 非空的行；不跨 evaluation_policy_version 聚合
        （§8.1 硬闸门 #4）。返回 outcome 字符串列表（顺序无关，聚合只看计数）。
        """
        query = (
            self.session.query(PromptExperiment.outcome)
            .filter(
                PromptExperiment.challenger_id == challenger_id,
                PromptExperiment.status == STATUS_SETTLED,
                PromptExperiment.evaluation_policy_version == evaluation_policy_version,
                PromptExperiment.outcome.isnot(None),
            )
        )
        if light_judge_version is not None:
            query = query.filter(PromptExperiment.light_judge_version == light_judge_version)
        return [row[0] for row in query.all()]

    def list_champion_reviews(
        self,
        genre: str,
        evaluation_policy_version: str,
        light_judge_version: Optional[str] = None,
    ) -> List[tuple]:
        """
        取某题材在指定评审策略版本窗口内的已结算 champion 异步复评序列，供冠军保真
        滚动窗口退化判定（§11.2 champion_fidelity_drop 唤醒信号）。

        仅取 status=settled 的行，按 finished_at 升序返回 (finished_at, async_review_result)
        二元组；不跨 evaluation_policy_version 聚合（§8.1 硬闸门 #4）。champion 侧是否可用
        由调用方在 Python 侧过滤（本层只读原始载荷，不解析结构）。
        """
        query = (
            self.session.query(
                PromptExperiment.finished_at,
                PromptExperiment.async_review_result,
            )
            .filter(
                PromptExperiment.genre == genre,
                PromptExperiment.status == STATUS_SETTLED,
                PromptExperiment.evaluation_policy_version == evaluation_policy_version,
            )
            .order_by(PromptExperiment.finished_at.asc())
        )
        if light_judge_version is not None:
            query = query.filter(PromptExperiment.light_judge_version == light_judge_version)
        return [(row[0], row[1]) for row in query.all()]

    def list_champion_ai_scores(
        self,
        genre: str,
        evaluation_policy_version: str,
        light_judge_version: Optional[str] = None,
    ) -> List[tuple]:
        """
        取某题材在指定评审策略版本窗口内的已结算冠军原始 AI 检测分序列，供冠军在线
        AI 率回升滚动窗口退化判定（§11.2 champion_ai_score_rise 唤醒信号 3a）。

        仅取 status=settled 且 champion_ai_score 非空的行，按 finished_at 升序返回
        (finished_at, champion_ai_score) 二元组；不跨 evaluation_policy_version 聚合
        （§8.1 硬闸门 #4）。历史行 champion_ai_score 为空（落库前）自动排除。
        """
        query = (
            self.session.query(
                PromptExperiment.finished_at,
                PromptExperiment.champion_ai_score,
            )
            .filter(
                PromptExperiment.genre == genre,
                PromptExperiment.status == STATUS_SETTLED,
                PromptExperiment.evaluation_policy_version == evaluation_policy_version,
                PromptExperiment.champion_ai_score.isnot(None),
            )
            .order_by(PromptExperiment.finished_at.asc())
        )
        if light_judge_version is not None:
            query = query.filter(PromptExperiment.light_judge_version == light_judge_version)
        return [(row[0], row[1]) for row in query.all()]

    def mark_dead(
        self, experiment_id: str, *, last_error_code: str, finished_at: Optional[datetime] = None
    ) -> PromptExperiment:
        """转异常终态 dead + 错误码（禁止落原文，仅结构化 code）。终态行幂等空操作，防晚到重试改判已结算实验。"""
        row = self.get_by_experiment_id(experiment_id)
        if row is None:
            raise ValueError(f"实验不存在: {experiment_id}")
        if row.status in _TERMINAL_STATUSES:
            return row
        row.status = STATUS_DEAD
        row.last_error_code = last_error_code
        row.lease_until = None
        row.finished_at = finished_at or datetime.now(timezone.utc)
        self.session.flush()
        return row
