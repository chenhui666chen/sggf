"""
同步轻量判定器（设计文档 §5.3）

在线双路服务的同步裁决层：两路都算硬门槛，都过后按排序分 + 不对称 margin 择优。

- 硬失败条件（任一命中即本路出局）：空/过短、长度严重收缩、数字/时间丢失、
  禁用词/模板残留/系统提示泄漏、段落结构破坏、AI 检测未过、内容安全未过、
  显式人名表实体丢失（可选，灵感方舟连续性资产）；
- 排序分：AI 痕迹改善 + 长度稳定 + 数字保留 + 结构完整 − 禁用词惩罚（越高越好）；
- 不对称 margin：挑战者排序分须显著领先才返回挑战者，平局/小胜一律返回冠军。

设计取舍（v2 修正）：
- 中文专名启发式误判率高，**降级为排序信号**，不单独判硬失败；精确实体一致性由异步评审承担；
- 事实漂移风险同步无法可靠计算，排序分中置 0，由异步 fact_consistency 承担；
- 纯函数、无 IO、无外部 API：AI 分数、内容安全结论、检测可用性均由调用方传入，
  使本模块可用离线回放样本直接验证一致率（§14 第 5 步、§3.4 第 1 层校准预热）。
"""
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from .challenger_pool import find_forbidden_words

# 硬门槛阈值（§5.3）
MIN_OUTPUT_LENGTH = 30          # 输出异常短下限（字符）
LENGTH_SHRINK_LIMIT = 0.5       # 相对参照文本收缩超过 50% 判失败
PARAGRAPH_SHRINK_LIMIT = 0.5    # 段落数收缩超过 50% 判结构破坏

# 排序分权重（各分项 0-100，加权求和后再减禁用词惩罚）
_W_AI_IMPROVEMENT = 0.4
_W_LENGTH_STABILITY = 0.2
_W_NUMBER_RETENTION = 0.2
_W_STRUCTURE = 0.2
_FORBIDDEN_PENALTY_PER_HIT = 10.0
_FORBIDDEN_PENALTY_CAP = 40.0

# 数字/时间 token 抽取（阿拉伯数字串，含小数与百分号）
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")

# 系统提示/元话语泄漏特征（改写文不应出现的指令性话术）
_PROMPT_LEAK_MARKERS = (
    "以下是改写", "改写后的文本", "改写后的内容", "作为一个", "作为AI",
    "降低AI", "降低ai", "AI痕迹", "根据要求", "按照要求", "以下为改写",
)

# 模板/Markdown 结构残留特征
_TEMPLATE_RESIDUE_PATTERNS = (
    re.compile(r"\*\*.+?\*\*"),                 # 加粗
    re.compile(r"^#{1,6}\s+", re.MULTILINE),    # 标题
    re.compile(r"^\s*[-*+]\s+", re.MULTILINE),  # 无序列表
    re.compile(r"^\s*\d+\.\s+", re.MULTILINE),  # 有序列表
    re.compile(r"`[^`]+`"),                     # 行内代码
)


def extract_number_tokens(text: str) -> set:
    """抽取文本中的数字/时间 token（阿拉伯数字串）"""
    return set(_NUMBER_PATTERN.findall(text or ""))


def find_missing_numbers(reference: str, candidate: str) -> list:
    """返回参照文本中出现、但候选文本缺失的数字 token"""
    ref_tokens = extract_number_tokens(reference)
    cand_tokens = extract_number_tokens(candidate)
    return sorted(ref_tokens - cand_tokens)


def has_template_residue(text: str) -> bool:
    """检测是否残留 Markdown / 列表 / 标题等模板结构"""
    return any(pattern.search(text or "") for pattern in _TEMPLATE_RESIDUE_PATTERNS)


def has_prompt_leak(text: str) -> bool:
    """检测是否泄漏系统提示 / 元话语指令"""
    return any(marker in (text or "") for marker in _PROMPT_LEAK_MARKERS)


def count_paragraphs(text: str) -> int:
    """按非空行计段落数"""
    return len([p for p in (text or "").split("\n") if p.strip()])


@dataclass(frozen=True)
class HardFailResult:
    """单路硬门槛判定结果"""

    failed: bool
    reasons: list


