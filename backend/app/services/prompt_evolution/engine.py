"""
提示词进化系统 - 核心引擎

整合所有组件，实现完整的自动化提示词优化循环
"""
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable, List, Dict, Tuple, Any

from .models import (
    PromptVersion,
    EvolutionHistory,
    EvolutionConfig,
    EvaluationResult,
    StopReason
)
from .storage import EvolutionStorage, get_evolution_storage
from .evaluator import PromptEvaluator
from .meta_optimizer import MetaOptimizer
from .semantic_judge import SemanticJudge
from .test_samples import TestSampleManager, get_sample_manager, generate_samples_via_llm
from .genre_detector import get_genre_detector  # 🆕 导入题材检测器
from app.services.ai_trace_storage import get_background_optimization_coordinator

logger = logging.getLogger(__name__)

# 进度回调类型
ProgressCallback = Callable[[str, int, dict], Awaitable[None]]


def _get_multi_model_service():
    """延迟导入多模型评估服务（避免循环依赖）"""
    from app.services.ai_trace_competition import MultiModelEvaluationService
    return MultiModelEvaluationService()


class PromptEvolutionEngine:
    """提示词进化引擎"""

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        storage: Optional[EvolutionStorage] = None,
        genre: Optional[str] = None  # 🔧 支持指定题材
    ):
        self.config = config or EvolutionConfig()
        self.storage = storage or get_evolution_storage()
        self.evaluator = PromptEvaluator()
        self.meta_optimizer = MetaOptimizer()
        self.sample_manager = get_sample_manager()

        # 🆕 题材配置
        self.genre = genre or self.config.genre  # 🔧 当前题材
        if self.genre:
            logger.info(f"🎭 启用题材定制化模式：{self.genre}")
            self.meta_optimizer.current_genre = self.genre

        # 当前进化状态
        self.history: Optional[EvolutionHistory] = None
        self.is_running = False

        # 🆕 改写执行模型：对齐生产活跃模型（竞争胜出者），避免默认路由模型污染进化信号
        self.rewrite_model_id: Optional[str] = None

        # 🆕 回滚机制：保存最优版本
        self.best_ever_version: Optional[PromptVersion] = None
        # 🔧 2026-10-16：跟踪信号从 avg_score（rewritten_ai_score 均值，
        # 在 LLM 改写区间恒为 100）改为「确定AI段落占比×100」（avg_ai_ratio）。
        # 旧初值 100 使首轮 score_diff 恒为 0，is_better/is_significantly_better
        # 永不成立，best_ever_version 永不被赋值，回滚保护形同虚设。
        # None 表示尚无基线，首轮评估时无条件建立基线。
        self.best_ever_score: Optional[float] = None
        self.consecutive_worse_count: int = 0  # 连续变差次数

        # 🆕 多维停止条件追踪
        self.score_history: List[float] = []           # AI分数历史
        self.readability_history: List[float] = []     # 可读性历史
        self.writing_history: List[float] = []         # 文笔历史
        self.convergence_count: int = 0                # 收敛计数
        self.oscillation_count: int = 0                # 震荡计数

        # 🔧 探索模式状态
        self.no_improvement_count: int = 0             # 无明显改善次数
        self.exploration_mode: bool = False            # 是否处于探索模式
        self.exploration_attempts: int = 0            # 探索模式尝试次数

        # 🔧 热启动缓存（增强版：基于评分的LRU缓存）
        self._evaluation_cache: Dict[str, Dict] = {}  # prompt_hash -> {score, composite_score, results, access_count, last_access}

        # 🆕 经验基线快照：用于中断时判断是否产生了新经验（避免把历史经验复读进报告池）
        self._experience_baseline: Optional[Dict[str, set]] = None

        # 🆕 A/B测试优化：失败变体记录
        self._failed_variants: Dict[str, int] = {}  # variant_hash -> fail_count

        # 🔧 候选挑战者注入追踪：确定性候选变体每批次只参与一轮 A/B，
        # 跨批次由失败计数（3次）淘汰，批次重置时清空注入记录
        self._injected_candidate_descs: set = set()


    @staticmethod
    def _is_complete_quality_evaluation(
        results: List[EvaluationResult], expected_count: int
    ) -> bool:
        """A/B候选必须完成全部计划样本，且每个样本均通过质量硬门槛。"""
        return (
            expected_count > 0
            and len(results) == expected_count
            and all(result.success for result in results)
        )

    # 质量硬失败容忍策略：失败（含缺失）样本占比超过该比例才取消资格，
    # 否则保留资格但排入更高层（见 `_quality_layer`）
    QUALITY_DISQUALIFY_FAILURE_RATIO = 0.5
    # 🔏 关于「质量罚分权重」的取证史（2026-10-16，勿再改回加权模型）：
    #
    # 本常量曾是 QUALITY_FAILURE_RANK_PENALTY，经历了 60.0 -> 0.5 -> 移除三步，
    # 每一步都因真实数据取证而改，最终被帕累托分层取代（原因见下）。
    #
    # 第一步 60.0 的缺陷：最小非零粒度 = (1/8) x 60.0 = 7.5 分，而朱雀 ratio
    # 的全部取值只有 0.0~1.0。真实 A/B 轮次（0e0024a3 iteration 2）候选失格数
    # 为「原始 4/8、变体 2/8、变体4 7/8」—— 失格数只要不同（哪怕差 1 个样本），
    # ratio 在跨组比较中完全不参与，胜负 100% 由失格数决定。该轮变体胜出
    # 本质是「2 失格 vs 4 失格」而非 AI 率更低，主项名不副实。
    #
    # 第二步降到 0.5 后四项回到0-1 同量纲，但真实 score_diff 上限仅 0.6595，
    # 远低于当时 ab_test_min_diff = 3.0 ⇒ 显著性判定恒不成立，A/B 唯一胜出
    # 路径退化成「原始被判 >100 失格」。即改动任一权重都会在另一个尺度上
    # 失效 —— 这正是线性加权模型的必然后果。
    #
    # 第三步移除：质量改为`_quality_layer` 的**分层键**（失格样本数直接计入
    # score），与 ratio 不再相互折价。层号步长 1.0 压过实测层内 ratio 最大差
    # 0.5318（L3 组），质量准入严格成立且无需调参。
    #
    # 🔧 2026-10-17(P27) 敏感度实验：P16 曾把「ratio 决胜作用被质量层挤压」
    # 标为待决策，此处取证后**证伪**，层键步长保持 1.0 不动。
    # 实测（8 轮 19 个版本）：
    #   - 失格数分布是 1/2/3/4 **四**层（P16 记的三层不完整）
    #   - 层内 ratio 最大跨度 **0.1949**（P16 记的 0.1497 偏小）
    #   - ratio 全域跨度仅约 0.53（0.217~0.473）
    # 把步长从 1.0 压到 0.25（4 倍余量压缩），**171 个真实配对零翻转**；
    # 只有降到 0.20（破坏分层严格性）才出现 3 次翻转。交叉验证「失格差 1 且
    # ratio 差最大」的 5 个配对，两种步长下胜者完全一致。
    # 根因：ratio 全域跨度 0.53 < 任何 >0.53 的步长，所以 1.0 与 0.25 等效。
    # ⇒ 改动零收益，且 1.0 语义最直观（层键即失格数本身），保持不动。
    #
    # 🔧 成功率门槛：成功样本占比低于该值的版本不得入选最佳列表，
    # 防止坍塔型提示词（超短/空输出）凭少数成功样本的分数获得虚高适应度
    # （2026-08-08 都市批 bd6c6b78 取证：iter4 半数样本篇幅守门失败仍以均值 0.0 入选）
    #
    # 🔧 2026-10-16 由 0.75 下调至 0.60，依据真实进化轮次 86cff7f7 取证：
    # 该轮 ratio 单调下降 0.473→0.409→0.362（降 23%，进化确有成效），
    # 但三个版本成功率分别 50%/50%/62%，全部低于 0.75 → best_versions 全空，
    # 进化成果无法传承，等于白跑。
    # 根因是质量门槛与评审分布错配：事实一致 23 样本 mean 88.5，
    # 门槛 90 恰切在分布中位数上（11 个 <90、12 个 ≥90），
    # 成功率天然卡在 50~62%。
    # 取 0.60 —— 让实测最优形态（62%）能入选，ratio 改善得以沿传承链累积。
    # 坍塔型防护改由更直接的手段承担：下面的 ratio 上限门（0.85）
    # 与 _is_complete_quality_evaluation 的全通过要求都已拦住「无降分效果」的版本，
    # 无需再靠较高的成功率门槛间接兜底。
    BEST_VERSION_MIN_SUCCESS_RATIO = 0.60
    # 🔧 2026-10-16：入选最佳列表允许的「质量失格样本占比」上限。
    #
    # 取证（真实轮次 c9ccd818）：方向 1 把成功率门下调至 0.60 后，
    # 该轮 8 样本成功 5 个 = 62.5%，**已越过成功率门**，
    # 但 best_versions 仍为空 —— 实际拦它的是保真门的「任一样本 hard_fail
    # 即全版否决」。该轮 fact_consistency 分布 [78,82,85,93,93,95,96,97]，
    # 3/8 低于 90 即整版否决；而这 3 个样本的评审置信度为 0.88/0.86/0.82，
    # 评审自己很确定，并非误判。
    #
    # 设计缺陷：质量硬门槛本属**逐样本准入**语义（回答「哪些样本失格、
    # 供优化器归因」），`_version_has_fidelity_failure` 却把它升级为
    # **整版全称否决**（要求全部样本事实一致 ≥90），混淆了两个问题：
    #   - 优化器需要：哪些样本失格 → 逐样本判据
    #   - 版本准入需要：这一版整体可用吗 → 应按失格占比衡量
    # 后果是进化链断裂：优化器的 `_build_quality_gap_analysis` 正是靠
    # 这些失格样本做质量短板归因，失格版本永不可入选则跨版本对比失去基线。
    #
    # 口径统一：失格占比上限 = 1 - BEST_VERSION_MIN_SUCCESS_RATIO，
    # 两处衡量同一件事，避免出现「成功率门已放行、保真门仍拦下」的
    # 无解释双重否决。坍塌防线由下方 ratio 上限门与安全门直接承担。
    BEST_VERSION_MAX_FAILURE_RATIO = 1.0 - BEST_VERSION_MIN_SUCCESS_RATIO
    # 🔧 2026-10-16：入选最佳列表的确定AI占比上限（0-1）。
    # 取 0.85 —— 宽松档，只拦「几乎没有任何段落脱离AI判定」的版本。
    # 不设更严（如 early_stop_threshold 0.10）：最佳列表需容纳过程中的
    # 阶段性版本，过严会把尚未收敛但方向正确的版本全部挡在传承链外。
    BEST_VERSION_MAX_AI_RATIO = 0.85
    # 🔧 2026-10-16：人感成本在 A/B 排名中的权重（朱雀 ratio 为主项，该项为并列项）。
    # 量纲对齐后取 0.01：人感成本满量程（0-100）对排名的影响是 0-1 分，
    # 与 ratio 的 0-1 分制等价；而实际 A/B 中 ratio 差距常达数个百分点，
    # 故客观检测必然主胜（2026-10-16 实测 0.05 时 ratio 60% 的人感优秀候选
    # 仍会反超 ratio 2% 的人感较差候选，属主项倒挂，已下调）。
    HUMAN_COST_TIEBREAK_WEIGHT = 0.01
    # 🔧 2026-10-16：无任何可用 ratio 时的失格基线（0-1 尺度）。
    # 必须高于「全部判AI」的真实上界 1.0，确保检测失败的候选排在所有真实候选之后，
    # 且沿用 101.0 与「质量硬失败失格」同档的既有约定（调用侧以 >100 判失格）。
    AI_RATIO_MISSING_PENALTY = 101.0

    # 🔧 2026-10-16 失败语义受控词表。原先只有 error 自由文本，事后无法区分
    # 「检测失败」与「未检测」，也无法判断失败样本是否仍持有实测 ratio——
    # 而这直接决定适应度口径是否偏乐观。
    FAILURE_KINDS = (
        # 样本自身不适用（原文 AI 率为 0），改写与检测都没跑
        "sample_excluded",
        # 改写产出为空或过短，未进入检测
        "rewrite_empty",
        # 篇幅守门拦截：改写存在但长度偏离过大，判定为信息丢失、未进入检测
        "length_gate",
        # 🔴 关键：检测**已成功**、ratio 有值，仅因语义评审硬门槛而判失败。
        # 这类样本的 ratio 是真实测量值，统计时必须计入（见 RATIO_AVAILABLE_KINDS）。
        "review_hard_fail",
        # 评审链路失效（返回格式无效/调用异常），质量维度未测量。
        # ratio 仍是实测值（检测已完成），因此统计口径照常计入——
        # 是否计入由字段值而非 kind 决定。
        "review_unavailable",
        # 朱雀检测链路失败，无 ratio
        "detect_failed",
        # 未预期异常，无 ratio
        "exception",
    )
    # 🔧 失败但 ratio 本应可得的类型：这些样本的 ratio 是实测值，
    # 统计口径不得因 success=False 而丢弃（丢弃会使均值系统性偏乐观）。
    RATIO_AVAILABLE_KINDS = ("review_hard_fail",)

    @staticmethod
    def _quality_failure_ratio(
        results: List[EvaluationResult], expected_count: int
    ) -> float:
        """失败（含缺失）样本占比；缺失样本按失败计。"""
        if expected_count <= 0:
            return 1.0
        passed = sum(1 for result in results if result.success)
        return max(0.0, (expected_count - passed) / expected_count)

    @staticmethod
    def _summarize_quality_failures(results: List[EvaluationResult]) -> str:
        """汇总硬失败样本的原因，用于日志诊断。"""
        reasons = [result.error or "未知原因" for result in results if not result.success]
        return "；".join(reasons) if reasons else "无"

    @classmethod
    def _diagnose_initial_failure(cls, results: List[EvaluationResult]) -> str:
        """初始全失格的归因诊断，供后续题材重试时切换活跃模型参考。"""
        if not results:
            return "改写全失格"
        failures = [r for r in results if not r.success]
        # 🔧 2026-10-16 优先用 failure_kind（结构化）而非 error 文本猜测。
        # 原实现靠关键词匹配 error，对「评审硬失败」这类没有特征词的路径
        # 会全部落到最后的兜底分支，给出「改写全失格」的错误结论。
        kinds = {r.failure_kind for r in failures if r.failure_kind}
        if kinds == {"length_gate"}:
            return "篇幅守门拦截"
        if kinds == {"detect_failed"}:
            return "检测失败"
        if "review_hard_fail" in kinds:
            # 质量门槛失格：改写与检测都跑通了，是语义评审不通过。
            # 这是提示词可通过进化解决的问题（针对性提升事实保真），
            # 与「检测链路失效」「守门拦截」性质完全不同，必须单独归因。
            return "质量门槛失格"

        # 篇幅守门：error 含篇幅/守门/字数/minimum 等关键词（旧存档无 kind）
        if failures and all(
            any(k in (f.error or "") for k in ("篇幅", "守门", "字数", "minimum", "length"))
            for f in failures
        ):
            return "篇幅守门拦截"
        # 检测失败：error 明确指向 AI 检测接口
        if failures and all(
            any(k in (f.error or "").lower() for k in ("检测", "detect", "ai_content", "腾讯"))
            for f in failures
        ):
            return "检测失败"
        # 质量门槛失格（旧存档无 failure_kind 时按评审特征词兜底）：
        # error 形如「事实一致性低于90；语义保真度低于80」，是评审的硬门槛结论
        if failures and all(
            any(k in (f.error or "") for k in ("低于90", "低于80", "低于75", "过度改写风险"))
            for f in failures
        ):
            return "质量门槛失格"
        # 活跃模型对文本的降分无反应。
        # 🔧 2026-10-16 改用「确定AI段落占比」判定：原先用 ai_score 绝对差，
        # 而该值在 LLM 改写区间恒为 100（把 AI 段落改判疑似不会让它下降），
        # 于是任何一轮都必然满足「差 ≤ 5」而被误判成模型降不动——
        # 2026-10-16 实测 8 样本真实归因是「质量门槛失格」，却报「活跃模型全降不动」。
        scored = [
            r for r in results
            if r.original_ai_score is not None and r.rewritten_ai_score is not None
        ]
        if scored and all(
            abs(r.original_ai_score - r.rewritten_ai_score) <= 5 for r in scored
        ):
            # ai_score 本就无分辨力，此处只能作为「尚未拿到 ratio 时的兜底」：
            # 若有 ratio 数据，说明检测成功，不应再归因到模型降分能力
            has_ratio = any(r.rewritten_ai_ratio is not None for r in results)
            if not has_ratio:
                return "活跃模型全降不动"
        return "改写全失格"

    @staticmethod
    def _now_iso() -> str:
        # 与文件内既有时间戳写法（L1301 completed_at）保持一致，使用本地时间
        return datetime.now().isoformat()

    @classmethod
    def _quality_layer(
        cls, results: List[EvaluationResult], expected_count: int
    ) -> float:
        """帕累托分层键：质量失格样本数 + 方差塌缩折算层数（值越小越优）。

        🔧 2026-10-16 新增。把「质量」从加权项改为**分层键**：
        质量是准入语义（这一版能不能用），ratio 是优化语义（这版好不好），
        两者不应相互折价。分层键取离散的失格样本数，不随真实分布形态
        连续变化 —— 这正是线性加权模型必须反复调参的根源。

        🔧 方差塌缩并入层键而非作为层外附加罚分：附加罚分能抵消层号差
        （层号步长 1.0压ratio 全域 1.0 已满，附加罚分再减 0.5 就会让
        低层候选反超高层），导致质量准入被推翻。并入层键后它与失格数
        同量级同位置，跨层顺序恒定。

        取 `VARIANCE_COLLAPSE_LAYER_STEP = 1.0`（= 1 个失格样本的层代价）
        而非直接判定失格：真实 8 版本中3/8 命中塌缩（含ratio 次优的
        8f85098d 0.3053），转失格会把可用候选一并淘汰，过于激进。
        折算为 1 个层单位既阻止它压过质量更好的候选，又保留其可排序性。
        """
        layer = float(cls._failed_sample_count(results, expected_count))
        if cls._variance_collapse_penalty(results) > 0:
            layer += cls.VARIANCE_COLLAPSE_LAYER_STEP
        return layer

    @staticmethod
    def _failed_sample_count(
        results: List[EvaluationResult], expected_count: int
    ) -> int:
        """质量硬失败（含缺失）样本数。"""
        if expected_count <= 0:
            return 0
        failed = expected_count - sum(1 for r in results if r.success)
        return max(0, failed)

    @classmethod
    def _ab_rank_score(
        cls, score: float, results: List[EvaluationResult], expected_count: int
    ) -> float:
        # 🔧 2026-10-16 主项为朱雀「确定AI段落占比」（0-1，越低越好）：
        # 此前仅用 LLM 语义人感成本排序，而改写者与评审者同为 doubao 系模型，
        # 存在自我偏好；朱雀是外部独立检测器，是唯一客观信号。
        #
        # 🔧 2026-10-16 改为帕累托分层：质量（层键）为准入，ratio 为层内主项，
        # 两者不再相互折价。score 语义为「层键 + 层内ratio」，
        # 层间必然大于层内差值，故**层间先比质量、层内再比 ratio**，无需调参。
        #
        # score 参数（rewritten_ai_score 均值，LLM 改写区间恒为 100）已无分辨力，
        # 仅为保持调用兼容不再参与排名。
        ratio = cls._median_ai_ratio(results)
        median = cls._median_human_cost(results)
        # 🔧 ratio 完全缺失 = 检测链路失效，无法判断优劣 → 失格（101.0 档）。
        # 否则人感成本会把「测不出」的候选排到「测得出且干净」之前
        # （2026-10-16 实测缺 ratio 得 2.6 分、真实 ratio 80% 反而得 7.4 分）。
        if ratio is None:
            return cls.AI_RATIO_MISSING_PENALTY + cls._variance_collapse_penalty(results)
        failed = cls._failed_sample_count(results, expected_count)
        fail_ratio = failed / expected_count if expected_count > 0 else 1.0
        if fail_ratio > cls.QUALITY_DISQUALIFY_FAILURE_RATIO:
            return 101.0 + ratio + cls._variance_collapse_penalty(results)

        # 🔧 层键已含方差塌缩折算（见 _quality_layer），此处不再叠加
        # _variance_collapse_penalty —— 它作为层外附加项会抵消层号差，
        # 让低层候选反超高层（实测：层0 ratio1.0+塌缩0.5 = 1.605
        # >层1 ratio0.0+无塌缩 = 1.105，质量准入被推翻）。
        # 层内主项为 ratio，人感成本仅作 ratio 持平时的并列项。
        return cls._quality_layer(results, expected_count) + ratio + (
            median * cls.HUMAN_COST_TIEBREAK_WEIGHT
        )

    @staticmethod
    def _median_ai_ratio(results: List[EvaluationResult]) -> Optional[float]:
        """「确定AI段落占比」的中位数（偶数取中间两数均值，0-1 尺度）。

        🔧 2026-10-16 无任何可用 ratio 时返回 None（而非 1.0 / 0.0）：
        0.0 是最优值（全部段落判为人工），1.0 是真实可达的最差值，
        两者都会让「检测失败」被误判成好/普通候选。返回 None 交由调用方
        显式判失格——缺失是「测不出」，不是「确定干净」。

        🔧 2026-10-16 口径修正：不再要求 r.success。原先 `if r.success` 会把
        「评审硬失败但检测成功」的样本整类剔除——那类样本的 ratio 是真实测量值
        （检测发生在评审之前），丢掉它们等于让最差样本不算数，候选的排名
        反而变好。实测上一轮大量失败正是事实分不达90，正是这一类。
        """
        ratios = sorted(
            r.rewritten_ai_ratio
            for r in results
            if r.rewritten_ai_ratio is not None
        )
        if not ratios:
            return None
        n = len(ratios)
        mid = n // 2
        if n % 2 == 1:
            return float(ratios[mid])
        return (ratios[mid - 1] + ratios[mid]) / 2.0

    @classmethod
    def _single_human_cost(cls, result: "EvaluationResult") -> Optional[float]:
        """单个 AC option: 语义人感成本（越低越像人）。

        优先用 LLM 语义评审的人感信号；语义评审不可用时返回 None
        （TMS 已于 2026-08-27 移除：格式复验确认其为格式触发的伪检测器，
        无真阳性能力，不能作代理，宁缺毋滥从中位数中排除该样本）。
        """
        review = result.llm_review or {}
        if not review.get("available"):
            return None  # 语义评审不可用：不用反向的 TMS 代理，排除出中位数

        def _d(key: str) -> float:
            v = review.get(key)
            return v.get("score", 100) if isinstance(v, dict) else 100.0

        over = str(review.get("over_rewrite_risk", "low")).strip().lower()
        over_cost = {"low": 0, "medium": 25, "high": 60}.get(over, 0)
        # 人感成本：满分100指最不像人。writing_naturalness/genre/over_rewrite 为主，
        # 事实与保真维度兜底，防止"自然化"以失真为代价。
        cost = (
            (100 - _d("writing_naturalness")) * 0.25
            + (100 - _d("genre_consistency")) * 0.20
            + (100 - _d("semantic_fidelity")) * 0.20
            + (100 - _d("fact_consistency")) * 0.10
            + (100 - _d("information_completeness")) * 0.10
            + over_cost * 0.15
        )
        return max(0.0, min(100.0, cost))

    @classmethod
    def _median_human_cost(cls, results: List["EvaluationResult"]) -> float:
        """样本"人感成本"的中位数（偶数取中间两数均值）。

        无可用样本时返回 100.0，等价于"全部失格"的高分位，配合
        _ab_rank_score 的质量硬失败判定使用。

        🔧 2026-10-16 口径修正：去掉 `if r.success`。原先只用成功样本算成本，
        而 ratio 已改为全量口径（质量失格样本的 ratio 是实测值）——两者口径
        不一致会让排名项在数量级上错位：失格样本的评审分同样是对该提示词的
        真实评价，剔除它等于让「只有好样本参与」的成本中位数去和「全体样本
        参与」的 ratio 中位数相加。质量失格的影响已由
        _quality_failure_ratio 的显式罚分与硬失格判定表达，不应在此处
        再被隐式剔除一次。
        """
        costs = sorted(
            c for c in (cls._single_human_cost(r) for r in results)
            if c is not None
        )
        if not costs:
            return 100.0
        n = len(costs)
        mid = n // 2
        if n % 2 == 1:
            return float(costs[mid])
        return (costs[mid - 1] + costs[mid]) / 2.0

    # 🔧 反退化守门：句式方差塌缩罚分（守门而非目标）
    # 有效降分文本的特征是句式模式不稳定（完整书面句、单字句、直陈句混用），
    # 句长方差自然不低；把文本洗平（各句长度趋同、每句都刚刚好）是
    # "AI 润色腔"退化信号（2026-08-23 人工改写实验：刻意短句化/白描化
    # 策略反而全文被判疑似）。只罚严重塌缩，不奖励高方差——旧版
    # "方差必须高于原文"的量化指标曾诱导机械制造方差。
    VARIANCE_COLLAPSE_RATIO = 0.5   # 改写稿方差 < 原文×此比例视为塌缩
    # 🔧 2026-10-16（P15）：方差塌缩折算为层键增量，而非层外附加罚分。
    #
    # 见 `_quality_layer` 的取证：作为附加罚分（0.5）时会抵消层号步长 1.0，
    # 使「层0 + ratio 1.0 + 塌缩0.5 = 1.605」反超「层1 + ratio 0.0 + 无塌缩
    # = 1.105」，质量准入被推翻。折算为层键增量后与失格数同量级同位置。
    #
    # 取 1.0（= 1 个失格样本的层代价）而非直接判定失格：真实 8 版本中
    # 3/8 命中塌缩，其中 8f85098d 是 ratio 次优版本（0.3053），
    # 转失格会把可用候选一并淘汰，过于激进。
    VARIANCE_COLLAPSE_LAYER_STEP = 1.0
    # 保留供诊断与失格分支使用（ratio 缺失/ 质量超限时并入 101 档）
    VARIANCE_COLLAPSE_PENALTY = 0.5  # 多数样本塌缩时的附加罚分（诊断用）

    @classmethod
    def _variance_collapse_penalty(cls, results: List[EvaluationResult]) -> float:
        """成功样本的改写稿句长方差相对原文严重塌缩（过半样本）时罚分。"""
        from .novel_rules import calculate_text_metrics

        pairs = [
            (r.original_text, r.rewritten_text)
            for r in results
            if r.success and r.original_text and r.rewritten_text
        ]
        if not pairs:
            return 0.0

        collapsed = 0
        for original, rewritten in pairs:
            orig_var = calculate_text_metrics(original).sentence_length_variance
            if orig_var <= 0:
                continue
            new_var = calculate_text_metrics(rewritten).sentence_length_variance
            if new_var < orig_var * cls.VARIANCE_COLLAPSE_RATIO:
                collapsed += 1

        # 严格过半样本塌缩才罚：个别样本塌缩可能只是段落特性，不构成退化信号
        if collapsed * 2 > len(pairs):
            logger.debug(
                "📉 句式方差塌缩守门命中: %d/%d 样本方差低于原文%.0f%%",
                collapsed, len(pairs), cls.VARIANCE_COLLAPSE_RATIO * 100,
            )
            return cls.VARIANCE_COLLAPSE_PENALTY
        return 0.0


    def _get_prompt_hash(self, prompt: str) -> str:
        """🔧 计算提示词的哈希值用于缓存"""
        import hashlib
        return hashlib.md5(prompt.encode()).hexdigest()[:16]

    def _get_cached_evaluation(self, prompt: str) -> Optional[Tuple[float, List]]:
        """🔧 获取缓存的评估结果（更新访问计数）"""
        import time
        prompt_hash = self._get_prompt_hash(prompt)
        cache_entry = self._evaluation_cache.get(prompt_hash)

        if cache_entry:
            # 更新访问记录
            cache_entry["access_count"] += 1
            cache_entry["last_access"] = time.time()
            return (cache_entry["score"], cache_entry["results"])

        return None

    def _cache_evaluation(self, prompt: str, score: float, results: List, composite_score: Optional[float] = None):
        """🔧 缓存评估结果（基于综合评分保留最优）"""
        import time
        prompt_hash = self._get_prompt_hash(prompt)

        # 计算综合评分（如果未提供）
        if composite_score is None:
            composite_score = score

        self._evaluation_cache[prompt_hash] = {
            "score": score,
            "composite_score": composite_score,
            "results": results,
            "access_count": 1,
            "last_access": time.time()
        }

        # 限制缓存大小（保留评分最好的20个）
        if len(self._evaluation_cache) > 20:
            # 按综合评分排序，移除评分最差的
            sorted_items = sorted(
                self._evaluation_cache.items(),
                key=lambda x: (x[1]["composite_score"], -x[1]["access_count"])  # 评分优先，访问次数其次
            )
            # 移除评分最差的
            worst_key = sorted_items[-1][0]
            removed_score = self._evaluation_cache[worst_key]["composite_score"]
            del self._evaluation_cache[worst_key]
            logger.debug(f"🗑️ 缓存已满，移除评分最差的缓存 (综合评分: {removed_score:.1f})")

    async def _run_multi_model_evaluation(
        self,
        prompt: str,
        sample_text: str,
        temperature: float,
        on_progress: Optional[ProgressCallback] = None,
        progress_pct: int = 0,
        prompt_version_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        🆕 运行多模型评估，追踪各模型表现并更新最优模型

        Args:
            prompt: 当前提示词
            sample_text: 测试样本文本（取第一个样本）
            temperature: LLM温度
            on_progress: 进度回调
            progress_pct: 当前进度百分比

        Returns:
            评估结果字典（含各模型分数、最佳模型ID等），失败时返回None
        """
        try:
            if not get_background_optimization_coordinator().consume_budget(1):
                logger.warning("今日全模型评测预算已用尽，跳过本轮多模型评测")
                return None
            multi_model_service = _get_multi_model_service()
            # 🔧 失败节流：上一次全 0/N 成功时，按累计计数跳过后续 1 个触发间隔
            if multi_model_service.should_skip_mm_eval():
                if on_progress:
                    await on_progress(
                        "⏭️ 多模型评估：上一轮全失败，跳过本次（节流）",
                        progress_pct,
                        {"multi_model_eval": True, "skipped": True},
                    )
                return None

            logger.info("🔬 启动多模型评估...")
            if on_progress:
                await on_progress(
                    "🔬 多模型评估：9个模型并发改写+检测...",
                    progress_pct,
                    {"multi_model_eval": True}
                )

            result = await multi_model_service.evaluate_across_models(
                text=sample_text,
                prompt=prompt,
                temperature=temperature,
                original_ai_score=self.evaluator.get_cached_original_score(sample_text),
                # 🔧 2026-10-17：多模型竞争准入守门改用确定AI占比降幅后，
                # 必须把原文 ratio 一并传下去，否则守门会因缺失而全盘拦掉
                # （曾导致实测 0/9 成功，改写模型选优永久失效）。
                original_ai_ratio=self.evaluator.get_cached_original_ai_ratio(sample_text),
                genre=self.genre,
                prompt_version_id=prompt_version_id,
            )

            if result.get("success") and result.get("results"):
                # 🔧 2026-10-08：排序主键由 ai_score 改为 ai_ratio。
                # ai_score ≈ (ai_ratio + suspect_ratio) × 100 在 LLM 改写区间恒为 100，
                # 旧排序等价于常数排序，best 与 model_scores 全是 100 的常量表，
                # 却被持久化进 PromptVersion.multi_model_scores 当作选型依据。
                best = result["results"][0]
                best_ratio = result.get("best_ai_ratio")
                if best_ratio is None:
                    best_ratio = best.get("ai_ratio")
                # 主项：确定AI段落占比 {model_id: ratio}（0-1，越低越好）
                model_scores = result.get("model_scores") or {
                    r["model_id"]: (
                        r.get("ai_ratio") if r.get("ai_ratio") is not None else 1.0
                    )
                    for r in result["results"]
                }
                # 诊断项：ai_score 恒为 100，仅留作回溯
                model_ai_scores = result.get("model_ai_scores") or {
                    r["model_id"]: r["ai_score"] for r in result["results"]
                }

                def _fmt_ratio(value) -> str:
                    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"

                logger.info(
                    f"🔬 多模型评估完成: "
                    f"最佳={best['model_name']}(确定AI占比={_fmt_ratio(best_ratio)}), "
                    f"{result['total_models_success']}/{result['total_models_tried']}成功, "
                    f"耗时={result['total_time_seconds']:.1f}秒"
                )

                # 输出排行榜
                for i, r in enumerate(result["results"][:5], 1):
                    logger.debug(
                        f"   #{i} {r['model_name']}: "
                        f"确定AI占比={_fmt_ratio(r.get('ai_ratio'))}, "
                        f"降低{r['improvement']}分, "
                        f"耗时={r['latency_seconds']:.1f}秒"
                    )

                if on_progress:
                    await on_progress(
                        f"🔬 多模型评估完成: 最佳={best['model_name']}"
                        f"(确定AI占比={_fmt_ratio(best_ratio)})",
                        progress_pct + 2,
                        {
                            "multi_model_eval_done": True,
                            "best_model": best["model_name"],
                            "best_score": best_ratio,
                            "model_scores": model_scores,
                        }
                    )

                return {
                    "best_model_id": best["model_id"],
                    "best_model_name": best["model_name"],
                    "best_ai_ratio": best_ratio,
                    "best_ai_score": best.get("ai_score"),
                    "model_scores": model_scores,
                    "model_ai_scores": model_ai_scores,
                    "evaluation_results": result["results"],
                    "total_time": result["total_time_seconds"],
                }
            else:
                logger.warning("⚠️ 多模型评估无有效结果")
                return None

        except Exception as e:
            logger.error(f"❌ 多模型评估异常: {e}", exc_info=True)
            return None

    def _check_stop_conditions(
        self,
        ai_score: float,
        readability_score: float,
        writing_score: float,
        fidelity_similarity: float
    ) -> StopReason:
        """
        🆕 检查多维停止条件

        Returns:
            StopReason: 包含是否停止、原因、是否需要回滚
        """
        # 记录历史
        self.score_history.append(ai_score)
        self.readability_history.append(readability_score)
        self.writing_history.append(writing_score)

        # === 1. 保护性停止（最高优先级）===
        # 可读性崩坏
        if readability_score < self.config.readability_crash_threshold:
            return StopReason(
                should_stop=True,
                reason_type="protection",
                reason_message=f"🛑 可读性崩坏 ({readability_score:.0f} < {self.config.readability_crash_threshold})",
                should_rollback=True,
                rollback_reason="可读性严重下降，回滚到上一个可用版本"
            )

        # 文笔崩坏
        if writing_score > self.config.writing_crash_threshold:
            return StopReason(
                should_stop=True,
                reason_type="protection",
                reason_message=f"🛑 文笔崩坏 ({writing_score:.0f} > {self.config.writing_crash_threshold})",
                should_rollback=True,
                rollback_reason="文笔过于干涩，回滚到上一个可用版本"
            )

        # === 2. 成功停止（达到理想状态）===
        # 🔧 2026-10-08 恢复 AI 维度判定（原为 TMS 移除后的硬编码 ai_ok = False）：
        # 旧 TMS 被认定为「格式触发的伪检测器」故清空权重，但朱雀已接替且经真实网关验证
        # 可靠（4 份人类基线全部判 0 分 / 100% 人工）。此处入参 ai_score 已改为
        # 「被判确定AI 的段落占比 ×100」（见调用侧 avg_ai_ratio），具备真实分辨力，
        # 与 early_stop_threshold 同向（越低越好），不再需要永久置否。
        ai_ok = ai_score <= self.config.early_stop_threshold
        readability_ok = readability_score >= self.config.min_readability_score
        writing_ok = writing_score <= self.config.max_writing_score
        fidelity_ok = fidelity_similarity >= self.config.min_fidelity_similarity

        if ai_ok and readability_ok and writing_ok and fidelity_ok:
            return StopReason(
                should_stop=True,
                reason_type="success",
                reason_message=f"🎉 完美达标！AI:{ai_score:.0f}≤{self.config.early_stop_threshold} "
                              f"可读性:{readability_score:.0f}≥{self.config.min_readability_score} "
                              f"文笔:{writing_score:.0f}≤{self.config.max_writing_score} "
                              f"保真:{fidelity_similarity:.0f}≥{self.config.min_fidelity_similarity}",
                should_rollback=False
            )

        # === 3. 收敛检查（改善幅度太小）===
        if len(self.score_history) >= 2:
            improvement = self.score_history[-2] - self.score_history[-1]

            if abs(improvement) < self.config.convergence_threshold:
                self.convergence_count += 1
                self.no_improvement_count += 1
            else:
                self.convergence_count = 0
                self.no_improvement_count = 0
                # 有改善时退出探索模式
                if self.exploration_mode:
                    logger.debug("   ✅ 探索模式成功找到改善方向，退出探索模式")
                    self.exploration_mode = False
                    self.exploration_attempts = 0

            # 🔧 进入探索模式而非直接停止
            if self.convergence_count >= self.config.convergence_count:
                if not self.exploration_mode and self.exploration_attempts < 2:
                    # 进入探索模式，尝试跳出局部最优
                    self.exploration_mode = True
                    self.exploration_attempts += 1
                    self.convergence_count = 0  # 重置计数
                    logger.debug(f"   🔍 进入探索模式（第{self.exploration_attempts}次尝试），使用更高温度和随机策略")
                    # 不返回停止，继续进化
                else:
                    # 探索模式也无法改善，真正停止
                    return StopReason(
                        should_stop=True,
                        reason_type="convergence",
                        reason_message=f"🔄 已收敛：连续{self.config.convergence_count}次改善幅度 < {self.config.convergence_threshold}分（探索模式已尝试{self.exploration_attempts}次）",
                        should_rollback=False
                    )

        # === 4. 震荡停止（分数反复升降）===
        if len(self.score_history) >= 3:
            # 检查最近3次是否升降交替
            diffs = [self.score_history[i+1] - self.score_history[i]
                    for i in range(len(self.score_history)-3, len(self.score_history)-1)]

            if len(diffs) >= 2:
                # 如果符号交替（一正一负或一负一正）
                if (diffs[0] > 0 and diffs[1] < 0) or (diffs[0] < 0 and diffs[1] > 0):
                    self.oscillation_count += 1
                else:
                    self.oscillation_count = 0

                if self.oscillation_count >= self.config.oscillation_count:
                    return StopReason(
                        should_stop=True,
                        reason_type="oscillation",
                        reason_message=f"🔄 策略震荡：分数连续{self.oscillation_count}次升降交替，无法稳定优化",
                        should_rollback=False
                    )

        # 未触发任何停止条件
        return StopReason(should_stop=False)

    def _reset_stop_tracking(self):
        """重置停止条件追踪状态"""
        self.score_history.clear()
        self.readability_history.clear()
        self.writing_history.clear()
        self.convergence_count = 0
        self.oscillation_count = 0
        self.no_improvement_count = 0
        self.exploration_mode = False
        self.exploration_attempts = 0
        self.reverse_optimization_mode = False  # 🆕 反向优化模式标志
        self._injected_candidate_descs = set()  # 🔧 候选挑战者注入追踪重置

    def _inject_candidate_challengers(
        self, filtered_variants: List[Tuple[str, str]]
    ) -> List[Tuple[str, str]]:
        """确定性注入候选挑战者变体（外部 skill 基准实验拆零件产出）。

        候选变体与 LLM 生成变体同台 A/B 竞争，每批次只注入一次
        （批次重置时清空注入记录）；跨批次由失败计数淘汰，历史失败
        达阈值的候选跳过（与既有失败变体过滤一致）。
        """
        from .meta_optimizer import build_candidate_challengers

        for prompt, desc in build_candidate_challengers(self.genre):
            if desc in self._injected_candidate_descs:
                continue
            variant_hash = self._get_prompt_hash(prompt)
            if self._failed_variants.get(variant_hash, 0) >= 3:
                logger.debug(f"   ⏭️ 跳过候选挑战者（已失败多次）: {desc}")
                continue
            filtered_variants.append((prompt, desc))
            self._injected_candidate_descs.add(desc)
            logger.info(f"   🎯 注入候选挑战者参与A/B: {desc}")
        return filtered_variants

    def _get_current_temperature(self) -> float:
        """🔧 获取当前温度（探索模式使用更高温度）"""
        if self.exploration_mode:
            return self.config.exploration_temperature
        return self.config.temperature

    async def _prepare_samples_for_evolution(self):
        """准备题材一致的有效样本；自动检测后必须重新按题材取样。"""
        samples = await self.sample_manager.prepare_evaluation_samples(
            self.config.samples_per_iteration,
            self.evaluator.cached_detector,
            genre=self.genre,
            generator=generate_samples_via_llm,
        )
        if not samples:
            raise RuntimeError("没有通过 AI 基线检测的测试样本")
        if self.genre:
            return samples

        detected_genre = get_genre_detector().detect_from_samples(samples)
        self.genre = detected_genre
        logger.info("🎭 自动检测到题材: %s，重新抽取同题材样本", detected_genre)
        samples = await self.sample_manager.prepare_evaluation_samples(
            self.config.samples_per_iteration,
            self.evaluator.cached_detector,
            genre=detected_genre,
            generator=generate_samples_via_llm,
        )
        if not samples:
            raise RuntimeError(f"题材「{detected_genre}」没有通过 AI 基线检测的测试样本")
        return samples

    def _reset_after_rollback(self):
        """
        🔧 回滚后重置状态（增强版）

        彻底清除失败方向的记忆，引入随机扰动以跳出局部最优
        """
        import random

        # 1. 清除所有历史分析（而非只保留最后2条）
        self.meta_optimizer.previous_analyses.clear()
        logger.info("🔄 回滚：清除所有历史分析记录")

        # 2. 重置收敛和震荡计数
        self.convergence_count = 0
        self.oscillation_count = 0
        self.no_improvement_count = 0

        # 3. 清除部分分数历史（保留最近2个作为参考）
        if len(self.score_history) > 2:
            self.score_history = self.score_history[-2:]
        if len(self.readability_history) > 2:
            self.readability_history = self.readability_history[-2:]
        if len(self.writing_history) > 2:
            self.writing_history = self.writing_history[-2:]

        # 4. 🔧 引入随机扰动：随机移除一些"无效策略"记录
        # 这样可以让系统重新尝试之前被标记为无效的策略
        if self.meta_optimizer.experience.ineffective_strategies:
            num_to_remove = min(3, len(self.meta_optimizer.experience.ineffective_strategies) // 2)
            if num_to_remove > 0:
                for _ in range(num_to_remove):
                    idx = random.randint(0, len(self.meta_optimizer.experience.ineffective_strategies) - 1)
                    removed = self.meta_optimizer.experience.ineffective_strategies.pop(idx)
                    logger.info(f"🎲 随机移除无效策略记录: {removed[:50]}...")

        # 5. 🆕 随机移除部分经验约束（探索模式核心）
        # 移除部分有效策略和失败原因，给系统更多试错空间
        if self.meta_optimizer.experience.effective_strategies:
            num_to_remove = max(1, len(self.meta_optimizer.experience.effective_strategies) // 3)
            for _ in range(num_to_remove):
                if self.meta_optimizer.experience.effective_strategies:
                    idx = random.randint(0, len(self.meta_optimizer.experience.effective_strategies) - 1)
                    removed = self.meta_optimizer.experience.effective_strategies.pop(idx)
                    logger.info(f"🎲 探索模式：随机移除有效策略约束: {removed[:50]}...")

        # 🆕 随机移除部分经验约束（探索模式核心）
        # 移除部分有效策略和无效策略，给系统更多试错空间
        if self.meta_optimizer.experience.effective_strategies:
            num_to_remove = max(1, len(self.meta_optimizer.experience.effective_strategies) // 3)
            for _ in range(num_to_remove):
                if self.meta_optimizer.experience.effective_strategies:
                    idx = random.randint(0, len(self.meta_optimizer.experience.effective_strategies) - 1)
                    removed = self.meta_optimizer.experience.effective_strategies.pop(idx)
                    logger.info(f"🎲 探索模式：随机移除有效策略约束: {removed[:50]}...")

        if self.meta_optimizer.experience.ineffective_strategies:
            num_to_remove = max(1, len(self.meta_optimizer.experience.ineffective_strategies) // 3)
            for _ in range(num_to_remove):
                if self.meta_optimizer.experience.ineffective_strategies:
                    idx = random.randint(0, len(self.meta_optimizer.experience.ineffective_strategies) - 1)
                    removed = self.meta_optimizer.experience.ineffective_strategies.pop(idx)
                    logger.info(f"🎲 探索模式：随机移除无效策略约束: {removed[:50]}...")

        # 6. 🆕 决定是否启用反向优化（50%概率）
        self.reverse_optimization_mode = random.random() < 0.5
        if self.reverse_optimization_mode:
            logger.info("🔀 启用反向优化模式：尝试与历史策略相反的方向")

        # 7. 进入探索模式（使用更高温度）
        self.exploration_mode = True
        self.exploration_attempts += 1
        logger.info(f"🔍 回滚后进入探索模式（第{self.exploration_attempts}次），使用更高温度尝试新方向")

    def _get_dynamic_variant_count(self, iteration: int) -> int:
        """
        🔧 动态变体生成：根据进化阶段调整变体数量

        策略：
        - 早期（前1/3迭代）：生成更多变体（4-5个），广泛探索
        - 中期（中间1/3）：正常数量（3个），平衡探索与利用
        - 后期（后1/3）：减少变体（2个），精细调优
        - 探索模式：增加变体数量
        """
        max_iter = self.config.max_iterations
        base_count = self.config.ab_test_variant_count

        # 探索模式时增加变体
        if self.exploration_mode:
            return min(base_count + 2, 5)

        # 根据进化阶段调整
        progress_ratio = iteration / max_iter

        if progress_ratio < 0.33:
            # 早期：多探索
            return min(base_count + 1, 5)
        elif progress_ratio < 0.66:
            # 中期：正常
            return base_count
        else:
            # 后期：精细调优
            return max(base_count - 1, 2)

    async def run_evolution(
        self,
        on_progress: Optional[ProgressCallback] = None
    ) -> EvolutionHistory:
        """
        运行进化优化流程

        Args:
            on_progress: 进度回调函数 (message, progress_percent, data)

        Returns:
            进化历史记录
        """
        if self.is_running:
            raise RuntimeError("进化引擎正在运行中")

        self.is_running = True

        # 初始化历史记录
        self.history = EvolutionHistory(
            target_score=self.config.target_score,
            max_iterations=self.config.max_iterations,
            genre=self.genre,
        )

        try:
            # 🆕 重置停止条件追踪
            self._reset_stop_tracking()

            # 🔧 准备改写全文临时工作区（清理残留 + 创建本批次目录），
            # 进化过程中可取证完整原文/改写，批次结束在 finally 中整目录删除
            self._prepare_rewrite_workspace()

            logger.debug("🚀🚀🚀 [进化引擎] 开始提示词进化优化...")
            logger.info("🚀 开始提示词进化优化")
            await self._notify_progress(on_progress, "🚀 开始提示词进化优化", 0, {})

            # 获取测试样本（用于题材检测，需早于经验加载/经验优化）
            samples = await self._prepare_samples_for_evolution()
            logger.debug(f"📝 获取到 {len(samples)} 个测试样本")

            # 🆕 自动检测题材（如果未指定）
            if not self.genre:
                logger.debug("🔍 未指定题材，开始自动检测...")
                detector = get_genre_detector()
                self.genre = detector.detect_from_samples(samples)
                logger.debug(f"🎭 自动检测到题材: {self.genre}")

            self.history.genre = self.genre

            if self.genre:
                # 统一设置题材上下文，确保经验加载/经验优化可用
                self.meta_optimizer.current_genre = self.genre
                await self._notify_progress(on_progress, f"🎭 当前题材: {self.genre}", 1, {"genre": self.genre})

            # 🆕 改写执行模型对齐该题材的竞争胜出模型（无竞争数据时回退默认路由）
            self.rewrite_model_id = _get_multi_model_service().get_active_model_id(self.genre)
            if self.rewrite_model_id:
                logger.info(f"🏆 进化改写使用竞争胜出模型: {self.rewrite_model_id}")
                await self._notify_progress(
                    on_progress, f"🏆 改写模型: {self.rewrite_model_id}", 1.5,
                    {"rewrite_model_id": self.rewrite_model_id}
                )
            else:
                logger.info("ℹ️ 该题材暂无竞争最优模型，进化改写使用默认路由")

            # 重置经验库并加载历史经验（跨批次传承）
            self.meta_optimizer.reset_experience()
            historical_reports = self.storage.get_all_experience_reports()

            # 🆕 自动触发经验优化（如果满足条件）
            if historical_reports:
                from .experience_optimizer import get_experience_optimizer
                optimizer = get_experience_optimizer()
                metadata = self.storage.get_optimization_metadata()

                total_reports = len(historical_reports)
                last_opt_count = metadata.get("last_optimization_count", 0)

                if optimizer.should_trigger_optimization(total_reports, last_opt_count):
                    logger.info(f"🔧 触发经验优化：当前 {total_reports} 个报告，上次优化 {last_opt_count} 个")
                    logger.debug(f"🔧 开始优化历史经验...")
                    await self._notify_progress(on_progress, "🔧 正在优化历史经验...", 1.2, {})

                    try:
                        # 执行优化
                        opt_result = await optimizer.optimize_experiences(historical_reports, self.genre)

                        # 保存优化结果
                        optimized_exps = [item.to_dict() for item in opt_result.top_strategies]
                        self.storage.save_optimized_experiences(optimized_exps)
                        self.storage.update_optimization_metadata(total_reports)

                        # 输出优化摘要
                        logger.debug(opt_result.optimization_summary)
                        logger.info(opt_result.optimization_summary)

                        await self._notify_progress(
                            on_progress,
                            f"✅ 经验优化完成: {opt_result.original_count} → {len(opt_result.top_strategies)} 条",
                            1.6,
                            {"optimization_summary": opt_result.optimization_summary}
                        )
                    except Exception as e:
                        logger.error(f"❌ 经验优化失败: {e}", exc_info=True)
                        logger.debug(f"⚠️ 经验优化失败，继续使用原始经验: {e}")

            if historical_reports:
                loaded_count = self.meta_optimizer.load_historical_experience(historical_reports, genre=self.genre)
                logger.debug(f"📚 从历史批次加载经验: {loaded_count} 条")
                await self._notify_progress(on_progress, f"📚 加载历史经验 {loaded_count} 条", 2, {})
            else:
                logger.debug("📚 无历史经验，从零开始")

            # 🆕 记录经验基线快照（此后新增的经验才算本次进化的产出）
            self._experience_baseline = self._snapshot_experience()

            # 尝试使用历史最佳提示词作为起点
            initial_prompt = self._get_best_starting_prompt()
            current_version = PromptVersion(
                prompt_text=initial_prompt,
                iteration=0
            )

            # 🔧 热启动：检查是否有缓存的评估结果
            cached = self._get_cached_evaluation(initial_prompt)
            if cached:
                avg_score, results = cached
                logger.debug(f"🔥 热启动：使用缓存的评估结果，平均得分: {avg_score:.1f}")
                await self._notify_progress(on_progress, f"🔥 热启动：使用缓存结果 {avg_score:.1f}", 5, {})
            else:
                # 评估初始版本
                logger.debug("📊 开始评估初始提示词...")
                await self._notify_progress(on_progress, "📊 评估初始提示词...", 5, {})
                avg_score, results = await self.evaluator.evaluate_prompt(
                    initial_prompt, samples, self.config.temperature,
                    model_id=self.rewrite_model_id
                )
                logger.debug(f"📊 初始评估完成，平均得分: {avg_score:.1f}")
                # 缓存结果（传入综合评分）
                # 此时还未计算综合评分，先用AI分数
                self._cache_evaluation(initial_prompt, avg_score, results, composite_score=avg_score)
            initial_failure_ratio = self._quality_failure_ratio(results, len(samples))
            if initial_failure_ratio > self.QUALITY_DISQUALIFY_FAILURE_RATIO:
                logger.warning(
                    "初始提示词多数样本缺失或质量硬失败（%s），版本评分按不合格处理",
                    self._summarize_quality_failures(results),
                )
                avg_score = 100.0
            elif initial_failure_ratio > 0:
                logger.warning(
                    "初始提示词存在少量质量硬失败样本（占比 %.0f%%）: %s",
                    initial_failure_ratio * 100,
                    self._summarize_quality_failures(results),
                )
            current_version.avg_ai_score = avg_score
            current_version.avg_ai_ratio = self._calc_avg_ai_ratio(results)
            current_version.evaluation_results = results
            current_version.avg_score_reduction = self._calc_avg_reduction(results)

            # 🔧 计算初始版本的多维评分（与迭代版本一致）
            readability_scores = []
            writing_scores = []
            composite_scores = []
            for r in results:
                if r.success and r.rewritten_multi_score:
                    readability_scores.append(r.rewritten_multi_score.get("readability_score", 80))
                    writing_scores.append(r.rewritten_multi_score.get("writing_score", 50))
                    composite_scores.append(r.rewritten_multi_score.get("composite_score", avg_score))
            current_version.avg_readability = sum(readability_scores) / len(readability_scores) if readability_scores else 80
            current_version.avg_writing = sum(writing_scores) / len(writing_scores) if writing_scores else 50
            current_version.avg_composite_score = sum(composite_scores) / len(composite_scores) if composite_scores else avg_score
            if initial_failure_ratio > self.QUALITY_DISQUALIFY_FAILURE_RATIO:
                current_version.avg_composite_score = 100.0
            logger.debug(f"📖 初始版本多维评分 - 可读性: {current_version.avg_readability:.1f}, 文笔: {current_version.avg_writing:.1f}, 综合: {current_version.avg_composite_score:.1f}")

            # 🔧 初始评估即全失格：硬停止，不进入迭代
            #    实测 08-23 科幻/历史题材：6 轮迭代全部 56 分钟跑完 best_versions=空，
            #    完全是模型侧降分能力问题，提示词无法通过进化解决，浪费 token。
            #    失败归因四类：改写全失格/篇幅守门拦截/检测失败/活跃模型全降不动。
            all_failed_hard = (
                initial_failure_ratio > self.QUALITY_DISQUALIFY_FAILURE_RATIO
                or (len(samples) > 0 and all(not r.success for r in results))
                or current_version.avg_composite_score >= 100.0
            )
            if all_failed_hard:
                attribution = self._diagnose_initial_failure(results)
                fail_detail = self._summarize_quality_failures(results)
                abort_msg = (
                    f"初始评估中止：{attribution}（失败占比{initial_failure_ratio:.0%}，"
                    f"综合分{current_version.avg_composite_score:.1f}）。{fail_detail}"
                )
                logger.warning("🛑 %s", abort_msg)
                self.history.error_message = abort_msg
                self.history.completed_at = self._now_iso()
                # 🔧 2026-10-17(P31)：落 stop_type，便于按类型聚合统计
                # （此前只有 error_message 文本，无法机器分类）。
                # status 保持 running + completed_at 的既有语义不在本轮改动范围内 ——
                # 实测存档 85337c99 就是 interrupted 态，改动它会影响前端列表筛选。
                self.history.stop_type = "initial_abort"
                self.history.stop_reason = abort_msg
                self.history.score_history = list(self.score_history)
                # 🔧 2026-10-16：留痕但不参评。整轮评估证据（逐样本 ratio、
                # 段落真值、质量分、失败语义）必须留档，否则连续中止时
                # 无法回答「到底哪个维度不达标」这个唯一有决策价值的问题。
                self._record_aborted_version(current_version, attribution)
                self._save_progress()
                # 中断兜底保存：初始失败通常在经验基线建立之后已落盘快照，
                # 但本轮未产生新迭代→new_count==0，_save_experience_on_interrupt
                # 内部会跳过不落盘，不污染跨题材经验池。
                self._save_experience_on_interrupt()
                await self._notify_progress(
                    on_progress,
                    f"🛑 {abort_msg}",
                    100,
                    {"iteration": 0, "aborted": True, "attribution": attribution},
                )
                return self.history

            self._update_best_versions(current_version)
            self.history.all_versions.append(current_version)
            self._save_progress()

            await self._notify_progress(
                on_progress,
                f"初始得分: {avg_score:.1f}",
                10,
                {"iteration": 0, "score": avg_score}
            )

            # 迭代优化
            for iteration in range(1, self.config.max_iterations + 1):
                logger.debug(f"\n🔄🔄🔄 [进化引擎] 开始迭代 {iteration}/{self.config.max_iterations}")
                self.history.current_iteration = iteration
                progress = 10 + int(80 * iteration / self.config.max_iterations)

                # 注意：多维停止条件在迭代结束时检查（_check_stop_conditions）
                # 这里只做简单的迭代进度通知
                await self._notify_progress(
                    on_progress,
                    f"🔄 迭代 {iteration}/{self.config.max_iterations}：优化提示词...",
                    progress,
                    {"iteration": iteration}
                )

                # 元优化：生成改进的提示词
                logger.debug(f"🧠 调用元优化器生成改进提示词...")
                # 🆕 传入探索模式和反向优化标志
                improved_prompt, analysis = await self.meta_optimizer.optimize_prompt(
                    current_version,
                    self.config.target_score,
                    self.history.all_versions,
                    exploration_mode=self.exploration_mode,
                    reverse_optimization=self.reverse_optimization_mode
                )
                if self.exploration_mode:
                    mode_info = "🔍探索模式"
                    if self.reverse_optimization_mode:
                        mode_info += " + 🔀反向优化"
                    logger.debug(f"{mode_info} 元优化完成，分析: {analysis[:100]}...")
                else:
                    logger.debug(f"🧠 元优化完成，分析: {analysis[:100]}...")

                # 🔧 A/B测试：根据配置间隔生成变体进行对比
                best_prompt = improved_prompt
                best_analysis = analysis
                best_score = float('inf')

                ab_interval = self.config.ab_test_interval
                if iteration % ab_interval == 0 and iteration > 0:
                    logger.debug(f"🔬 进行A/B测试...")
                    await self._notify_progress(
                        on_progress,
                        f"🔬 迭代 {iteration}: 进行A/B变体测试...",
                        progress + 2,
                        {"iteration": iteration, "ab_test": True}
                    )

                    # 🔧 动态变体生成：根据进化阶段调整数量
                    variant_count = self._get_dynamic_variant_count(iteration)
                    # 🆕 传入探索模式标志
                    variants = await self.meta_optimizer.generate_prompt_variants(
                        improved_prompt,
                        variant_count,
                        exploration_mode=self.exploration_mode
                    )

                    # 🆕 过滤失败变体（失败次数>=3的变体）
                    filtered_variants = []
                    skipped_count = 0
                    for variant_prompt, variant_desc in variants:
                        if variant_prompt:
                            variant_hash = self._get_prompt_hash(variant_prompt)
                            fail_count = self._failed_variants.get(variant_hash, 0)
                            if fail_count >= 3:
                                logger.debug(f"   ⏭️ 跳过失败变体（已失败{fail_count}次）: {variant_desc}")
                                skipped_count += 1
                            else:
                                filtered_variants.append((variant_prompt, variant_desc))

                    # 🔧 确定性注入候选挑战者（单次运行只参与一轮 A/B）
                    filtered_variants = self._inject_candidate_challengers(filtered_variants)

                    if not filtered_variants:
                        logger.debug(f"   ℹ️ 所有变体均已失败，跳过A/B测试")
                    else:
                        if skipped_count > 0:
                            logger.debug(f"   🛡️ 已过滤 {skipped_count} 个失败变体")

                        # 🔧 使用配置的样本数进行A/B评估
                        ab_sample_count = min(self.config.ab_test_sample_count, len(samples))
                        ab_samples = samples[:ab_sample_count]
                        # 🆕 A/B 统一执行模型（进化启动时锁定的题材活跃模型）：
                        # 提示词效应是模型条件性的（同一提示词 step=0 分、
                        # doubao=94 分，九模型实测），日志显式记录执行模型，
                        # 供挑战者模型条件性追溯
                        logger.debug(
                            f"   📋 使用 {ab_sample_count} 个样本进行A/B评估"
                            f"（{len(filtered_variants)}个有效变体，"
                            f"执行模型={self.rewrite_model_id or '默认路由'}）"
                        )

                        # 🆕 评估原始版本（优先使用缓存）
                        cached_orig = self._get_cached_evaluation(improved_prompt)
                        if cached_orig:
                            orig_score, orig_results = cached_orig
                            logger.debug(f"   📊 原始版本得分: {orig_score:.1f} (💾缓存)")
                        else:
                            orig_score, orig_results = await self.evaluator.evaluate_prompt(
                                improved_prompt, ab_samples, self.config.temperature,
                                model_id=self.rewrite_model_id
                            )
                            logger.debug(f"   📊 原始版本得分: {orig_score:.1f}")
                            # 缓存原始版本评估结果
                            self._cache_evaluation(improved_prompt, orig_score, orig_results)

                        orig_rank_score = self._ab_rank_score(
                            orig_score, orig_results, ab_sample_count
                        )
                        best_score = orig_rank_score
                        if orig_rank_score > 100:
                            logger.warning(
                                "   原始A/B候选多数样本缺失或质量硬失败，取消获胜资格: %s",
                                self._summarize_quality_failures(orig_results),
                            )
                        elif not self._is_complete_quality_evaluation(orig_results, ab_sample_count):
                            logger.warning(
                                "   原始A/B候选存在少量质量硬失败样本，排入更高质量层: %s",
                                self._summarize_quality_failures(orig_results),
                            )

                        # 收集所有变体得分用于统计
                        all_scores = [(orig_rank_score, improved_prompt, "原始版本")]

                        # 🆕 评估变体（优先使用缓存；并行评估，样本级并发由评估器信号量限流）
                        async def _evaluate_variant(variant_prompt: str):
                            cached_var = self._get_cached_evaluation(variant_prompt)
                            if cached_var:
                                return cached_var[0], cached_var[1], True
                            var_score, var_results = await self.evaluator.evaluate_prompt(
                                variant_prompt, ab_samples, self.config.temperature,
                                model_id=self.rewrite_model_id
                            )
                            # 缓存变体评估结果
                            self._cache_evaluation(variant_prompt, var_score, var_results)
                            return var_score, var_results, False

                        variant_outcomes = await asyncio.gather(
                            *[_evaluate_variant(vp) for vp, _ in filtered_variants]
                        )

                        for i, ((variant_prompt, variant_desc), outcome) in enumerate(
                            zip(filtered_variants, variant_outcomes), 1
                        ):
                            var_score, var_results, from_cache = outcome
                            cache_note = " (💾缓存)" if from_cache else ""
                            logger.debug(f"   📊 变体{i}得分: {var_score:.1f} ({variant_desc}){cache_note}")

                            var_rank_score = self._ab_rank_score(
                                var_score, var_results, ab_sample_count
                            )
                            if var_rank_score > 100:
                                logger.warning(
                                    "   变体%d多数样本缺失或质量硬失败，取消获胜资格: %s | 原因: %s",
                                    i, variant_desc,
                                    self._summarize_quality_failures(var_results),
                                )
                            elif not self._is_complete_quality_evaluation(var_results, ab_sample_count):
                                logger.warning(
                                    f"   变体%d存在少量质量硬失败样本，排入更高质量层: %s | 原因: %s",
                                    i, variant_desc,
                                    self._summarize_quality_failures(var_results),
                                )
                            all_scores.append((var_rank_score, variant_prompt, variant_desc))

                        # 🔧 选择最佳版本（需要满足显著性差异）
                        all_scores.sort(key=lambda x: x[0])
                        winner_score, winner_prompt, winner_desc = all_scores[0]

                        # 检查是否有显著改善
                        score_diff = orig_rank_score - winner_score
                        if winner_score <= 100 and (
                            orig_rank_score > 100
                            or score_diff >= self.config.ab_test_min_diff
                        ):
                            best_score = winner_score
                            best_prompt = winner_prompt
                            # 🔧 2026-10-16 用 .3f：分层后 score = 失格数(层号)
                            # + ratio(0~1) + 并列项，层内差异常在 0.1~0.5 量级
                            # （实测同层ratio 最大差 0.5318），`.1f` 会把
                            # 0.17 读成 0.2 而与阈值比较失真。
                            best_analysis = f"{analysis} [A/B胜出: {winner_desc}, ↓{score_diff:.3f}分]"
                            logger.debug(f"   ✨ {winner_desc}显著胜出! (差异: {score_diff:.3f}分)")
                        elif winner_prompt != improved_prompt:
                            logger.debug(
                                f"   ➡️ 差异不显著({score_diff:.3f}<{self.config.ab_test_min_diff})，保持原版本"
                            )
                            # 🆕 记录失败变体
                            for var_score, var_prompt, var_desc in all_scores[1:]:
                                if var_prompt != improved_prompt:  # 排除原始版本
                                    var_hash = self._get_prompt_hash(var_prompt)
                                    self._failed_variants[var_hash] = self._failed_variants.get(var_hash, 0) + 1
                                    fail_count = self._failed_variants[var_hash]
                                    if fail_count >= 3:
                                        logger.debug(f"   ⚠️ {var_desc}已失败{fail_count}次，将被标记")

                # 创建新版本
                new_version = PromptVersion(
                    prompt_text=best_prompt,
                    iteration=iteration,
                    parent_version_id=current_version.version_id,
                    analysis=best_analysis
                )

                # 评估新版本（完整评估）
                # 🔧 使用动态温度（探索模式时使用更高温度）
                current_temp = self._get_current_temperature()
                if self.exploration_mode:
                    logger.debug(f"   🔍 探索模式：使用温度 {current_temp}")
                avg_score, results = await self.evaluator.evaluate_prompt(
                    best_prompt, samples, current_temp,
                    model_id=self.rewrite_model_id
                )
                # 🔧 真实优化信号：改写后被判「确定AI」的段落占比（0-1，越低越好）。
                # 实测 ai_score ≈ (ai_ratio + suspect_ratio) × 100，在 LLM 改写区间恒为 100，
                # 无法感知「AI→疑似」的真实进步；ai_ratio 才能反映它（实测可 100%→0%）。
                # 🔧 2026-10-16：原先此处内联了一份带 success 过滤的重复实现，
                # 与 _calc_avg_ai_ratio 已漂移（初版初始评估走引擎方法、迭代走内联）。
                # 统一走方法，避免两处口径再次分叉。
                avg_ai_ratio = self._calc_avg_ai_ratio(results)
                ratio_covered, ratio_total = self._ratio_coverage(results)
                if ratio_total and ratio_covered < ratio_total:
                    logger.warning(
                        "⚠️ ratio 覆盖率 %d/%d，缺失样本未计入均值（检测链路可能部分失败）",
                        ratio_covered, ratio_total,
                    )
                full_failure_ratio = self._quality_failure_ratio(results, len(samples))
                if full_failure_ratio > self.QUALITY_DISQUALIFY_FAILURE_RATIO:
                    logger.warning(
                        "当前提示词多数样本缺失或质量硬失败（%s），版本评分按不合格处理",
                        self._summarize_quality_failures(results),
                    )
                    avg_score = 100.0
                elif full_failure_ratio > 0:
                    logger.warning(
                        "当前提示词存在少量质量硬失败样本（占比 %.0f%%）: %s",
                        full_failure_ratio * 100,
                        self._summarize_quality_failures(results),
                    )
                new_version.avg_ai_score = avg_score
                new_version.avg_ai_ratio = avg_ai_ratio
                new_version.evaluation_results = results
                new_version.avg_score_reduction = self._calc_avg_reduction(results)

                # 🆕 提取可读性和文笔分数
                readability_scores = []
                writing_scores = []
                for r in results:
                    if r.success and r.rewritten_multi_score:
                        readability_scores.append(r.rewritten_multi_score.get("readability_score", 80))
                        writing_scores.append(r.rewritten_multi_score.get("writing_score", 50))
                avg_readability = sum(readability_scores) / len(readability_scores) if readability_scores else 80
                avg_writing = sum(writing_scores) / len(writing_scores) if writing_scores else 50

                # 🆕 提取保真度相似度（0-100，越高越好）
                fidelity_scores = []
                for r in results:
                    if r.success and r.rewritten_multi_score:
                        fidelity_score = r.rewritten_multi_score.get("fidelity_score")
                        if isinstance(fidelity_score, (int, float)):
                            fidelity_scores.append(float(fidelity_score))
                avg_fidelity_score = sum(fidelity_scores) / len(fidelity_scores) if fidelity_scores else 50.0
                avg_fidelity_similarity = 100 - avg_fidelity_score

                # 🔧 计算并保存综合评分
                composite_scores = []
                for r in results:
                    if r.success and r.rewritten_multi_score:
                        composite_scores.append(r.rewritten_multi_score.get("composite_score", avg_score))
                avg_composite = sum(composite_scores) / len(composite_scores) if composite_scores else avg_score
                if full_failure_ratio > self.QUALITY_DISQUALIFY_FAILURE_RATIO:
                    avg_composite = 100.0

                new_version.avg_readability = avg_readability
                new_version.avg_writing = avg_writing
                new_version.avg_composite_score = avg_composite

                # 🆕 添加题材标签
                if self.genre:
                    new_version.genre = self.genre
                    new_version.genre_optimized = True

                logger.debug(
                    f"   📖 平均可读性: {avg_readability:.1f}, 平均文笔: {avg_writing:.1f}, "
                    f"平均保真: {avg_fidelity_similarity:.1f}, 综合评分: {avg_composite:.1f}",
                    flush=True
                )
                if self.genre:
                    logger.debug(f"   🎭 题材标签: {self.genre}", flush=True)

                # 🆕 缓存评估结果（传入综合评分以便优化缓存策略）
                self._cache_evaluation(best_prompt, avg_score, results, composite_score=avg_composite)

                # 🆕 多模型评估：按配置间隔触发
                mm_interval = self.config.multi_model_eval_interval
                if mm_interval > 0 and iteration % mm_interval == 0:
                    # 取第一个成功样本的原文作为多模型评测文本
                    eval_sample_text = samples[(iteration - 1) % len(samples)].text if samples else None
                    if eval_sample_text:
                        mm_result = await self._run_multi_model_evaluation(
                            prompt=best_prompt,
                            sample_text=eval_sample_text,
                            temperature=current_temp,
                            on_progress=on_progress,
                            progress_pct=progress + 3,
                            prompt_version_id=new_version.version_id,
                        )
                        if mm_result:
                            new_version.best_model_id = mm_result["best_model_id"]
                            new_version.multi_model_scores = mm_result["model_scores"]

                        # 🆕 挑战赛：定期让淘汰模型有机会复活
                        multi_model_service = _get_multi_model_service()
                        challenge_result = None
                        should_challenge = multi_model_service.config_storage.should_run_challenge(
                            self.genre, iteration
                        )
                        if should_challenge and get_background_optimization_coordinator().consume_budget(1):
                            challenge_result = await multi_model_service.run_challenge_round(
                                text=eval_sample_text,
                                prompt=best_prompt,
                                temperature=current_temp,
                                original_ai_score=self.evaluator.get_cached_original_score(eval_sample_text),
                                original_ai_ratio=self.evaluator.get_cached_original_ai_ratio(eval_sample_text),
                                genre=self.genre,
                                current_iteration=iteration,
                                baseline_results=mm_result.get("evaluation_results") if mm_result else None,
                                prompt_version_id=new_version.version_id,
                            )
                        elif should_challenge:
                            logger.warning("今日全模型评测预算已用尽，跳过挑战赛")
                        if challenge_result:
                            logger.info(
                                f"⚔️ 挑战赛结果: 挑战者={challenge_result['challengers']}, "
                                f"复活={challenge_result['revived']}"
                            )

                # 🆕 多维停止条件检查
                # 🔧 传入 ai_ratio×100 作为 AI 维度信号（有分辨力），而非恒为 100 的 ai_score
                # 🔧 2026-10-16 ratio 缺失时不再回退 avg_score（恒 100）：
                # 那会让「检测链路失效」被当作一个真实的收敛值写进 score_history，
                # 污染收敛/震荡判定。改为传最差值 100.0 —— 与回退目标同数值，
                # 但明确表达「无可用信号」，且 ai_ok 恒 False 不会误判达标。
                ai_signal = avg_ai_ratio * 100.0 if avg_ai_ratio is not None else 100.0
                if avg_ai_ratio is None:
                    logger.warning(
                        "   ⚠️ 本轮无有效确定AI占比，停止条件按最差值参与判定"
                    )
                stop_reason = self._check_stop_conditions(ai_signal, avg_readability, avg_writing, avg_fidelity_similarity)

                if stop_reason.should_stop:
                    logger.debug(f"\n   {stop_reason.reason_message}", flush=True)

                    # 🔧 2026-10-17(P31) 停止原因落盘。
                    # 原先只把 reason_message 发给前端进度通知，从不写回 history。
                    # 取证（真实 10 轮存档）：86cff7f7(max=6,实际3)、8260b160(max=5,实际3)、
                    # 13aa3353(max=4,实际1) 三轮 status=completed 而迭代数远小于上限，
                    # error_message 却为 None —— 事后无法区分「跑满」与「收敛/震荡/崩坏退出」。
                    # score_history 一并落盘：它是收敛/震荡判定的唯一数据源
                    # （:754-755、:789-792），只存内存的话进程一退出就无法离线复核。
                    self.history.stop_type = stop_reason.reason_type or None
                    self.history.stop_reason = stop_reason.reason_message or None
                    self.history.score_history = list(self.score_history)

                    if stop_reason.should_rollback and self.best_ever_version:
                        logger.debug(f"   🔄 {stop_reason.rollback_reason}", flush=True)
                        # 回滚到最优版本
                        current_version = self.best_ever_version
                        self._update_best_versions(current_version)
                        self.history.all_versions.append(new_version)  # 仍记录当前版本
                        self._save_progress()

                    await self._notify_progress(
                        on_progress,
                        stop_reason.reason_message,
                        100,
                        {"stop_type": stop_reason.reason_type, "stop_reason": stop_reason.reason_message}
                    )
                    break

                # 🆕 回滚机制：检测是否需要回滚（基于连续退化）
                should_rollback = False

                # 🆕 综合判断：AI分数下降 + 可读性保持 + 文笔保持
                readability_ok = avg_readability >= self.config.readability_crash_threshold
                writing_ok = avg_writing <= self.config.writing_crash_threshold
                quality_ok = readability_ok and writing_ok

                # 🔧 修复：区分"显著改善"、"保持相当"、"退化"三种状态
                SIGNIFICANT_IMPROVEMENT_THRESHOLD = 2.0  # 显著改善阈值（分数下降超过此值）
                EQUIVALENT_THRESHOLD = 1.0  # 相当阈值（分数变化在此范围内视为相当）

                # 🔧 2026-10-16：追踪信号改为「确定AI段落占比×100」。
                # avg_score 来自 rewritten_ai_score 均值，在 LLM 改写区间恒为 100，
                # 用它做追踪基线会使 score_diff 恒为 0 —— is_better(>0) 与
                # is_significantly_better(>=2) 永不成立，best_ever_version 永不赋值，
                # 连续退化回滚与停止时回滚两条保护链同时失效。
                # ratio 缺失（检测链路失效）时无法判断优劣，按持平处理但不刷新基线。
                ratio_signal: Optional[float] = (
                    avg_ai_ratio * 100.0 if avg_ai_ratio is not None else None
                )

                if ratio_signal is None:
                    logger.warning("   ⚠️ 本轮无有效确定AI占比，跳过最优追踪（检测链路可能失效）")
                    score_diff = 0.0
                    is_significantly_better = False
                    is_equivalent = quality_ok
                    is_better = False
                elif self.best_ever_score is None:
                    # 首轮：无历史基线，无条件建立
                    self.best_ever_score = ratio_signal
                    self.best_ever_version = new_version
                    self.consecutive_worse_count = 0
                    score_diff = 0.0
                    is_significantly_better = False
                    is_equivalent = True
                    is_better = False
                    logger.debug(f"   📌 建立最优基线 确定AI占比:{ratio_signal:.1f}%", flush=True)
                else:
                    score_diff = self.best_ever_score - ratio_signal  # 正值表示改善
                    is_significantly_better = (
                        score_diff >= SIGNIFICANT_IMPROVEMENT_THRESHOLD and quality_ok
                    )
                    is_equivalent = abs(score_diff) < EQUIVALENT_THRESHOLD and quality_ok
                    is_better = score_diff > 0 and quality_ok  # 任何程度的改善

                    if is_significantly_better:
                        self.best_ever_score = ratio_signal
                        self.best_ever_version = new_version
                        self.consecutive_worse_count = 0
                        logger.debug(
                            f"   🏆 新的最优版本! 确定AI占比:{ratio_signal:.1f}% "
                            f"可读性:{avg_readability:.1f} 文笔:{avg_writing:.1f} "
                            f"(↓{score_diff:.1f}个百分点)", flush=True
                        )
                    elif is_better:
                        self.best_ever_score = ratio_signal
                        self.best_ever_version = new_version
                        self.consecutive_worse_count = 0
                        logger.debug(
                            f"   ✅ 略有改善 确定AI占比:{ratio_signal:.1f}% "
                            f"(↓{score_diff:.1f}个百分点)", flush=True
                        )
                    elif is_equivalent:
                        # 🔧 保持相当：不累加退化计数，但也不更新最优版本
                        logger.debug(
                            f"   ➡️ 保持相当 确定AI占比:{ratio_signal:.1f}% "
                            f"(±{abs(score_diff):.1f}个百分点)", flush=True
                        )
                    else:
                        self.consecutive_worse_count += 1
                        if not readability_ok:
                            logger.debug(f"   ⚠️ 可读性不合格({avg_readability:.1f})，连续{self.consecutive_worse_count}次未改善", flush=True)
                        elif not writing_ok:
                            logger.debug(f"   ⚠️ 文笔不合格({avg_writing:.1f})，连续{self.consecutive_worse_count}次未改善", flush=True)
                        else:
                            logger.debug(
                                f"   ⚠️ 效果变差 (+{-score_diff:.1f}个百分点)，"
                                f"连续{self.consecutive_worse_count}次", flush=True
                            )

                        # 连续3次变差，触发回滚
                        if self.consecutive_worse_count >= 3 and self.best_ever_version:
                            should_rollback = True
                            logger.debug(
                                f"   🔄 触发回滚！恢复到最优版本 "
                                f"(确定AI占比: {self.best_ever_score:.1f}%)",
                                flush=True,
                            )
                            await self._notify_progress(
                                on_progress,
                                f"🔄 连续退化，回滚到最优版本 (确定AI占比: {self.best_ever_score:.1f}%)",
                                progress + 3,
                                {"rollback": True, "best_ai_ratio_pct": self.best_ever_score}
                            )

                if should_rollback and self.best_ever_version:
                    # 回滚到最优版本
                    current_version = self.best_ever_version
                    self.consecutive_worse_count = 0
                    # 添加回滚记录
                    rollback_note = (
                        f"[回滚] 从确定AI占比{ratio_signal:.1f}% 回滚到 {self.best_ever_score:.1f}%"
                        if ratio_signal is not None
                        else "[回滚] 本轮无有效ratio，回滚到最优版本"
                    )
                    new_version.analysis = f"{best_analysis} {rollback_note}"

                    # 🔧 增强版回滚重置：彻底清除失败方向记忆
                    self._reset_after_rollback()
                else:
                    current_version = new_version

                self._update_best_versions(new_version)
                self.history.all_versions.append(new_version)
                self._save_progress()

                await self._notify_progress(
                    on_progress,
                    f"迭代 {iteration} 完成: 得分 {avg_score:.1f}",
                    progress + 5,
                    {"iteration": iteration, "score": avg_score, "analysis": best_analysis}
                )

            # 完成
            self.history.status = "completed"
            self.history.completed_at = datetime.now().isoformat()
            # 🔧 2026-10-17(P31)：循环正常跑完（跑满 max_iterations）时，
            # stop_type 仍未被 :1556 的停止分支赋值 —— 而这恰恰是最需要区分的一类：
            # 「跑满」与「收敛/震荡/崩坏提前退出」在 status 上都是 completed。
            # 只在此处补默认值，不会覆盖停止分支已写入的真实原因。
            if not self.history.stop_type:
                self.history.stop_type = "max_iter"
                self.history.stop_reason = (
                    f"跑满最大迭代数 {self.config.max_iterations}"
                )
            # score_history 一并落盘，供离线复核收敛/震荡判定
            self.history.score_history = list(self.score_history)
            self._save_progress()

            # 🆕 进化结束时强制触发全模型评测（如果配置启用）
            if self.config.multi_model_eval_at_end and self.history.best_versions:
                best_version = self.history.best_versions[0]
                eval_sample_text = samples[0].text if samples else None
                if eval_sample_text and best_version.prompt_text:
                    logger.info("🔬 进化结束，执行最终全模型评测...")
                    final_mm_result = await self._run_multi_model_evaluation(
                        prompt=best_version.prompt_text,
                        sample_text=eval_sample_text,
                        temperature=self.config.temperature,
                        on_progress=on_progress,
                        progress_pct=95,
                        prompt_version_id=best_version.version_id,
                    )
                    if final_mm_result:
                        best_version.best_model_id = final_mm_result["best_model_id"]
                        best_version.multi_model_scores = final_mm_result["model_scores"]
                        self._save_progress()
                        _final_ratio = final_mm_result.get("best_ai_ratio")
                        _final_ratio_text = (
                            f"{_final_ratio:.3f}"
                            if isinstance(_final_ratio, (int, float))
                            else "N/A"
                        )
                        logger.info(
                            f"🏆 最终多模型排行: 最佳模型={final_mm_result['best_model_name']}"
                            f"(确定AI占比={_final_ratio_text})"
                        )

            # 保存经验报告
            experience_report = self.meta_optimizer.get_experience_report()
            self._save_experience_report(experience_report)

            _top_version = self.history.best_versions[0] if self.history.best_versions else None
            # 🔧 2026-10-08：对外展示的「最佳得分」改用确定AI占比（换算回 0-100 标度）。
            # 旧值取自恒为 100 的 avg_ai_score，等于无论优化好坏都显示「100 分」。
            _top_ratio = _top_version.avg_ai_ratio if _top_version else None
            best_score = (
                _top_ratio * 100.0
                if _top_ratio is not None
                else (_top_version.avg_ai_score if _top_version else 100)
            )
            await self._notify_progress(
                on_progress,
                f"✅ 进化完成！最佳确定AI占比: {best_score:.1f}%",
                100,
                {
                    "best_score": best_score,
                    "best_ai_ratio": _top_ratio,
                    "total_iterations": self.history.current_iteration,
                    "experience_report": experience_report
                }
            )

            return self.history

        except Exception as e:
            logger.error(f"❌ 进化过程出错: {e}")
            if self.history:
                self.history.status = "failed"
                self.history.error_message = str(e)
                # 🔧 2026-10-17(P31)：失败轮次同样落 stop_type/score_history，
                # 否则「失败发生在第几轮、当时信号如何」事后无从判断。
                # 只在未赋值时写，避免覆盖停止分支已落的真实原因。
                if not self.history.stop_type:
                    self.history.stop_type = "exception"
                    self.history.stop_reason = str(e)
                self.history.score_history = list(self.score_history)
                self._save_progress()
                # 🆕 中断兜底：本次进化已产生新经验时也保存经验报告，避免小进步丢失
                self._save_experience_on_interrupt()
            raise
        finally:
            self.is_running = False
            # 🔧 无论成功/失败，批次结束删除本批次改写全文临时工作区，不积留文件
            self._cleanup_rewrite_workspace()

    def _prepare_rewrite_workspace(self) -> None:
        """准备改写全文临时工作区：清理残留目录 + 创建本批次目录并注入评估器。

        残留目录来自上一次进程被杀死的异常退出，启动时自愈清理。
        """
        self._workspace_batch_dir: Optional[Path] = None
        if not self.history:
            return
        root = self.storage.storage_dir / "rewrite_workspace"
        root.mkdir(parents=True, exist_ok=True)
        for entry in root.iterdir():
            if entry.name != self.history.evolution_id:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
        batch_dir = root / self.history.evolution_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_batch_dir = batch_dir
        self.evaluator.workspace_dir = batch_dir
        logger.info(f"🗂️ 改写全文临时工作区: {batch_dir}")

    def _cleanup_rewrite_workspace(self) -> None:
        """批次结束：整目录删除本批次改写全文工作区并清除注入。"""
        self.evaluator.workspace_dir = None
        batch_dir = getattr(self, "_workspace_batch_dir", None)
        if batch_dir is not None:
            if batch_dir.exists():
                shutil.rmtree(batch_dir, ignore_errors=True)
                logger.info("🧹 已清理改写全文临时工作区")
            self._workspace_batch_dir = None

    def _update_best_versions(self, version: PromptVersion) -> None:
        """更新最佳版本列表（保留前N个）"""
        # 🔧 分数门槛（TMS 移除后停用）：TMS 为格式触发的伪检测器（格式干净后
        # 真人与 AI 均得 0），按 avg_ai_score 设上限会把真正的人感版本挡在最佳列表外。降分有效性
        # 改由 composite（语义人感）与保真/成功率门槛保障。
        # 🔧 保真门槛：含硬失败、或语义保真低于 QUALITY_GATES 的版本不得入选
        # 最佳列表，防止带毒提示词（授权增量/固定语境示例）凭高降分进入传承链
        # （2026-08-07 批次 db1cdd3e 取证：85分评审仍入选最佳导致污染闭环）
        #
        # 🔧 2026-10-17(P24)：本注释原先写死了一个保真门槛数字，而实际门槛
        # P7 已下调为 QUALITY_GATES["semantic_fidelity"]。数字与代码脱节，
        # 留着比没有更危险 —— 故改为引用常量名，不再在注释里复制取值。
        if self._version_has_fidelity_failure(version):
            logger.warning(f"🚫 版本 {version.version_id} 含硬失败或低保真样本，不得入选最佳列表")
            return
        # 🔧 成功率门槛：篇幅守门失败样本无评审记录，会穿透保真门槛；
        # 均值只统计成功样本，坍塔型版本借此获得虚高适应度，须按成功率拒绝
        results = version.evaluation_results or []
        if results:
            success_ratio = sum(1 for r in results if r.success) / len(results)
            if success_ratio < self.BEST_VERSION_MIN_SUCCESS_RATIO:
                logger.warning(
                    f"🚫 版本 {version.version_id} 成功样本占比 {success_ratio:.0%} "
                    f"低于下限 {self.BEST_VERSION_MIN_SUCCESS_RATIO:.0%}，疑似坍塔型提示词，不得入选最佳列表"
                )
                return
        # 🔧 2026-10-16：确定AI占比门槛。A/B 选优已改用朱雀 ratio 作主项，
        # 但本门槛此前只看成功率 —— 一个"全部段落仍被判确定AI、只是文笔漂亮"的
        # 提示词仍可凭语义评分入选最佳列表并进入传承链，与优化目标相悖。
        # 阈值取 A/B 显著胜出所需的最小差距量级（2 个百分点）的宽松档：
        # 只拦「完全没有降AI效果」的版本，不与 A/B 的严苛选优标准混淆。
        if (
            version.avg_ai_ratio is not None
            and version.avg_ai_ratio > self.BEST_VERSION_MAX_AI_RATIO
        ):
            logger.warning(
                f"🚫 版本 {version.version_id} 确定AI占比 {version.avg_ai_ratio:.0%} "
                f"高于上限 {self.BEST_VERSION_MAX_AI_RATIO:.0%}，无实际降分效果，不得入选最佳列表"
            )
            return
        # 🔧 安全门槛：提示词文本未通过安全校验不得入选（2026-08-07 批次 17d57ae2
        # 取证：fa2f6e3c 凭一次 A/B 恰好全过的评估携带毒文本入选 best_prompts）
        safety_reason = MetaOptimizer._prompt_safety_reason(version.prompt_text)
        if safety_reason is not None:
            logger.warning(
                f"🚫 版本 {version.version_id} 提示词未通过安全校验，不得入选最佳列表（原因: {safety_reason}）"
            )
            return

        self.history.best_versions.append(version)
        # 🔧 2026-10-08：排序主键由 avg_ai_score 改为 avg_ai_ratio。
        # avg_ai_score 在 LLM 改写区间恒为 100，旧排序退化为按插入序，
        # keep_top_n 截断等于随机丢版本。缺失值按最差 1.0 计。
        self.history.best_versions.sort(
            key=lambda v: (
                v.avg_ai_ratio if v.avg_ai_ratio is not None else 1.0
            )
        )
        self.history.best_versions = self.history.best_versions[:self.config.keep_top_n]

        # 同时保存到文件
        self.storage.save_best_prompts(self.history.best_versions, self.config.keep_top_n)

    @staticmethod
    def _version_has_fidelity_failure(version: PromptVersion) -> bool:
        """检查版本的**失格样本占比**是否超过上限。

        🔧 2026-10-16 三次修正，均依真实轮次取证：

        1) 阈值 `<90` → `<80`：原 90 无出处——`semantic_judge._normalize`
           的正式门槛是 80，而实测语义保真 mean 仅 87.9~91.9，
           `<90` 在真实分布上几乎恒真，使该门完全失效。
           引用 judge 的实际常量，避免门槛值散落多处漂移。

        2) 🔴 全称否决 → 按占比判断（真实轮次 c9ccd818）：
           本函数原为「任一样本 hard_fail 即 return True」，等价于要求
           「全部样本事实一致 ≥ 90」。该轮 fact_consistency 分布
           [78,82,85,93,93,95,96,97]，3/8 低于 90 → 整版否决；
           而成功率已是 62.5%（越过 0.60 门槛）却仍被拦，
           两门口径重叠且保真门更严，导致 best_versions 恒空。
           现改为失格占比 <= BEST_VERSION_MAX_FAILURE_RATIO。

        3) 🔴 「评审置信度不足」不计入失格：
           `semantic_judge` 在 confidence < 0.6 时也记入 hard_fail_reasons，
           但那是**评审自己都说不准**（测量不可靠），不是内容有缺陷。
           把它算作失格，等于用随机噪声否决内容优秀的版本。
           这是「未测量≠合格」的镜像问题：不可靠的测量既不能证明合格、
           也不能证明失格，故既不计入分子也不计入分母。
        """
        judged = 0      # 可用于判定的样本数（排除评审不可靠者）
        failed = 0      # 其中真正失格的样本数
        for r in version.evaluation_results or []:
            review = r.llm_review
            if not isinstance(review, dict):
                continue
            # 评审不可用是「未测量」，不参与判定（P6 已确立的语义）
            if not review.get("available", True):
                continue
            confidence = review.get("confidence")
            if (
                isinstance(confidence, (int, float))
                and confidence < SemanticJudge.MIN_CONFIDENCE
            ):
                logger.debug(
                    f"  样本 {r.sample_id} 评审置信度 {confidence:.2f} 低于下限，"
                    f"按未测量处理，不计入保真门分母"
                )
                continue

            judged += 1
            reasons = review.get("hard_fail_reasons") or []
            # 置信度不足类reason 已在上面按未测量排除，此处不会重复计入
            if review.get("hard_fail") or reasons:
                failed += 1
                continue
            score = (review.get("semantic_fidelity") or {}).get("score")
            if isinstance(score, (int, float)) and score < MetaOptimizer.QUALITY_GATES["semantic_fidelity"]:
                failed += 1

        if judged == 0:
            # 全部样本的评审都不可用/不可靠 → 无任何质量证据可用。
            # 「未测量≠合格」：此时不得放行（放行等于把无证据当合格）。
            logger.warning("  全部样本评审均不可用或置信度不足，无质量证据，按失格处理")
            return True

        failure_ratio = failed / judged
        if failure_ratio > PromptEvolutionEngine.BEST_VERSION_MAX_FAILURE_RATIO:
            logger.warning(
                f"  失格样本占比 {failure_ratio:.0%}（{failed}/{judged}）"
                f"高于上限 {PromptEvolutionEngine.BEST_VERSION_MAX_FAILURE_RATIO:.0%}"
            )
            return True
        return False

    def _calc_avg_reduction(self, results: List[EvaluationResult]) -> float:
        """计算平均得分下降"""
        valid = [r for r in results if r.success]
        if not valid:
            return 0.0
        return sum(r.score_reduction for r in valid) / len(valid)

    @staticmethod
    def _calc_avg_ai_ratio(results: List[EvaluationResult]) -> Optional[float]:
        """改写后被判「确定AI」的段落占比均值（0-1，越小越好）；无实测样本返回 None。

        🔧 2026-08：这是提示词版本的真实适应度。avg_ai_score ≈
        (ai_ratio + suspect_ratio) × 100 在 LLM 改写区间恒为 100，按它排序
        等于按常数排序，无法区分版本优劣。

        🔧 2026-10-16 口径修正：去掉 `r.success` 过滤。理由同_median_ai_ratio——
        评审硬失败的样本已完成检测、ratio 是实测值，剔除它们会让均值只反映
        「质量合格的子集」，失败越多数字越好看（实测迭代2 的 0.4695 就是在
        2/4 失败下算出的）。真实检测均值不应随质量失败而变乐观。
        无实测样本时返回 None（而非 0.0），交由调用方显式判失格。
        """
        ratios = [
            r.rewritten_ai_ratio
            for r in results
            if r.rewritten_ai_ratio is not None
        ]
        return sum(ratios) / len(ratios) if ratios else None

    def _record_aborted_version(
        self, version: PromptVersion, attribution: str
    ) -> None:
        """初始评估中止时保留评估证据（只留痕，不参评）。

        🔧 2026-10-16：中止分支原先只写 history.error_message 就 return，
        `current_version.evaluation_results` 从未进入 all_versions ——
        整轮 8 样本的改写/朱雀检测/语义评审调用（约 2.5 分钟 + 三段 API 费用）
        全部丢弃，事后无法复查哪几个维度不达标、ratio 真实值是多少。
        连续两轮真实进化都是「跑完即丢」（85337c99 与上一轮）。

        严格区分两件事：
        - **留痕**：写进 all_versions，供事后归因与复盘
        - **参评**：绝不调_update_best_versions —— 把失格版本放进传承链
          等于用不可用的提示词污染后续所有轮次
        """
        # 幂等：中止路径可能被多次触达（异常重试、进度回调重入），
        # 重复 append 会让同一份数据在存档里出现多份
        if any(v.version_id == version.version_id for v in self.history.all_versions):
            return

        version.mutation_strategy = f"aborted:{attribution}"
        version.analysis = (
            f"初始评估中止（{attribution}）。本版本仅作留痕，"
            f"不参与最佳列表评选。样本数 {len(version.evaluation_results)}，"
            f"确定AI段落占比均值 "
            f"{version.avg_ai_ratio:.1%}"
            if version.avg_ai_ratio is not None
            else "初始评估中止（" + attribution + "）。本版本仅作留痕，"
                 "不参与最佳列表评选。确定AI段落占比无有效数据（检测链路失效）。"
        )
        self.history.all_versions.append(version)
        logger.info(
            "   💾 已保留中止版本评估证据（%d 样本，确定AI占比 %s）",
            len(version.evaluation_results),
            f"{version.avg_ai_ratio:.1%}" if version.avg_ai_ratio is not None else "N/A",
        )

    @staticmethod
    def _ratio_coverage(results: List[EvaluationResult]) -> tuple:
        """(有 ratio 的样本数, 总样本数)。

        🔧 2026-10-16：均值本身不携带可信度信息——1个样本算出 0.05 与 8 个
        样本算出 0.05 显然不是一回事。缺少覆盖率时，读档者无法判断
        适应度是实测还是少数样本的偶然结果。
        """
        if not results:
            return (0, 0)
        covered = sum(1 for r in results if r.rewritten_ai_ratio is not None)
        return (covered, len(results))

    def _save_progress(self) -> None:
        """保存进化进度"""
        if self.history:
            self.storage.save_evolution_history(self.history)

    def _save_experience_report(self, report: dict) -> None:
        """保存经验报告"""
        if self.history:
            self.storage.save_experience_report(self.history.evolution_id, report)

    def _snapshot_experience(self) -> Dict[str, set]:
        """快照当前经验库（用于中断时判断是否有新增经验）"""
        exp = self.meta_optimizer.experience
        return {
            "effective": set(exp.effective_strategies),
            "ineffective": set(exp.ineffective_strategies),
            "forbidden": set(exp.forbidden_patterns),
            "best_practice": set(exp.best_practices),
            "strategic_insight": set(exp.strategic_insights),
        }

    def _save_experience_on_interrupt(self) -> None:
        """中断/失败时兜底保存经验报告（仅当迭代中产生了新经验，避免历史经验复读污染报告池）"""
        try:
            if self._experience_baseline is None:
                # 尚未完成经验加载即失败，无本次产出
                return
            current = self._snapshot_experience()
            new_count = sum(
                len(current[key] - self._experience_baseline.get(key, set()))
                for key in current
            )
            if new_count == 0:
                logger.info("📚 中断时无新增经验，跳过经验报告保存")
                return
            experience_report = self.meta_optimizer.get_experience_report()
            self._save_experience_report(experience_report)
            logger.info(f"📚 中断兜底保存经验报告: 新增经验 {new_count} 条")
        except Exception as save_err:
            logger.warning(f"⚠️ 中断兜底保存经验报告失败: {save_err}")

    def _get_best_starting_prompt(self) -> str:
        """
        获取最佳起始提示词

        🔧 优先级调整（使用综合评分选择效果最好的）：
        1. 🆕 同题材的历史最佳提示词（综合评分最低的）- 最高优先级
        2. 历史最佳提示词（综合评分最低的）- 优先使用实际效果最好的
        3. 已批准的提示词 - 作为备选
        4. 默认初始提示词

        说明：使用综合评分（而非单纯AI分数）来选择起点，
        综合评分考虑了AI检测、可读性、文笔等多个维度。
        """
        best_score = float('inf')
        best_prompt = None
        best_source = ""
        best_version_id = ""
        best_ai_score = 100.0

        # 1. 🆕 检查历史最佳提示词（优先选择同题材）
        # 🆕 使用全局历史最佳集合，而非上一轮
        best_prompts = self.storage.load_global_best_prompts()
        # 🔧 传承链安全校验：守门建立前的历史带毒版本（授权增量/固定语境示例）
        # 不得被选为起点（2026-08-07 批次 17d57ae2 实证：42cd8e6e 漏网导致
        # "幽影短剑→短刀"在四个批次稳定复现硬失败）
        if best_prompts:
            safe_prompts = [p for p in best_prompts if MetaOptimizer._validate_prompt_safety(p.prompt_text)]
            skipped = len(best_prompts) - len(safe_prompts)
            if skipped:
                logger.warning(f"🚫 起点选择跳过 {skipped} 个未通过安全校验的历史最佳版本")
            best_prompts = safe_prompts
        if best_prompts:
            # 🆕 先筛选同题材的提示词
            if self.genre:
                same_genre_prompts = [p for p in best_prompts if p.genre == self.genre]
                if same_genre_prompts:
                    # 选择同题材中综合评分最低（效果最好）的
                    history_best = min(same_genre_prompts, key=lambda p: p.avg_composite_score)
                    logger.debug(f"🎭 同题材「{self.genre}」最佳: {history_best.version_id}, 综合评分: {history_best.avg_composite_score}, AI分数: {history_best.avg_ai_score}")
                    # （TMS 已移除（格式假象伪检测器），按 avg_ai_score
                    #  <80 设门槛会拒掉真正的人感版本，只看 composite）
                    if history_best.avg_composite_score < best_score:
                        best_score = history_best.avg_composite_score
                        best_ai_score = history_best.avg_ai_score
                        best_prompt = history_best.prompt_text
                        best_source = f"同题材「{self.genre}」最佳"
                        best_version_id = history_best.version_id
                else:
                    logger.debug(f"🎭 没有同题材「{self.genre}」的历史提示词")

            # 如果没有找到同题材的，或者没有指定题材，选择所有历史中最好的
            if not best_prompt:
                # 🔧 选择综合评分最低（效果最好）的
                history_best = min(best_prompts, key=lambda p: p.avg_composite_score)
                logger.debug(f"📊 历史最佳: {history_best.version_id}, 综合评分: {history_best.avg_composite_score}, AI分数: {history_best.avg_ai_score}")
                # （TMS 已移除（格式假象伪检测器），同上，只看 composite，不再设 avg_ai_score 门槛）
                if history_best.avg_composite_score < best_score:
                    best_score = history_best.avg_composite_score
                    best_ai_score = history_best.avg_ai_score
                    best_prompt = history_best.prompt_text
                    best_source = "历史最佳"
                    best_version_id = history_best.version_id
        else:
            logger.debug("📊 没有历史最佳提示词")

        # 2. 检查已批准的提示词（仅当比历史最佳更好时使用）
        approved = self.storage.get_latest_approved_prompt()
        if approved and approved.get("prompt_text") and not MetaOptimizer._validate_prompt_safety(approved["prompt_text"]):
            logger.warning("🚫 已批准提示词未通过安全校验，跳过")
            approved = None
        if approved and approved.get("prompt_text"):
            # 🔧 优先使用综合评分，如果没有则回退到AI分数
            approved_score = approved.get("avg_composite_score", approved.get("avg_ai_score", 100))
            logger.debug(f"📊 已批准: {approved.get('version_id')}, 综合评分: {approved_score}, AI分数: {approved.get('avg_ai_score')}")
            if approved_score < best_score:
                best_score = approved_score
                best_ai_score = approved.get("avg_ai_score", 100)
                best_prompt = approved["prompt_text"]
                best_source = "已批准"
                best_version_id = approved.get("version_id", "?")
        else:
            logger.debug("📊 没有已批准提示词")

        # 使用找到的最佳提示词
        if best_prompt:
            logger.debug(f"✨ 使用{best_source}提示词作为起点 (综合评分: {best_score:.1f}, AI分数: {best_ai_score:.1f})")
            logger.info(f"✨ 使用{best_source}提示词: {best_version_id}, 综合评分: {best_score}, AI分数: {best_ai_score}")
            return best_prompt

        # 3. 使用默认初始提示词（🔧 支持按题材定制）
        if self.genre:
            logger.debug(f"📝 使用默认初始提示词（题材: {self.genre}）")
        else:
            logger.debug("📝 使用默认初始提示词")
        return self.meta_optimizer.get_initial_prompt(genre=self.genre)

    async def _notify_progress(
        self,
        callback: Optional[ProgressCallback],
        message: str,
        progress: int,
        data: dict
    ) -> None:
        """通知进度"""
        logger.info(f"[{progress}%] {message}")
        if callback:
            try:
                await callback(message, progress, data)
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")


async def run_evolution(
    config: Optional[EvolutionConfig] = None,
    on_progress: Optional[ProgressCallback] = None
) -> EvolutionHistory:
    """便捷函数：运行进化优化"""
    engine = PromptEvolutionEngine(config)
    return await engine.run_evolution(on_progress)
