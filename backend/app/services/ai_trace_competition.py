"""
织文无迹 - 多模型评估与活跃模型管理服务

核心职责：
1. 管理适合改写的模型白名单
2. 为提示词进化系统提供多模型并发评估能力
3. 持久化存储各模型的历史表现数据
4. 管理「活跃模型」配置：管理员手动选定 或 自动选择历史最优模型

使用场景：
- 提示词进化系统在后台评估时，调用 evaluate_across_models() 对所有模型评测
- 用户使用 /reduce 时，通过 get_active_model_id() 获取当前应使用的最优模型
- 管理员通过 API 查看模型表现排行并手动选定模型
"""
import asyncio
import json
import time
import hashlib
import uuid
import logging
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any

from core.unified_llm_client import get_llm_client
from core.model_resolution import build_thinking_disabled_extra_body
from app.services.zhuque_ai_detect import zhuque_ai_detect_service
from app.services.prompt_evolution.novel_rules import (
    _calculate_fidelity_score,
    preprocess_text,
    postprocess_text,
)
from app.services.prompt_evolution.genre import normalize_genre
from app.services.prompt_evolution.semantic_judge import SemanticJudge, calculate_hybrid_score
from app.services.ai_trace_storage import AtomicJsonStore
from app.services.ai_trace_storage import get_background_optimization_coordinator

logger = logging.getLogger(__name__)
# 🔧 评测口径版本（2026-10-08 提升到 v5）。
#
# 这个常量是**历史数据的有效期闸门**：读取联合表现记录时会按它过滤
# （见 get_best_combination / get_best_model_for_prompt*），
# 版本不符的记录一律不参与选型。
#
# 升级原因：v4 及以前的记录由旧 TMS 检测器产出，且排序主项是 avg_ai_score ——
# 该指标在 LLM 改写区间恒为 100（= 确定AI占比 + 疑似AI占比），
# 无法分辨「改成疑似」与「原样没动」，等于按常数排序。这批数据已整体重置。
# 现在排序主项改为 avg_ai_ratio（确定AI段落占比，实测有分辨力），
# 且检测器换成了朱雀。旧数据在新口径下不可比，故必须升版。
#
# ⚠️ 后续任何下列变更都必须再次升版，否则新旧数据会被混在一起排序：
#   检测器/网关更换、ai_score 与 ai_ratio 的口径定义变化、排序公式变化。
EVALUATION_POLICY_VERSION = "ai-trace-v5-zhuque-ai-ratio"


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class RewriteModelInfo:
    """可参与改写评估的模型信息"""
    model_id: str
    name: str
    provider: str
    quality_score: float
    cost_per_1k_input: float
    cost_per_1k_output: float
    avg_latency: float


@dataclass
class ModelPerformanceRecord:
    """单个模型的历史表现记录"""
    model_id: str
    model_name: str
    provider: str
    total_evaluations: int = 0       # 总评估次数
    total_success: int = 0           # 成功次数
    avg_ai_score: float = 100.0      # 平均AI分数（诊断用；改写区间恒为 100）
    # 🔧 选型/淘汰依据（2026-10-08 起）：改写后被判「确定AI」的段落占比均值（0-1，越低越好）。
    # 旧口径以 avg_ai_score 选型，而该值在 LLM 改写区间恒为 100，使
    # update_auto_best_model 与 evaluate_elimination 退化为按常数比较
    # —— 淘汰判据 avg_ai_score > best+20 永不成立，性能淘汰从未真正触发过。
    avg_ai_ratio: float = 1.0
    ai_ratio_m2: float = 0.0
    ai_ratio_stddev: float = 0.0
    best_ai_ratio: float = 1.0       # 历史最低确定AI占比
    avg_improvement: float = 0.0     # 平均降分幅度
    best_ai_score: float = 100.0     # 历史最佳AI分数（诊断用）
    avg_latency: float = 0.0         # 平均耗时
    last_evaluated_at: str = ""      # 最近评估时间


@dataclass
class SingleModelResult:
    """单个模型的单次评估结果"""
    model_id: str
    model_name: str
    provider: str
    reduced_text: str
    ai_score: int
    latency_seconds: float
    improvement: int = 0
    success: bool = True
    error: Optional[str] = None
    fidelity_similarity: float = 100.0
    semantic_review: Optional[Dict[str, Any]] = None
    hybrid_score: float = 100.0
    # 🔧 改写后被判「确定AI」的段落占比（0-1，越低越好）——2026-10-08 新增。
    # 为什么不是 ai_score：实测 ai_score ≈ (ai_ratio + suspect_ratio) × 100，
    # 在 LLM 改写区间恒为 100，完全不区分「确定AI」与「疑似AI」这两种天差地别的结果，
    # 而 LLM 改写的真实进步恰恰就是 AI→疑似。仅用 ai_score 排序等于按常数排序。
    ai_ratio: Optional[float] = None
    # 🔧 2026-10-17：原文（改写前）的确定AI段落占比，用于准入守门。
    # 为什么需要它：MIN_REQUIRED_IMPROVEMENT 守的是「改写是否真的有效」，
    # 而 improvement = original_score - ai_score 在 LLM 改写区间恒为 0
    # （实测 2026-10-17 01:04，9 个模型全部「降低0分」⇒ 多模型竞争 0/9 成功，
    #  且触发「上一次 0/N 成功 ⇒ 跳过本次评测」，改写模型选优永久失效）。
    # 原文 ai_ratio 在 :1271 附近已被采集，只是从未传入本结果对象。
    original_ai_ratio: Optional[float] = None


@dataclass
class CombinationPerformanceRecord:
    """题材、提示词版本与模型的联合表现。"""
    prompt_version_id: str
    prompt_text: str
    model_id: str
    model_name: str
    provider: str
    total_evaluations: int = 0
    total_success: int = 0
    avg_ai_score: float = 100.0
    # 🔧 排序依据（2026-10-08 起）：改写后被判「确定AI」的段落占比均值（0-1，越低越好）。
    # 旧口径用 avg_ai_score 作为 composite_score 的主项，而该指标在改写区间恒为 100，
    # 导致 1005 条历史记录的排序等价于按常数排序 —— 已整体重置，见
    # .workbuddy/memory/2026-10-08.md。avg_ai_score 保留作诊断，不再参与排序。
    avg_ai_ratio: float = 1.0
    ai_ratio_m2: float = 0.0
    ai_ratio_stddev: float = 0.0
    avg_improvement: float = 0.0
    avg_fidelity_similarity: float = 0.0
    avg_latency: float = 0.0
    composite_score: float = 100.0
    last_evaluated_at: str = ""
    distinct_sample_count: int = 0
    sample_hashes: List[str] = field(default_factory=list)
    worst_ai_score: float = 100.0
    ai_score_m2: float = 0.0
    ai_score_stddev: float = 0.0
    confidence_score: float = 100.0
    evaluation_policy_version: str = EVALUATION_POLICY_VERSION


def rank_by_ai_ratio(results: List[SingleModelResult]) -> List[SingleModelResult]:
    """质量门槛内按「确定AI」段落占比升序排（改写最彻底者居首）。

    🔧 2026-10-08：主键由 ai_score 改为 ai_ratio。实测
    ai_score ≈ (ai_ratio + suspect_ratio) × 100，在 LLM 改写区间恒为 100，
    按它排序等价于按常数排序（1005 条历史记录据此整体失效，见
    .workbuddy/memory/2026-10-08.md），无法分辨「确定AI→疑似」这一改写
    唯一能产生的真实进步。ai_score 保留作诊断，不再参与排序。

    资格门槛（is_eligible_result 七项）已保证质量，排序再计入质量分只会
    重复奖励少改写，使恒等映射占优（2026-08-19 玄幻轮实证：降 0 分模型
    当选最佳并被选为进化改写执行模型）。

    次序：ai_ratio ↑（缺失按最差 1.0 计，避免检测异常被当成「降得干净」）
    → 保真度 ↑（同占比时优先保留原文更多）→ 耗时 ↑。
    """
    return sorted(
        results,
        key=lambda r: (
            r.ai_ratio if r.ai_ratio is not None else 1.0,
            -r.fidelity_similarity,
            r.latency_seconds,
        ),
    )


def rank_by_ai_score(results: List[SingleModelResult]) -> List[SingleModelResult]:
    """已废弃别名：保留仅为兼容外部脚本的导入，语义同 rank_by_ai_ratio。

    名称中的 ai_score 是历史遗留，实际排序依据已是 ai_ratio。
    """
    return rank_by_ai_ratio(results)


