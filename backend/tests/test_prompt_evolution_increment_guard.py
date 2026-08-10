"""守卫测试：反"授权增量"与反"固定语境示例"守门（2026-08-07 硬失败取证结论）。

背景：批次 db1cdd3e 取证确认元优化器生成的提示词包含
"你被授权且必须补充……信息增量不属于篡改事实"与固定语境整句示例
（"深空寂静得像是一口被遗忘的古井"→"声响都停了"），导致改写模型
否定反转、数值编造、关键修饰词清洗四类硬失败。
"""
import inspect

import pytest

from app.services.prompt_evolution.meta_optimizer import MetaOptimizer


class TestAuthorizationIncrementGuard:
    """授权增量类指令必须被安全校验拒绝。"""

    # 取自 2026-08-07 16:45/16:47/16:49 真实落盘提示词
    REAL_TOXIC_CLAUSES = (
        "你被授权且必须补充上述内核在给定物理环境下必然或高度合理引发的感官证据",
        "这种为了显示而进行的信息增量，是重构的基础，不属于篡改事实",
        "通过基于物理逻辑的感官补全，将原文的抽象表达直接重构为具体",
        # 批次结束时写回的 7d94722b 变体措辞（无“被授权”字样）
        "你必须为原文中一切抽象描写补全其必然或高度合理的物理伴随现象、感官证据与具体动作",
        "通过补全基于物理逻辑的感官证据，将其转化为节奏多变的人类叙事",
    )

    def test_real_toxic_prompts_rejected(self):
        for clause in self.REAL_TOXIC_CLAUSES:
            prompt = f"你是一位小说家。{clause}。请改写文本。"
            assert not MetaOptimizer._validate_prompt_safety(prompt), clause

    def test_safe_prompt_not_affected(self):
        safe = (
            "你是一位严谨的中文小说文字编辑。不得改变人物姓名、时间、地点、"
            "数量、因果关系与既有设定；仅允许在保真前提下调整表达方式。"
        )
        assert MetaOptimizer._validate_prompt_safety(safe)


class TestFixedContextExampleGuard:
    """固定语境整句改写示例（原句→改句）必须被安全校验拒绝。"""

    def test_sentence_pair_example_rejected(self):
        prompt = (
            "禁止抽象词。\n- **示例**：“深空寂静得像是一口被遗忘的古井” → "
            "“通讯频道只剩下一片均匀的白噪音。”\n请按此改写。"
        )
        assert not MetaOptimizer._validate_prompt_safety(prompt)

    def test_instructional_example_rejected(self):
        # 指令式示例（如“寂静”“像一片枯叶”）同样是固定语境素材，应拒绝
        prompt = "找出原文中的抽象情绪词（如“寂静”、“绝望”）、模糊比喻（如“像一片枯叶”），然后重构它们。"
        assert not MetaOptimizer._validate_prompt_safety(prompt)

    def test_short_word_list_not_affected(self):
        # 禁用词表类的短词引用不属于固定语境示例，不应误伤
        prompt = "删除“深邃”“寂寥”等AI高频抽象词汇，保留全部事实。"
        assert MetaOptimizer._validate_prompt_safety(prompt)


class TestEvolutionBoundaryClauses:
    """【不可突破的进化边界】必须显式禁止两类行为。"""

    def test_boundary_forbids_increment_and_examples(self):
        src = inspect.getsource(MetaOptimizer.optimize_prompt)
        assert "授权" in src or "信息增量" in src, "边界需禁止授权增量类指令"
        assert "示例" in src and "通用" in src, "边界需禁止固定语境整句示例"


class TestBestVersionFidelityGate:
    """门槛加固：含硬失败或语义保真<90样本的版本不得入选最佳列表。"""

    def _make_engine(self, tmp_path):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        from app.services.prompt_evolution.models import EvolutionHistory
        from app.services.prompt_evolution.storage import EvolutionStorage
        engine = PromptEvolutionEngine(storage=EvolutionStorage(str(tmp_path)))
        engine.history = EvolutionHistory()
        return engine

    def _make_version(self, review):
        from app.services.prompt_evolution.models import EvaluationResult, PromptVersion
        result = EvaluationResult(
            sample_id="s1", original_text="原文", rewritten_text="改写",
            original_ai_score=99, rewritten_ai_score=80, score_reduction=19,
            success=True, llm_review=review,
        )
        return PromptVersion(prompt_text="p", avg_ai_score=80.0,
                            evaluation_results=[result])

    def test_hard_fail_version_rejected(self, tmp_path):
        engine = self._make_engine(tmp_path)
        version = self._make_version({"hard_fail": True, "hard_fail_reasons": ["事实一致性低于90"]})
        engine._update_best_versions(version)
        assert engine.history.best_versions == []

    def test_low_semantic_fidelity_version_rejected(self, tmp_path):
        engine = self._make_engine(tmp_path)
        version = self._make_version(
            {"hard_fail": False, "semantic_fidelity": {"score": 85.0, "reason": "偏离意境"}}
        )
        engine._update_best_versions(version)
        assert engine.history.best_versions == []

    def test_clean_version_accepted(self, tmp_path):
        engine = self._make_engine(tmp_path)
        version = self._make_version(
            {"hard_fail": False, "semantic_fidelity": {"score": 96.0, "reason": "ok"}}
        )
        engine._update_best_versions(version)
        assert len(engine.history.best_versions) == 1