def check_hard_fail(
    *,
    text: str,
    reference_text: str,
    ai_score: Optional[float],
    ai_threshold: float,
    content_safety_passed: bool,
    detector_available: bool = True,
    required_entities: Sequence[str] = (),
    min_length: int = MIN_OUTPUT_LENGTH,
    shrink_ratio_limit: float = LENGTH_SHRINK_LIMIT,
) -> HardFailResult:
    """单路同步硬门槛（§5.3），累计所有命中原因（非短路，便于观测）"""
    reasons: list = []
    body = (text or "").strip()

    # 1. 空或异常短
    if len(body) < min_length:
        reasons.append(f"输出为空或异常短（{len(body)} < {min_length}）")
        # 后续长度/数字类检查对空文本无意义，直接返回
        return HardFailResult(failed=True, reasons=reasons)

    # 2. 长度相对参照严重收缩
    ref_len = len((reference_text or "").strip())
    if ref_len > 0 and len(body) / ref_len < shrink_ratio_limit:
        reasons.append(f"长度严重收缩（{len(body)}/{ref_len} < {shrink_ratio_limit}）")

    # 3. 数字/时间丢失
    missing = find_missing_numbers(reference_text, body)
    if missing:
        reasons.append(f"数字/时间丢失: {missing[:5]}")

    # 4. 显式人名表实体丢失（仅在给定连续性资产人名表时检查）
    missing_entities = [e for e in required_entities if e and e not in body]
    if missing_entities:
        reasons.append(f"显式人物实体丢失: {missing_entities[:5]}")

    # 5. 禁用词残留
    forbidden = find_forbidden_words(body)
    if forbidden:
        reasons.append(f"禁用词残留: {sorted(set(forbidden))[:5]}")

    # 6. 模板残留 / 系统提示泄漏
    if has_template_residue(body):
        reasons.append("模板结构残留（Markdown/列表/标题）")
    if has_prompt_leak(body):
        reasons.append("系统提示/元话语泄漏")

    # 7. 段落结构破坏
    ref_paras = count_paragraphs(reference_text)
    if ref_paras > 1 and count_paragraphs(body) / ref_paras < PARAGRAPH_SHRINK_LIMIT:
        reasons.append("段落结构破坏（段落数骤降）")

    # 8. AI 检测未通过（检测不可用视为无法判定 → 失败）
    if not detector_available or ai_score is None:
        reasons.append("AI 检测不可用，无法判定")
    elif ai_score > ai_threshold:
        reasons.append(f"AI 检测未通过（{ai_score} > {ai_threshold}）")

    # 9. 内容安全检测未通过
    if not content_safety_passed:
        reasons.append("内容安全检测未通过")

    return HardFailResult(failed=bool(reasons), reasons=reasons)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def compute_ranking_score(
    *,
    original_text: str,
    rewritten_text: str,
    original_ai_score: Optional[float],
    rewritten_ai_score: Optional[float],
) -> float:
    """
    轻量排序分（§5.3，越高越好），两路都过硬门槛后计算：
        AI 痕迹改善 + 长度稳定 + 数字保留 + 结构完整 − 禁用词惩罚
    事实漂移风险由异步评审承担，此处不计入。
    """
    orig_ai = 100.0 if original_ai_score is None else float(original_ai_score)
    rw_ai = 100.0 if rewritten_ai_score is None else float(rewritten_ai_score)
    ai_improvement = _clamp(orig_ai - rw_ai)

    orig_len = len(original_text or "")
    rw_len = len(rewritten_text or "")
    if orig_len > 0:
        length_stability = _clamp(100.0 * (1.0 - abs(1.0 - rw_len / orig_len)))
    else:
        length_stability = 100.0

    orig_numbers = extract_number_tokens(original_text)
    if orig_numbers:
        retained = orig_numbers & extract_number_tokens(rewritten_text)
        number_retention = 100.0 * len(retained) / len(orig_numbers)
    else:
        number_retention = 100.0

    orig_paras = count_paragraphs(original_text)
    rw_paras = count_paragraphs(rewritten_text)
    if orig_paras > 0:
        structure = _clamp(100.0 * (1.0 - abs(orig_paras - rw_paras) / orig_paras))
    else:
        structure = 100.0

    forbidden_penalty = min(
        len(find_forbidden_words(rewritten_text)) * _FORBIDDEN_PENALTY_PER_HIT,
        _FORBIDDEN_PENALTY_CAP,
    )

    score = (
        _W_AI_IMPROVEMENT * ai_improvement
        + _W_LENGTH_STABILITY * length_stability
        + _W_NUMBER_RETENTION * number_retention
        + _W_STRUCTURE * structure
        - forbidden_penalty
    )
    return _clamp(score)