def collect_rejection_reasons(
    result: SingleModelResult, min_improvement: int
) -> List[str]:
    """逐项推导未入选竞争的原因，供诊断日志使用（与 is_eligible_result 同步）。

    🔧 2026-10-17：准入门从 improvement 改为确定AI占比降幅后，诊断措辞同步更新。
    旧措辞「降幅0分低于门槛3分」在 LLM 改写区间恒成立，会把**检测口径问题**
    误报成**模型质量问题**（实测 9 个模型全部命中该条，
    使真实选优失效的原因在日志里完全不可见）。
    `min_improvement` 参数保留是为了兼容既有调用签名，不再参与准入门判定。
    """
    reasons: List[str] = []
    if not ModelConfigStorage._has_real_ratio_reduction(result):
        if result.ai_ratio is None:
            reasons.append("改写后确定AI占比缺失（检测失败），无法判断是否真的降下来")
        elif result.original_ai_ratio is None:
            reasons.append("原文确定AI占比缺失，无法判断是否真的降下来")
        else:
            drop = result.original_ai_ratio - result.ai_ratio
            reasons.append(
                f"确定AI占比仅从{result.original_ai_ratio:.3f}降到{result.ai_ratio:.3f}"
                f"（降{drop:.3f}，不足门槛"
                f"{ModelConfigStorage.MIN_REQUIRED_AI_RATIO_REDUCTION}）"
            )
    review = result.semantic_review or {}
    if not review.get("available"):
        if result.fidelity_similarity < ModelConfigStorage.FALLBACK_FIDELITY_SIMILARITY:
            reasons.append(
                f"评审不可用且文本相似度{result.fidelity_similarity:.0f}低于回退门槛"
            )
    else:
        if review.get("hard_fail"):
            reasons.append("评审硬失败")
        risk = review.get("over_rewrite_risk")
        if risk != "low":
            reasons.append(f"过度改写风险={risk}")
        confidence = review.get("confidence") or 0
        if confidence < SemanticJudge.MIN_CONFIDENCE:
            reasons.append(f"评审置信度低({confidence})")
        # 🔧 2026-10-17(P23) 门槛收敛：此处原先是裸字面量(80/90/75)，与下方
        # `is_eligible_result` 的准入门各写一份。两者必须同源 —— 否则会出现
        # 「诊断报某原因、但其实合格」的自相矛盾输出。
        # 唯一来源是 SemanticJudge 类常量（2026-10-16/17 立，理由见其注释）。
        for label, key, threshold in (
            ("语义保真", "semantic_fidelity", SemanticJudge.MIN_SEMANTIC_FIDELITY),
            ("事实一致", "fact_consistency", SemanticJudge.MIN_FACT_CONSISTENCY),
            ("信息完整", "information_completeness", SemanticJudge.MIN_INFORMATION_COMPLETENESS),
        ):
            score = (review.get(key) or {}).get("score", 0)
            if score < threshold:
                reasons.append(f"{label}={score}低于{threshold}")
    if result.fidelity_similarity < ModelConfigStorage.MIN_FIDELITY_SIMILARITY:
        reasons.append(
            f"文本相似度{result.fidelity_similarity:.0f}低于"
            f"{ModelConfigStorage.MIN_FIDELITY_SIMILARITY}"
        )
    return reasons


# ============================================================================
# 默认可评估模型白名单
# ============================================================================
#
# ⚠️ 降 AI 率实测战绩（2026-10-08 淘汰赛，真实朱雀网关，9 模型 10 轮 66 场）：
# 「有效」= 确定AI占比相对原文下降≥5pp 且 语义≥80/事实≥90/信息≥75/无hard_fail/篇幅≥60%
#
# | 模型                    | 场次 | 有效 | 质量合格 | 结局        |
# |-------------------------|------|------|----------|-------------|
# | doubao-seed-evolving    | 10   | 4    | 50%      | ✅ 冠军     |
# | doubao-seed-character   | 10   | 2    | 30%      | ✅ 存活     |
# | deepseek-flash          | 8    | 2    | 25%      | ❌ 三振出局 |
# | MiniMax/MiniMax-M3      | 7    | 1    | 14%      | ❌ 三振出局 |
# | glm-5.2 / step-3.7-flash / mimo-v2.6-flash / kimi-k2.6 / qwen3.7-plus | 各3 | 0 | 0% | ❌ 三振出局 |
#
# 结论：**模型选择 ≫ 提示词调参**。下列 quality_score 是通用写作质量评分，
# 与本任务（降低被判 AI 的比例）相关性很弱，不可作为选型依据。
# 且不存在通吃样本的模型：evolving 在 fantasy_001 上会翻车到 AI=1.000。

# 无管理员指定、无自动最优时的最终回退（淘汰赛冠军）
DEFAULT_REWRITE_MODEL = "doubao-seed-evolving"

REWRITE_CAPABLE_MODELS: List[RewriteModelInfo] = [
    RewriteModelInfo(
        model_id="qwen-plus",
        name="Qwen3.7 Plus",
        provider="alibaba",
        quality_score=9.2,
        cost_per_1k_input=0.002,
        cost_per_1k_output=0.008,
        avg_latency=1.6,
    ),
    RewriteModelInfo(
        model_id="deepseek-flash",
        name="DeepSeek Flash",
        provider="deepseek",
        quality_score=8.5,
        cost_per_1k_input=0.002,
        cost_per_1k_output=0.008,
        avg_latency=2.0,
    ),
    RewriteModelInfo(
        model_id="doubao-seed-character",
        name="Doubao Seed Character",
        provider="volcengine",
        quality_score=8.8,
        cost_per_1k_input=0.0012,
        cost_per_1k_output=0.006,
        avg_latency=1.5,
    ),
    RewriteModelInfo(
        model_id="kimi-preview",
        name="Kimi K2.8 Preview",
        provider="moonshot",
        quality_score=8.9,
        cost_per_1k_input=0.0065,
        cost_per_1k_output=0.027,
        avg_latency=4.5,
    ),
    RewriteModelInfo(
        model_id="glm",
        name="GLM-5.3",
        provider="zhipu",
        quality_score=9.1,
        cost_per_1k_input=0.008,
        cost_per_1k_output=0.028,
        avg_latency=2.5,
    ),
    RewriteModelInfo(
        model_id="minimax-m",
        name="MiniMax M3",
        provider="minimax",
        quality_score=9.0,
        cost_per_1k_input=0.0042,
        cost_per_1k_output=0.0168,
        avg_latency=2.2,
    ),
    RewriteModelInfo(
        model_id="mimo-flash",
        name="MiMo V2.6 Flash",
        provider="xiaomi",
        quality_score=9.0,
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.002,
        avg_latency=1.5,
    ),
    RewriteModelInfo(
        model_id="doubao-seed-evolving",
        name="Doubao Seed Evolving",
        provider="volcengine",
        quality_score=9.3,
        cost_per_1k_input=0.006,
        cost_per_1k_output=0.03,
        avg_latency=2.5,
    ),
    RewriteModelInfo(
        model_id="step-preview",
        name="Step 5 Preview",
        provider="stepfun",
        quality_score=8.8,
        cost_per_1k_input=0.007,
        cost_per_1k_output=0.02,
        avg_latency=2.0,
    ),
]

_MODEL_INFO_MAP: Dict[str, RewriteModelInfo] = {
    m.model_id: m for m in REWRITE_CAPABLE_MODELS
}


# ============================================================================
# 模型配置存储
# ============================================================================

