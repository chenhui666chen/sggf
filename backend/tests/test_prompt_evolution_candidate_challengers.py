"""候选挑战者变体测试（外部 skill 基准实验拆零件产出，报告 §5.2）。

背景：用户侧 A/B 实验实证"增补注入不如独立竞争"——把外部策略混入
SAFE_INITIAL_PROMPT 会与六法互相拉扯，应作为独立 challenger arm 参与
A/B 竞争。本模块提供两个确定性候选变体：
1. 结构句式候选条款变体：基线提示词 + 四类结构句式禁令块（负面清单
   真实空白区，stop-slop/story-deslop/shuorenhua 三源收敛），待 A/B
   验证后由经验回流进池；
2. 去精致化独立策略族变体：独立提示词（不与六法混合），携带保真/
   篇幅硬约束。
"""
from app.services.prompt_evolution.meta_optimizer import (
    DESLOP_CHALLENGER_DESC,
    DESLOP_CHALLENGER_PROMPT,
    MetaOptimizer,
    STRUCTURE_CLAUSE_BLOCK,
    STRUCTURE_CLAUSE_DESC,
    STRUCTURE_CLAUSE_MARKER,
    build_candidate_challengers,
)
from app.services.prompt_evolution.engine import PromptEvolutionEngine


class TestBuildCandidateChallengers:
    def test_returns_two_variants(self):
        """固定产出两个候选变体：结构条款 + 去精致化。"""
        variants = build_candidate_challengers()
        assert len(variants) == 2
        descs = [desc for _, desc in variants]
        assert STRUCTURE_CLAUSE_DESC in descs
        assert DESLOP_CHALLENGER_DESC in descs

    def test_structure_variant_is_base_plus_clause_block(self):
        """结构条款变体 = 基线提示词 + 条款块（独立 arm，不混合改写）。"""
        variants = dict((desc, prompt) for prompt, desc in build_candidate_challengers())
        structure_prompt = variants[STRUCTURE_CLAUSE_DESC]
        assert STRUCTURE_CLAUSE_MARKER in structure_prompt
        # 基线核心内容保留（说明是基线+条款块组装，而非独立重写）
        assert "六法重构" in structure_prompt

    def test_structure_block_contains_four_clause_categories(self):
        """条款块覆盖四类结构句式盲区。"""
        variants = dict((desc, prompt) for prompt, desc in build_candidate_challengers())
        block = variants[STRUCTURE_CLAUSE_DESC]
        assert "二元对比" in block        # 否定铺垫句式
        assert "解释腔" in block          # 叙述者解释腔/预告腔
        assert "对话标签" in block        # 公式化对话标签
        assert "名词化" in block          # 通过/基于+名词化骨架

    def test_deslop_variant_is_independent_prompt(self):
        """去精致化变体是独立策略族：不携带六法指令（独立竞争不混合）。"""
        assert "六法重构" not in DESLOP_CHALLENGER_PROMPT
        assert "去精致化" in DESLOP_CHALLENGER_PROMPT

    def test_deslop_variant_carries_fidelity_constraints(self):
        """去精致化变体携带保真与篇幅硬约束（防过度改写换虚假低分）。"""
        prompt = MetaOptimizer._enforce_fidelity_constraint(DESLOP_CHALLENGER_PROMPT)
        assert "事实保真" in prompt
        assert "篇幅" in prompt

    def test_deslop_variant_carries_genre_addon(self):
        """去精致化变体追加题材约束。

        朴素化方向有把古典语域拉向现代口语的风险（玄幻/历史/武侠），
        六法靠 SAFE_GENRE_ADDONS 防护，去精致化变体同样需要。
        """
        variants = dict((desc, prompt) for prompt, desc in build_candidate_challengers("玄幻"))
        deslop_prompt = variants[DESLOP_CHALLENGER_DESC]
        assert "玄幻题材约束" in deslop_prompt
        # 通用题材（无addon的题材/None）不追加，保持独立提示词精简
        assert "题材约束" not in dict(
            (desc, prompt) for prompt, desc in build_candidate_challengers()
        )[DESLOP_CHALLENGER_DESC]

    def test_structure_block_has_no_development_marker(self):
        """条款块正文不带开发态元信息（候选条款字样）。

        该字样是给开发者看的状态标签，混入改写模型的 system prompt
        会被理解成可选项，削弱执行力；状态信息只保留在 DESC（日志用）。
        """
        assert "候选条款" not in STRUCTURE_CLAUSE_BLOCK

    def test_variants_pass_prompt_safety(self):
        """两个候选变体均通过提示词安全检查（否则会被 A/B 丢弃）。"""
        for prompt, desc in build_candidate_challengers():
            assert MetaOptimizer._validate_prompt_safety(prompt), f"安全检查未过: {desc}"

    def test_variants_are_deterministic(self):
        """同输入同输出（确定性组装，供缓存与幂等入库）。"""
        assert build_candidate_challengers() == build_candidate_challengers()


class TestEngineCandidateInjection:
    """引擎 A/B 轮次确定性注入候选挑战者（单次运行只注入一次）。"""

    def _make_engine(self):
        engine = PromptEvolutionEngine.__new__(PromptEvolutionEngine)
        engine._failed_variants = {}
        engine._injected_candidate_descs = set()
        engine.genre = None
        return engine

    def test_inject_appends_both_candidates(self):
        """候选变体追加到既有变体列表末尾，原变体不丢失。"""
        engine = self._make_engine()
        existing = [("prompt-x", "既有变体")]
        merged = engine._inject_candidate_challengers(existing)
        descs = [desc for _, desc in merged]
        assert descs[0] == "既有变体"
        assert STRUCTURE_CLAUSE_DESC in descs
        assert DESLOP_CHALLENGER_DESC in descs

    def test_inject_once_per_run(self):
        """同一次运行内重复调用不重复注入（避免多轮 A/B 占位）。"""
        engine = self._make_engine()
        first = engine._inject_candidate_challengers([])
        second = engine._inject_candidate_challengers([])
        assert len(first) == 2
        assert second == []

    def test_skip_failed_candidate(self):
        """历史失败达阈值的候选不再注入（与既有失败变体过滤一致）。"""
        engine = self._make_engine()
        for prompt, desc in build_candidate_challengers():
            if desc == DESLOP_CHALLENGER_DESC:
                engine._failed_variants[engine._get_prompt_hash(prompt)] = 3
        merged = engine._inject_candidate_challengers([])
        descs = [desc for _, desc in merged]
        assert STRUCTURE_CLAUSE_DESC in descs
        assert DESLOP_CHALLENGER_DESC not in descs
