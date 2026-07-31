"""
returnable best-of-2 择优返回核心（设计文档 §5.4 / §14 第 8 步 · 子块 A）

在 ai-trace 请求路径对已开闸的 returnable 挑战者做双路并行 best-of-2 择优返回：
    双路并行生成 → 同步硬门槛 → 两路都过按排序分 + 不对称 margin 择优 → 返回胜者文本。

设计纪律：
- **fail-safe 红线**：任何环节异常一律回退冠军（reason=error:<类型名>），绝不影响用户返回；
- **opt-in 合规（§10）**：returnable 同样要拿原文生成挑战者，须 opt-in 授权，默认拒绝；
- **运行期熔断（§5.4）**：判定器滚动作废率越限即降级为恒返回冠军，报警待人工介入；
- **分桶域分离**：returnable 分桶 campaign id 加 ":returnable" 后缀，与 shadow 分桶解耦，
  避免 returnable 组恒为 shadow 组子集导致选择相关；
- **模型冻结（§4.1）**：挑战者复用冠军已解析的 model_id，禁止各自重新选择模型。

本模块含纯逻辑 + async 编排（依赖注入 rewrite/detect）+ 命中结果落库统计回流（子块 B）
+ reduce 端点挂载编排 returnable_reduce（子块 C）。
"""
import hashlib
import json
import logging
import math
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptChallengerStateTransition

from .challenger_repository import ChallengerRepository
from .experiment_contract import (
    EXPERIMENT_EVALUATION_POLICY_VERSION,
    LIGHT_JUDGE_VERSION,
    FrozenModelContract,
    ServingMode,
    assign_bucket,
    bucket_hits_epsilon,
    select_challenger_index,
)
from .experiment_privacy import ExperimentConsentRegistry, PayloadVault
from .experiment_repository import ExperimentRepository
from .light_judge import judge_pair
from .replay_calibration import DEFAULT_MIN_SAMPLES, compute_replay_consistency

logger = logging.getLogger(__name__)

# returnable 分桶 campaign 后缀（与 shadow 分桶域分离，§5.1）
RETURNABLE_CAMPAIGN = EXPERIMENT_EVALUATION_POLICY_VERSION + ":returnable"


def _env_float(name: str, default: float) -> float:
    # 两类区分（六轮评审②）：未设置/空白 → 默认值；已设置但不可解析 → 带配置名
    # ValueError 失败关闭，不得静默回退掩盖部署侧配置错误（值范围由 __post_init__ 兜底）
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"非法配置 {name}={raw!r}：必须为数值") from exc


def _env_int(name: str, default: int) -> int:
    # 直接按整数解析（六轮评审②）："10.9" 不得经 float→int 隐式截断为 10
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"非法配置 {name}={raw!r}：必须为整数") from exc


# EXPERIMENT_AI_SCORE_THRESHOLD 环境变量名（shadow 与 returnable 两路径共用）
_AI_SCORE_THRESHOLD_ENV = "EXPERIMENT_AI_SCORE_THRESHOLD"
_AI_SCORE_THRESHOLD_DEFAULT = 25.0


def parse_ai_threshold(default: float = _AI_SCORE_THRESHOLD_DEFAULT) -> float:
    """
    解析并校验 AI 硬门槛阈值（八轮评审①）：与 ReturnableConfig.__post_init__ 同一规则，
    供 shadow 装配层（experiment_tasks._build_deps）与 returnable 配置共用——杜绝
    experiment_tasks 裸 float() 放行 nan/inf/负值/越界导致两路径 AI 硬门槛语义分裂
    （nan 使 ai_score > ai_threshold 恒 False、硬门槛静默失效并污染校准/作废率统计）。
    未设置/空白 → 默认值；已设置但非法（不可解析、非有限、越界 [0,100]）→ 带配置名失败关闭。
    """
    value = _env_float(_AI_SCORE_THRESHOLD_ENV, default)
    if not (math.isfinite(value) and 0.0 <= value <= 100.0):
        raise ValueError(
            f"非法配置 {_AI_SCORE_THRESHOLD_ENV}={value!r}：须为有限数且在 [0, 100]"
        )
    return value


