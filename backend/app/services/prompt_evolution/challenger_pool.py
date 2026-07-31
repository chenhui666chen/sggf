"""
挑战者池纯逻辑（设计文档 §3.1 / §3.2）

- 统一七项离线准入门槛 evaluate_offline_gate：把原先散落在 meta_optimizer / evaluator /
  ai_trace_competition 三处的合格判断收敛为单一聚合函数（§3.2 七条，按顺序短路）；
- challenger_id / prompt_hash 生成（带内容哈希，供 prompt_challengers 唯一约束）；
- strategy_family 策略族分类（把仅有 strategy_desc 的变体映射到分层统计分组键，§3.1）。

纯函数、无 IO、无数据库；提示词安全检查复用 MetaOptimizer._validate_prompt_safety 单一真源。
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from .meta_optimizer import MetaOptimizer
from .novel_rules import ALL_FORBIDDEN_WORDS

# 七项准入门槛阈值（§3.2 ①②③）
GATE_MIN_FIDELITY = 80.0
GATE_MIN_FACT = 90.0
GATE_MIN_COMPLETENESS = 75.0

# strategy_desc → strategy_family 关键词映射（首个命中即归类，§3.1 分层统计分组键）
_STRATEGY_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sentence_structure", ("句式", "句子", "长短句", "断句", "语序", "同构", "结构")),
    ("vocabulary", ("词汇", "用词", "措辞", "词语", "同义", "替换词", "选词")),
    ("entity_compression", ("实体", "专名", "压缩", "精简", "冗余", "删减", "重复")),
    ("rhythm", ("节奏", "停顿", "韵律", "语气", "缓急", "段落")),
)


def compute_prompt_hash(prompt_text: str) -> str:
    """内容哈希：sha256 前 16 位，带 sha256: 前缀（与 prompt_challengers.prompt_hash 对齐）"""
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def make_challenger_id(genre: str, prompt_hash: str, date_str: Optional[str] = None) -> str:
    """生成 challenger_id：chg_{题材}_{日期}_{内容哈希前 4 位}（确定性，同输入同 id）"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    hex_part = prompt_hash.split(":", 1)[-1]
    return f"chg_{genre}_{date_str}_{hex_part[:4]}"


def classify_strategy_family(strategy_desc: str) -> str:
    """按关键词把策略描述归入策略族，无命中归 other"""
    text = strategy_desc or ""
    for family, keywords in _STRATEGY_FAMILY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return family
    return "other"


def find_forbidden_words(text: str) -> list[str]:
    """检出文本中残留的禁用词（§3.2 ⑥ 的基础检查）"""
    return [word for word in ALL_FORBIDDEN_WORDS if word in text]


@dataclass(frozen=True)
class OfflineGateResult:
    """离线准入判定结果"""

    passed: bool
    failed_gate: Optional[str]
    reason: str
    scores: dict


def evaluate_offline_gate(
    *,
    prompt_text: str,
    prompt_hash: str,
    semantic_fidelity: float,
    fact_consistency: float,
    information_completeness: float,
    over_rewrite_risk: str,
    rewrite_texts: Sequence[str] = (),
    blocked_hashes: Iterable[str] = (),
    review_available: bool = True,
) -> OfflineGateResult:
    """
    统一七项离线准入门槛（§3.2），按顺序短路，返回第一个失败项。

    进入在线挑战者池的先决条件（七条全过）：
    ① 语义保真 ≥ 80  ② 事实一致 ≥ 90  ③ 信息完整 ≥ 75  ④ 过度改写风险 = low
    ⑤ 提示词安全检查通过  ⑥ 改写输出无禁用词残留  ⑦ 不在失败变体记录中
    """
    scores = {
        "semantic_fidelity": semantic_fidelity,
        "fact_consistency": fact_consistency,
        "information_completeness": information_completeness,
        "over_rewrite_risk": over_rewrite_risk,
    }

    def _fail(gate: str, reason: str) -> OfflineGateResult:
        return OfflineGateResult(passed=False, failed_gate=gate, reason=reason, scores=scores)

    # 前置：评审必须可用（不可用时无法判定 ①-④，直接拒绝）
    if not review_available:
        return _fail("review_unavailable", "语义评审不可用，无法判定准入")

    # ① 语义保真
    if semantic_fidelity < GATE_MIN_FIDELITY:
        return _fail("semantic_fidelity", f"语义保真 {semantic_fidelity} < {GATE_MIN_FIDELITY}")
    # ② 事实一致
    if fact_consistency < GATE_MIN_FACT:
        return _fail("fact_consistency", f"事实一致 {fact_consistency} < {GATE_MIN_FACT}")
    # ③ 信息完整
    if information_completeness < GATE_MIN_COMPLETENESS:
        return _fail(
            "information_completeness",
            f"信息完整 {information_completeness} < {GATE_MIN_COMPLETENESS}",
        )
    # ④ 过度改写风险
    if over_rewrite_risk != "low":
        return _fail("over_rewrite_risk", f"过度改写风险为 {over_rewrite_risk}，非 low")
    # ⑤ 提示词安全（复用元优化器的单一真源）
    if not MetaOptimizer._validate_prompt_safety(prompt_text):
        return _fail("prompt_safety", "提示词包含可能破坏原文的高风险策略")
    # ⑥ 改写输出禁用词残留
    forbidden: list[str] = []
    for text in rewrite_texts:
        forbidden.extend(find_forbidden_words(text))
    if forbidden:
        return _fail("forbidden_words", f"改写输出残留禁用词: {sorted(set(forbidden))[:5]}")
    # ⑦ 不在失败变体记录中
    if prompt_hash in set(blocked_hashes):
        return _fail("failed_variant", "命中失败变体记录（历史多次落败）")

    return OfflineGateResult(passed=True, failed_gate=None, reason="七项准入全过", scores=scores)
