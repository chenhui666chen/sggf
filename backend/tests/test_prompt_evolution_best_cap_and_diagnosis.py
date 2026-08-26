"""守卫测试：best 入选 AI 分上限门槛 + 安全拒绝可诊断性（2026-08-07 批次 4cf9057b 取证）。

背景：批次 4cf9057b（玄幻）取证确认两类问题：
- 漏洞C：_update_best_versions 只查保真与安全，不查降分效果，avg_ai_score
  97.25~98.5 的高分版本入选 best_prompts.json，被消费端按 min composite
  当真冠军使用（与起点选择 <80 门槛脱节，"94+ 假最佳"问题复发）；
- 漏洞D：安全拒绝日志只记录策略前 80 字符且不含命中原因，疑似误伤
  （"减少这/那开头判断句"等合法句式策略被丢弃）无法取证定位。
"""
import json
import logging
from pathlib import Path

from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionHistory,
    PromptVersion,
)

CLEAN_PROMPT = (
    "你是一位严谨的中文小说文字编辑。不得改变人物姓名、时间、地点、"
    "数量、因果关系与既有设定；仅允许在保真前提下调整表达方式。"
)
# 命中授权增量词表"逻辑推演"（批次 17d57ae2 真实残留毒条款）
TOXIC_PROMPT = "所有重构行为必须在原文信息基础上进行逻辑推演。"

assert MetaOptimizer._validate_prompt_safety(CLEAN_PROMPT), "前置条件：安全文本须通过校验"
assert not MetaOptimizer._validate_prompt_safety(TOXIC_PROMPT), "前置条件：毒文本须被校验拒绝"

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "prompt_evolution"


def _make_engine(tmp_path):
    from app.services.prompt_evolution.engine import PromptEvolutionEngine
    from app.services.prompt_evolution.storage import EvolutionStorage
    engine = PromptEvolutionEngine(storage=EvolutionStorage(str(tmp_path)))
    engine.history = EvolutionHistory()
    return engine


def _make_version(prompt_text: str, avg_ai_score: float) -> PromptVersion:
    # 全维度高保真评估结果（保真/安全门槛均通过，仅分数维度可变）
    result = EvaluationResult(
        sample_id="s1", original_text="原文", rewritten_text="改写",
        original_ai_score=99, rewritten_ai_score=int(avg_ai_score),
        score_reduction=int(99 - avg_ai_score), success=True,
        llm_review={"hard_fail": False, "semantic_fidelity": {"score": 96.0}},
    )
    return PromptVersion(prompt_text=prompt_text, avg_ai_score=avg_ai_score,
                         evaluation_results=[result])


class TestBestVersionScoreCap:
    """漏洞C修正（2026-08-23 黄金对照实验证伪 TMS）：avg_ai_score 上限门槛移除。

    TMS 为反向文风分类器（GPT人工化金标准(朱雀0%)得 TMS=97、AI文学腔
    原文得 TMS=0），按 TMS 分拒版本会把真正的人感版本挡在最佳列表外；
    降分有效性改由 composite（语义人感）与保真/成功率门槛保障。
    """

    def test_high_score_version_no_longer_rejected_by_tms(self, tmp_path):
        """TMS 高分（97+）不再一票否决（朱雀人感版本可能恰是高 TMS 分）。"""
        engine = _make_engine(tmp_path)
        engine._update_best_versions(_make_version(CLEAN_PROMPT, 97.25))
        assert len(engine.history.best_versions) == 1

    def test_low_score_version_accepted(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine._update_best_versions(_make_version(CLEAN_PROMPT, 63.5))
        assert len(engine.history.best_versions) == 1


class TestBestListScoreCleanliness:
    """数据清洁度：best 双源头不得残留 avg_ai_score>80 的高分版本。"""

    def test_best_prompts_file_no_high_score(self):
        path = DATA_DIR / "best_prompts.json"
        if not path.exists():
            return
        items = json.load(open(path, encoding="utf-8"))
        bad = [x.get("version_id") for x in items
               if (x.get("avg_ai_score") or 0) > 80]
        assert bad == [], f"best_prompts.json 残留高分版本: {bad}"

    def test_history_best_versions_no_high_score(self):
        path = DATA_DIR / "evolution_history.json"
        if not path.exists():
            return
        d = json.load(open(path, encoding="utf-8"))
        batches = d if isinstance(d, list) else d.get("batches", d)
        bad = [
            (b.get("evolution_id", "?")[:8], v.get("version_id"))
            for b in batches
            for v in (b.get("best_versions") or [])
            if (v.get("avg_ai_score") or 0) > 80
        ]
        assert bad == [], f"evolution_history 残留高分 best_versions: {bad}"


class TestSafetyRejectionDiagnosis:
    """漏洞D：安全校验拒绝必须给出命中原因，拒绝日志可诊断。"""

    def test_reason_reports_wordlist_hit(self):
        reason = MetaOptimizer._prompt_safety_reason(TOXIC_PROMPT)
        assert reason is not None and "逻辑推演" in reason

    def test_reason_none_for_clean_text(self):
        assert MetaOptimizer._prompt_safety_reason(CLEAN_PROMPT) is None

    def test_reason_reports_sentence_example(self):
        prompt = (
            "禁止抽象词。\n- **示例**：“深空寂静得像是一口被遗忘的古井” → "
            "“通讯频道只剩下一片均匀的白噪音。”\n请按此改写。"
        )
        reason = MetaOptimizer._prompt_safety_reason(prompt)
        assert reason is not None and "示例" in reason

    def test_rejection_log_contains_hit_reason(self, tmp_path, caplog):
        engine = _make_engine(tmp_path)
        with caplog.at_level(logging.WARNING):
            engine._update_best_versions(_make_version(TOXIC_PROMPT, 60.0))
        assert engine.history.best_versions == []
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "逻辑推演" in joined, f"拒绝日志须含命中原因，实际: {joined}"
