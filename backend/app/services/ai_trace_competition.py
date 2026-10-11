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
EVALUATION_POLICY_VERSION = "ai-trace-v4-semantic-fidelity"


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
    avg_ai_score: float = 100.0      # 平均AI分数（越低越好）
    avg_improvement: float = 0.0     # 平均降分幅度
    best_ai_score: float = 100.0     # 历史最佳AI分数
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


def rank_by_ai_score(results: List[SingleModelResult]) -> List[SingleModelResult]:
    """质量门槛内按 AI 分数升序排（降分最大者居首）；hybrid_score 仅作展示参考。

    资格门槛（is_eligible_result 七项）已保证质量，排序再计入质量分只会
    重复奖励少改写，使恒等映射占优（2026-08-19 玄幻轮实证：降 0 分模型
    当选最佳并被选为进化改写执行模型）。AI 分数直接对应竞争目的本身。
    """
    return sorted(results, key=lambda r: r.ai_score)


def collect_rejection_reasons(
    result: SingleModelResult, min_improvement: int
) -> List[str]:
    """逐项推导未入选竞争的原因，供诊断日志使用（与 is_eligible_result 同步）。"""
    reasons: List[str] = []
    if result.improvement < min_improvement:
        reasons.append(f"降幅{result.improvement}分低于门槛{min_improvement}分")
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
        if confidence < 0.6:
            reasons.append(f"评审置信度低({confidence})")
        for label, key, threshold in (
            ("语义保真", "semantic_fidelity", 80),
            ("事实一致", "fact_consistency", 90),
            ("信息完整", "information_completeness", 75),
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

REWRITE_CAPABLE_MODELS: List[RewriteModelInfo] = [
    RewriteModelInfo(
        model_id="qwen3.7-plus",
        name="Qwen3.7 Plus",
        provider="alibaba",
        quality_score=9.2,
        cost_per_1k_input=0.002,
        cost_per_1k_output=0.008,
        avg_latency=1.6,
    ),
    RewriteModelInfo(
        model_id="deepseek-v4-flash",
        name="DeepSeek V4 Flash",
        provider="deepseek",
        quality_score=8.5,
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.002,
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
        model_id="kimi/kimi-k2.6",
        name="Kimi K2.6",
        provider="moonshot",
        quality_score=8.9,
        cost_per_1k_input=0.0065,
        cost_per_1k_output=0.027,
        avg_latency=2.0,
    ),
    RewriteModelInfo(
        model_id="glm-5.2",
        name="GLM-5.2",
        provider="zhipu",
        quality_score=9.1,
        cost_per_1k_input=0.008,
        cost_per_1k_output=0.028,
        avg_latency=2.5,
    ),
    RewriteModelInfo(
        model_id="MiniMax/MiniMax-M3",
        name="MiniMax M3",
        provider="minimax",
        quality_score=9.0,
        cost_per_1k_input=0.0042,
        cost_per_1k_output=0.0168,
        avg_latency=2.2,
    ),
    RewriteModelInfo(
        model_id="mimo-v2.5",
        name="MiMo V2.5",
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
        model_id="step-3.7-flash",
        name="Step 3.7 Flash",
        provider="stepfun",
        quality_score=8.8,
        cost_per_1k_input=0.00135,
        cost_per_1k_output=0.0081,
        avg_latency=1.2,
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

    @classmethod
    def is_eligible_result(cls, result: SingleModelResult) -> bool:
        """只有完整成功、达到降幅门槛且满足保真门槛的结果才能参与竞争统计。"""
        if not result.success:
            return False
        if result.improvement < cls.MIN_REQUIRED_IMPROVEMENT:
            return False
        review = result.semantic_review or {}
        if not review.get("available"):
            return result.fidelity_similarity >= cls.FALLBACK_FIDELITY_SIMILARITY
        return (
            not review.get("hard_fail")
            and review.get("over_rewrite_risk") == "low"
            and review.get("confidence", 0) >= 0.6
            and review.get("semantic_fidelity", {}).get("score", 0) >= 80
            and review.get("fact_consistency", {}).get("score", 0) >= 90
            and review.get("information_completeness", {}).get("score", 0) >= 75
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
                    agg.avg_improvement = (
                        agg.avg_improvement * agg.total_success + rec.avg_improvement * rec.total_success
                    ) / total_success
                    agg.avg_latency = (
                        agg.avg_latency * agg.total_success + rec.avg_latency * rec.total_success
                    ) / total_success
                agg.total_evaluations += rec.total_evaluations
                agg.total_success = total_success
                agg.best_ai_score = min(agg.best_ai_score, rec.best_ai_score)
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
                record.avg_improvement = record.avg_improvement * (n - 1) / n + result.improvement / n
                record.avg_fidelity_similarity = record.avg_fidelity_similarity * (n - 1) / n + result.fidelity_similarity / n
                record.avg_latency = record.avg_latency * (n - 1) / n + result.latency_seconds / n
                record.worst_ai_score = max(result.ai_score, record.worst_ai_score if n > 1 else result.ai_score)
                record.composite_score = record.avg_ai_score + (100 - record.avg_fidelity_similarity) * 0.2
                record.confidence_score = record.composite_score + record.ai_score_stddev / max(n ** 0.5, 1.0)
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

        # 按平均AI分数升序（越低越好）
        best_model_id = min(qualified, key=lambda k: qualified[k].avg_ai_score)
        config = self.load_config()
        auto_best_by_genre = config.get("auto_best_by_genre", {})
        auto_best_by_genre[target_genre] = best_model_id
        config["auto_best_by_genre"] = auto_best_by_genre
        self.save_config(config)

        logger.info(
            f"自动最优模型更新[{target_genre}]: {best_model_id} "
            f"(avg_score={qualified[best_model_id].avg_ai_score:.1f})"
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

        # 找到当前最佳分数
        best_score = min(v.avg_ai_score for v in qualified.values())

        # 淘汰门槛
        threshold = best_score + self.ELIMINATION_SCORE_GAP

        # 找出应被淘汰的模型（按平均分降序从最差开始，保留至少 MIN_ALIVE_MODELS 个存活模型）
        config = self.load_config()
        eliminated_map = config.get("eliminated_models", {})
        current_eliminated = set(eliminated_map.get(target_genre, []))

        candidates = [
            model_id for model_id, rec in qualified.items()
            if model_id not in current_eliminated and rec.avg_ai_score > threshold
        ]
        candidates.sort(key=lambda mid: -records[mid].avg_ai_score)

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
        successful = sorted(
            (r for r in all_results if self.is_eligible_result(r)),
            key=lambda result: (result.ai_score, result.model_id),
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
                records[mid] = ModelPerformanceRecord(
                    model_id=challenge.model_id,
                    model_name=challenge.model_name,
                    provider=challenge.provider,
                    total_evaluations=1,
                    total_success=1,
                    avg_ai_score=float(challenge.ai_score),
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
                    "avg_ai_score": round(perf.avg_ai_score, 1) if perf else None,
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
            original_ai_score: 原始AI分数
            genre: 题材（用于按题材记录模型表现）

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

        # 检测原始AI分数
        if original_ai_score is not None:
            orig_score = original_ai_score
        else:
            detect_result = await zhuque_ai_detect_service.detect_ai_content(text)
            orig_score = detect_result.get("ai_score", 50) if detect_result.get("success") else 50

        # 并发评估所有模型
        tasks = [
            self._evaluate_single_model(m, prompt, text, temperature, orig_score, normalize_genre(genre))
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

        # 质量门槛内按 AI 分数升序排（降分最大者居首）；
        # hybrid_score 仅作展示参考，质量由 is_eligible_result 门槛保证
        success_results = rank_by_ai_score(success_results)

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
                f"  最佳: {best.model_name} (AI分数={best.ai_score}, "
                f"降低{best.improvement}分, 耗时={best.latency_seconds:.1f}秒, "
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
            "results": [
                {
                    "model_id": r.model_id,
                    "model_name": r.model_name,
                    "provider": r.provider,
                    "reduced_text": r.reduced_text,
                    "ai_score": r.ai_score,
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
            "ranking": {r.model_name: r.ai_score for r in success_results},
        }

    async def _evaluate_single_model(
        self,
        model_info: RewriteModelInfo,
        prompt: str,
        text: str,
        temperature: float,
        original_score: int,
        genre: str,
    ) -> SingleModelResult:
        """单个模型的改写+检测流程"""
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

            logger.info(
                f"  [{model_info.name}] AI分数={ai_score}, "
                f"降低{improvement}分, 耗时={latency:.1f}秒"
            )

            return SingleModelResult(
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
            )

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
        if original_ai_score is not None:
            orig_score = original_ai_score
        else:
            detect_result = await zhuque_ai_detect_service.detect_ai_content(text)
            orig_score = detect_result.get("ai_score", 50) if detect_result.get("success") else 50

        # 常规轮次已经评估过活跃模型，挑战赛只产生挑战者的额外成本。
        tasks = [
            self._evaluate_single_model(m, prompt, text, temperature, orig_score, normalize_genre(genre))
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