# EXPERIMENT_MAX_ATTEMPTS 环境变量名（shadow Celery 任务最大重试次数）
_MAX_ATTEMPTS_ENV = "EXPERIMENT_MAX_ATTEMPTS"
_MAX_ATTEMPTS_DEFAULT = 3


def parse_max_attempts(default: int = _MAX_ATTEMPTS_DEFAULT) -> int:
    """
    解析并校验 shadow 任务最大重试次数（九轮评审）：与 parse_ai_threshold 对称，
    供 experiment_tasks._build_deps 复用，杜绝裸 int() 放行 0/-1——执行器判定
    `attempt_count >= max_attempts`，< 1 会使任务首次异常即入 dead、重试保护失效。
    未设置/空白 → 默认值；已设置但非整数（含 1.5 小数串，_env_int 直接 int() 拒绝）
    或 < 1 → 带配置名失败关闭。
    """
    value = _env_int(_MAX_ATTEMPTS_ENV, default)
    if value < 1:
        raise ValueError(f"非法配置 {_MAX_ATTEMPTS_ENV}={value!r}：须为 >= 1 的整数")
    return value


@dataclass(frozen=True)
class ReturnableConfig:
    """returnable 择优配置（环境变量直读）"""

    enabled: bool
    epsilon: float               # EXPERIMENT_EPSILON_RETURNABLE：returnable 阶梯当前值
    margin_threshold: float      # EXPERIMENT_MARGIN_THRESHOLD：择优所需排序分领先幅度
    bucket_secret: str           # EXPERIMENT_BUCKET_SECRET
    ai_threshold: float          # EXPERIMENT_AI_SCORE_THRESHOLD：硬门槛 AI 分上限
    invalidation_rate_max: float # EXPERIMENT_INVALIDATED_RATE_MAX：熔断作废率上限
    payload_key: str = ""        # EXPERIMENT_PAYLOAD_KEY：落库载荷加密密钥（子块 B）
    payload_ttl_seconds: int = 24 * 3600  # EXPERIMENT_PAYLOAD_TTL：载荷 TTL
    # EXPERIMENT_CIRCUIT_WINDOW_HOURS：熔断滚动窗口，默认 168h（§5.4 既定 7 日）
    circuit_window_hours: float = 168.0
    # EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES：熔断最小有效样本门槛，
    # 复用 replay 校准作废率统计可信门槛（DEFAULT_MIN_SAMPLES=200），不足视为预热态
    circuit_min_samples: int = DEFAULT_MIN_SAMPLES
    # 预热期双层规则（五轮评审②）：有效样本未达 circuit_min_samples 时不再无条件放行，
    # ≥ warmup_min_samples 且作废率越 warmup_invalidation_rate_max 即熔断，堵住开闸后
    # 供应商漂移/检测器异常在预热期的盲区。20/0.20 为评审建议初值（文档无既定值），
    # 上线前按业务风险复核（§13 #13 / §15）。
    # EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES
    warmup_min_samples: int = 20
    # EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX
    warmup_invalidation_rate_max: float = 0.20

    def __post_init__(self) -> None:
        # 集中范围校验（五轮评审③）：覆盖所有构造路径（from_env / 直接构造 / 测试），
        # 非法配置带配置名失败关闭——如负窗口会让 since 落在未来、熔断静默永久关闭
        checks = (
            (
                math.isfinite(self.circuit_window_hours) and self.circuit_window_hours > 0,
                "EXPERIMENT_CIRCUIT_WINDOW_HOURS",
                self.circuit_window_hours,
                "须为有限正数",
            ),
            (
                self.circuit_min_samples >= 1,
                "EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES",
                self.circuit_min_samples,
                "须 >= 1",
            ),
            (
                self.warmup_min_samples >= 1,
                "EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES",
                self.warmup_min_samples,
                "须 >= 1",
            ),
            (
                0.0 <= self.epsilon <= 1.0,
                "EXPERIMENT_EPSILON_RETURNABLE",
                self.epsilon,
                "须在 [0, 1]",
            ),
            (
                0.0 <= self.invalidation_rate_max <= 1.0,
                "EXPERIMENT_INVALIDATED_RATE_MAX",
                self.invalidation_rate_max,
                "须在 [0, 1]",
            ),
            (
                0.0 <= self.warmup_invalidation_rate_max <= 1.0,
                "EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX",
                self.warmup_invalidation_rate_max,
                "须在 [0, 1]",
            ),
            (
                self.payload_ttl_seconds > 0,
                "EXPERIMENT_PAYLOAD_TTL",
                self.payload_ttl_seconds,
                "须为正数",
            ),
            # 七轮评审①：硬门槛为 ai_score > ai_threshold，nan 使比较恒 False →
            # AI 保护静默失效；业务量表 0-100（compute_ranking_score 以 100.0 为最差占位）
            (
                math.isfinite(self.ai_threshold) and 0.0 <= self.ai_threshold <= 100.0,
                "EXPERIMENT_AI_SCORE_THRESHOLD",
                self.ai_threshold,
                "须为有限数且在 [0, 100]",
            ),
            # 七轮评审①：排序分差值无固定上限故不设上界；负值/-inf 即放水，inf 永不返回
            (
                math.isfinite(self.margin_threshold) and self.margin_threshold >= 0.0,
                "EXPERIMENT_MARGIN_THRESHOLD",
                self.margin_threshold,
                "须为有限非负数",
            ),
        )
        for ok, name, value, rule in checks:
            if not ok:
                raise ValueError(f"非法配置 {name}={value!r}：{rule}")
        # 跨字段约束（七轮评审②）：warmup >= circuit 时预热分支恒假、预热保护静默
        # 失效（#13 区间 warmup ≤ 有效样本 < circuit 为空集）；未定义"相等 = 关闭
        # 预热"语义，失败关闭要求严格小于
        if self.warmup_min_samples >= self.circuit_min_samples:
            raise ValueError(
                f"非法配置：EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES"
                f"={self.warmup_min_samples!r} 必须小于 "
                f"EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES={self.circuit_min_samples!r}"
            )

    @classmethod
    def from_env(cls) -> "ReturnableConfig":
        return cls(
            enabled=os.getenv("EXPERIMENT_ENABLED", "false").lower() == "true",
            epsilon=_env_float("EXPERIMENT_EPSILON_RETURNABLE", 0.0),
            margin_threshold=_env_float("EXPERIMENT_MARGIN_THRESHOLD", 5.0),
            bucket_secret=os.getenv("EXPERIMENT_BUCKET_SECRET", ""),
            ai_threshold=parse_ai_threshold(),
            invalidation_rate_max=_env_float("EXPERIMENT_INVALIDATED_RATE_MAX", 0.05),
            payload_key=os.getenv("EXPERIMENT_PAYLOAD_KEY", ""),
            payload_ttl_seconds=_env_int("EXPERIMENT_PAYLOAD_TTL", 24 * 3600),
            circuit_window_hours=_env_float("EXPERIMENT_CIRCUIT_WINDOW_HOURS", 168.0),
            circuit_min_samples=_env_int(
                "EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES", DEFAULT_MIN_SAMPLES
            ),
            warmup_min_samples=_env_int("EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES", 20),
            warmup_invalidation_rate_max=_env_float(
                "EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX", 0.20
            ),
        )