@dataclass(frozen=True)
class LightJudgeResult:
    """同步判定结果（对齐 §7.2 light_judge_result）"""

    hard_fail: bool
    score_champion: Optional[float]
    score_challenger: Optional[float]
    margin_passed: bool
    returned_variant: str
    reasons: list


def judge_pair(
    *,
    original_text: str,
    champion_text: str,
    challenger_text: str,
    champion_ai_score: Optional[float],
    challenger_ai_score: Optional[float],
    ai_threshold: float,
    champion_content_safety_passed: bool = True,
    challenger_content_safety_passed: bool = True,
    detector_available: bool = True,
    required_entities: Sequence[str] = (),
    margin: float = 5.0,
) -> LightJudgeResult:
    """
    成对同步裁决（§5.3 + §5.5 降级表的同步部分）：
    - 挑战者硬失败 → 返回冠军（不算本路硬失败，冠军仍可用）；
    - 两路都硬失败 → 本路整体硬失败，返回冠军占位；
    - 两路都过 → 按排序分 + 不对称 margin 择优，挑战者须显著领先才返回挑战者。
    """
    champ_fail = check_hard_fail(
        text=champion_text, reference_text=original_text,
        ai_score=champion_ai_score, ai_threshold=ai_threshold,
        content_safety_passed=champion_content_safety_passed,
        detector_available=detector_available, required_entities=required_entities,
    )
    chal_fail = check_hard_fail(
        text=challenger_text, reference_text=original_text,
        ai_score=challenger_ai_score, ai_threshold=ai_threshold,
        content_safety_passed=challenger_content_safety_passed,
        detector_available=detector_available, required_entities=required_entities,
    )

    # 两路都硬失败：本次判定整体硬失败
    if champ_fail.failed and chal_fail.failed:
        return LightJudgeResult(
            hard_fail=True, score_champion=None, score_challenger=None,
            margin_passed=False, returned_variant="champion",
            reasons=["champion: " + "；".join(champ_fail.reasons),
                     "challenger: " + "；".join(chal_fail.reasons)],
        )

    # 挑战者硬失败：返回冠军（冠军可用，本路不算硬失败）
    if chal_fail.failed:
        return LightJudgeResult(
            hard_fail=False, score_champion=None, score_challenger=None,
            margin_passed=False, returned_variant="champion",
            reasons=["challenger 硬失败: " + "；".join(chal_fail.reasons)],
        )

    # 冠军硬失败但挑战者可用：返回挑战者（§5.5 仅 returnable 场景，serving_mode 由上层把关）
    if champ_fail.failed:
        return LightJudgeResult(
            hard_fail=False, score_champion=None, score_challenger=None,
            margin_passed=False, returned_variant="challenger",
            reasons=["champion 硬失败，回退挑战者: " + "；".join(champ_fail.reasons)],
        )

    # 两路都过：排序分 + 不对称 margin
    score_champ = compute_ranking_score(
        original_text=original_text, rewritten_text=champion_text,
        original_ai_score=None, rewritten_ai_score=champion_ai_score,
    )
    score_chal = compute_ranking_score(
        original_text=original_text, rewritten_text=challenger_text,
        original_ai_score=None, rewritten_ai_score=challenger_ai_score,
    )
    margin_passed = (score_chal - score_champ) >= margin
    returned = "challenger" if margin_passed else "champion"
    return LightJudgeResult(
        hard_fail=False, score_champion=score_champ, score_challenger=score_chal,
        margin_passed=margin_passed, returned_variant=returned, reasons=[],
    )
