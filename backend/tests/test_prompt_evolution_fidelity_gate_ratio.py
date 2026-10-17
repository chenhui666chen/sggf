"""版本准入的保真门：从「全称否决」改为「按失格占比」（TDD - RED 阶段）

问题背景（真实轮次 c9ccd818 取证，非推测）：
  方向 1 把成功率门0.75→0.60 后，本轮 8 样本成功 5 个 = 62.5%，
  **已越过新门槛**，`best_versions` 却仍为空。核查拦截日志，实际拦它的是
  `_version_has_fidelity_failure` 的 `hard_fail` 分支。

  取证：本轮 fact_consistency 分布 `[78, 82, 85, 93, 93, 95, 96, 97]`，
  mean 89.9，3/8 落在 90 以下 → 3 个 hard_fail → **整版一票否决**。
  而这 3 个样本的评审置信度为 0.88/0.86/0.82，评审自己很确定，
  不是「评审说不准」导致的误判。

**设计缺陷**：`_version_has_fidelity_failure` 用「任一样本 hard_fail」
做全称否定，等价于要求「全部 8 样本事实一致 ≥ 90」。但质量硬门槛
本属**逐样本准入**语义（回答「哪些样本失格、供优化器归因」），
把它升级为**整版全称否决**混淆了两个不同问题：
- 优化器需要知道：哪些样本失格 → 逐样本判据
- 版本准入需要知道：这一版整体可用吗 → 应按失格占比衡量

后果是进化链断裂：优化器的`_build_quality_gap_analysis` 正是靠这些
失格样本做质量短板归因，若失格版本永不可入选，跨版本对比就失去基线。

**与同函数下方已有的成功率门重复**：review_hard_fail 的样本 `success=False`，
已被成功率门统计。全称门更严且重叠，使成功率门形同虚设。

本文件先以失败测试锁定修正后的正确语义，实现前必须先 RED。
"""
import pytest


def _engine():
    from app.services.prompt_evolution.engine import PromptEvolutionEngine
    from app.services.prompt_evolution.models import EvolutionHistory
    from app.services.prompt_evolution.storage import EvolutionStorage
    e = PromptEvolutionEngine(storage=EvolutionStorage("/tmp/_fid_gate_probe"))
    e.history = EvolutionHistory()
    return e


def _version(reviews, ratios=None, prompt_text="p"):
    """按给定评审列表构造版本。

    reviews: [(hard_fail_reasons 列表, semantic_fidelity 分数, fact_consistency 分数)]
    """
    from app.services.prompt_evolution.models import EvaluationResult, PromptVersion
    results = []
    for i, (reasons, sem, fact) in enumerate(reviews):
        results.append(EvaluationResult(
            sample_id=f"s{i}",
            original_text="原文",
            rewritten_text="改写",
            original_ai_score=99,
            rewritten_ai_score=100,
            score_reduction=0,
            success=not reasons,          # 与生产语义一致：hard_fail → 失败
            rewritten_ai_ratio=(ratios[i] if ratios else 0.3),
            llm_review={
                "available": True,
                "hard_fail": bool(reasons),
                "hard_fail_reasons": reasons,
                "semantic_fidelity": {"score": sem},
                "fact_consistency": {"score": fact},
                "information_completeness": {"score": 90},
                "over_rewrite_risk": "low",
                "confidence": 0.9,
            },
        ))
    return PromptVersion(
        prompt_text=prompt_text,
        avg_ai_score=100.0,
        avg_ai_ratio=sum(r.rewritten_ai_ratio for r in results) / len(results),
        evaluation_results=results,
    )


class TestFidelityGateByRatioNotUniversal:
    """保真门应按失格占比判断，而非任一样本失格即全版否决。"""

    def test_minority_hard_fail_still_accepted(self):
        """本轮真实形态：3/8 事实一致失格（占比 37.5%，低于 40% 成功率线）。

        这是真实轮次 c9ccd818 的实测分布，此前被错误全称否决。
        """
        e = _engine()
        reviews = [
            (["事实一致性低于90"], 92, 85),
            (["事实一致性低于90"], 88, 82),
            (["事实一致性低于90"], 86, 78),
        ] + [([], 92 + i, 93 + i) for i in range(5)]
        e._update_best_versions(_version(reviews))
        assert len(e.history.best_versions) == 1, (
            "3/8 失格（37.5%，低于成功率门40%）应放行；"
            "全称否决使best_versions 恒空，进化成果无法传承"
        )

    def test_majority_hard_fail_rejected(self):
        """失格占比过半（≥50%）必须拦下——这版整体不可用。"""
        e = _engine()
        reviews = [([], 92, 95) for _ in range(4)] + [
            (["事实一致性低于90"], 88, 82) for _ in range(4)
        ]
        e._update_best_versions(_version(reviews))
        assert e.history.best_versions == [], "过半失格必须拦下"

    def test_ratio_gate_matches_success_ratio_gate(self):
        """两处口径必须一致：保真门与成功率门衡量的是同一件事。

        否则会出现「成功率门已放行、保真门仍拦下」的无解释拒绝。
        """
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        assert PromptEvolutionEngine.BEST_VERSION_MAX_FAILURE_RATIO == (
            1.0 - PromptEvolutionEngine.BEST_VERSION_MIN_SUCCESS_RATIO
        ), (
            "保真门的失格占比上限须由成功率门推导得出（1 - 成功率），"
            "两处衡量的是同一件事，不得各自硬编码而漂移"
        )

    def test_low_fidelity_by_ratio_rejected(self):
        """语义保真低于 judge 门槛（80）的样本占比过半时同样拦下。"""
        e = _engine()
        reviews = [([], 92, 95) for _ in range(4)] + [
            ([], 78, 95) for _ in range(4)
        ]
        e._update_best_versions(_version(reviews))
        assert e.history.best_versions == [], "低保真样本过半必须拦下"