class ModelConfigStorage:
    """模型配置与历史表现的持久化存储（按题材分离）"""

    DEFAULT_GENRE = "通用"
    MIN_FIDELITY_SIMILARITY = 25.0
    FALLBACK_FIDELITY_SIMILARITY = 70.0
    EVALUATION_DETAIL_LIMIT = 5000
    AVAILABILITY_FAILURE_THRESHOLD = 3
    # 🎯 最低降幅门槛：降幅不足此值的结果没有竞争与统计价值，不进本次
    # 成功列表、不计历史表现（零降幅恒等映射曾当选最佳并抑制进化，
    # 2026-08-19 玄幻轮取证）
    MIN_REQUIRED_IMPROVEMENT = 3
    # 🔧 2026-10-17：准入守门改用「确定AI占比」的绝对降幅（0-1 尺度）。
    #
    # 为什么废弃 MIN_REQUIRED_IMPROVEMENT 作为准入门：
    # improvement = original_score - ai_score。ai_score 把「确定AI」与「疑似AI」
    # 合并计数，LLM 改写的典型效果（AI→疑似）不会让它下降，于是 improvement
    # 对改写效果**不敏感**（实测 2026-10-17 01:04~01:05，9 个模型全部
    # 「AI分数=100, 降低0分」⇒ `多模型评估完成: 0/9 成功`）。由于存在
    # 「上一次多模型评测 0/N 成功 ⇒ 跳过本次评测」的逻辑，
    # 一旦 0/9 就会持续跳过，改写模型选优永久失效。
    #
    # 为什么不能简单删掉这道门：该门 2026-08-19 是为防「零降幅恒等映射
    # 当选最佳并抑制进化」而加的，删掉等于让原样返回的模型重新当选最佳。
    # 因此换成等价守门：原文确定AI占比必须比改写后高出 MIN_REQUIRED_AI_RATIO_REDUCTION
    # 以上，否则视为「没实际降下来」，零降幅恒等映射仍被排除。
    #
    # 取值 0.05 的依据：真实档期跨版本 ratio 跨度实测 0.169
    # （如 0.4024 → 0.3053），单轮改写的典型改善在 0.05~0.15 量级；
    # 0.05 明显高于朱雀噪声级（重复检测同文本波动约 0.01），
    # 又不会把真实有效的小幅改善挡在门外。
    MIN_REQUIRED_AI_RATIO_REDUCTION = 0.05

    @classmethod
    def _has_real_ratio_reduction(cls, result: SingleModelResult) -> bool:
        """准入守门：改写后确定AI占比必须比原文有实质下降。

        口径选择（与 rank_by_ai_ratio 一致）：
        - ai_ratio 缺失（检测失败）⇒ 不通过。「测不出」不能当成「很干净」，
          否则检测异常的模型会挤掉真实有效的模型。
        - 原文 ai_ratio 缺失 ⇒ 不通过。无法判断是否有改善，
          此时放行等于重新引入 2026-08-19 的恒等映射病。
        """
        if result.ai_ratio is None or result.original_ai_ratio is None:
            return False
        return (
            result.original_ai_ratio - result.ai_ratio
            >= cls.MIN_REQUIRED_AI_RATIO_REDUCTION
        )

    @staticmethod
    def describe_ratio_reduction(result: SingleModelResult) -> str:
        """🔧 2026-10-17：产出有分辨力的改写效果描述（0-1 ratio 口径）。

        为什么不用 improvement：它是 `original_score - ai_score`。ai_score 合并了
        「确定AI」与「疑似AI」两类计数，对「AI→疑似」这种最典型的改写进步
        **不敏感**（实测 P18：7 个模型全部「降低0分」，而同期 ratio 从
        0.530 到 1.000 差异巨大）。用 improvement 描述效果等于对所有模型
        输出同一句话 —— 既零信息量，又会让人误以为「这些模型都没效果」。

        实测同一轮里 Doubao Seed Evolving 是 0.720→0.530（真实有效），
        DeepSeek Flash 是 1.000→1.000（恒等映射），必须一眼可区分。

        ratio 缺失时明说「不可用」，绝不编造降幅 ——
        「测不出」与「没降下来」是相反的结论。
        """
        if result.ai_ratio is None:
            return "确定AI占比不可用（改写后检测失败）"
        if result.original_ai_ratio is None:
            return f"确定AI占比={result.ai_ratio:.3f}（原文占比缺失，无法判断降幅）"
        drop = result.original_ai_ratio - result.ai_ratio
        return (
            f"确定AI占比 {result.original_ai_ratio:.3f}→{result.ai_ratio:.3f}"
            f"（降{drop:.3f}）"
        )

    @classmethod
    def is_eligible_result(cls, result: SingleModelResult) -> bool:
        """只有完整成功、确定AI占比有实质下降且满足保真门槛的结果才能参与竞争统计。"""
        if not result.success:
            return False
        if not cls._has_real_ratio_reduction(result):
            return False
        review = result.semantic_review or {}
        if not review.get("available"):
            return result.fidelity_similarity >= cls.FALLBACK_FIDELITY_SIMILARITY
        return (
            not review.get("hard_fail")
            and review.get("over_rewrite_risk") == "low"
            # 🔧 2026-10-17(P23)：门槛收敛为引用 SemanticJudge 类常量，
            # 与 collect_rejection_reasons 的诊断措辞同源（原先两处各写一份）。
            and review.get("confidence", 0) >= SemanticJudge.MIN_CONFIDENCE
            and (review.get("semantic_fidelity") or {}).get("score", 0)
                >= SemanticJudge.MIN_SEMANTIC_FIDELITY
            and (review.get("fact_consistency") or {}).get("score", 0)
                >= SemanticJudge.MIN_FACT_CONSISTENCY
            and (review.get("information_completeness") or {}).get("score", 0)
                >= SemanticJudge.MIN_INFORMATION_COMPLETENESS
            and result.fidelity_similarity >= cls.MIN_FIDELITY_SIMILARITY
        )

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.storage_dir / "model_config.json"
        self.performance_file = self.storage_dir / "model_performance.json"
        self.combination_performance_file = self.storage_dir / "model_prompt_performance.json"
        self.evaluation_details_file = self.storage_dir / "model_evaluation_details.json"
        self._config_store = AtomicJsonStore(self.config_file)
        self._performance_store = AtomicJsonStore(self.performance_file)
        self._combination_store = AtomicJsonStore(self.combination_performance_file)
        self._details_store = AtomicJsonStore(self.evaluation_details_file)
        # 首次加载时执行数据迁移
        self._migrate_if_needed()

    def _migrate_if_needed(self) -> None:
        """向后兼容：将旧的全局性能数据迁移至'通用'题材下"""
        if not self.performance_file.exists():
            return
        try:
            with open(self.performance_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                return
            # 旧格式的顶层 value 是单个性能记录；新格式的顶层 value 是模型映射。
            first_value = next(iter(data.values()))
            is_legacy = isinstance(first_value, dict) and "model_id" in first_value
            if is_legacy:
                # 旧格式 → 迁移到 "通用" 下
                migrated = {self.DEFAULT_GENRE: data}
                with open(self.performance_file, "w", encoding="utf-8") as f:
                    json.dump(migrated, f, ensure_ascii=False, indent=2)
                logger.info("📦 模型性能数据已迁移至按题材分离的新格式")
                # 同步迁移 config 中的 auto_best_model → auto_best_by_genre
                config = self.load_config()
                old_auto = config.get("auto_best_model")
                if old_auto and "auto_best_by_genre" not in config:
                    config["auto_best_by_genre"] = {self.DEFAULT_GENRE: old_auto}
                    config.pop("auto_best_model", None)
                    self.save_config(config)
        except (json.JSONDecodeError, IOError, StopIteration):
            pass

    def load_config(self) -> Dict[str, Any]:
        """加载模型配置（含管理员选定的活跃模型、连续失败跳隔计数）"""
        data = self._config_store.read()
        if data:
            data.setdefault("admin_selected_model", None)
            data.setdefault("auto_best_by_genre", {})
            data.setdefault("consecutive_mm_fail_count", 0)  # 🔧 全 0/N 成功时累加，跳过后续评测
            return data
        return {
            "admin_selected_model": None,  # 管理员手动选定的模型ID（全局覆盖）
            "auto_best_by_genre": {},      # 按题材自动最优 {"通用": "model_id", "玄幻": ...}
            "updated_at": "",
            "consecutive_mm_fail_count": 0,
        }

    def save_config(self, config: Dict[str, Any]) -> None:
        """保存模型配置"""
        from datetime import datetime
        config["updated_at"] = datetime.now().isoformat()
        self._config_store.write(config)

    def update_availability_status(
        self, result: SingleModelResult, genre: Optional[str] = None
    ) -> int:
        """按题材记录连续调用失败，并在达到阈值后临时熔断模型。"""
        target_genre = normalize_genre(genre)

        def update(config: Dict[str, Any]) -> Dict[str, Any]:
            failures = config.setdefault("availability_failures", {}).setdefault(target_genre, {})
            current = int(failures.get(result.model_id, 0))
            next_count = 0 if result.success else current + 1
            failures[result.model_id] = next_count
            if next_count >= self.AVAILABILITY_FAILURE_THRESHOLD:
                eliminated = config.setdefault("eliminated_models", {}).setdefault(target_genre, [])
                if result.model_id not in eliminated:
                    # 存活模型地板保护：降到下限后不再熔断淘汰，避免可用模型池见底
                    alive_count = sum(
                        1 for m in REWRITE_CAPABLE_MODELS
                        if m.model_id not in set(eliminated)
                    )
                    if alive_count > self.MIN_ALIVE_MODELS:
                        eliminated.append(result.model_id)
                    else:
                        logger.warning(
                            f"⚠️ 熔断地板保护[{target_genre}]: {result.model_id} 连续失败达阈值，"
                            f"但存活模型已至下限（{self.MIN_ALIVE_MODELS}），暂不淘汰"
                        )
            return config

        updated = self._config_store.update(update)
        return int(updated.get("availability_failures", {}).get(target_genre, {}).get(result.model_id, 0))

    def set_admin_model(self, model_id: Optional[str]) -> None:
        """管理员手动设置活跃模型（传 None 则清除选定，回退到自动最优）"""
        def update(config: Dict[str, Any]) -> Dict[str, Any]:
            config["admin_selected_model"] = model_id
            config["updated_at"] = datetime.now().isoformat()
            return config

        from datetime import datetime
        self._config_store.update(update)
        logger.info(f"管理员设置活跃模型: {model_id or '(自动最优)'}")

    def get_active_model_id(self, genre: Optional[str] = None) -> Optional[str]:
        """
        获取当前活跃模型ID

        优先级：管理员选定 > 该题材自动最优 > 通用自动最优 > None
        """
        config = self.load_config()
        # 优先管理员选定（全局覆盖）
        admin_model = config.get("admin_selected_model")
        if admin_model and admin_model in _MODEL_INFO_MAP:
            return admin_model
        # 其次按题材自动最优
        auto_best_by_genre = config.get("auto_best_by_genre", {})
        # 兼容旧格式
        if not auto_best_by_genre and config.get("auto_best_model"):
            auto_best_by_genre = {self.DEFAULT_GENRE: config["auto_best_model"]}
        target_genre = normalize_genre(genre)
        # 优先该题材，回退通用
        auto_best = auto_best_by_genre.get(target_genre)
        if auto_best and auto_best in _MODEL_INFO_MAP:
            return auto_best
        if target_genre != self.DEFAULT_GENRE:
            auto_best = auto_best_by_genre.get(self.DEFAULT_GENRE)
            if auto_best and auto_best in _MODEL_INFO_MAP:
                return auto_best
        # 🔧 最终回退：返回淘汰赛冠军而非 None（2026-10-08 实测）。
        # 原先返回 None 时调用方只能走「默认路由」，而通用写作质量分最高的模型
        # 在本任务上并无优势（实测 qwen3.7-plus 平均降幅为负）。
        if DEFAULT_REWRITE_MODEL in _MODEL_INFO_MAP:
            return DEFAULT_REWRITE_MODEL
        return None

    def load_performance(self, genre: Optional[str] = None) -> Dict[str, ModelPerformanceRecord]:
        """
        加载模型历史表现数据

        Args:
            genre: 指定题材（None 返回通用题材数据）
        """
        all_data = self._performance_store.read()

        target_genre = normalize_genre(genre)
        genre_data = all_data.get(target_genre, {})
        try:
            return {k: ModelPerformanceRecord(**v) for k, v in genre_data.items()}
        except TypeError:
            return {}

    def load_all_performance(self) -> Dict[str, Dict[str, ModelPerformanceRecord]]:
        """加载所有题材的模型表现（用于管理页展示）"""
        if not self.performance_file.exists():
            return {}
        try:
            with open(self.performance_file, "r", encoding="utf-8") as f:
                all_data = json.load(f)
            result = {}
            for genre_key, genre_records in all_data.items():
                result[genre_key] = {
                    k: ModelPerformanceRecord(**v) for k, v in genre_records.items()
                }
            return result
        except (json.JSONDecodeError, IOError, TypeError):
            return {}

    def load_aggregated_performance(self) -> Dict[str, ModelPerformanceRecord]:
        """聚合所有题材的模型表现（"通用"视角展示用）

        评测数据按题材分库存储，"通用"键下通常没有记录；
        该方法把各题材数据加权合并成跨题材汇总视图。
        """
        merged: Dict[str, ModelPerformanceRecord] = {}
        for genre_records in self.load_all_performance().values():
            for model_id, rec in genre_records.items():
                agg = merged.get(model_id)
                if agg is None:
                    merged[model_id] = replace(rec)
                    continue
                total_success = agg.total_success + rec.total_success
                if total_success > 0:
                    # 平均值只在成功样本上累计，按成功次数加权合并
                    agg.avg_ai_score = (
                        agg.avg_ai_score * agg.total_success + rec.avg_ai_score * rec.total_success
                    ) / total_success
                    # 🔧 选型主项（2026-10-08 起）按同样口径加权合并
                    agg.avg_ai_ratio = (
                        agg.avg_ai_ratio * agg.total_success + rec.avg_ai_ratio * rec.total_success
                    ) / total_success
                    agg.avg_improvement = (
                        agg.avg_improvement * agg.total_success + rec.avg_improvement * rec.total_success
                    ) / total_success
                    agg.avg_latency = (
                        agg.avg_latency * agg.total_success + rec.avg_latency * rec.total_success
                    ) / total_success
                agg.total_evaluations += rec.total_evaluations
                agg.total_success = total_success
                agg.best_ai_score = min(agg.best_ai_score, rec.best_ai_score)
                agg.best_ai_ratio = min(agg.best_ai_ratio, rec.best_ai_ratio)
                agg.last_evaluated_at = max(agg.last_evaluated_at, rec.last_evaluated_at)
        return merged

    def save_performance(self, records: Dict[str, ModelPerformanceRecord], genre: Optional[str] = None) -> None:
        """保存指定题材的模型表现数据"""
        target_genre = normalize_genre(genre)
        # 读取全量数据
        serialized = {k: asdict(v) for k, v in records.items()}
        self._performance_store.update(
            lambda all_data: {**all_data, target_genre: serialized}
        )

    def update_performance(self, result: SingleModelResult, genre: Optional[str] = None) -> None:
        """根据单次评估结果更新模型表现记录"""
        from datetime import datetime
        target_genre = normalize_genre(genre)

        def update(all_data: Dict[str, Any]) -> Dict[str, Any]:
            genre_data = all_data.setdefault(target_genre, {})
            raw = genre_data.get(result.model_id)
            rec = ModelPerformanceRecord(**raw) if raw else ModelPerformanceRecord(
                model_id=result.model_id,
                model_name=result.model_name,
                provider=result.provider,
            )
            rec.total_evaluations += 1
            if self.is_eligible_result(result):
                rec.total_success += 1
                n = rec.total_success
                rec.avg_ai_score = rec.avg_ai_score * (n - 1) / n + result.ai_score / n
                # 🔧 确定AI占比的在线均值/方差（Welford）。缺失按最差 1.0 计，
                # 避免检测异常被误判为「降得干净」而占便宜。
                ratio = result.ai_ratio if result.ai_ratio is not None else 1.0
                ratio_prev = rec.avg_ai_ratio if n > 1 else float(ratio)
                rec.avg_ai_ratio = ratio_prev + (ratio - ratio_prev) / n
                rec.ai_ratio_m2 += (ratio - ratio_prev) * (ratio - rec.avg_ai_ratio)
                rec.ai_ratio_stddev = (rec.ai_ratio_m2 / (n - 1)) ** 0.5 if n > 1 else 0.0
                rec.best_ai_ratio = min(
                    rec.best_ai_ratio if n > 1 else float(ratio), ratio
                )
                # ⚠️ avg_improvement 的分辨力问题（2026-10-17 取证修正）。
                # 它**并非数学上恒为 0** —— ai_score = ratio_confidence × 100，
                # 只要改写结果里出现人工段落（label=0），它就会下降。
                # 但它分辨不出 LLM 改写的真实进步：ai_score 把「确定AI(1)」与
                # 「疑似AI(2)」合并计数，而改写的典型效果正是 AI→疑似，
                # 这一步 ratio_confidence 不变 ⇒ improvement 仍为 0。
                # P18 实测印证：多数模型 1.000→1.000（降0.000），原文带人工
                # 段落的样本（如 Kimi 0.910）也只因口径合并而不体现降幅。
                # 故排序与准入一律用 avg_ai_ratio，**不要把本字段当主要指标**。
                rec.avg_improvement = rec.avg_improvement * (n - 1) / n + result.improvement / n
                rec.avg_latency = rec.avg_latency * (n - 1) / n + result.latency_seconds / n
                rec.best_ai_score = min(rec.best_ai_score, result.ai_score)
            rec.last_evaluated_at = datetime.now().isoformat()
            genre_data[result.model_id] = asdict(rec)
            return all_data

        self._performance_store.update(update)

    def load_combination_performance(
        self, genre: Optional[str] = None
    ) -> Dict[str, Dict[str, CombinationPerformanceRecord]]:
        """加载指定题材下按提示词版本和模型分组的联合表现。"""
        try:
            all_data = self._combination_store.read()
            genre_data = all_data.get(normalize_genre(genre), {})
            return {
                prompt_id: {
                    model_id: CombinationPerformanceRecord(**record)
                    for model_id, record in models.items()
                }
                for prompt_id, models in genre_data.items()
            }
        except (json.JSONDecodeError, IOError, TypeError):
            return {}

    def load_all_combination_performance(
        self,
    ) -> Dict[str, Dict[str, Dict[str, CombinationPerformanceRecord]]]:
        """加载所有题材的联合表现（"通用"视角合并展示用）"""
        try:
            all_data = self._combination_store.read()
            return {
                genre_key: {
                    prompt_id: {
                        model_id: CombinationPerformanceRecord(**record)
                        for model_id, record in models.items()
                    }
                    for prompt_id, models in genre_data.items()
                }
                for genre_key, genre_data in all_data.items()
            }
        except (json.JSONDecodeError, IOError, TypeError):
            return {}

    def save_combination_performance(
        self,
        records: Dict[str, Dict[str, CombinationPerformanceRecord]],
        genre: Optional[str] = None,
    ) -> None:
        """更新指定题材的联合表现存储桶。"""
        genre_data = {
            prompt_id: {model_id: asdict(record) for model_id, record in models.items()}
            for prompt_id, models in records.items()
        }
        target_genre = normalize_genre(genre)
        self._combination_store.update(
            lambda all_data: {**all_data, target_genre: genre_data}
        )

    def update_combination_performance(
        self,
        result: SingleModelResult,
        genre: Optional[str],
        prompt_version_id: str,
        prompt_text: str,
        sample_hash: Optional[str] = None,
    ) -> None:
        """增量更新一个模型与提示词版本的联合表现。"""
        from datetime import datetime

        target_genre = normalize_genre(genre)

        def update(all_data: Dict[str, Any]) -> Dict[str, Any]:
            prompt_records = all_data.setdefault(target_genre, {}).setdefault(prompt_version_id, {})
            raw = prompt_records.get(result.model_id)
            record = CombinationPerformanceRecord(**raw) if raw else CombinationPerformanceRecord(
                prompt_version_id=prompt_version_id,
                prompt_text=prompt_text,
                model_id=result.model_id,
                model_name=result.model_name,
                provider=result.provider,
            )
            record.total_evaluations += 1
            if self.is_eligible_result(result):
                record.total_success += 1
                n = record.total_success
                previous_mean = record.avg_ai_score if n > 1 else float(result.ai_score)
                record.avg_ai_score = previous_mean + (result.ai_score - previous_mean) / n
                record.ai_score_m2 += (result.ai_score - previous_mean) * (result.ai_score - record.avg_ai_score)
                record.ai_score_stddev = (record.ai_score_m2 / (n - 1)) ** 0.5 if n > 1 else 0.0
                # 🔧 「确定AI」段落占比的在线均值/方差（Welford）。缺失时按最差 1.0 计，
                # 避免检测异常被误判为「降得很干净」而占到便宜。
                ratio = result.ai_ratio if result.ai_ratio is not None else 1.0
                ratio_prev = record.avg_ai_ratio if n > 1 else float(ratio)
                record.avg_ai_ratio = ratio_prev + (ratio - ratio_prev) / n
                record.ai_ratio_m2 += (ratio - ratio_prev) * (ratio - record.avg_ai_ratio)
                record.ai_ratio_stddev = (record.ai_ratio_m2 / (n - 1)) ** 0.5 if n > 1 else 0.0
                # ⚠️ 同 update_performance 的口径说明：avg_improvement 不是恒 0，
                # 但把确定AI与疑似AI合并计数，分辨不出 AI→疑似 这类真实进步，
                # 故仅作历史存档保留，不参与排序与准入。
                record.avg_improvement = record.avg_improvement * (n - 1) / n + result.improvement / n
                record.avg_fidelity_similarity = record.avg_fidelity_similarity * (n - 1) / n + result.fidelity_similarity / n
                record.avg_latency = record.avg_latency * (n - 1) / n + result.latency_seconds / n
                record.worst_ai_score = max(result.ai_score, record.worst_ai_score if n > 1 else result.ai_score)
                # 🔧 综合分主项由 avg_ai_score 改为 avg_ai_ratio（2026-10-08）：
                # ai_score 恒为 100 使旧公式等价于常数 + 保真项，选不出真正有效的模型。
                # 新公式主项 = 确定AI占比（0-100 标度），保真仍作次要约束（权重 0.2）。
                record.composite_score = (
                    record.avg_ai_ratio * 100.0 + (100 - record.avg_fidelity_similarity) * 0.2
                )
                record.confidence_score = (
                    record.composite_score + record.ai_ratio_stddev * 100.0 / max(n ** 0.5, 1.0)
                )
                if sample_hash and sample_hash not in record.sample_hashes:
                    record.sample_hashes = (record.sample_hashes + [sample_hash])[-50:]
                    record.distinct_sample_count = len(record.sample_hashes)
            record.last_evaluated_at = datetime.now().isoformat()
            prompt_records[result.model_id] = asdict(record)
            return all_data

        self._combination_store.update(update)

    def get_best_combination(
        self,
        genre: Optional[str],
        min_success: int = 3,
        min_fidelity_similarity: float = 25.0,
    ) -> Optional[CombinationPerformanceRecord]:
        """在保真门槛和样本门槛后选择综合分最低的联合记录。"""
        records = self.load_combination_performance(genre)
        qualified = [
            record
            for models in records.values()
            for record in models.values()
            if record.total_success >= min_success
            and record.avg_fidelity_similarity >= min_fidelity_similarity
            and record.evaluation_policy_version == EVALUATION_POLICY_VERSION
        ]
        return min(qualified, key=lambda record: record.confidence_score) if qualified else None

    def get_best_model_for_prompt(
        self,
        genre: Optional[str],
        prompt_text: str,
        min_success: int = 3,
    ) -> Optional[CombinationPerformanceRecord]:
        """仅在最终选中的提示词范围内选择满足质量门槛的模型。"""
        records = self.load_combination_performance(genre)
        qualified = [
            record
            for models in records.values()
            for record in models.values()
            if record.prompt_text == prompt_text
            and record.total_success >= min_success
            and record.avg_fidelity_similarity >= self.MIN_FIDELITY_SIMILARITY
            and record.distinct_sample_count >= min_success
            and record.evaluation_policy_version == EVALUATION_POLICY_VERSION
        ]
        return min(qualified, key=lambda record: record.confidence_score) if qualified else None

    def get_best_model_for_prompt_version(
        self, genre: Optional[str], prompt_version_id: str, min_success: int = 3
    ) -> Optional[CombinationPerformanceRecord]:
        records = self.load_combination_performance(genre)
        qualified = [
            record for record in records.get(prompt_version_id, {}).values()
            if record.total_success >= min_success
            and record.distinct_sample_count >= min_success
            and record.avg_fidelity_similarity >= self.MIN_FIDELITY_SIMILARITY
            and record.evaluation_policy_version == EVALUATION_POLICY_VERSION
        ]
        return min(qualified, key=lambda record: record.confidence_score) if qualified else None

    def record_evaluation_detail(self, detail: Dict[str, Any]) -> None:
        """追加不可变评测事实，供审计、指标和汇总重建使用。"""
        item = dict(detail)
        item["genre"] = normalize_genre(item.get("genre"))
        self._details_store.update(lambda data: {
            **data,
            "records": [*data.get("records", []), item][-self.EVALUATION_DETAIL_LIMIT:],
        })

    def load_evaluation_details(self, genre: Optional[str] = None) -> List[Dict[str, Any]]:
        records = self._details_store.read().get("records", [])
        if genre is None:
            return records
        target = normalize_genre(genre)
        return [item for item in records if normalize_genre(item.get("genre")) == target]

    def get_evaluation_metrics(self, genre: Optional[str] = None) -> Dict[str, Any]:
        # "通用"视角下统计全部题材的评测事实（数据按具体题材记录）
        target = normalize_genre(genre)
        records = self.load_evaluation_details(None if target == self.DEFAULT_GENRE else target)
        total = len(records)
        successes = sum(bool(item.get("success")) for item in records)
        rejected = sum(not bool(item.get("fidelity_eligible", True)) for item in records)
        timeouts = sum(item.get("error_type") == "timeout" for item in records)
        return {
            "total": total,
            "success_rate": successes / total if total else 0.0,
            "fidelity_rejection_rate": rejected / total if total else 0.0,
            "timeout_count": timeouts,
        }

    def update_auto_best_model(self, genre: Optional[str] = None) -> Optional[str]:
        """根据历史表现自动计算并更新该题材的最优模型"""
        target_genre = normalize_genre(genre)
        records = self.load_performance(target_genre)
        if not records:
            return None

        # 筛选至少评估过3次的模型
        qualified = {
            k: v for k, v in records.items()
            if v.total_success >= 3
        }
        if not qualified:
            return None

        # 按「确定AI」段落占比升序（越低越好）
        # 🔧 2026-10-08：主键由 avg_ai_score 改为 avg_ai_ratio。旧口径下该值恒为 100，
        # 此函数等价于从字典里随便取一个（按插入序），会把已被淘汰/表现差的模型
        # 写进 auto_best_by_genre，进而左右题材路由。
        best_model_id = min(qualified, key=lambda k: qualified[k].avg_ai_ratio)
        config = self.load_config()
        auto_best_by_genre = config.get("auto_best_by_genre", {})
        auto_best_by_genre[target_genre] = best_model_id
        config["auto_best_by_genre"] = auto_best_by_genre
        self.save_config(config)

        logger.info(
            f"自动最优模型更新[{target_genre}]: {best_model_id} "
            f"(avg_ai_ratio={qualified[best_model_id].avg_ai_ratio:.4f}, "
            f"n={qualified[best_model_id].total_success})"
        )
        return best_model_id

    # ====== 淘汰与轮换机制 ======

    ELIMINATION_MIN_EVALS = 5       # 至少评估N次后才参与淘汰判定
    ELIMINATION_MIN_MODELS = 2      # 至少N个成熟模型后才开始横向比较
    ELIMINATION_SCORE_GAP = 20      # 与最佳模型分差超过此值则淘汰
    MIN_ALIVE_MODELS = 6            # 淘汰后至少保留N个存活模型（性能淘汰与熔断共用地板），关思考后放宽到6
    CHALLENGE_INTERVAL = 5          # 每N轮进化迭代触发一次挑战赛
    CHALLENGE_PICK_COUNT = 1        # 每次挑战赛从淘汰池选取的模型数
    CHALLENGE_REVIVE_RANK = 3       # 挑战者进入前N名时复活

    def get_eliminated_models(self, genre: Optional[str] = None) -> List[str]:
        """获取指定题材下被淘汰的模型ID列表"""
        config = self.load_config()
        eliminated = config.get("eliminated_models", {})
        target_genre = normalize_genre(genre)
        return eliminated.get(target_genre, [])

    def get_active_models(self, genre: Optional[str] = None) -> List[RewriteModelInfo]:
        """获取排除淘汰后的活跃参与模型列表"""
        eliminated = set(self.get_eliminated_models(genre))
        return [m for m in REWRITE_CAPABLE_MODELS if m.model_id not in eliminated]

    def evaluate_elimination(self, genre: Optional[str] = None) -> List[str]:
        """
        评估淘汰：根据当前题材表现数据，淘汰表现差的模型。

        Returns:
            新增被淘汰的模型ID列表
        """
        target_genre = normalize_genre(genre)
        records = self.load_performance(target_genre)
        if not records:
            return []

        # 找出有足够评估次数的模型
        qualified = {
            k: v for k, v in records.items()
            if v.total_success >= self.ELIMINATION_MIN_EVALS
        }
        if len(qualified) < self.ELIMINATION_MIN_MODELS:
            return []

        # 找到当前最佳（确定AI占比最低）
        # 🔧 2026-10-08：主键由 avg_ai_score 改为 avg_ai_ratio。旧口径下
        # avg_ai_score 恒为 100 → threshold = 120 → 判据 avg_ai_score > 120
        # 永不成立，性能淘汰从未真正触发过（此前仅三振熔断在起作用）。
        # ELIMINATION_SCORE_GAP 仍以「百分点」计，故此处换算到 0-100 标度比较。
        best_score = min(v.avg_ai_ratio for v in qualified.values()) * 100.0

        # 淘汰门槛
        threshold = best_score + self.ELIMINATION_SCORE_GAP

        # 找出应被淘汰的模型（按确定AI占比降序从最差开始，保留至少 MIN_ALIVE_MODELS 个存活模型）
        config = self.load_config()
        eliminated_map = config.get("eliminated_models", {})
        current_eliminated = set(eliminated_map.get(target_genre, []))

        candidates = [
            model_id for model_id, rec in qualified.items()
            if model_id not in current_eliminated and rec.avg_ai_ratio * 100.0 > threshold
        ]
        candidates.sort(key=lambda mid: -records[mid].avg_ai_ratio)

        alive_count = sum(
            1 for m in REWRITE_CAPABLE_MODELS if m.model_id not in current_eliminated
        )
        quota = max(0, alive_count - self.MIN_ALIVE_MODELS)
        newly_eliminated = candidates[:quota]
        for model_id in newly_eliminated:
            current_eliminated.add(model_id)
        if len(candidates) > quota:
            logger.warning(
                f"⚠️ 淘汰地板保护[{target_genre}]: {len(candidates) - quota} 个模型达淘汰门槛，"
                f"因存活模型下限（{self.MIN_ALIVE_MODELS}）保留"
            )

        if newly_eliminated:
            eliminated_map[target_genre] = list(current_eliminated)
            config["eliminated_models"] = eliminated_map
            self.save_config(config)
            for mid in newly_eliminated:
                name = _MODEL_INFO_MAP[mid].name if mid in _MODEL_INFO_MAP else mid
                logger.info(
                    f"🚫 模型淘汰[{target_genre}]: {name} "
                    f"(avg={records[mid].avg_ai_score:.1f}, 门槛={threshold:.1f})"
                )

        return newly_eliminated

    def get_challenge_candidates(self, genre: Optional[str] = None) -> List[str]:
        """从淘汰池中选取挑战赛候选模型"""
        import random
        eliminated = self.get_eliminated_models(genre)
        if not eliminated:
            return []
        pick = min(self.CHALLENGE_PICK_COUNT, len(eliminated))
        return random.sample(eliminated, pick)

    def process_challenge_results(
        self,
        genre: Optional[str] = None,
        challenge_results: List[SingleModelResult] = None,
        all_results: List[SingleModelResult] = None,
    ) -> List[str]:
        """
        处理挑战赛结果：表现进入前三名的模型复活。

        Args:
            genre: 题材
            challenge_results: 挑战赛模型的评估结果
            all_results: 本轮全部模型的评估结果（含挑战者）

        Returns:
            复活的模型ID列表
        """
        if not challenge_results or not all_results:
            return []

        target_genre = normalize_genre(genre)

        # 固定前三名；同分时按模型 ID 稳定排序，避免阈值同分扩大名额。
        # 🔧 2026-10-08：主键由 ai_score 改为 ai_ratio（ai_score 在改写区间恒为 100，
        # 旧排序实际只按 model_id 字典序，复活名额会被名称顺序决定）。
        # 缺失 ai_ratio 按最差 1.0 计，避免检测异常者凭名字占优。
        successful = sorted(
            (r for r in all_results if self.is_eligible_result(r)),
            key=lambda result: (
                result.ai_ratio if result.ai_ratio is not None else 1.0,
                result.model_id,
            ),
        )
        if not successful:
            return []
        qualifying_count = min(self.CHALLENGE_REVIVE_RANK, len(successful))
        qualifying_ids = {result.model_id for result in successful[:qualifying_count]}

        # 判断挑战者是否复活
        revived = []
        for cr in challenge_results:
            if self.is_eligible_result(cr) and cr.model_id in qualifying_ids:
                revived.append(cr.model_id)

        if revived:
            # 从淘汰池中移除复活的模型
            config = self.load_config()
            eliminated_map = config.get("eliminated_models", {})
            current_eliminated = eliminated_map.get(target_genre, [])
            current_eliminated = [m for m in current_eliminated if m not in revived]
            eliminated_map[target_genre] = current_eliminated
            config["eliminated_models"] = eliminated_map
            self.save_config(config)

            # 旧历史清零，挑战通过结果作为新竞争周期的第一条记录。
            records = self.load_performance(target_genre)
            for mid in revived:
                challenge = next(result for result in challenge_results if result.model_id == mid)
                challenge_ratio = (
                    challenge.ai_ratio if challenge.ai_ratio is not None else 1.0
                )
                records[mid] = ModelPerformanceRecord(
                    model_id=challenge.model_id,
                    model_name=challenge.model_name,
                    provider=challenge.provider,
                    total_evaluations=1,
                    total_success=1,
                    avg_ai_score=float(challenge.ai_score),
                    # 🔧 新周期的第一条记录必须带上选型主项，否则复活模型
                    # 会带着 avg_ai_ratio=1.0 的默认值参与下一轮横向比较
                    avg_ai_ratio=challenge_ratio,
                    best_ai_ratio=challenge_ratio,
                    avg_improvement=float(challenge.improvement),
                    best_ai_score=float(challenge.ai_score),
                    avg_latency=challenge.latency_seconds,
                )
            self.save_performance(records, target_genre)

            config = self.load_config()
            failures = config.setdefault("availability_failures", {}).setdefault(target_genre, {})
            for mid in revived:
                failures[mid] = 0
            self.save_config(config)

            for mid in revived:
                name = _MODEL_INFO_MAP[mid].name if mid in _MODEL_INFO_MAP else mid
                logger.info(f"✅ 模型复活[{target_genre}]: {name} (挑战赛通过)")

        return revived

    def record_regular_evaluation_round(self, genre: Optional[str] = None) -> int:
        """增加题材级单调评测轮次并返回新计数。"""
        target_genre = normalize_genre(genre)
        config = self.load_config()
        rounds = config.get("evaluation_rounds_by_genre", {})
        rounds[target_genre] = int(rounds.get(target_genre, 0)) + 1
        config["evaluation_rounds_by_genre"] = rounds
        self.save_config(config)
        return rounds[target_genre]

    def should_run_challenge(self, genre: Optional[str] = None, current_iteration: int = 0) -> bool:
        """判断当前迭代是否应该运行挑战赛"""
        target_genre = normalize_genre(genre)
        eliminated = self.get_eliminated_models(target_genre)
        if not eliminated:
            return False
        config = self.load_config()
        last_challenge = config.get("last_challenge_iteration", {})
        rounds = config.get("evaluation_rounds_by_genre", {})
        current_round = int(rounds.get(target_genre, 0))
        last_round = int(last_challenge.get(target_genre, 0))
        return (current_round - last_round) >= self.CHALLENGE_INTERVAL

    def mark_challenge_done(self, genre: Optional[str] = None, iteration: int = 0) -> None:
        """标记挑战赛已在某迭代执行"""
        target_genre = normalize_genre(genre)
        config = self.load_config()
        last_challenge = config.get("last_challenge_iteration", {})
        rounds = config.get("evaluation_rounds_by_genre", {})
        last_challenge[target_genre] = int(rounds.get(target_genre, 0))
        config["last_challenge_iteration"] = last_challenge
        self.save_config(config)


# ============================================================================
# 多模型评估服务（服务于提示词进化系统 & 管理员评测）
# ============================================================================

class MultiModelEvaluationService:
    """
    多模型评估服务

    核心用途：
    1. 提示词进化系统在每次迭代时调用，评估当前提示词在所有模型上的效果
    2. 管理员手动触发全模型评测，查看表现排行
    """

    MODEL_CONCURRENCY = 8
    DETECT_CONCURRENCY = 3
    SINGLE_MODEL_TIMEOUT = 90.0
    # 🔧 多模型评测默认关思考：改写+检测+评审链路属风格转换/清单打分任务，
    #    无深度推理收益；thinking tokens 曾吃光 max_tokens 导致 finish_reason=length
    #    空输出（历史题材实测多模型评测 0/4 成功）。
    #    extra_body 按模型族分发（doubao 系拒绝 reasoning_effort+thinking 同传，
    #    400 InvalidParameter 九模型验证实测），max_tokens 统一 4096。

    @classmethod
    def get_model_evaluation_policy(cls, model_id: str) -> Dict[str, Any]:
        return {
            "timeout": cls.SINGLE_MODEL_TIMEOUT,
            "max_tokens": 4096,
            "extra_body": build_thinking_disabled_extra_body(model_id),
        }

    def __init__(self):
        self.llm_client = get_llm_client()
        self.config_storage = ModelConfigStorage()
        self._model_semaphore = asyncio.Semaphore(self.MODEL_CONCURRENCY)
        self._detect_semaphore = asyncio.Semaphore(self.DETECT_CONCURRENCY)
        self._review_semaphore = asyncio.Semaphore(3)
        self.semantic_judge = SemanticJudge(self.llm_client)

    def should_skip_mm_eval(self) -> bool:
        """
        🔧 是否跳过本次多模型评测（用于失败批次后的节流）。
        每次全 0/N 成功后，consecutive_mm_fail_count 累加；若当前计数>0，
        则跳过本次并将计数-1（等价于每失败 1 次跳过后续 1 个触发间隔）。
        """
        cfg = self.config_storage.load_config()
        count = int(cfg.get("consecutive_mm_fail_count", 0))
        if count <= 0:
            return False
        cfg["consecutive_mm_fail_count"] = count - 1
        self.config_storage.save_config(cfg)
        logger.info(
            "⏭️ 因上一次多模型评测 0/N 成功，跳过本次评测（剩余跳过次数: %d）",
            cfg["consecutive_mm_fail_count"],
        )
        return True

    def get_available_models(self, genre: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有可参与评估的模型列表（含历史表现和淘汰状态）"""
        target = normalize_genre(genre)
        # "通用"视角展示跨题材聚合数据（评测记录按具体题材分库，"通用"键下无数据）
        performance = (
            self.config_storage.load_aggregated_performance()
            if target == ModelConfigStorage.DEFAULT_GENRE
            else self.config_storage.load_performance(target)
        )
        config = self.config_storage.load_config()
        active_model = self.config_storage.get_active_model_id(genre)
        eliminated_set = set(self.config_storage.get_eliminated_models(genre))

        result = []
        for m in REWRITE_CAPABLE_MODELS:
            perf = performance.get(m.model_id)
            result.append({
                "model_id": m.model_id,
                "name": m.name,
                "provider": m.provider,
                "quality_score": m.quality_score,
                "cost_per_1k_input": m.cost_per_1k_input,
                "cost_per_1k_output": m.cost_per_1k_output,
                "avg_latency": m.avg_latency,
                "is_active": m.model_id == active_model,
                "is_eliminated": m.model_id in eliminated_set,
                # 历史表现
                "performance": {
                    "total_evaluations": perf.total_evaluations if perf else 0,
                    # 🔧 选型/淘汰主项（2026-10-08 起）：确定AI段落占比，越低越好
                    "avg_ai_ratio": round(perf.avg_ai_ratio, 4) if perf else None,
                    "ai_ratio_stddev": round(perf.ai_ratio_stddev, 4) if perf else None,
                    "best_ai_ratio": round(perf.best_ai_ratio, 4) if perf else None,
                    # avg_ai_score = ratio_confidence × 100（确定AI+疑似AI 合并计数）。
                    # 不是恒 100：出现人工段落即下降。但它分辨不出 AI→疑似，
                    # 故不可用于选型；avg_ai_ratio 才是当前主项。
                    "avg_ai_score": round(perf.avg_ai_score, 1) if perf else None,
                    # 同上：口径合并导致对真实改写进步不敏感，
                    # 人工占比上来后才会有可观的非零值。
                    "avg_improvement": round(perf.avg_improvement, 1) if perf else None,
                    "best_ai_score": perf.best_ai_score if perf else None,
                    "avg_latency": round(perf.avg_latency, 2) if perf else None,
                } if perf else None,
            })
        return result

    def get_active_model_id(self, genre: Optional[str] = None) -> Optional[str]:
        """获取当前生产使用的活跃模型ID"""
        return self.config_storage.get_active_model_id(genre)

    def get_best_model_for_prompt(
        self, genre: Optional[str], prompt_text: str
    ) -> Optional[CombinationPerformanceRecord]:
        return self.config_storage.get_best_model_for_prompt(genre, prompt_text)

    def get_best_model_for_prompt_version(
        self, genre: Optional[str], prompt_version_id: str
    ) -> Optional[CombinationPerformanceRecord]:
        return self.config_storage.get_best_model_for_prompt_version(genre, prompt_version_id)

    def set_admin_model(self, model_id: Optional[str]) -> None:
        """管理员设置活跃模型"""
        self.config_storage.set_admin_model(model_id)

    def get_model_config(self, genre: Optional[str] = None) -> Dict[str, Any]:
        """获取完整的模型配置状态"""
        config = self.config_storage.load_config()
        target_genre = normalize_genre(genre)
        active_id = self.get_active_model_id(target_genre)
        active_info = _MODEL_INFO_MAP.get(active_id) if active_id else None
        auto_best_by_genre = config.get("auto_best_by_genre", {})
        if config.get("admin_selected_model"):
            selection_source = "admin_selected"
            fallback_applied = False
        elif auto_best_by_genre.get(target_genre):
            selection_source = "genre_model_summary"
            fallback_applied = False
        elif target_genre != "通用" and auto_best_by_genre.get("通用"):
            selection_source = "general_model_fallback"
            fallback_applied = True
        else:
            selection_source = "default_route"
            fallback_applied = True
        return {
            "admin_selected_model": config.get("admin_selected_model"),
            "auto_best_model": auto_best_by_genre.get("通用"),  # 兼容前端
            "auto_best_by_genre": auto_best_by_genre,
            "genre": target_genre,
            "selection_source": selection_source,
            "fallback_applied": fallback_applied,
            "active_model_id": active_id,
            "active_model_name": active_info.name if active_info else None,
            "active_model_provider": active_info.provider if active_info else None,
            "updated_at": config.get("updated_at", ""),
        }

    async def evaluate_across_models(
        self,
        text: str,
        prompt: str,
        models: Optional[List[str]] = None,
        temperature: float = 0.8,
        original_ai_score: Optional[int] = None,
        original_ai_ratio: Optional[float] = None,
        genre: Optional[str] = None,
        prompt_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        对所有模型进行并发评估

        用于提示词进化系统的多模型评测和管理员手动评测。

        Args:
            text: 待改写文本
            prompt: 改写提示词
            models: 指定参与模型（None=全部）
            temperature: LLM温度
            original_ai_score: 原始AI分数（诊断用，不参与排序）
            original_ai_ratio: 原始「确定AI」段落占比（0-1）。调用方已有检测结果时
                应传入以避免重复检测；不传则在本方法内检测一次。
            genre: 题材（用于按题材记录模型表现）
            prompt_version_id: 提示词版本ID（用于联合表现记录）

        Returns:
            评估结果摘要
        """
        total_start = time.time()
        sample_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        evaluation_batch_id = uuid.uuid4().hex

        # 确定参与模型（排除被淘汰的）
        if models:
            participate = [_MODEL_INFO_MAP[m] for m in models if m in _MODEL_INFO_MAP]
            if not participate:
                participate = list(REWRITE_CAPABLE_MODELS)
        else:
            participate = self.config_storage.get_active_models(genre)

        logger.info(
            f"多模型评估启动: {len(participate)} 个模型, 文本长度={len(text)}, 题材={genre or '通用'}"
        )
        coordinator = get_background_optimization_coordinator()
        coordinator.update_progress(len(participate), 0, 0, 0)

        # 检测原文基线：ai_score 仅作诊断，ai_ratio 是新排序主项。
        # 🔧 2026-10-08：原文 ai_ratio 此前被丢弃，导致明细记录无法重建新口径，此处补采。
        if original_ai_score is not None and original_ai_ratio is not None:
            orig_score = original_ai_score
            orig_ratio = original_ai_ratio
        else:
            detect_result = await zhuque_ai_detect_service.detect_ai_content(text)
            if detect_result.get("success"):
                orig_score = (
                    original_ai_score
                    if original_ai_score is not None
                    else detect_result.get("ai_score", 50)
                )
                orig_ratio = (
                    original_ai_ratio
                    if original_ai_ratio is not None
                    else detect_result.get("ai_ratio")
                )
            else:
                orig_score = original_ai_score if original_ai_score is not None else 50
                orig_ratio = original_ai_ratio

        # 并发评估所有模型
        tasks = [
            self._evaluate_single_model(
                m, prompt, text, temperature, orig_score,
                normalize_genre(genre), original_ai_ratio=orig_ratio,
            )
            for m in participate
        ]
        results: List[SingleModelResult] = await asyncio.gather(*tasks)
        eligible_count = sum(self.config_storage.is_eligible_result(result) for result in results)
        coordinator.update_progress(
            len(participate), len(results), eligible_count, len(results) - eligible_count
        )

        # 更新历史表现并排序
        success_results = []
        for r in results:
            self.config_storage.record_evaluation_detail({
                "evaluation_id": f"{evaluation_batch_id}:{r.model_id}",
                "batch_id": evaluation_batch_id,
                "genre": normalize_genre(genre),
                "sample_hash": sample_hash,
                "model_id": r.model_id,
                "model_revision": r.model_id,
                "prompt_version_id": prompt_version_id,
                "original_ai_score": orig_score,
                "rewritten_ai_score": r.ai_score,
                # 🔧 2026-10-08：新排序主项。明细记录号称「不可变评测事实，供审计与
                # 汇总重建」，此前却只存恒为 100 的 ai_score，导致新口径无法重建。
                "original_ai_ratio": orig_ratio,
                "rewritten_ai_ratio": r.ai_ratio,
                "fidelity_similarity": r.fidelity_similarity,
                "fidelity_eligible": r.fidelity_similarity >= (
                    self.config_storage.MIN_FIDELITY_SIMILARITY
                    if r.semantic_review and r.semantic_review.get("available")
                    else self.config_storage.FALLBACK_FIDELITY_SIMILARITY
                ),
                "quality_eligible": self.config_storage.is_eligible_result(r),
                "semantic_review": r.semantic_review,
                "hybrid_score": r.hybrid_score,
                "latency_seconds": r.latency_seconds,
                "success": r.success,
                "error_type": "timeout" if r.error and "超时" in r.error else ("evaluation_error" if r.error else None),
                "error": r.error,
                "evaluation_policy_version": EVALUATION_POLICY_VERSION,
                "detector_version": "tencent-ai-detect",
                "evaluated_at": datetime.now().isoformat(),
            })
            self.config_storage.update_performance(r, genre)
            self.config_storage.update_availability_status(r, genre)
            if prompt_version_id:
                self.config_storage.update_combination_performance(
                    r, genre, prompt_version_id, prompt, sample_hash=sample_hash
                )
            if self.config_storage.is_eligible_result(r):
                success_results.append(r)

        # 质量门槛内按「确定AI」段落占比升序排（改写最彻底者居首）；
        # 🔧 2026-10-08：主键由 ai_score 改为 ai_ratio（ai_score 在改写区间恒为 100，
        # 按它排序等价于常数排序）。hybrid_score 仅作展示参考，
        # 质量由 is_eligible_result 门槛保证
        success_results = rank_by_ai_ratio(success_results)

        # 🔧 未入选原因落日志：可诊断性（方案 C）——逐项推导被拒原因，
        # 避免事后靠猜（如 2026-08-19 降 0 分当选最佳因排序键误用）
        for r in results:
            if r.success and not self.config_storage.is_eligible_result(r):
                detail = "；".join(
                    collect_rejection_reasons(
                        r, self.config_storage.MIN_REQUIRED_IMPROVEMENT
                    )
                )
                logger.info(f"  [未入选] {r.model_name}: {detail}")

        # 更新该题材的自动最优模型
        self.config_storage.update_auto_best_model(genre)

        # 评估后触发淘汰判定
        self.config_storage.evaluate_elimination(genre)
        self.config_storage.record_regular_evaluation_round(genre)

        total_time = time.time() - total_start
        logger.info(
            f"多模型评估完成: {len(success_results)}/{len(participate)} 成功, "
            f"耗时={total_time:.1f}秒"
        )
        if success_results:
            best = success_results[0]
            review = best.semantic_review or {}
            fid = (review.get("semantic_fidelity") or {}).get("score")
            fact = (review.get("fact_consistency") or {}).get("score")
            comp = (review.get("information_completeness") or {}).get("score")
            logger.info(
                f"  最佳: {best.model_name} "
                f"({ModelConfigStorage.describe_ratio_reduction(best)}, "
                f"耗时={best.latency_seconds:.1f}秒, "
                f"hybrid={best.hybrid_score:.2f}, "
                f"评审 保真={fid}/事实={fact}/完整={comp}, "
                f"文本相似度={best.fidelity_similarity:.1f})"
            )

        # 🔧 更新多模型评测连续失败计数：0/N 成功则累加，有成功则清零
        #    防止全 0 批重复浪费 token（下一次引擎触发时会被跳过 1 个触发间隔）
        cfg = self.config_storage.load_config()
        if success_results:
            cfg["consecutive_mm_fail_count"] = 0
        else:
            cfg["consecutive_mm_fail_count"] = int(cfg.get("consecutive_mm_fail_count", 0)) + 1
            logger.warning(
                f"🚫 多模型评测 0/{len(participate)} 成功，连续失败计数: "
                f"{cfg['consecutive_mm_fail_count']}"
            )
        self.config_storage.save_config(cfg)

        return {
            "success": len(success_results) > 0,
            "original_ai_score": orig_score,
            "original_ai_ratio": orig_ratio,
            # 主排序键：确定AI段落占比 {model_id: ratio}（0-1，越低越好）
            "model_scores": {
                r.model_id: (r.ai_ratio if r.ai_ratio is not None else 1.0)
                for r in success_results
            },
            # 诊断用：ai_score 恒为 100，仅保留供日志与回溯
            "model_ai_scores": {r.model_id: r.ai_score for r in success_results},
            "best_model_id": success_results[0].model_id if success_results else None,
            "best_model_name": success_results[0].model_name if success_results else None,
            "best_ai_ratio": (
                success_results[0].ai_ratio if success_results else None
            ),
            "best_ai_score": success_results[0].ai_score if success_results else None,
            "results": [
                {
                    "model_id": r.model_id,
                    "model_name": r.model_name,
                    "provider": r.provider,
                    "reduced_text": r.reduced_text,
                    "ai_score": r.ai_score,
                    "ai_ratio": r.ai_ratio,
                    # 🔧 2026-10-17：baseline 会原样传给 run_challenge_round 重建，
                    # 漏掉原文 ratio 会让 baseline 在准入门全盘不合格，
                    # 挑战者自动进入前三而复活。
                    "original_ai_ratio": r.original_ai_ratio,
                    "latency_seconds": round(r.latency_seconds, 2),
                    "improvement": r.improvement,
                    "fidelity_similarity": round(r.fidelity_similarity, 2),
                    "semantic_review": r.semantic_review,
                    "hybrid_score": round(r.hybrid_score, 2),
                }
                for r in success_results
            ],
            "total_models_tried": len(participate),
            "total_models_success": len(success_results),
            "total_time_seconds": round(total_time, 2),
            # 🔧 2026-10-08：排行榜主键由 ai_score 改为 ai_ratio
            "ranking": {
                r.model_name: (r.ai_ratio if r.ai_ratio is not None else 1.0)
                for r in success_results
            },
        }

    async def _evaluate_single_model(
        self,
        model_info: RewriteModelInfo,
        prompt: str,
        text: str,
        temperature: float,
        original_score: int,
        genre: str,
        original_ai_ratio: Optional[float] = None,
    ) -> SingleModelResult:
        """单个模型的改写+检测流程

        🔧 2026-10-17：新增 `original_ai_ratio`，写入结果对象供准入门使用。
        此前原文 ratio 虽在调用方算好（`orig_ratio`），却从未传进来，
        导致 `is_eligible_result` 只能用恒零的 improvement 守门。
        """
        start = time.time()

        try:
            policy = self.get_model_evaluation_policy(model_info.model_id)
            async with self._model_semaphore:
                preprocessed, _ = preprocess_text(text)
                messages = [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"请改写以下文本，降低其AI痕迹：\n\n{preprocessed}"},
                ]

                call_options: Dict[str, Any] = {"use_cache": False, "disable_fallback": True}
                if policy["max_tokens"] is not None:
                    call_options["max_tokens"] = policy["max_tokens"]
                if policy["extra_body"]:
                    call_options["extra_body"] = policy["extra_body"]

                rewrite_result = await asyncio.wait_for(
                    self.llm_client.chat(
                        messages=messages,
                        model=model_info.model_id,
                        temperature=temperature,
                        **call_options,
                    ),
                    timeout=policy["timeout"],
                )

                if not rewrite_result or len(rewrite_result.strip()) < 50:
                    return SingleModelResult(
                        model_id=model_info.model_id,
                        model_name=model_info.name,
                        provider=model_info.provider,
                        reduced_text="",
                        ai_score=100,
                        latency_seconds=time.time() - start,
                        success=False,
                        error="改写结果过短或为空",
                    )

                final_text, _ = postprocess_text(rewrite_result.strip())

            # 检测AI分数
            async with self._detect_semaphore:
                detect_result = await zhuque_ai_detect_service.detect_ai_content(
                    final_text
                )

            ai_score = (
                detect_result.get("ai_score", 100)
                if detect_result.get("success")
                else 100
            )
            # 🔧 「确定AI」段落占比：唯一能区分「改写成功/失败」的检测信号
            ai_ratio = detect_result.get("ai_ratio") if detect_result.get("success") else None
            if not detect_result.get("success"):
                return SingleModelResult(
                    model_id=model_info.model_id,
                    model_name=model_info.name,
                    provider=model_info.provider,
                    reduced_text=final_text,
                    ai_score=100,
                    latency_seconds=time.time() - start,
                    success=False,
                    error=detect_result.get("error", "AI检测失败"),
                )
            fidelity_similarity = 100.0 - _calculate_fidelity_score(text, final_text)
            async with self._review_semaphore:
                semantic_review = await self.semantic_judge.evaluate(text, final_text, genre)
            hybrid_score = calculate_hybrid_score(
                ai_score, 100.0 - fidelity_similarity, semantic_review
            )
            latency = time.time() - start
            improvement = original_score - ai_score

            result = SingleModelResult(
                model_id=model_info.model_id,
                model_name=model_info.name,
                provider=model_info.provider,
                reduced_text=final_text,
                ai_score=ai_score,
                latency_seconds=latency,
                improvement=improvement,
                success=True,
                fidelity_similarity=fidelity_similarity,
                semantic_review=semantic_review,
                hybrid_score=hybrid_score,
                ai_ratio=ai_ratio,
                original_ai_ratio=original_ai_ratio,
            )

            # 🔧 2026-10-17：日志改打 ratio 口径。`降低N分` 对改写效果不敏感
            # （ai_score 合并确定AI与疑似AI，AI→疑似不降分；实测 7 个模型
            # 全部输出「降低0分」，而同期 ratio 差异很大）—— 旧措辞既零
            # 信息量又误导读者。
            # improvement 字段保留（历史存档依赖），仅不再用于描述效果。
            logger.info(
                f"  [{model_info.name}] "
                f"{ModelConfigStorage.describe_ratio_reduction(result)}, "
                f"耗时={latency:.1f}秒"
            )
            return result

        except asyncio.TimeoutError:
            latency = time.time() - start
            logger.warning(f"  [{model_info.name}] 超时 ({latency:.1f}秒)")
            return SingleModelResult(
                model_id=model_info.model_id,
                model_name=model_info.name,
                provider=model_info.provider,
                reduced_text="",
                ai_score=100,
                latency_seconds=latency,
                success=False,
                error=f"超时 ({policy['timeout']}秒)",
            )
        except Exception as e:
            latency = time.time() - start
            logger.error(f"  [{model_info.name}] 异常: {e}")
            return SingleModelResult(
                model_id=model_info.model_id,
                model_name=model_info.name,
                provider=model_info.provider,
                reduced_text="",
                ai_score=100,
                latency_seconds=latency,
                success=False,
                error=str(e),
            )

    async def run_challenge_round(
        self,
        text: str,
        prompt: str,
        temperature: float = 0.8,
        original_ai_score: Optional[int] = None,
        genre: Optional[str] = None,
        current_iteration: int = 0,
        baseline_results: Optional[List[Dict[str, Any]]] = None,
        prompt_version_id: Optional[str] = None,
        original_ai_ratio: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        运行挑战赛：从淘汰池中选模型与活跃模型同场竞技。

        如果被淘汰模型表现进入前三名，则复活。

        Args:
            text: 评测文本
            prompt: 改写提示词
            temperature: LLM温度
            original_ai_score: 原始AI分数
            genre: 题材
            current_iteration: 当前进化迭代号

        Returns:
            挑战赛结果摘要（None 表示本轮不需要挑战赛）
        """
        if not self.config_storage.should_run_challenge(genre, current_iteration):
            return None

        candidates = self.config_storage.get_challenge_candidates(genre)
        if not candidates:
            return None

        logger.info(f"⚔️ 挑战赛启动[{genre or '通用'}]: {candidates}")

        # 挑战者模型
        challenger_models = [_MODEL_INFO_MAP[m] for m in candidates if m in _MODEL_INFO_MAP]

        # 检测原始AI分数
        # 🔧 2026-10-17：与常规轮次对齐，一并取原文 ratio 供准入门使用。
        if original_ai_score is not None and original_ai_ratio is not None:
            orig_score = original_ai_score
            orig_ratio = original_ai_ratio
        elif original_ai_score is not None:
            orig_score = original_ai_score
            orig_ratio = original_ai_ratio
        else:
            detect_result = await zhuque_ai_detect_service.detect_ai_content(text)
            orig_score = detect_result.get("ai_score", 50) if detect_result.get("success") else 50
            orig_ratio = (
                original_ai_ratio
                if original_ai_ratio is not None
                else detect_result.get("ai_ratio")
            )

        # 常规轮次已经评估过活跃模型，挑战赛只产生挑战者的额外成本。
        tasks = [
            self._evaluate_single_model(
                m, prompt, text, temperature, orig_score,
                normalize_genre(genre), original_ai_ratio=orig_ratio,
            )
            for m in challenger_models
        ]
        challenge_results: List[SingleModelResult] = await asyncio.gather(*tasks)

        baseline = [
            SingleModelResult(
                model_id=item["model_id"],
                model_name=item["model_name"],
                provider=item["provider"],
                reduced_text=item.get("reduced_text", ""),
                ai_score=item["ai_score"],
                latency_seconds=item["latency_seconds"],
                improvement=item.get("improvement", 0),
                success=True,
                fidelity_similarity=item.get("fidelity_similarity", 100.0),
                semantic_review=item.get("semantic_review"),
                hybrid_score=item.get("hybrid_score", 100.0),
                # 🔧 2026-10-17：重建 baseline 时必须带上 ratio 两个字段。
                # 缺失时 baseline 会被准入门全盘判为不合格，
                # 挑战者便自动「进入前三」而复活 —— 复活名额将由缺字段决定，
                # 而非真实表现（实测会让本用例复活名单从 [] 变成 ['qwen-plus']）。
                ai_ratio=item.get("ai_ratio"),
                original_ai_ratio=item.get("original_ai_ratio", orig_ratio),
            )
            for item in (baseline_results or [])
        ]
        all_results = baseline + challenge_results

        # 活跃模型结果已由常规轮次写入，只更新挑战者。
        for r in challenge_results:
            self.config_storage.update_performance(r, genre)
            self.config_storage.update_availability_status(r, genre)
            if prompt_version_id:
                self.config_storage.update_combination_performance(
                    r,
                    genre,
                    prompt_version_id,
                    prompt,
                    sample_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                )

        # 处理复活
        revived = self.config_storage.process_challenge_results(
            genre=genre,
            challenge_results=challenge_results,
            all_results=all_results,
        )

        # 至少一个挑战者完成改写和检测后才消耗本次挑战周期。
        challenge_completed = any(result.success for result in challenge_results)
        if challenge_completed:
            self.config_storage.mark_challenge_done(genre, current_iteration)
        else:
            logger.warning("挑战赛所有模型均失败，本轮不推进挑战周期")

        return {
            "challengers": candidates,
            "revived": revived,
            "completed": challenge_completed,
            "all_scores": {r.model_id: r.ai_score for r in all_results if r.success},
        }


# ============================================================================
# 全局单例
# ============================================================================

_service: Optional[MultiModelEvaluationService] = None


def get_multi_model_service() -> MultiModelEvaluationService:
    """获取多模型评估服务单例"""
    global _service
    if _service is None:
        _service = MultiModelEvaluationService()
    return _service


# 保持向后兼容的别名
get_competition_service = get_multi_model_service
