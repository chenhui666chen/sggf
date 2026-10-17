"""初始评估中止的留痕护栏：花钱跑出来的证据不得随中止一起丢弃。

背景（2026-10-16 真实进化轮次取证）：
- 初始评估 8 样本全部跑完（约 2.5 分钟，含改写/朱雀检测/语义评审三段调用），
  随后 engine 因「失败占比 62%」走 all_failed_hard 分支直接 return。
- 该分支只写 history.error_message 就返回，
  `current_version.evaluation_results`（8 个样本的 ratio、段落真值、
  质量分、失败语义）**从未 append 进 history.all_versions** → 全部丢失。
- 后果：连续两轮真实进化（85337c99、上一轮）都是「跑完即丢」，
  事后无法复查到底哪几个维度不达标、ratio 真实值是多少，
  而这些恰恰是判断该不该继续进化的唯一依据。

本文件锁定：中止必须留痕，且留痕内容足以支撑事后归因。
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import (
    EvolutionConfig,
    EvolutionHistory,
    PromptVersion,
)
from app.services.prompt_evolution.storage import EvolutionStorage


def _result(sample_id, ratio, *, success, fact=95.0, segments=None):
    return {
        "sample_id": sample_id,
        "original_text": "原文内容，" * 30,
        "rewritten_text": "改写内容，" * 30,
        "original_ai_score": 100,
        "rewritten_ai_score": 100,
        "score_reduction": 0,
        "success": success,
        "error": None if success else "事实一致性低于90",
        "llm_review": {
            "available": True,
            "hard_fail": not success,
            "hard_fail_reasons": [] if success else ["事实一致性低于90"],
            "semantic_fidelity": {"score": 92.0},
            "fact_consistency": {"score": fact},
            "information_completeness": {"score": 91.0},
            "writing_naturalness": {"score": 88.0},
            "genre_consistency": {"score": 90.0},
            "over_rewrite_risk": "low",
        },
        "rewritten_ai_ratio": ratio,
        "rewritten_segments": segments or [],
        "failure_kind": None if success else "review_hard_fail",
    }


class TestAbortLeavesEvidence:
    """中止分支必须保留评估证据。"""

    def _engine(self, tmp_path):
        engine = PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )
        engine.history = EvolutionHistory()
        return engine

    def _version(self, results):
        from app.services.prompt_evolution.models import EvaluationResult

        evals = [EvaluationResult(**r) for r in results]
        version = PromptVersion(prompt_text="p", evaluation_results=evals)
        version.avg_ai_ratio = PromptEvolutionEngine._calc_avg_ai_ratio(evals)
        return version

    def test_abort_appends_version_to_history(self, tmp_path):
        """中止时当前版本必须进 all_versions —— 这是留痕的载体。"""
        engine = self._engine(tmp_path)
        version = self._version([
            _result("a", 0.5, success=False),
            _result("b", 0.6, success=False),
            _result("c", 0.4, success=True),
            _result("d", 0.7, success=False),
        ])

        # 复现中止判定所需的最小状态
        engine._record_aborted_version(version, "活跃模型全降不动")

        assert len(engine.history.all_versions) == 1
        assert engine.history.all_versions[0] is version

    def test_abort_preserves_evaluation_results(self, tmp_path):
        """8 个样本的明细必须完整保留，不能只留个汇总数字。"""
        engine = self._engine(tmp_path)
        segs = [{"text": "被判AI的段落", "label": 1, "conf": 0.9, "start": 0, "end": 10}]
        results = [_result(f"s{i}", 0.5, success=False, segments=segs) for i in range(4)]
        version = self._version(results)

        engine._record_aborted_version(version, "测试")

        saved = engine.history.all_versions[0]
        assert len(saved.evaluation_results) == 4
        assert saved.evaluation_results[0].rewritten_ai_ratio == 0.5
        assert saved.evaluation_results[0].rewritten_segments == segs
        assert saved.evaluation_results[0].failure_kind == "review_hard_fail"

    def test_abort_marks_version_with_attribution(self, tmp_path):
        """版本要带上中止归因，否则事后无法区分「中止」与「正常迭代」。"""
        engine = self._engine(tmp_path)
        version = self._version([_result("a", 0.5, success=False)])

        engine._record_aborted_version(version, "篇幅守门拦截")

        saved = engine.history.all_versions[0]
        assert "篇幅守门拦截" in saved.mutation_strategy
        assert "中止" in saved.analysis

    def test_abort_does_not_enter_best_versions(self, tmp_path):
        """🔴 留痕 ≠ 参评。中止版本绝不能进最佳列表。

        留痕是为事后归因，最佳列表是给下一轮继承的——把失格版本放进
        传承链等于用不可用的提示词去污染后续所有轮次。
        """
        engine = self._engine(tmp_path)
        version = self._version([
            _result("a", 0.05, success=False),
        ])
        version.avg_ai_ratio = 0.05

        engine._record_aborted_version(version, "测试")

        assert engine.history.best_versions == []

    def test_abort_is_idempotent(self, tmp_path):
        """同一版本重复留痕不得产生重复条目（中止路径可能被多次触达）。"""
        engine = self._engine(tmp_path)
        version = self._version([_result("a", 0.5, success=False)])

        engine._record_aborted_version(version, "测试")
        engine._record_aborted_version(version, "测试")

        assert len(engine.history.all_versions) == 1

    def test_history_error_message_still_set_by_caller(self, tmp_path):
        """error_message 仍由调用方设置（存的是人读的中止原因全文）。"""
        engine = self._engine(tmp_path)
        version = self._version([_result("a", 0.5, success=False)])

        engine._record_aborted_version(version, "检测失败")
        # 调用方随后设置
        engine.history.error_message = "初始评估中止：检测失败（失败占比62%）"

        assert "检测失败" in engine.history.error_message
        assert len(engine.history.all_versions) == 1