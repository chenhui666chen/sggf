import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from backend.app.services.agents.layered_summarizer import LayeredSummarizer
from backend.app.services.agents.structured_memory_store import StructuredMemoryStore


def test_model_limit_comes_from_registry_config():
    from core.model_hub import model_hub

    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "llm_models.yaml")
    model_hub.initialize(config_path)
    summarizer = LayeredSummarizer()

    assert summarizer._get_model_limit("qwen3.7-plus") == 1000000
    assert summarizer._get_model_limit("qwen-" + "plus") == summarizer.DEFAULT_MODEL_LIMIT


def test_prepare_context_uses_pass_through_when_input_is_small():
    summarizer = LayeredSummarizer()

    result = summarizer.prepare_context_for_expansion(
        outline="""第1章：雨夜入城
- 主要内容：主角抵达青石城，发现宵禁异常。""",
        characters="""### 【姓名】：林舟
【角色定位】：主角""",
        worldview="""- 核心规则：夜禁期间城门不会无故开启。""",
        scenario="outline_expand",
        current_count=1,
    )

    assert result["stats"]["mode"] == "pass_through"
    assert "【故事大纲】" in result["context"]
    assert "第1章：雨夜入城" in result["context"]
    assert result["stats"]["compression_ratio"] <= 1.1
    assert "structured_memory" in result
    assert "memory_text" in result
    assert result["memory_text"].startswith("【结构化记忆】")
    assert "【结构化记忆】" in result["context"]
    assert result["structured_memory"]["character_states"]
    assert result["structured_memory"]["world_rules_hard_constraints"]


def test_prepare_context_uses_forced_model_budget(monkeypatch):
    summarizer = LayeredSummarizer()

    def fake_get_model_limit(model_id: str) -> int:
        if model_id == "doubao-seed-character":
            return 1600
        if model_id == "qwen3.7-plus":
            return 1000000
        return summarizer.DEFAULT_MODEL_LIMIT

    def fake_generate_skeleton(content: str, content_type: str, target_tokens: int, force_map_reduce: bool = False) -> str:
        return summarizer._shrink_text_to_token_budget(content, target_tokens)

    monkeypatch.setattr(summarizer, "_get_model_limit", fake_get_model_limit)
    monkeypatch.setattr(summarizer, "_generate_skeleton", fake_generate_skeleton)

    result = summarizer.prepare_context_for_expansion(
        outline="第1章：雨夜入城\n" + ("- 主线冲突：旧案线索浮现。\n" * 900),
        characters="### 【姓名】：林舟\n" + ("【当前状态】：继续追查旧案。\n" * 360),
        worldview="- 核心规则：夜禁期间城门不会无故开启。\n" * 240,
        scenario="chapter_generation",
        current_count=3,
        focus_range=(1, 6),
        forced_model="doubao-seed-character",
        forced_target_ratio=0.50,
    )

    assert result["selected_model"] == "doubao-seed-character"
    assert result["stats"]["model_limit_tokens"] == 1600
    assert result["stats"]["target_tokens"] == 800
    assert result["stats"]["mode"] != "pass_through"
    assert result["stats"]["total_tokens"] <= 800


def test_regex_extract_range_returns_complete_chapter_blocks():
    summarizer = LayeredSummarizer()
    outline = """故事总纲

第1章：雨夜入城
- 主要内容：主角抵达青石城。
- 关键事件：发现城门暗号。

第2章：旧案浮现
- 主要内容：主角查看卷宗。
- 关键事件：得知十年前旧案与今夜有关。

第3章：暗巷试探
- 主要内容：主角试探线人。
- 关键事件：敌对势力第一次露面。"""

    extracted = summarizer._regex_extract_range(
        outline=outline,
        target_range=(2, 2),
        available_tokens=800,
    )

    assert "第2章：旧案浮现" in extracted
    assert "- 主要内容：主角查看卷宗。" in extracted
    assert "- 关键事件：得知十年前旧案与今夜有关。" in extracted
    assert "第1章：雨夜入城" not in extracted


class _EmptyKnowledgeBase:
    def search(self, query, k=5):
        return []


def test_add_detailed_sections_falls_back_to_regex_when_rag_is_empty():
    summarizer = LayeredSummarizer(knowledge_base=_EmptyKnowledgeBase())
    outline = """第1章：雨夜入城
- 主要内容：主角抵达青石城。

第2章：旧案浮现
- 主要内容：主角查看卷宗。
- 关键事件：旧案与当前命案出现重叠线索。"""

    detailed = summarizer._add_detailed_sections(
        outline=outline,
        characters="",
        current_count=2,
        available_tokens=600,
        focus_range=(2, 2),
    )

    assert "第2章：旧案浮现" in detailed
    assert "旧案与当前命案出现重叠线索" in detailed


