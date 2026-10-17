"""P15 护栏：A/B 选优改为「质量分层 + 层内 ratio 排序」，不再依赖罚分权重。

背景（2026-10-16 连续取证）：
P14 把两项守门罚分从 60.0/ 10.0 降到 0.5，使四项排分项回到0-1 同量纲。
但这暴露出**加权多目标模型的根本局限**：

1. **权重调参无法回避**。质量失格占比与 ratio 的相对权重必须人为设定，
   每次真实轮次形态变化都要重新校准（P8 校准0.75→0.60、P14 校准 60→0.5
   都是同一类反复）。

2. **更严重：真实 score_diff 被压到阈值以下**。用 P14 校准后的真实 8 版本回放：

       8f937f18 0.7652   31c84958 1.1795   e1d4192a 1.0983   53a36ee1 0.6568
       253cd2e3 0.5199   ac737c96 0.6317   8f85098d 0.9456   5df0af76 0.5665

   score 区间仅 0.5199 ~ 1.1795，**最大可能 score_diff = 0.6595**，
   而 `ab_test_min_diff = 3.0` ⇒ `score_diff >= ab_test_min_diff`
   **恒不成立**。A/B 唯一的胜出路径退化成「原始版本被判 >100 失格」，
   正常候选之间的比较被彻底压死。

   即P14 的校准解决了「守门淹没主项」，却让显著性阈值失去了可达性 ——
   两处改动互相拆台。这正是线性加权模型的必然后果：改动任一权重都会
   在另一个尺度上失效。

**解法：帕累托分层（质量准入 + 层内纯 ratio 排序）**

把「质量」从**加权项**改为**分层键**，质量与 ratio 不再相互折价：

    第 0 层：ratio 缺失（测不出）→ 失格（101 档，沿用既有约定）
    第 1 层：失格占比 > 0.5 → 失格（101 档，沿用既有约定）
    第 2 层：质量合格候选 → 按 ratio 纯排序
              人感成本与方差塌缩仅作 ratio 完全相等时的并列项

关键性质：
- **质量是准入而非折价**。失格 4/8 的候选不会因为 ratio 更低而压过失格 1/8 的候选，
  这与「质量硬门槛本属准入语义」的原始设计一致（对比：纯加权会让 4/8 与 1/8 同层竞争）。
- **无需权重调参**。分层键是离散的（失格样本数），不随真实分布形态连续变化。
- **score 区间收敛**。合格候选的 score 落在 0 ~ 2，且层间有明确间隔。

本文件锁定分层语义，并对「阈值必须与新score 尺度一致」一并设防 ——
P14 的教训是：改排分口径必须同时验证 `ab_test_min_diff` 的可达性。
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionConfig,
)


def _review(naturalness=80.0):
    return {
        "available": True,
        "writing_naturalness": {"score": naturalness},
        "genre_consistency": {"score": 90.0},
        "semantic_fidelity": {"score": 90.0},
        "fact_consistency": {"score": 95.0},
        "information_completeness": {"score": 90.0},
        "over_rewrite_risk": "low",
    }


def _r(sample_id, ratio, *, hard_fail=False, naturalness=80.0):
    return EvaluationResult(
        sample_id=sample_id,
        original_text="山风掠过断崖，碎石滚入深涧，林渊握紧手中长剑。" * 6,
        rewritten_text="山风掠过断崖。碎石滚入深涧。林渊握紧长剑，剑身映出冷光。" * 6,
        original_ai_score=100,
        rewritten_ai_score=100,
        score_reduction=0,
        success=not hard_fail,
        error="事实一致性低于90" if hard_fail else None,
        failure_kind="review_hard_fail" if hard_fail else None,
        llm_review=dict(
            _review(naturalness),
            **({"hard_fail": True, "hard_fail_reasons": ["事实一致性低于90"],
                "confidence": 0.9} if hard_fail else {}),
        ),
        rewritten_ai_ratio=ratio,
    )


def _cands(n, ratio, *, fail_count, naturalness=80.0):
    """构造 8 样本候选：前 fail_count 个为质量失格。"""
    return [_r(f"s{i}", ratio, hard_fail=i < fail_count, naturalness=naturalness)
            for i in range(n)]


class TestQualityIsGateNotTradeoff:
    """质量是准入：低 ratio 不能赎买质量失格。"""

    def test_lower_ratio_cannot_buy_back_quality(self):
        """失格 4/8 但 ratio 更低的候选，不得压过失格 1/8 的候选。

        这是「质量准入」与「加权折价」的本质区别：加权模型下
        ratio 优势会直接折算成分数，把质量差距抵消掉。
        """
        n = 8
        clean = _cands(n, 0.45, fail_count=1)     # 质量好，ratio 较差
        dirty = _cands(n, 0.05, fail_count=4)     # ratio 好但失格多

        clean_score = PromptEvolutionEngine._ab_rank_score(0.0, clean, n)
        dirty_score = PromptEvolutionEngine._ab_rank_score(0.0, dirty, n)
        assert clean_score < dirty_score, (
            f"失格 1/8 的候选必须优于失格 4/8 的候选（质量准入优先）；"
            f"实际 {clean_score:.3f} vs {dirty_score:.3f}"
        )

    def test_within_same_fail_layer_ratio_decides(self):
        """失格数相同时，ratio 更低的必须胜出。"""
        n = 8
        low = _cands(n, 0.25, fail_count=2)
        high = _cands(n, 0.60, fail_count=2)
        assert (PromptEvolutionEngine._ab_rank_score(0.0, low, n)
                < PromptEvolutionEngine._ab_rank_score(0.0, high, n))

    def test_equal_fail_count_equal_ratio_uses_tiebreak(self):
        """失格数与 ratio 完全相同时，用并列项（人感成本）决出胜负。"""
        n = 8
        natural = _cands(n, 0.30, fail_count=1, naturalness=90.0)
        artificial = _cands(n, 0.30, fail_count=1, naturalness=60.0)
        assert (PromptEvolutionEngine._ab_rank_score(0.0, natural, n)
                < PromptEvolutionEngine._ab_rank_score(0.0, artificial, n))


class TestDisqualificationUnchanged:
    """既有失格档位不得因分层而改变。"""

    def test_missing_ratio_disqualified(self):
        n = 8
        no_ratio = [
            EvaluationResult(
                sample_id=f"s{i}", original_text="山风掠过断崖。" * 20,
                rewritten_text="山风掠过断崖。" * 20,
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=True, llm_review=_review(),
                rewritten_ai_ratio=None,
            ) for i in range(n)
        ]
        assert (PromptEvolutionEngine._ab_rank_score(0.0, no_ratio, n)
                > 100.0)

    def test_majority_failure_disqualified(self):
        n = 8
        heavy = _cands(n, 0.0, fail_count=5)
        assert (PromptEvolutionEngine._ab_rank_score(0.0, heavy, n)
                > 100.0)

    def test_clean_candidate_not_disqualified(self):
        n = 8
        clean = _cands(n, 0.30, fail_count=0)
        assert (PromptEvolutionEngine._ab_rank_score(0.0, clean, n) < 100.0)


class TestScoreScaleMatchesThreshold:
    """score 尺度必须与 ab_test_min_diff 一致（P14 的教训）。

    P14 把罚分降到 0.5 后，真实候选 score_diff 上限仅 0.6595 < 阈值 3.0，
    使 `score_diff >= ab_test_min_diff` 恒不成立、A/B 压死。本类锁定：
    真实量级的质量分层改进必须能让显著性阈值判定成立。
    """

    n = 8

    def test_real_magnitude_gate_improvement_is_significant(self):
        """真实 A/B 量级：1 个样本的质量差异应能被判为显著。

        取真实候选形态（同为ratio 0.30，失格 1/8 vs 3/8），
        分层后 score_diff 必须达到阈值。
        """
        config = EvolutionConfig()
        near = _cands(self.n, 0.30, fail_count=1)
        far = _cands(self.n, 0.30, fail_count=3)
        diff = (PromptEvolutionEngine._ab_rank_score(0.0, far, self.n)
                - PromptEvolutionEngine._ab_rank_score(0.0, near, self.n))
        assert diff >= config.ab_test_min_diff, (
            f"质量分层带来的真实改进（{diff:.3f}）应达到阈值 "
            f"{config.ab_test_min_diff}，否则 A/B 判定恒不成立"
        )

    def test_real_magnitude_ratio_improvement_is_significant(self):
        """真实量级：ratio 明显更低的同层候选应能被判为显著。

        取实测版本间 ratio 跨度（0.42 -> 0.25，差 0.17），
        失格数相同（同层）时的 score_diff 必须达到阈值。
        """
        config = EvolutionConfig()
        worse = _cands(self.n, 0.42, fail_count=1)
        better = _cands(self.n, 0.25, fail_count=1)
        diff = (PromptEvolutionEngine._ab_rank_score(0.0, worse, self.n)
                - PromptEvolutionEngine._ab_rank_score(0.0, better, self.n))
        assert diff >= config.ab_test_min_diff, (
            f"真实 ratio 改善（{diff:.3f}，取实测跨度 0.169）应达到阈值 "
            f"{config.ab_test_min_diff}"
        )

    def test_threshold_reachable_from_score_range(self):
        """合格候选的 score 区间必须能覆盖阈值量级。"""
        config = EvolutionConfig()
        clean = _cands(self.n, 0.0, fail_count=0)
        dirtiest_pass = _cands(self.n, 1.0, fail_count=4)
        span = (PromptEvolutionEngine._ab_rank_score(0.0, dirtiest_pass, self.n)
                - PromptEvolutionEngine._ab_rank_score(0.0, clean, self.n))
        assert span >= config.ab_test_min_diff, (
            f"合格候选 score 全域 {span:.3f} 必须 >= 阈值 {config.ab_test_min_diff}，"
            f"否则任何真实改进都无法被判显著"
        )

    def test_noise_level_difference_not_significant(self):
        """噪声级差异不得误判为显著（阈值不能退化成 0）。

        ratio 差 0.01（同层）应判不显著——避免把改写随机性当成果。
        """
        config = EvolutionConfig()
        a = _cands(self.n, 0.4000, fail_count=1)
        b = _cands(self.n, 0.3900, fail_count=1)
        diff = (PromptEvolutionEngine._ab_rank_score(0.0, a, self.n)
                - PromptEvolutionEngine._ab_rank_score(0.0, b, self.n))
        assert 0 < diff < config.ab_test_min_diff, (
            f"ratio 差 0.01（{diff:.4f}）不应被判为显著胜出"
        )

class TestVariancePenaltyCannotLeakAcrossLayers:
    """方差塌缩折算入层键后，不得翻转跨层顺序。

    取证：作为层外附加罚分（0.5）时会抵消层号步长 1.0 ——
    实测「层键0 + 方差0.5 + ratio1.0 = 1.605」反超
    「层键1 + ratio0.0 = 1.105」，质量准入被推翻。
    折算入层键后为「层键1.0 + ratio1.0 = 2.105」，正确排在 1.105 之后。
    """

    # 命中方差塌缩的真实形态（句长方差比 0.104，取自 31c84958）
    _COLLAPSED_ORIG = (
        "他走了很长的路，风很大，天很黑，路很长，没有人说话，他一直走。"
        "林渊握紧了手中的长剑，剑身在夜色里泛出一点微光，风从山口灌进来。"
        "他抬起头看了看天色，乌云压得很低，看不见月亮，也没有星星。"
    ) * 2
    _COLLAPSED_NEW = (
        "他走。风大。天黑。路长。无人说话。他走。"
        "林渊握剑。剑光微。夜色。风来。抬头。天低。无月。无星。"
    ) * 6

    def test_collapsed_candidate_cannot_beat_better_layer(self):
        """命中塌缩者（层键1.0）不得压过失格 1 个但无塌缩者（层键1.0）后的更优层。

        两候选层键相同（都是 1.0），此时由 ratio 决胜——这验证的是
        塌缩折算后仍保留可排序性，不会直接出局。
        """
        n = 8
        collapsed = [
            EvaluationResult(
                sample_id=f"s{i}", original_text=self._COLLAPSED_ORIG,
                rewritten_text=self._COLLAPSED_NEW,
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=True, llm_review=_review(),
                rewritten_ai_ratio=1.0,
            ) for i in range(n)
        ]
        one_fail = [_r(f"s{i}", 0.0, hard_fail=(i == 0)) for i in range(n)]
        assert (PromptEvolutionEngine._ab_rank_score(0.0, one_fail, n)
                < PromptEvolutionEngine._ab_rank_score(0.0, collapsed, n)), (
            "同为层键 1.0 时，ratio 更低的无塌缩候选应排在塌缩候选之前"
        )

    def test_true_cross_layer_order_holds(self):
        """真正跨层：层键 0（无塌缩）即便 ratio 极差也必须排在层键 1 之前。

        取真实量级：实测跨版本 ratio 跨度 0.169、同层内最大差 0.5318。
        层键差 1.0 应稳定压过这些真实差距，而不是只在ratio 极小时才成立。

        注：不用 ratio 端点极值（1.0 vs 0.0）—— 端点差恰为 1.0，
        与层键步长打平（`0+1.0` == `1+0.0`），那是分层模型的定义边界而非缺陷，
        真实存档从未出现。
        """
        n = 8
        clean_but_worse = [
            EvaluationResult(
                sample_id=f"s{i}", original_text=self._COLLAPSED_ORIG,
                rewritten_text=self._COLLAPSED_ORIG,
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=True, llm_review=_review(),
                rewritten_ai_ratio=0.5318,
            ) for i in range(n)
        ]
        one_fail_best = [_r(f"s{i}", 0.0, hard_fail=(i == 0)) for i in range(n)]
        assert (PromptEvolutionEngine._ab_rank_score(0.0, clean_but_worse, n)
                < PromptEvolutionEngine._ab_rank_score(0.0, one_fail_best, n)), (
            "层键 0 的候选必须排在层键 1 之前，即便其 ratio 达实测层内最大差 0.5318"
        )

    def test_collapse_adds_exactly_one_layer(self):
        """方差塌缩折算的层键增量恒为1.0（等价于1 个失格样本）。"""
        n = 8
        collapsed = [
            EvaluationResult(
                sample_id=f"s{i}", original_text=self._COLLAPSED_ORIG,
                rewritten_text=self._COLLAPSED_NEW,
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=True, llm_review=_review(),
                rewritten_ai_ratio=0.30,
            ) for i in range(n)
        ]
        assert (PromptEvolutionEngine._quality_layer(collapsed, n)
                == pytest.approx(1.0)), (
            "全通过但命中塌缩 => 层键应为 1.0"
        )
        assert (PromptEvolutionEngine._variance_collapse_penalty(collapsed) > 0
                and PromptEvolutionEngine._quality_layer(collapsed, n) > 0), (
            "塌缩仍应是可检测的退化信号"
        )
