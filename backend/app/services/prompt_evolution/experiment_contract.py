"""
实验契约冻结模块（设计文档 §4）

在线 Champion/Challenger 双路实验的契约层，包含四部分：
1. 模型冻结契约 FrozenModelContract —— 模型解析一次、两路共享，禁止各自重新选模型
2. HMAC-SHA256 确定性分桶 —— 禁止 Python hash()（进程随机盐不可复现）
3. 评审版本体系常量 —— 任一实质变化即开启新的统计窗口
4. serving_mode 状态机 —— 挑战者生命周期的合法转换定义

本模块只定义契约与纯函数，不做 IO、不依赖数据库。
"""
import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional


# ============================================================================
# 版本体系（§4.3）
# 任一常量实质变化时必须递增版本号，统计聚合按版本分组、旧窗口自然隔离
# ============================================================================

# 同步轻量判定器（硬门槛 + 排序分）版本
LIGHT_JUDGE_VERSION = "light-judge-v1"

# 实验评审策略版本（区别于 ai_trace_competition.EVALUATION_POLICY_VERSION，
# 后者属于多模型竞争评测体系；两套统计窗口独立演进）
EXPERIMENT_EVALUATION_POLICY_VERSION = "experiment-policy-v1"

# 进化体系覆盖的题材（单一定义点：API 面板 / 调度 beat 任务均引用本常量，
# 杜绝双份维护漂移——新增题材只改这里）
EVOLUTION_GENRES = ["玄幻", "都市", "言情", "悬疑", "科幻", "历史", "武侠"]


# ============================================================================
# HMAC-SHA256 确定性分桶（§4.2）
# ============================================================================

BUCKET_COUNT = 10000


def _hmac_int(secret: str, message: str) -> int:
    """HMAC-SHA256 前 4 字节大端整数（确定性，跨进程/重启可复现）"""
    digest = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return int.from_bytes(digest[:4], "big")


def assign_bucket(secret: str, subject_id: str, genre: str, experiment_id: str) -> int:
    """
    确定性分桶：同一 (主体, 题材, 实验) 在实验周期内稳定命中同一桶。

    Returns:
        0 .. BUCKET_COUNT-1 的桶号
    """
    return _hmac_int(secret, f"{subject_id}:{genre}:{experiment_id}") % BUCKET_COUNT


def bucket_hits_epsilon(bucket: int, epsilon: float) -> bool:
    """桶号是否落入实验流量比例 ε（前 ε×BUCKET_COUNT 个桶为实验组）"""
    return bucket < int(epsilon * BUCKET_COUNT)


def select_challenger_index(
    secret: str, subject_id: str, genre: str, experiment_id: str, challenger_count: int
) -> int:
    """
    确定性挑战者选择：同一用户在实验周期内稳定命中同一挑战者，不得每请求漂移。

    与 assign_bucket 做域分离（消息加 ":challenger" 后缀），
    避免挑战者索引与分桶结果强相关。
    """
    if challenger_count <= 0:
        raise ValueError(f"challenger_count 必须为正数，当前为 {challenger_count}")
    return (
        _hmac_int(secret, f"{subject_id}:{genre}:{experiment_id}:challenger")
        % challenger_count
    )


# ============================================================================
# 模型冻结契约（§4.1）
# ============================================================================

@dataclass(frozen=True)
class FrozenModelContract:
    """
    两路共享的模型冻结契约。

    按现有规则（admin_selected > get_best_model_for_prompt_version >
    get_active_model_id 兜底）为冠军请求解析一次最终模型后冻结，
    冠军路与挑战者路禁止各自重新执行模型选择。
    """
    resolved_model_id: str
    model_selection_source: str  # admin_selected | prompt_combination | genre_model_summary | default_route
    model_config_version: str
    prompt_version_id: str
    temperature: float
    max_tokens: Optional[int]
    provider_parameters_hash: str
    extra_provider_params: Optional[str] = None  # 冻结时序列化的附加供应商参数（JSON 字符串）

    @classmethod
    def freeze(
        cls,
        resolved_model_id: str,
        model_selection_source: str,
        model_config_version: str,
        prompt_version_id: str,
        temperature: float,
        max_tokens: Optional[int] = None,
        extra_provider_params: Optional[Dict[str, Any]] = None,
    ) -> "FrozenModelContract":
        """解析结果 → 不可变契约，自动计算 provider_parameters_hash"""
        params_json = (
            json.dumps(extra_provider_params, ensure_ascii=False, sort_keys=True)
            if extra_provider_params
            else None
        )
        fingerprint = json.dumps(
            {
                "model": resolved_model_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "extra": params_json,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        params_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
        return cls(
            resolved_model_id=resolved_model_id,
            model_selection_source=model_selection_source,
            model_config_version=model_config_version,
            prompt_version_id=prompt_version_id,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_parameters_hash=params_hash,
            extra_provider_params=params_json,
        )


# ============================================================================
# serving_mode 状态机（§3.1）
# ============================================================================

class ServingMode(str, Enum):
    """挑战者生命周期状态"""
    SHADOW = "shadow"          # 后台成对实验，不参与返回
    ELIGIBLE = "eligible"      # 四层校准达标，待人工批准
    RETURNABLE = "returnable"  # 参与 best-of-2 择优返回
    CHAMPION = "champion"      # 当前冠军
    SUSPENDED = "suspended"    # 近期表现差，暂停流量，保留数据
    ELIMINATED = "eliminated"  # 确认退化，永久淘汰（终态）
    COOLDOWN = "cooldown"      # 基础设施故障冷却，不计质量败场


# 合法转换表：
# - 晋升路径逐级推进，禁止跳级
# - 活跃状态（shadow/eligible/returnable）可进入 suspended/eliminated/cooldown
# - suspended 恢复只能回 shadow（重新校准），eliminated 为终态
# - cooldown 恢复到冷却前的活跃状态（不含 champion）
# - champion 被新冠军替换后回 suspended（保留可回滚）或 eliminated
_ALLOWED_TRANSITIONS: Dict[ServingMode, FrozenSet[ServingMode]] = {
    ServingMode.SHADOW: frozenset(
        {ServingMode.ELIGIBLE, ServingMode.SUSPENDED, ServingMode.ELIMINATED, ServingMode.COOLDOWN}
    ),
    ServingMode.ELIGIBLE: frozenset(
        {ServingMode.RETURNABLE, ServingMode.SUSPENDED, ServingMode.ELIMINATED, ServingMode.COOLDOWN}
    ),
    ServingMode.RETURNABLE: frozenset(
        {ServingMode.CHAMPION, ServingMode.SUSPENDED, ServingMode.ELIMINATED, ServingMode.COOLDOWN}
    ),
    ServingMode.CHAMPION: frozenset(
        {ServingMode.SUSPENDED, ServingMode.ELIMINATED}
    ),
    ServingMode.SUSPENDED: frozenset(
        {ServingMode.SHADOW, ServingMode.ELIMINATED}
    ),
    ServingMode.ELIMINATED: frozenset(),
    ServingMode.COOLDOWN: frozenset(
        {ServingMode.SHADOW, ServingMode.ELIGIBLE, ServingMode.RETURNABLE, ServingMode.ELIMINATED}
    ),
}


def can_transition(current: ServingMode, target: ServingMode) -> bool:
    """判断状态转换是否合法"""
    return target in _ALLOWED_TRANSITIONS[current]


def assert_transition(current: ServingMode, target: ServingMode) -> None:
    """校验状态转换，非法时抛出 ValueError"""
    if not can_transition(current, target):
        raise ValueError(f"非法的 serving_mode 转换: {current.value} -> {target.value}")