@dataclass(frozen=True)
class ReturnableDeps:
    """执行期外部依赖（全部注入，便于测试与替换供应商）

    - rewrite_fn(prompt_text, original_text, model_id) -> challenger_text（async）：
      挑战者生成，model_id 为冠军已冻结的解析模型（§4.1）；
    - detect_fn(text) -> Optional[float]（async）：AI 检测分，None 表示检测不可用；
    - consent_registry：opt-in 授权注册表，默认构造真实 ExperimentConsentRegistry。
    """

    rewrite_fn: Callable[[str, str, Optional[str]], Awaitable[str]]
    detect_fn: Callable[[str], Awaitable[Optional[float]]]
    consent_registry: Optional[ExperimentConsentRegistry] = None


@dataclass(frozen=True)
class BestOfTwoOutcome:
    """择优结果：returned_variant 决定返回哪路文本，reason 说明决策链落点"""

    returned_variant: str        # champion | challenger
    returned_text: str
    reason: str
    challenger_id: Optional[str] = None
    light_judge_result: Optional[dict] = None
    challenger_text: Optional[str] = None
    challenger_ai_score: Optional[float] = None


def returnable_bucket_hit(config: ReturnableConfig, subject_id: str, genre: str) -> bool:
    """returnable ε 流量判定（与 shadow 分桶域分离）"""
    bucket = assign_bucket(config.bucket_secret, subject_id, genre, RETURNABLE_CAMPAIGN)
    return bucket_hits_epsilon(bucket, config.epsilon)