def test_build_structured_memory_extracts_key_categories():
    summarizer = LayeredSummarizer()

    memory = summarizer._build_structured_memory(
        outline="""第1章：雨夜入城
- 主要内容：主角抵达青石城。
- 结尾钩子：城门暗号为何提前泄露？

第2章：旧案浮现
- 关键事件：旧案与当前命案出现重叠线索。
- 伏笔：卷宗中缺失的最后一页去向不明。""",
        characters="""### 【姓名】：林舟
【角色定位】：主角
【核心能力】：擅长拆解旧案线索
【核心动机】：查明师父失踪真相

### 【姓名】：顾晚
【角色定位】：盟友
【关键关系】：林舟 ↔ 顾晚：共同追查旧案""",
        worldview="""- 核心规则：夜禁期间城门不会无故开启。
- 禁忌：未经许可不得调阅甲级旧案卷宗。""",
        detail_content="",
        focus_range=(1, 2),
    )

    assert memory["global_story_arcs"]
    assert any("林舟" in item for item in memory["character_states"])
    assert any("顾晚" in item for item in memory["relationship_edges"])
    assert memory["pending_foreshadowings"]
    assert memory["world_rules_hard_constraints"]


def test_render_structured_memory_respects_budget():
    summarizer = LayeredSummarizer()
    memory = {
        "global_story_arcs": [f"主线节点{i}" for i in range(10)],
        "character_states": [f"角色状态{i}" for i in range(10)],
        "relationship_edges": [f"关系边{i}" for i in range(10)],
        "pending_foreshadowings": [f"伏笔{i}" for i in range(10)],
        "world_rules_hard_constraints": [f"世界规则{i}" for i in range(10)],
    }

    rendered = summarizer._render_structured_memory(memory, budget_tokens=120)

    assert rendered.startswith("【结构化记忆】")
    assert summarizer._estimate_tokens(rendered) <= 120


def test_prepare_context_reuses_persisted_structured_memory_across_rounds(tmp_path):
    store = StructuredMemoryStore(persist_directory=str(tmp_path))
    summarizer = LayeredSummarizer(structured_memory_store=store)

    first_result = summarizer.prepare_context_for_expansion(
        outline="""第1章：雨夜入城
- 伏笔：城门暗号为何提前泄露？""",
        characters="""### 【姓名】：林舟
【角色定位】：主角""",
        worldview="""- 核心规则：夜禁期间城门不会无故开启。""",
        scenario="outline_expand",
        current_count=1,
        project_id=42,
    )

    assert "城门暗号为何提前泄露" in "".join(first_result["structured_memory"]["pending_foreshadowings"])

    second_result = summarizer.prepare_context_for_expansion(
        outline="""第2章：旧案浮现
- 关键事件：主角查看卷宗。""",
        characters="""### 【姓名】：顾晚
【角色定位】：盟友""",
        worldview="""- 禁忌：未经许可不得调阅甲级旧案卷宗。""",
        scenario="chapter_generation",
        current_count=2,
        focus_range=(1, 2),
        project_id=42,
    )

    merged_foreshadowings = "".join(second_result["structured_memory"].get("pending_foreshadowings", []))
    merged_rules = "".join(second_result["structured_memory"].get("world_rules_hard_constraints", []))

    assert "城门暗号为何提前泄露" in merged_foreshadowings
    assert "夜禁期间城门不会无故开启" in merged_rules


def test_estimate_selected_model_matches_current_capability_tiers():
    assert LayeredSummarizer.REDUCE_SUMMARY_MODEL == "qwen3.7-plus"
    assert LayeredSummarizer.estimate_selected_model("chapter_generation", 20) == "qwen3.7-plus"
    assert LayeredSummarizer.estimate_selected_model("chapter_generation", 120) == "qwen3.7-plus"
    assert LayeredSummarizer.estimate_selected_model("chapter_generation", 500) == "qwen3.7-plus"
    assert LayeredSummarizer.estimate_selected_model("structure_design", 20) == "qwen3.7-plus"
    assert LayeredSummarizer.estimate_selected_model("outline_expand", 30) == "qwen3.7-plus"
    assert LayeredSummarizer.estimate_selected_model("character_expand", 180) == "qwen3.7-plus"


def test_summarize_chapter_block_prefers_standardized_outline_fields():
    summarizer = LayeredSummarizer()

    block = """第12章：黑市试探
- 场景目标：林舟潜入黑市确认卷宗下落。
- 冲突设计：线人设局试探林舟的真实立场。
- 人物推进：林舟与顾晚从互相试探转向有限合作。
- 信息落地：确认卷宗已经被第三方势力截走。
- 结尾钩子：黑市深处有人提前留下了林舟的名字。"""

    summary = summarizer._summarize_chapter_block(block)

    assert summary.startswith("第12章：黑市试探：")
    assert "场景目标：林舟潜入黑市确认卷宗下落。" in summary
    assert "冲突设计：线人设局试探林舟的真实立场。" in summary
