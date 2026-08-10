"""守卫测试：传承链安全校验与入选安全门槛（2026-08-07 批次 17d57ae2 取证结论）。

背景：批次 17d57ae2 全程使用漏网带毒初始提示词 42cd8e6e（含"逻辑推演"
授权增量残留与三组固定语境整句示例），导致"幽影短剑→短刀"在迭代 1/3/4/5
四个批次稳定复现硬失败；且：
- 漏洞A：_get_best_starting_prompt 从历史最佳列表选起点时不做安全校验，
  守门建立前的 25 个带毒历史版本仍可被选中；
- 漏洞B：_update_best_versions 仅做保真门槛，validate=False 的提示词文本
  可凭一次恰好全过的评估（fa2f6e3c，A/B 4 样本）入选 best_prompts.json。
"""
import json
from pathlib import Path

from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionHistory,
    PromptVersion,
)

# 真实残留毒条款（批次 17d57ae2 初始提示词 42cd8e6e 原文节选）
REAL_RESIDUAL_TOXIC = (
    "所有重构行为必须在原文信息基础上进行逻辑推演。"
    "允许并鼓励为此添加经过逻辑推导的物理细节。"
)
CLEAN_PROMPT = (
    "你是一位严谨的中文小说文字编辑。不得改变人物姓名、时间、地点、"
    "数量、因果关系与既有设定；仅允许在保真前提下调整表达方式。"
)

assert not MetaOptimizer._validate_prompt_safety(REAL_RESIDUAL_TOXIC), "前置条件：毒文本须被校验拒绝"
assert MetaOptimizer._validate_prompt_safety(CLEAN_PROMPT), "前置条件：安全文本须通过校验"

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "prompt_evolution"


def _make_engine(tmp_path):
    from app.services.prompt_evolution.engine import PromptEvolutionEngine
    from app.services.prompt_evolution.storage import EvolutionStorage
    engine = PromptEvolutionEngine(storage=EvolutionStorage(str(tmp_path)))
    engine.history = EvolutionHistory()
    return engine


class TestSafeDefaultNotFalsePositive:
    """误伤修复：否定语境中的词表项（不得改变事件顺序）不应触发拦截。

    实证：SAFE_INITIAL_PROMPT 含"不得改变事件顺序"被"改变事件顺序"
    子串误伤，导致安全回退默认提示词自身 validate=False。
    """

    def test_safe_initial_prompt_passes(self):
        import app.services.prompt_evolution.meta_optimizer as mo
        assert MetaOptimizer._validate_prompt_safety(mo.SAFE_INITIAL_PROMPT)

    def test_all_genre_addons_pass(self):
        import app.services.prompt_evolution.meta_optimizer as mo
        for genre, addon in mo.SAFE_GENRE_ADDONS.items():
            full = mo.SAFE_INITIAL_PROMPT + "\n\n" + addon
            assert MetaOptimizer._validate_prompt_safety(full), f"题材 {genre} 默认提示词被误伤"

    def test_negative_context_not_flagged(self):
        prompt = "不得改变事件顺序、因果关系；禁止统一改成现代口语。"
        assert MetaOptimizer._validate_prompt_safety(prompt)

    def test_banned_word_list_not_flagged(self):
        # 禁用词表是"要删除的词"，不是固定语境示例素材，不应误伤
        prompt = '禁止使用“仿佛”、“像极了”、“似乎”、“深邃”、“璀璨”等空洞词汇。'
        assert MetaOptimizer._validate_prompt_safety(prompt)

    def test_positive_context_still_flagged(self):
        # 同样措辞出现在肯定语境仍须拦截（真实毒条款复测）
        for clause in (
            "你可以改变事件顺序以增强戏剧性",
            "将所有叙述统一改成现代口语",
            "你被授权且必须补充感官证据",
            "你必须为原文中一切抽象描写补全其必然或高度合理的物理伴随现象",
        ):
            assert not MetaOptimizer._validate_prompt_safety(clause), clause