# 审批原因上限，与审计表 prompt_challenger_state_transitions.reason String(500) 对齐
APPROVAL_REASON_MAX_LENGTH = 500


def normalize_approval_reason(reason: str) -> str:
    """
    审批原因规范化 + 防御验证（五轮评审④）：换行/制表等空白统一规范化为单个
    空格（防日志与审计记录注入伪造行）、strip 后拒纯空白、上限对齐审计表
    String(500) 失败关闭而非静默截断。服务层与 API 层共用同一规则。
    """
    normalized = " ".join(reason.split())
    if not normalized:
        raise ValueError("审批原因不能为空白（审计必填）")
    if len(normalized) > APPROVAL_REASON_MAX_LENGTH:
        raise ValueError(
            f"审批原因超长：{len(normalized)} > {APPROVAL_REASON_MAX_LENGTH}"
            f"（审计表 reason 列上限）"
        )
    return normalized


def is_circuit_open(
    session: Session,
    config: ReturnableConfig,
    *,
    evaluation_policy_version: str = EXPERIMENT_EVALUATION_POLICY_VERSION,
    now: Optional[datetime] = None,
) -> bool:
    """
    运行期熔断（§5.4）：本策略版本 returnable 场景滚动窗口（circuit_window_hours，
    默认 7 日）内判定器作废率越限即开，双层规则（五轮评审②）：

    - 成熟期（有效样本 >= circuit_min_samples）：作废率 > invalidation_rate_max 熔断；
    - 预热期（warmup_min_samples <= 有效样本 < circuit_min_samples）：用更宽的
      warmup_invalidation_rate_max 兜底严重劣化，容忍小样本统计噪声；
    - 有效样本 < warmup_min_samples：证据不足不熔断（1/1=100% 不应停摆），
      由校准层门槛兜底。

    仅统计 serving_mode=returnable 的样本（shadow ε 量级碾压会稀释信号）。
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=config.circuit_window_hours)
    outcomes = ExperimentRepository(session).list_recent_returnable_outcomes(
        evaluation_policy_version, since
    )
    if not outcomes:
        return False
    report = compute_replay_consistency(outcomes)
    if report.effective_total < config.circuit_min_samples:
        return (
            report.effective_total >= config.warmup_min_samples
            and report.invalidation_rate > config.warmup_invalidation_rate_max
        )
    return report.invalidation_rate > config.invalidation_rate_max


def approve_returnable(session: Session, challenger_id: str, *, operator: str, reason: str):
    """
    人工开闸（§14 第 8 步生产闭环）：管理员批准 eligible 挑战者进入 returnable。

    开闸语义限定从 eligible 出发（cooldown 恢复走既有状态机路径，不经本入口）；
    审批 operator + reason 与状态变更同事务落审计表（五轮评审①：普通日志可
    轮转/丢失，不构成审计记录），日志仅为辅助可观测。
    reason 经 normalize_approval_reason 防御验证（五轮评审④，不依赖 HTTP 层）。
    状态转换走条件更新（六轮评审①）：并发审批只有一个事务赢得
    eligible → returnable，输者失败关闭且不插入审计行，保证审计只记录
    真实发生的状态变更。
    挑战者不存在返回 None；非 eligible、并发冲突或 reason 非法抛 ValueError。
    """
    reason = normalize_approval_reason(reason)
    repo = ChallengerRepository(session)
    row = repo.get_by_challenger_id(challenger_id)
    if row is None:
        return None
    if row.serving_mode != ServingMode.ELIGIBLE.value:
        raise ValueError(
            f"人工开闸要求挑战者当前状态为 eligible: "
            f"challenger={challenger_id} 当前={row.serving_mode}"
        )
    genre = row.genre
    if not repo.transition_serving_mode(
        challenger_id, ServingMode.ELIGIBLE.value, ServingMode.RETURNABLE.value
    ):
        # 条件更新未命中：另一请求在本事务读取后已完成处理（六轮评审①），
        # 重读真实状态供管理端区分重复点击与真正的状态迁移
        session.expire_all()
        current = repo.get_by_challenger_id(challenger_id)
        current_mode = current.serving_mode if current is not None else "不存在"
        raise ValueError(
            f"人工开闸并发冲突：challenger={challenger_id} 已被其他请求处理，"
            f"当前={current_mode}"
        )
    session.add(
        PromptChallengerStateTransition(
            challenger_id=challenger_id,
            genre=genre,
            from_mode=ServingMode.ELIGIBLE.value,
            to_mode=ServingMode.RETURNABLE.value,
            operator=operator,
            reason=reason,
        )
    )
    session.commit()
    logger.info(
        "returnable 人工开闸: challenger=%s genre=%s operator=%s reason=%s",
        challenger_id,
        genre,
        operator,
        reason,
    )
    return row


def _champion(champion_text: str, reason: str) -> BestOfTwoOutcome:
    return BestOfTwoOutcome(
        returned_variant="champion", returned_text=champion_text, reason=reason
    )


async def choose_returnable_variant(
    session: Session,
    *,
    subject_id: str,
    genre: str,
    original_text: str,
    champion_text: str,
    champion_ai_score: Optional[float],
    model_id: Optional[str],
    deps: ReturnableDeps,
    config: Optional[ReturnableConfig] = None,
) -> BestOfTwoOutcome:
    """
    双路并行 best-of-2 择优（§5.4 + §5.5 降级表同步部分）。

    决策链（便宜检查在前，异常一律回退冠军）：
    ① 总开关关闭 → 冠军；② 分桶密钥缺失 → 冠军；③ 无 opt-in 授权 → 冠军；
    ④ 熔断开启 → 冠军；⑤ ε 未命中 → 冠军；⑥ returnable 池空 → 冠军；
    ⑦ 确定性选挑战者 → 生成挑战者文本 + AI 检测 → judge_pair 择优 → 按胜者返回。
    """
    if config is None:
        config = ReturnableConfig.from_env()

    try:
        # ① 总开关（默认关闭，完全惰性）
        if not config.enabled:
            return _champion(champion_text, "disabled")

        # ② 分桶密钥缺失失败关闭
        if not config.bucket_secret:
            return _champion(champion_text, "missing_config")

        # ③ opt-in 授权（默认拒绝，§10）
        consent = deps.consent_registry or ExperimentConsentRegistry()
        if not consent.has_consent(subject_id):
            return _champion(champion_text, "no_consent")

        # ④ 运行期熔断（§5.4）
        if is_circuit_open(session, config):
            return _champion(champion_text, "circuit_open")

        # ⑤ HMAC 分桶 ε（returnable 独立 campaign）
        if not returnable_bucket_hit(config, subject_id, genre):
            return _champion(champion_text, "epsilon_miss")

        # ⑥ returnable 池内确定性选挑战者
        challengers = ChallengerRepository(session).list_serving(
            genre, serving_mode=ServingMode.RETURNABLE.value
        )
        if not challengers:
            return _champion(champion_text, "no_challenger")
        index = select_challenger_index(
            config.bucket_secret, subject_id, genre, RETURNABLE_CAMPAIGN, len(challengers)
        )
        challenger = challengers[index]

        # ⑦ 双路并行：挑战者生成 + AI 检测（模型复用冠军冻结契约）
        challenger_text = await deps.rewrite_fn(
            challenger.prompt_text, original_text, model_id
        )
        challenger_ai_score = await deps.detect_fn(challenger_text)
        detector_available = challenger_ai_score is not None

        # 同步硬门槛 + margin 择优（judge_pair 已实现 §5.3/§5.5 同步语义）
        light = judge_pair(
            original_text=original_text,
            champion_text=champion_text,
            challenger_text=challenger_text,
            champion_ai_score=champion_ai_score,
            challenger_ai_score=challenger_ai_score,
            ai_threshold=config.ai_threshold,
            detector_available=detector_available,
            margin=config.margin_threshold,
        )
        returned_text = (
            challenger_text if light.returned_variant == "challenger" else champion_text
        )
        return BestOfTwoOutcome(
            returned_variant=light.returned_variant,
            returned_text=returned_text,
            reason="best_of_2",
            challenger_id=challenger.challenger_id,
            light_judge_result=asdict(light),
            challenger_text=challenger_text,
            challenger_ai_score=challenger_ai_score,
        )
    except Exception as exc:  # noqa: BLE001 —— fail-safe 红线：绝不影响用户返回
        logger.warning(
            "returnable 择优异常回退冠军: type=%s, genre=%s",
            type(exc).__name__,
            genre,
        )
        return _champion(champion_text, f"error:{type(exc).__name__}")


def persist_returnable_experiment(
    session: Session,
    *,
    outcome: BestOfTwoOutcome,
    subject_id: str,
    genre: str,
    request_id: str,
    original_text: str,
    champion_text: str,
    champion_ai_score: Optional[float],
    contract: FrozenModelContract,
    champion_prompt_text: str,
    config: ReturnableConfig,
    vault: Optional[PayloadVault] = None,
) -> Optional[str]:
    """
    returnable 命中双路结果落库统计回流（设计文档 §5.4 / §14 第 8 步 · 子块 B）。

    仅对真正跑了双路的命中（reason == "best_of_2" 且有 challenger_id）落一条 pending 行，
    加密载荷预置同步双路结果（挑战者文本 + AI 分 + light_judge_result + returned_variant），
    交由 shadow 执行器只补异步复评 + 结算（不重复生成、不占用 shadow 预算，§5.1 风险治理）。

    幂等：结算键三元组 (request_id, challenger_id, evaluation_policy_version) 命中既有行则返回其 id。
    fail-safe：任何异常静默回滚返回 None，绝不影响用户返回。返回 experiment_id 或 None。
    """
    # 只回流真正双路命中；无载荷密钥无法加密则跳过（失败关闭，§10）
    if outcome.reason != "best_of_2" or not outcome.challenger_id:
        return None
    if not config.payload_key or not config.bucket_secret:
        return None

    try:
        repo = ExperimentRepository(session)
        existing = repo.find_settlement(
            request_id, outcome.challenger_id, EXPERIMENT_EVALUATION_POLICY_VERSION
        )
        if existing is not None:
            return existing.experiment_id

        # 取挑战者行拿 prompt_hash（缺失说明挑战者已下线，不回流）
        challenger = ChallengerRepository(session).get_by_challenger_id(outcome.challenger_id)
        if challenger is None:
            return None

        # returnable 独立 campaign 分桶值（与 shadow 域分离）
        bucket = assign_bucket(
            config.bucket_secret, subject_id, genre, RETURNABLE_CAMPAIGN
        )

        # 原文 + 双路产出加密入库，任务表只带 opaque ref（§10）
        if vault is None:
            vault = PayloadVault(config.payload_key)
        payload_ref = vault.put(
            subject_id,
            json.dumps(
                {
                    "subject_id": subject_id,
                    "original_text": original_text,
                    "champion_text": champion_text,
                    "champion_ai_score": champion_ai_score,
                    # 预置双路结果：执行器据此跳过重复生成，只补异步复评（子块 B）
                    "preset_challenger": {
                        "challenger_text": outcome.challenger_text,
                        "challenger_ai_score": outcome.challenger_ai_score,
                        "light_judge_result": outcome.light_judge_result,
                        "returned_variant": outcome.returned_variant,
                    },
                },
                ensure_ascii=False,
            ),
            ttl_seconds=config.payload_ttl_seconds,
        )

        now = datetime.now(timezone.utc)
        champion_hash = hashlib.sha256(champion_prompt_text.encode("utf-8")).hexdigest()
        experiment_id = f"exp_{uuid.uuid4().hex[:16]}"
        row = repo.create_experiment(
            experiment_id=experiment_id,
            request_id=request_id,
            challenger_id=outcome.challenger_id,
            genre=genre,
            champion_id=contract.prompt_version_id,
            assignment_bucket=bucket,
            serving_mode=ServingMode.RETURNABLE.value,
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
        return row.experiment_id
    except Exception as exc:  # noqa: BLE001 —— fail-safe 红线：落库失败绝不影响用户返回
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "returnable 落库异常跳过: type=%s, genre=%s, request_id=%s",
            type(exc).__name__,
            genre,
            request_id,
        )
        return None


async def returnable_reduce(
    session: Session,
    *,
    subject_id: str,
    genre: str,
    request_id: str,
    original_text: str,
    champion_text: str,
    champion_ai_score: Optional[float],
    model_id: Optional[str],
    contract: FrozenModelContract,
    champion_prompt_text: str,
    deps: ReturnableDeps,
    config: Optional[ReturnableConfig] = None,
    vault: Optional[PayloadVault] = None,
) -> BestOfTwoOutcome:
    """
    reduce 端点挂载编排（设计文档 §5.4 / §14 第 8 步 · 子块 C）。

    组合择优与落库回流：先 choose_returnable_variant 双路择优，命中真实双路比较
    （reason == "best_of_2"）即 persist_returnable_experiment 落一条 returnable 样本，
    交由执行器只补异步复评（子块 B）。返回 outcome 供端点覆盖响应文本 / 上报 returned_variant。

    fail-safe 由 choose / persist 各自保证（异常一律回退冠军 / 静默跳过落库），
    本函数只做无副作用的组合编排。
    """
    if config is None:
        config = ReturnableConfig.from_env()

    outcome = await choose_returnable_variant(
        session,
        subject_id=subject_id,
        genre=genre,
        original_text=original_text,
        champion_text=champion_text,
        champion_ai_score=champion_ai_score,
        model_id=model_id,
        deps=deps,
        config=config,
    )

    persist_returnable_experiment(
        session,
        outcome=outcome,
        subject_id=subject_id,
        genre=genre,
        request_id=request_id,
        original_text=original_text,
        champion_text=champion_text,
        champion_ai_score=champion_ai_score,
        contract=contract,
        champion_prompt_text=champion_prompt_text,
        config=config,
        vault=vault,
    )
    return outcome