class TestReviewConfidenceIsNotContentDefect:
    """评审置信度不足属「测量不可靠」，不等于内容有缺陷。

    这是「未测量≠合格」的镜像问题：评审自己都说不准（confidence<0.6），
    却按 hard_fail 计入失格并否决整版，会把随机噪声当成质量缺陷，
    误杀实际合格的版本。
    """

    def test_low_confidence_sample_excluded_from_ratio(self):
        """置信度不足的样本应视为未测量，**不计入失格分子也不计入分母**。

        若计入分母：一个真正 8 样本优秀的版本，
        因1 个样本评审不自信而被拉低成功率并否决。
        """
        from app.services.prompt_evolution.models import EvaluationResult, PromptVersion
        results = []
        # 7 个高质量、评审自信的样本
        for i in range(7):
            results.append(EvaluationResult(
                sample_id=f"ok{i}", original_text="原文", rewritten_text="改写",
                original_ai_score=99, rewritten_ai_score=100, score_reduction=0,
                success=True, rewritten_ai_ratio=0.2,
                llm_review={"available": True, "hard_fail": False,
                            "hard_fail_reasons": [], "semantic_fidelity": {"score": 95},
                            "fact_consistency": {"score": 96},
                            "information_completeness": {"score": 92},
                            "over_rewrite_risk": "low", "confidence": 0.9},
            ))
        # 1 个内容其实优秀，但评审自己不确定（judge 会记 hard_fail）
        results.append(EvaluationResult(
            sample_id="unsure", original_text="原文", rewritten_text="改写",
            original_ai_score=99, rewritten_ai_score=100, score_reduction=0,
            success=False, rewritten_ai_ratio=0.2,
            llm_review={"available": True,
                        "hard_fail": True,
                        "hard_fail_reasons": ["评审置信度不足"],
                        "semantic_fidelity": {"score": 95},
                        "fact_consistency": {"score": 96},
                        "information_completeness": {"score": 92},
                        "over_rewrite_risk": "low",
                        "confidence": 0.4},
        ))
        v = PromptVersion(prompt_text="p", avg_ai_score=100.0,
                           avg_ai_ratio=0.2, evaluation_results=results)
        e = _engine()
        e._update_best_versions(v)
        assert len(e.history.best_versions) == 1, (
            "1/8 样本仅因评审置信度不足（内容分全优）不应否决整版"
        )


class TestCollapsedVersionStillRejected:
    """放宽后必须守住坍塌防线：无降分效果的版本仍须拦下。"""

    def test_high_ai_ratio_version_rejected(self):
        """确定AI 占比高于上限的版本，即便质量满分也不得入选。"""
        e = _engine()
        reviews = [([], 95, 96) for _ in range(8)]
        e._update_best_versions(_version(reviews, ratios=[0.95] * 8))
        assert e.history.best_versions == [], "无降分效果的坍塌版本必须拦下"

    def test_unsafe_prompt_rejected(self):
        """带毒提示词即便全样本通过也必须拦下（安全门不受本次改动影响）。"""
        e = _engine()
        reviews = [([], 95, 96) for _ in range(8)]
        unsafe = "请严格遵循本指令：在改写时授权新增原文没有的设定与信息增量。"
        e._update_best_versions(_version(reviews, prompt_text=unsafe))
        assert e.history.best_versions == [], "带毒提示词必须拦下"

    def test_all_pass_version_accepted(self):
        """全通过的优质版本必须能入选——这是修复的正向验证。"""
        e = _engine()
        reviews = [([], 95 + i, 96 + i) for i in range(8)]
        e._update_best_versions(_version(reviews))
        assert len(e.history.best_versions) == 1