class TestStartingPromptSafetyFilter:
    """漏洞A：历史最佳起点选择必须跳过安全校验失败的带毒版本。"""

    def test_toxic_history_best_skipped(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.genre = "玄幻"
        toxic = PromptVersion(
            version_id="42cd8e6e", prompt_text=REAL_RESIDUAL_TOXIC,
            avg_ai_score=50.0, avg_composite_score=2.0, genre="玄幻",
        )
        clean = PromptVersion(
            version_id="c1e4n000", prompt_text=CLEAN_PROMPT,
            avg_ai_score=60.0, avg_composite_score=5.0, genre="玄幻",
        )
        # 带毒版本综合评分更低，旧逻辑会优先选中它
        engine.storage.load_global_best_prompts = lambda: [toxic, clean]
        engine.storage.get_latest_approved_prompt = lambda: None

        starting = engine._get_best_starting_prompt()
        assert starting != REAL_RESIDUAL_TOXIC, "不得把带毒历史版本选为起点"
        assert starting == CLEAN_PROMPT

    def test_all_toxic_falls_back_to_safe_default(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.genre = "玄幻"
        toxic = PromptVersion(
            version_id="42cd8e6e", prompt_text=REAL_RESIDUAL_TOXIC,
            avg_ai_score=50.0, avg_composite_score=2.0, genre="玄幻",
        )
        engine.storage.load_global_best_prompts = lambda: [toxic]
        engine.storage.get_latest_approved_prompt = lambda: None

        starting = engine._get_best_starting_prompt()
        assert MetaOptimizer._validate_prompt_safety(starting), "回退提示词必须通过安全校验"


class TestBestVersionSafetyGate:
    """漏洞B：提示词文本未通过安全校验的版本不得入选最佳列表。"""

    def _make_clean_evaluated_version(self, prompt_text):
        # 评估结果全维度高保真（模拟 fa2f6e3c 的 A/B 恰好全过）
        result = EvaluationResult(
            sample_id="s1", original_text="原文", rewritten_text="改写",
            original_ai_score=99, rewritten_ai_score=80, score_reduction=19,
            success=True,
            llm_review={"hard_fail": False, "semantic_fidelity": {"score": 96.0}},
        )
        return PromptVersion(prompt_text=prompt_text, avg_ai_score=80.0,
                             evaluation_results=[result])

    def test_toxic_text_version_rejected(self, tmp_path):
        engine = _make_engine(tmp_path)
        version = self._make_clean_evaluated_version(REAL_RESIDUAL_TOXIC)
        engine._update_best_versions(version)
        assert engine.history.best_versions == []

    def test_clean_text_version_accepted(self, tmp_path):
        engine = _make_engine(tmp_path)
        version = self._make_clean_evaluated_version(CLEAN_PROMPT)
        engine._update_best_versions(version)
        assert len(engine.history.best_versions) == 1


class TestBestListDataCleanliness:
    """数据清洁度：最佳列表双源头不得残留安全校验失败的带毒版本。"""

    def test_best_prompts_file_clean(self):
        path = DATA_DIR / "best_prompts.json"
        if not path.exists():
            return
        items = json.load(open(path, encoding="utf-8"))
        toxic = [x.get("version_id") for x in items
                 if not MetaOptimizer._validate_prompt_safety(x.get("prompt_text", ""))]
        assert toxic == [], f"best_prompts.json 残留带毒版本: {toxic}"

    def test_history_best_versions_clean(self):
        path = DATA_DIR / "evolution_history.json"
        if not path.exists():
            return
        d = json.load(open(path, encoding="utf-8"))
        batches = d if isinstance(d, list) else d.get("batches", d)
        toxic = [
            (b.get("evolution_id", "?")[:8], v.get("version_id"))
            for b in batches
            for v in (b.get("best_versions") or [])
            if not MetaOptimizer._validate_prompt_safety(v.get("prompt_text", ""))
        ]
        assert toxic == [], f"evolution_history 残留带毒版本: {toxic}"
