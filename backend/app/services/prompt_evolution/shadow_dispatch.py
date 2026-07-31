"""
shadow 分流决策 + 入队编排（设计文档 §5.1 / §5.5 / §10 / §14 第 6 步子块 B-1）

冠军路径成功返回前的旁路挂载点调用 maybe_create_shadow_experiment，决策链：
① 总开关 EXPERIMENT_ENABLED → ② 密钥存在（失败关闭）→ ③ opt-in 授权（默认拒绝）
→ ④ HMAC 分桶 ε 命中 → ⑤ 池内确定性选挑战者 → ⑥ 结算键幂等预查
→ ⑦ 四维预算 reserve（global / genre / challenger / user，任一失败整体回滚）
→ ⑧ PayloadVault 加密载荷 → ⑨ 创建 pending 实验行，同事务 commit。

红线：
- 任何环节失败只静默跳过（结构化 reason），绝不抛出影响冠军路径；
- 日志只落异常类型名与结构化字段，禁止落用户原文；
- 本模块不接 Celery、不调外部 API——执行由子块 B-2 的 worker 认领。
"""
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.services.prompt_evolution.budget_ledger import BudgetLedger
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.experiment_contract import (
    EXPERIMENT_EVALUATION_POLICY_VERSION,
    LIGHT_JUDGE_VERSION,
    FrozenModelContract,
    ServingMode,
    assign_bucket,
    bucket_hits_epsilon,
    select_challenger_index,
)
from app.services.prompt_evolution.experiment_privacy import (
    ExperimentConsentRegistry,
    PayloadVault,
)
from app.services.prompt_evolution.experiment_repository import ExperimentRepository

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_optional_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_optional_float(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class ShadowDispatchConfig:
    """分流配置（环境变量直读，None 表示该维度不设限）"""

    enabled: bool
    epsilon: float
    bucket_secret: str
    payload_key: str
    payload_ttl_seconds: int
    estimated_cost: float
    daily_calls_limit: Optional[int]
    daily_cost_limit: Optional[float]
    per_genre_cost_limit: Optional[float]
    per_challenger_cost_limit: Optional[float]
    per_user_daily_calls: Optional[int]

    @classmethod
    def from_env(cls) -> "ShadowDispatchConfig":
        return cls(
            enabled=os.getenv("EXPERIMENT_ENABLED", "false").lower() == "true",
            epsilon=_env_float("EXPERIMENT_EPSILON_SHADOW", 0.0),
            bucket_secret=os.getenv("EXPERIMENT_BUCKET_SECRET", ""),
            payload_key=os.getenv("EXPERIMENT_PAYLOAD_KEY", ""),
            payload_ttl_seconds=int(_env_float("EXPERIMENT_PAYLOAD_TTL", 24 * 3600)),
            estimated_cost=_env_float("EXPERIMENT_ESTIMATED_COST", 0.01),
            daily_calls_limit=_env_optional_int("EXPERIMENT_DAILY_BUDGET_CALLS"),
            daily_cost_limit=_env_optional_float("EXPERIMENT_DAILY_BUDGET_COST"),
            per_genre_cost_limit=_env_optional_float("EXPERIMENT_DAILY_BUDGET_PER_GENRE"),
            per_challenger_cost_limit=_env_optional_float(
                "EXPERIMENT_DAILY_BUDGET_PER_CHALLENGER"
            ),
            per_user_daily_calls=_env_optional_int("EXPERIMENT_DAILY_BUDGET_PER_USER_FREQ"),
        )


@dataclass(frozen=True)
class ShadowDispatchResult:
    """分流结果：dispatched=False 时 reason 说明在决策链哪一环跳过"""

    dispatched: bool
    reason: str
    experiment_id: Optional[str] = None
    challenger_id: Optional[str] = None


def _reserve_all_budgets(
    ledger: BudgetLedger,
    *,
    budget_date: str,
    genre: str,
    challenger_id: str,
    subject_id: str,
    config: ShadowDispatchConfig,
) -> bool:
    """
    四维预算依次 set_limits + reserve，任一失败即返回 False（由调用方整体回滚）。
    维度限额映射（§9）：global=调用+费用；genre=费用；challenger=费用；user=调用频次。
    """
    dimensions = (
        ("global", "", config.daily_cost_limit, config.daily_calls_limit),
        ("genre", genre, config.per_genre_cost_limit, None),
        ("challenger", challenger_id, config.per_challenger_cost_limit, None),
        ("user", subject_id, None, config.per_user_daily_calls),
    )
    for scope, scope_key, cost_limit, calls_limit in dimensions:
        ledger.set_limits(
            budget_date, scope, scope_key, cost_limit=cost_limit, calls_limit=calls_limit
        )
        if not ledger.reserve(
            budget_date, scope, scope_key, cost=config.estimated_cost, calls=1
        ):
            return False
    return True


def maybe_create_shadow_experiment(
    session: Session,
    *,
    subject_id: str,
    genre: str,
    request_id: str,
    original_text: str,
    champion_text: str,
    original_ai_score: Optional[float],
    champion_ai_score: Optional[float],
    champion_prompt_text: str,
    contract: FrozenModelContract,
    config: Optional[ShadowDispatchConfig] = None,
    consent_registry: Optional[ExperimentConsentRegistry] = None,
    vault: Optional[PayloadVault] = None,
) -> ShadowDispatchResult:
    """
    冠军路径旁路：按决策链判定是否为本次请求创建 shadow 实验（pending 行）。

    事务边界：本函数自管 commit / rollback——挂载点（reduce 路由）对该 session
    没有其它未提交写操作，预算占用 + 实验行必须同事务原子落库。
    任何异常静默捕获返回 error:<类型名>，绝不向冠军路径抛出。
    """
    if config is None:
        config = ShadowDispatchConfig.from_env()

    try:
        # ① 总开关（默认关闭，完全惰性）
        if not config.enabled:
            return ShadowDispatchResult(dispatched=False, reason="disabled")

        # ② 密钥缺失失败关闭：无分桶密钥 / 无载荷加密密钥一律不实验
        if not config.bucket_secret or not config.payload_key:
            return ShadowDispatchResult(dispatched=False, reason="missing_config")

        # ③ opt-in 授权（默认拒绝，§10）
        if consent_registry is None:
            consent_registry = ExperimentConsentRegistry()
        if not consent_registry.has_consent(subject_id):
            return ShadowDispatchResult(dispatched=False, reason="no_consent")

        # ④ HMAC 分桶 ε：campaign id 用评估策略版本（统计窗口内稳定，§5.1）
        bucket = assign_bucket(
            config.bucket_secret, subject_id, genre, EXPERIMENT_EVALUATION_POLICY_VERSION
        )
        if not bucket_hits_epsilon(bucket, config.epsilon):
            return ShadowDispatchResult(dispatched=False, reason="epsilon_miss")

        # ⑤ 池内确定性选挑战者（list_serving 已按 challenger_id 排序）
        challengers = ChallengerRepository(session).list_serving(
            genre, serving_mode=ServingMode.SHADOW.value
        )
        if not challengers:
            return ShadowDispatchResult(dispatched=False, reason="no_challenger")
        index = select_challenger_index(
            config.bucket_secret,
            subject_id,
            genre,
            EXPERIMENT_EVALUATION_POLICY_VERSION,
            len(challengers),
        )
        challenger = challengers[index]

        # ⑥ 结算键幂等预查：命中既有行不重复扣预算、不重复入队
        repo = ExperimentRepository(session)
        existing = repo.find_settlement(
            request_id, challenger.challenger_id, EXPERIMENT_EVALUATION_POLICY_VERSION
        )
        if existing is not None:
            return ShadowDispatchResult(
                dispatched=False,
                reason="already_exists",
                experiment_id=existing.experiment_id,
                challenger_id=existing.challenger_id,
            )

        # ⑦ 四维预算 reserve（任一失败整体回滚，不留半截占用）
        now = datetime.now(timezone.utc)
        ledger = BudgetLedger(session)
        if not _reserve_all_budgets(
            ledger,
            budget_date=now.strftime("%Y-%m-%d"),
            genre=genre,
            challenger_id=challenger.challenger_id,
            subject_id=subject_id,
            config=config,
        ):
            session.rollback()
            return ShadowDispatchResult(dispatched=False, reason="budget_exhausted")

        # ⑧ 原文 + 冠军产出打包加密入库，任务表只带 opaque ref（§10）
        if vault is None:
            vault = PayloadVault(config.payload_key)
        payload_ref = vault.put(
            subject_id,
            json.dumps(
                {
                    "subject_id": subject_id,
                    "original_text": original_text,
                    "champion_text": champion_text,
                    "original_ai_score": original_ai_score,
                    "champion_ai_score": champion_ai_score,
                },
                ensure_ascii=False,
            ),
            ttl_seconds=config.payload_ttl_seconds,
        )

        # ⑨ 创建 pending 实验行（冠军契约冻结自 FrozenModelContract）
        champion_hash = hashlib.sha256(
            champion_prompt_text.encode("utf-8")
        ).hexdigest()
        experiment_id = f"exp_{uuid.uuid4().hex[:16]}"
        row = repo.create_experiment(
            experiment_id=experiment_id,
            request_id=request_id,
            challenger_id=challenger.challenger_id,
            genre=genre,
            champion_id=contract.prompt_version_id,
            assignment_bucket=bucket,
            serving_mode=ServingMode.SHADOW.value,
            resolved_model_id=contract.resolved_model_id,
            model_selection_source=contract.model_selection_source,
            prompt_version_id=contract.prompt_version_id,
            provider_parameters_hash=contract.provider_parameters_hash,
            light_judge_version=LIGHT_JUDGE_VERSION,
            evaluation_policy_version=EXPERIMENT_EVALUATION_POLICY_VERSION,
            champion_prompt_hash=f"sha256:{champion_hash}",
            challenger_prompt_hash=challenger.prompt_hash,
            payload_ref=payload_ref,
            payload_expires_at=now + timedelta(seconds=config.payload_ttl_seconds),
            model_config_version=contract.model_config_version,
        )
        session.commit()
        return ShadowDispatchResult(
            dispatched=True,
            reason="created",
            experiment_id=row.experiment_id,
            challenger_id=row.challenger_id,
        )
    except Exception as exc:  # noqa: BLE001 —— fail-safe 红线：绝不影响冠军路径
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        # 日志纪律：只落异常类型名与结构化字段，不落原文
        logger.warning(
            "shadow 分流异常跳过: type=%s, genre=%s, request_id=%s",
            type(exc).__name__,
            genre,
            request_id,
        )
        return ShadowDispatchResult(
            dispatched=False, reason=f"error:{type(exc).__name__}"
        )
