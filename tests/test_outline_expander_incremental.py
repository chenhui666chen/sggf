import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import backend.app.services.agents.outline_expander as outline_expander_module
from backend.app.services.agents.outline_expander import OutlineExpander
from backend.app.services.outline_merger import parse_framework_to_volumes


class _DummySummarizer:
    def prepare_context_for_expansion(self, **kwargs):
        return {
            "selected_model": "qwen-plus",
            "context": "压缩后的上下文",
            "memory_text": "结构化记忆约束",
            "structured_memory": {"story": 1},
            "stats": {
                "compression_ratio": 0.5,
                "total_tokens": 100,
                "target_tokens": 1000,
            },
        }


class _DummyRecognizer:
    def count_characters(self, text, use_ai_verification=False):
        names = []
        seen = set()
        for match in re.finditer(r"(?m)^(?:###\s*)?【姓名】[：:]\s*(.+?)\s*$", text or ""):
            name = match.group(1).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return len(names), names


class _DummyValidator:
    def __init__(self, score=85):
        self.score = score

    def validate_character_plot_alignment(self, **kwargs):
        return {
            "score": self.score,
            "redundant_characters": [],
            "missing_characters": [],
            "relationship_issues": [],
            "suggestions": [],
        }


class _QueueDesigner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.llm = "original-llm"

    def process(self, prompt, _context):
        assert self.outputs, f"收到未预期的人物 prompt：{prompt[:200]}"
        return self.outputs.pop(0)


class _CapturingQueueDesigner(_QueueDesigner):
    def __init__(self, outputs):
        super().__init__(outputs)
        self.prompts = []

    def process(self, prompt, _context):
        self.prompts.append(prompt)
        return super().process(prompt, _context)


class _LLMResponse:
    def __init__(self, content: str):
        self.content = content


class _QueueLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def invoke(self, messages):
        assert self.outputs, "收到未预期的大纲 LLM 调用"
        return _LLMResponse(self.outputs.pop(0))


class _DummyMemoryManager:
    def clear_history(self):
        return None


class _QueueAgent:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.llm = "original-llm"
        self.memory_manager = _DummyMemoryManager()

    def process(self, prompt, _context):
        assert self.outputs, f"收到未预期的 Agent prompt：{prompt[:200]}"
        return self.outputs.pop(0)


class _CapturingQueueAgent(_QueueAgent):
    def __init__(self, outputs):
        super().__init__(outputs)
        self.prompts = []

    def process(self, prompt, _context):
        self.prompts.append(prompt)
        return super().process(prompt, _context)


class _DummyRenumberer:
    def detect_and_fix(self, content, expected_start, expected_count_range):
        chapter_numbers = [int(num) for num in re.findall(r"第\s*(\d+)\s*章", content)]
        if chapter_numbers:
            fixed_range = (min(chapter_numbers), max(chapter_numbers))
        else:
            fixed_range = (0, 0)
        return {
            "fixed_content": content,
            "was_fixed": False,
            "original_range": fixed_range,
            "fixed_range": fixed_range,
            "offset": 0,
            "details": "章节编号正确，无需修正",
        }


class _DummyConsistencyResult:
    def __init__(self, passed=True):
        self.passed = passed
        self.suggestions = []

    def get_summary(self):
        return "校验通过"

    def to_dict(self):
        return {
            "issues": [],
            "suggestions": [],
        }


class _DummyConsistencyValidator:
    def validate(self, **kwargs):
        return _DummyConsistencyResult()


def _make_base_expander() -> OutlineExpander:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.layered_summarizer = _DummySummarizer()
    expander.character_recognizer = _DummyRecognizer()
    expander.character_plot_validator = _DummyValidator()
    expander.genre_module = {}
    expander.project_id = None
    expander.genre = ""
    expander.planned_chapters_max = 0
    return expander


def test_story_build_character_context_adds_roster_summary_before_truncated_cards():
    expander = _make_base_expander()
    long_characters = "\n\n".join(
        [
            f"### 【姓名】：角色{i}\n【角色定位】：配角\n【背景/当前处境】：{'背景信息' * 12}"
            for i in range(1, 7)
        ]
    )

    context = expander._story_build_character_context(
        long_characters,
        detail_limit=120,
        summary_limit=120,
    )

    assert "【角色名单摘要】" in context
    assert "1. 角色1" in context
    assert "2. 角色2" in context
    assert "【人物运行摘要】" in context
    assert "角色1（配角）" in context
    assert "背景信息背景信息背景信息" not in context


def test_expand_plot_outline_legacy_entry_delegates_to_incremental():
    expander = _make_base_expander()
    captured = {}

    def fake_incremental(**kwargs):
        captured.update(kwargs)
        return {
            "expanded_outline": "新大纲",
            "chapter_breakdown": "新细纲",
            "plot_arcs": {"主线": "青石旧案"},
            "current_chapter_count": 4,
            "should_continue": False,
            "continue_reason": "主线与卷级结构已经完整",
        }

    expander.expand_plot_outline_incremental = fake_incremental
    expander.count_chapters_in_outline = lambda outline: 2

    result = expander.expand_plot_outline(
        current_outline="第1章：入城\n第2章：探案",
        world_setting="蒸汽仙侠",
        characters="林舟、顾晚",
        target_chapters=4,
    )

    assert captured["current_chapter_count"] == 2
    assert captured["increment"] == 2
    assert captured["target_total_chapters"] == 4
    assert result["expanded_outline"] == "新大纲"
    assert result["target_chapters"] == 4
    assert result["expansion_analysis"] == "主线与卷级结构已经完整"
    assert result["should_continue"] is False


def test_expand_characters_legacy_entry_delegates_to_incremental():
    expander = _make_base_expander()
    captured = {}

    def fake_incremental(**kwargs):
        captured.update(kwargs)
        return {
            "all_characters": "林舟\n顾晚\n沈砚",
            "character_relationships": "林舟 ↔ 顾晚：盟友",
            "role_distribution": {"主角": 1, "支持角色": 2},
            "current_character_count": 3,
            "should_continue": False,
            "continue_reason": "当前剧情阶段人物槽位已经补齐",
        }

    expander.expand_characters_incremental = fake_incremental
    expander.count_characters_in_text = lambda text: 1

    result = expander.expand_characters(
        main_characters="林舟",
        world_setting="蒸汽仙侠",
        plot_outline="第1章：入城查案",
        target_count=3,
    )

    assert captured["current_character_count"] == 1
    assert captured["increment"] == 2
    assert captured["target_total_characters"] == 3
    assert result["all_characters"] == "林舟\n顾晚\n沈砚"
    assert result["target_count"] == 3
    assert result["character_analysis"] == "当前剧情阶段人物槽位已经补齐"
    assert result["should_continue"] is False


def test_expand_plot_outline_legacy_entry_short_circuits_when_target_not_greater():
    expander = _make_base_expander()
    expander.count_chapters_in_outline = lambda outline: 5
    expander.expand_plot_outline_incremental = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("不应继续调用增量扩展")
    )

    result = expander.expand_plot_outline(
        current_outline="第1章到第5章",
        world_setting="蒸汽仙侠",
        characters="林舟、顾晚",
        target_chapters=5,
    )

    assert result["expanded_outline"] == "第1章到第5章"
    assert result["current_chapter_count"] == 5
    assert result["should_continue"] is False
    assert "无需继续扩展" in result["continue_reason"]


def test_expand_characters_legacy_entry_short_circuits_when_target_not_greater():
    expander = _make_base_expander()
    expander.count_characters_in_text = lambda text: 4
    expander.expand_characters_incremental = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("不应继续调用增量扩展")
    )

    result = expander.expand_characters(
        main_characters="林舟\n顾晚\n沈砚\n陆遥",
        world_setting="蒸汽仙侠",
        plot_outline="第1章：入城查案",
        target_count=4,
    )

    assert result["all_characters"] == "林舟\n顾晚\n沈砚\n陆遥"
    assert result["current_character_count"] == 4
    assert result["should_continue"] is False
    assert "无需继续扩展" in result["continue_reason"]


def test_generate_expansion_summary_handles_structured_payloads():
    expander = _make_base_expander()

    summary = expander.generate_expansion_summary(
        outline_expansion={
            "target_chapters": 12,
            "expansion_analysis": {"mode": "incremental", "reason": "主线已完整"},
            "plot_arcs": {"主线": "青石旧案", "支线": ["夜市追踪"]},
            "chapter_breakdown": {"volume_1": ["第1章", "第2章"]},
        },
        character_expansion={
            "target_count": 5,
            "role_distribution": {"主角": 1, "支持角色": 2},
            "character_relationships": {"核心关系": ["林舟 ↔ 顾晚"]},
        },
    )

    assert "12" in summary
    assert "\"mode\": \"incremental\"" in summary
    assert "\"主线\": \"青石旧案\"" in summary
    assert "\"支持角色\": 2" in summary
    assert "\"核心关系\": [\"林舟 ↔ 顾晚\"]" in summary


def test_expand_characters_incremental_prefers_structured_json_payloads():
    expander = _make_base_expander()
    expander.character_long_llm = object()
    expander.character_designer = _QueueDesigner(
        [
            """
            {
              "characters": [
                {
                  "name": "顾晚",
                  "age_gender": "19岁/女",
                  "story_stance": "主角方",
                  "affiliation": "青石城旧案线",
                  "importance": "重要角色",
                  "role_position": "情报盟友",
                  "appearance_anchor": "短发利落，目光冷静。",
                  "personality_anchor": "性格：克制敏锐，做事果断。\\n价值倾向：相信秩序需要被纠正，而不是被盲从。",
                  "background_status": "出身旧案相关家族，长期追查真相。",
                  "motivation": "查清家族旧事并阻止灭口。",
                  "ability_outline": "擅长潜入与情报梳理。",
                  "limitation": "过度戒备，不轻易信任他人。",
                  "mainline_role": "协助主角补齐调查线的情报缺口。",
                  "growth_direction": "从单独追查到主动结盟。",
                  "key_relationships": "与林舟从试探转为盟友。",
                  "mainline_clues": "旧案残卷、夜市暗号"
                }
              ]
            }
            """,
            """
            {
              "updates": [
                {
                  "name": "林舟",
                  "relationship_updates": [
                    {
                      "target": "顾晚",
                      "description": "开始共享旧案线索"
                    }
                  ],
                  "mainline_clues_patch": "旧案残卷",
                  "mainline_role_patch": "从独自追查转向双线配合",
                  "growth_direction_patch": "开始尝试信任新盟友"
                }
              ]
            }
            """,
            """
            {
              "relationship_groups": [
                {
                  "group": "主角阵营内部",
                  "relationships": [
                    {
                      "source": "林舟",
                      "target": "顾晚",
                      "type": "盟友",
                      "description": "共同调查旧案"
                    }
                  ]
                }
              ]
            }
            """,
            '{"主角": 1, "配角": 0, "对手": 0, "支持角色": 1, "中立角色": 0}',
            '{"should_continue": false, "reason": "两名关键角色已覆盖当前调查阶段"}',
        ]
    )

    result = expander.expand_characters_incremental(
        main_characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        plot_outline="第1章：雨夜入城\n- 涉及人物：林舟",
        current_character_count=1,
        increment=1,
        target_total_characters=2,
    )

    assert "### 【姓名】：顾晚" in result["all_characters"]
    assert "【故事立场】：主角方" in result["all_characters"]
    assert "【所属势力】：青石城旧案线" in result["all_characters"]
    assert "## 已有角色关系更新" not in result["all_characters"]
    assert "【关键关系】：顾晚：开始共享旧案线索" in result["all_characters"]
    assert "【主线绑定】：剧情职责：从独自追查转向双线配合" in result["all_characters"]
    assert "关联线索：旧案残卷" in result["all_characters"]
    assert "【成长方向】：开始尝试信任新盟友" in result["all_characters"]
    assert "**主角阵营内部**：" in result["character_relationships"]
    assert "- 林舟 ↔ 顾晚：盟友（共同调查旧案）" in result["character_relationships"]
    assert result["role_distribution"]["支持角色"] == 1
    assert result["current_character_count"] == 2
    assert result["should_continue"] is False


def test_story_merge_character_cards_with_patches_absorbs_historical_patch_sections():
    expander = _make_base_expander()

    merged = expander._story_merge_character_cards_with_patches(
        main_characters="""### 【姓名】：林岩
【故事立场】：主角方
【角色定位】：主角
【关键关系】：扳手：同伴
【主线绑定】：剧情职责：逃亡并调查ES-01
【成长方向】：学会独立承担责任

## 已有角色关系更新
### 林岩
【关键关系·补充】：回声：逐步建立信任
【关联线索·补充】：星云残留带坐标
【剧情职责·补充】：开始承担团队决策
【成长方向·补充】：从单兵逃亡转向主动带队
""",
        new_cards="",
        patch_payload={"updates": []},
    )

    assert "## 已有角色关系更新" not in merged
    assert "【关键关系】：扳手：同伴；回声：逐步建立信任" in merged
    assert "剧情职责：逃亡并调查ES-01；开始承担团队决策" in merged
    assert "关联线索：星云残留带坐标" in merged
    assert "【成长方向】：学会独立承担责任；从单兵逃亡转向主动带队" in merged


def test_expand_characters_incremental_structured_prompts_include_story_context():
    expander = _make_base_expander()
    designer = _CapturingQueueDesigner(
        [
            """
            {
              "characters": [
                {
                  "name": "顾晚",
                  "age_gender": "19岁/女",
                  "story_stance": "主角方",
                  "affiliation": "青石城旧案线",
                  "importance": "重要角色",
                  "role_position": "情报盟友",
                  "appearance_anchor": "短发利落，目光冷静。",
                  "personality_anchor": "性格：克制敏锐，做事果断。\\n价值倾向：相信秩序需要被纠正，而不是被盲从。",
                  "background_status": "出身旧案相关家族，长期追查真相。",
                  "motivation": "查清家族旧事并阻止灭口。",
                  "ability_outline": "擅长潜入与情报梳理。",
                  "limitation": "过度戒备，不轻易信任他人。",
                  "mainline_role": "协助主角补齐调查线的情报缺口。",
                  "growth_direction": "从单独追查到主动结盟。",
                  "key_relationships": "与林舟从试探转为盟友。",
                  "mainline_clues": "旧案残卷、夜市暗号"
                }
              ]
            }
            """,
            '{"updates": []}',
            '{"relationship_groups": []}',
            '{"主角": 1, "配角": 0, "对手": 0, "支持角色": 1, "中立角色": 0}',
            '{"should_continue": false, "reason": "当前调查阶段的人物槽位已补齐"}',
        ]
    )
    expander.character_designer = designer

    result = expander.expand_characters_incremental(
        main_characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界，青石城旧案牵动宗门暗线。",
        plot_outline="第1章：雨夜入城\n- 主要内容：林舟抵达青石城并接触旧案线索。",
        current_character_count=1,
        increment=1,
        target_total_characters=2,
    )

    assert len(designer.prompts) == 5
    assert "【现有角色名单】" in designer.prompts[0]
    assert "林舟" in designer.prompts[0]
    assert "青石城旧案" in designer.prompts[0]
    assert "本轮需新增：1 个" in designer.prompts[0]
    assert "【本轮新增角色卡】" in designer.prompts[1]
    assert "【人物运行摘要】" in designer.prompts[1]
    assert "顾晚" in designer.prompts[1]
    assert "【当前大纲】" in designer.prompts[2]
    assert "【人物体系】" in designer.prompts[3]
    assert "【完整人物体系】" in designer.prompts[4]
    assert "新增角色：顾晚" in designer.prompts[4]
    assert result["current_character_count"] == 2


def test_expand_plot_outline_incremental_prefers_structured_json_payloads():
    expander = _make_base_expander()
    expander.llm = _QueueLLM(
        [
            """
            {
              "story_overview": "林舟入城后被旧案牵引，调查线正式启动。",
              "volumes": [
                {
                  "volume_index": 1,
                  "title": "青石初局",
                  "start_chapter": 1,
                  "end_chapter": 2,
                  "written_chapters": [1],
                  "stage_goal": "让主角从入城过渡到查案",
                  "core_conflict": "衙门旧档被封锁",
                  "ending_climax": "拿到残卷并锁定暗线",
                  "key_characters": ["林舟", "顾晚"],
                  "new_chapter_direction": "通过查档与线索交接打开旧案主线"
                }
              ]
            }
            """,
            """
            {
              "volume_title": "青石初局",
              "volume_goal": "旧案线正式启动",
              "chapters": [
                {
                  "chapter_number": 1,
                  "title": "雨夜入城",
                  "status": "written"
                },
                {
                  "chapter_number": 2,
                  "title": "旧案浮现",
                  "status": "new",
                  "scene_goal": "衙门查档 + 林舟 + 锁定调查入口",
                  "conflict_design": "旧档被临时封存，主角冒险查出残页异常",
                  "emotional_curve": "谨慎 → 压迫 → 坚定",
                  "highlight_type": "信息反转 + ⭐⭐⭐",
                  "information_payoff": "获得残卷并确认旧案被人为遮掩",
                  "ending_hook": "残卷上的名字指向主角旧识"
                }
              ]
            }
            """,
            '{"should_continue": false, "reason": "当前两章已形成清晰开局，可先进入写作"}',
        ]
    )

    result = expander.expand_plot_outline_incremental(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=1,
        increment=1,
        target_total_chapters=2,
    )

    assert "## 新增章节规划" in result["expanded_outline"]
    assert "旧案线正式启动" not in result["expanded_outline"]
    assert "#### 第1章：《雨夜入城》 [已写]" in result["chapter_breakdown"]
    assert "- 主要内容：主角抵达青石城。" in result["chapter_breakdown"]
    assert "#### 第2章：《旧案浮现》" in result["chapter_breakdown"]
    assert "- **场景目标**：衙门查档 + 林舟 + 锁定调查入口" in result["chapter_breakdown"]
    assert "- **爽点类型**：信息反转 + ⭐⭐⭐" in result["chapter_breakdown"]
    assert "## 故事概述" not in result["chapter_breakdown"]
    assert result["current_chapter_count"] == 2
    assert result["should_continue"] is False


def test_expand_plot_outline_incremental_keeps_actual_count_when_no_new_chapters_are_generated():
    expander = _make_base_expander()
    expander.llm = _QueueLLM(
        [
            '{"story_overview": "", "volumes": []}',
            '{"chapters": []}',
            '{"should_continue": false, "reason": "需要先补充更明确的章节目标。"}',
        ]
    )

    result = expander.expand_plot_outline_incremental(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=1,
        increment=15,
        target_total_chapters=100,
    )

    assert result["current_chapter_count"] == 1
    assert result["should_continue"] is False


def test_generate_epic_framework_prefers_structured_json_payloads():
    expander = _make_base_expander()
    expander.creative_director = _QueueAgent(
        [
            """
            {
              "genre_type": "修仙",
              "global_theme": "在旧秩序崩坏中重建个人道途",
              "story_phases": [
                {
                  "phase": "前期",
                  "volume_span": "第1-1卷",
                  "chapter_span": "60-80",
                  "focus": "主角进入新世界并建立基础同盟"
                },
                {
                  "phase": "中期",
                  "volume_span": "第2-2卷",
                  "chapter_span": "60-80",
                  "focus": "宗门暗线升级并触发更高层阴谋"
                }
              ],
              "power_progression": [
                {
                  "volume_span": "第1-1卷",
                  "realm_stage": "炼气一层→炼气九层",
                  "chapter_span": "60-80",
                  "notes": "完成凡俗阶段到修行入门的跨越"
                },
                {
                  "volume_span": "第2-2卷",
                  "realm_stage": "筑基初期→筑基后期",
                  "chapter_span": "60-80",
                  "notes": "卷末完成第一次真正意义上的破局"
                }
              ],
              "volumes": [
                {
                  "volume_index": 1,
                  "title": "星火入局",
                  "chapter_span": "60-80",
                  "core_goal": "主角立足青石城并摸到旧案真相入口",
                  "realm_stage": "炼气一层→炼气九层",
                  "major_enemy": "青石城执掌旧档的灰衣掌簿",
                  "ending_climax": "旧案残卷暴露主角身世线索"
                },
                {
                  "volume_index": 2,
                  "title": "天关试炼",
                  "chapter_span": "60-80",
                  "core_goal": "主角进入宗门并对抗隐藏在内门的操盘者",
                  "realm_stage": "筑基初期→筑基后期",
                  "major_enemy": "内门监察使与其背后势力",
                  "ending_climax": "宗门试炼场公开爆发阵营决裂"
                }
              ],
              "foreshadowings": [
                {
                  "content": "主角真实身世与旧案残卷相关",
                  "plant_at": "第1卷",
                  "pave_at": ["第2卷"],
                  "reveal_at": "第2卷"
                }
              ],
              "character_lifecycle": [
                {
                  "character": "林舟",
                  "debut": "第1卷",
                  "active_span": "1-2卷",
                  "transition": "持续作为核心视角人物"
                }
              ]
            }
            """
        ]
    )
    # epic 两段式已按设计切到 creative_director_pro（_base.py 中与 creative_director 同源），
    # 测试脚手架用同一个注入 agent 别名即可
    expander.creative_director_pro = expander.creative_director

    result = expander.generate_epic_framework(
        world_setting="修仙世界，旧案牵动宗门暗线。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        total_volumes=2,
        total_chapters_range=(120, 160),
    )

    framework_text = result["expanded_outline"]
    assert "## 一、故事总纲与终局" in framework_text
    assert "## 二、阶段路线图" in framework_text
    assert "## 三、力量与冲突升级路线" in framework_text
    assert "## 四、滚动细化策略" in framework_text
    assert "## 五、分卷规划（共2卷）" in framework_text
    assert "【第1卷】星火入局" in framework_text
    assert "【第2卷】天关试炼" in framework_text
    assert "## 六、关键伏笔布局" in framework_text
    assert "## 七、核心人物生命周期" in framework_text

    volumes_data = parse_framework_to_volumes(framework_text, 2)
    assert volumes_data["framework_header"]
    assert volumes_data["framework_footer"]
    assert volumes_data["volumes"]["1"]["title"] == "星火入局"
    assert volumes_data["volumes"]["2"]["title"] == "天关试炼"
    assert result["framework_type"] == "epic"
    assert result["estimated_chapters"] == 140


def test_generate_epic_framework_falls_back_when_json_has_no_volumes():
    expander = _make_base_expander()
    expander.creative_director = _QueueAgent(
        [
            """
            {
              "story_positioning": {
                "genre_type": "修仙",
                "global_theme": "逆命求生"
              },
              "stage_roadmap": [],
              "power_progression": [],
              "rolling_strategy": {}
            }
            """,
            """## 一、故事总纲与终局
- 题材类型：修仙
- 全局主题：逆命求生

## 二、阶段路线图
- 前期聚焦主角立足与主线引子

## 三、力量与冲突升级路线
- 以阶段冲突递进推动升级

## 四、滚动细化策略
- 先固定全书总纲，再按卷细化

## 五、分卷规划（共2卷）
【第1卷】陵火初醒
- 章节规模：1-60章
- 卷定位：开篇立足
- 核心目标：主角逃出生天并建立立身之本

【第2卷】鬼市入局
- 章节规模：61-120章
- 卷定位：势力展开
- 核心目标：主角进入更大的冲突格局

## 六、关键伏笔布局
- 埋下守陵血脉与天道残片的联系

## 七、核心人物生命周期
- 主角：第1卷登场并持续成长"""
        ]
    )
    expander.creative_director_pro = expander.creative_director

    result = expander.generate_epic_framework(
        world_setting="修仙世界，主角自陵墓逃生。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        total_volumes=2,
        total_chapters_range=(120, 160),
    )

    framework_text = result["expanded_outline"]
    assert "待补充分卷规划" not in framework_text
    assert "【第1卷】陵火初醒" in framework_text
    assert "【第2卷】鬼市入局" in framework_text


def test_generate_epic_framework_falls_back_when_json_has_incomplete_volumes():
    expander = _make_base_expander()
    creative_director = _CapturingQueueAgent(
        [
            """
            {
              "story_positioning": {
                "genre_type": "修仙",
                "global_theme": "逆命求生",
                "story_premise": "主角在旧秩序崩坏中寻找自身道途。"
              },
              "stage_roadmap": [
                {
                  "stage": "前期",
                  "volume_span": "第1-3卷",
                  "chapter_span": "1-180",
                  "phase_goal": "主角立足"
                }
              ],
              "volumes": [
                {
                  "volume_index": 1,
                  "title": "陵火初醒",
                  "chapter_span": "1-60",
                  "stage_positioning": "开篇立足",
                  "core_goal": "主角逃出生天"
                },
                {
                  "volume_index": 2,
                  "title": "鬼市入局",
                  "chapter_span": "61-120",
                  "stage_positioning": "势力展开",
                  "core_goal": "进入更大冲突"
                }
              ]
            }
            """,
            """## 一、故事总纲与终局
- 题材类型：修仙
- 全局主题：逆命求生
- 故事总纲：主角在旧秩序崩坏中寻找自身道途。

## 二、阶段路线图
- 前期聚焦主角立足与宗门暗线

## 三、力量与冲突升级路线
- 以阶段冲突递进推动升级

## 四、滚动细化策略
- 先锁定全书总纲，再逐卷细化

## 五、分卷规划（共3卷）
【第1卷】陵火初醒
- 章节规模：1-60章
- 卷定位：开篇立足
- 核心目标：主角逃出生天

【第2卷】鬼市入局
- 章节规模：61-120章
- 卷定位：势力展开
- 核心目标：进入更大冲突

【第3卷】宗门试锋
- 章节规模：121-180章
- 卷定位：第一次正面碰撞旧秩序
- 核心目标：主角打通主线升级口

## 六、关键伏笔布局
- 埋下旧案残卷与宗门黑幕的联系

## 七、核心人物生命周期
- 主角：第1卷登场并持续成长"""
        ]
    )
    expander.creative_director = creative_director
    expander.creative_director_pro = creative_director

    result = expander.generate_epic_framework(
        world_setting="修仙世界，主角自陵墓逃生。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        total_volumes=3,
        total_chapters_range=(180, 240),
    )

    framework_text = result["expanded_outline"]
    assert len(creative_director.prompts) == 2
    assert "`volumes` 数组长度必须严格等于 3" in creative_director.prompts[0]
    assert "当前仅检测到：1、2" in creative_director.prompts[1]
    assert "【第1卷】陵火初醒" in framework_text
    assert "【第2卷】鬼市入局" in framework_text
    assert "【第3卷】宗门试锋" in framework_text
    assert OutlineExpander._story_list_parseable_volume_indexes(framework_text) == [1, 2, 3]


def test_story_extract_volume_block_includes_full_volume_body_until_next_volume():
    framework_text = """## 五、分卷规划（共3卷）
【第1卷】守陵血祭
- 章节规模：60章
- 核心目标：主角逃出天陨陵

【第2卷】纸人替死
- 章节规模：35章
- 核心目标：掌握替死底牌
- 卷尾钩子：赎罪崖雷劫将至

【第3卷】叛宗道葬
- 章节规模：40章
- 核心目标：硬撼第一次清道雷劫
- 主冲突：营救苏晚晴并对抗净灵天宗

## 六、关键伏笔布局
- 伏笔：天道残缺的真正起源
"""

    volume_two_block = OutlineExpander._story_extract_volume_block(framework_text, 2)
    volume_three_block = OutlineExpander._story_extract_volume_block(framework_text, 3)

    assert "【第2卷】纸人替死" in volume_two_block
    assert "掌握替死底牌" in volume_two_block
    assert "【第3卷】叛宗道葬" not in volume_two_block

    assert "【第3卷】叛宗道葬" in volume_three_block
    assert "硬撼第一次清道雷劫" in volume_three_block
    assert "关键伏笔布局" not in volume_three_block


def test_expand_volume_detail_prefers_structured_json_payloads(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _QueueAgent(
        [
            """
            {
              "story_overview": "林舟承接上一卷残卷线索，正式进入宗门暗线调查阶段。",
              "volume_title": "青石余烬",
              "chapters": [
                {
                  "chapter_number": 31,
                  "title": "入局宗门",
                  "scene_goal": "山门议事 + 林舟顾晚 + 取得外门通行资格",
                  "conflict_design": "外门执事故意设卡，主角借残卷线索反制并换取入门机会",
                  "emotional_curve": "压抑 → 对峙 → 振奋",
                  "highlight_type": "身份反转 + ⭐⭐⭐",
                  "information_payoff": "确认宗门内有人篡改旧案记录，并拿到首个内门坐标",
                  "ending_hook": "顾晚发现坐标对应的是一处禁闭旧阁",
                  "involved_characters": ["林舟", "顾晚"]
                },
                {
                  "chapter_number": 32,
                  "title": "旧阁留痕",
                  "scene_goal": "旧阁夜探 + 林舟顾晚 + 找到失落档案",
                  "conflict_design": "禁制与巡查同时逼近，主角必须在暴露前完成破局",
                  "emotional_curve": "紧张 → 危急 → 亢奋",
                  "highlight_type": "破局推进 + ⭐⭐⭐⭐",
                  "information_payoff": "找到旧案缺页，并锁定下一卷内门调查入口",
                  "ending_hook": "内门监察使主动现身，暗示真正敌人已盯上主角",
                  "involved_characters": ["林舟", "顾晚"]
                }
              ],
              "foreshadowing_checks": [
                {
                  "chapter": "第31章",
                  "action": "埋设",
                  "content": "埋设宗门印记与旧案残卷的关联"
                }
              ],
              "volume_connection_check": {
                "core_task_completion": "完成入宗试探并找到旧阁调查切口",
                "next_volume_opening": "携带线索进入内门继续追查",
                "ending_hook": "监察使现身试探林舟来历"
              }
            }
            """
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="""## 一、整体叙事节奏
- 前期（第1-2卷）：旧案入局

## 三、2卷概要
【第1卷】星火入局
- 核心：主角发现旧案入口

【第2卷】青石余烬
- 核心：宗门暗线调查升级

## 四、关键伏笔布局
- 伏笔：宗门印记对应旧案残卷""",
        target_volume_index=2,
        world_setting="修仙世界，宗门与旧案暗线交织。",
        characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
        start_chapter_num=31,
        chapters_count_range=(2, 3),
        prev_volume_summary={
            "core_plot_completed": "主角获得残卷并锁定宗门方向",
            "ending_hook": "残卷上的印记指向外门旧阁",
            "next_volume_target": "潜入宗门查明印记来源",
            "character_status_update": "林舟与顾晚形成稳定同盟",
            "new_foreshadowings": ["残卷印记的真正主人"],
        },
        pending_foreshadowings=[
            {"action": "plant", "content": "宗门印记与旧案残卷的关联", "reveal_volume": 3},
        ],
    )

    volume_text = result["expanded_outline"]
    assert "## 一、故事概述" in volume_text
    assert "## 二、第2卷详细规划（预计2-3章，从第31章开始）" in volume_text
    assert "### 第31章：《入局宗门》" in volume_text
    assert "### 第32章：《旧阁留痕》" in volume_text
    assert "- **场景目标**：山门议事 + 林舟顾晚 + 取得外门通行资格" in volume_text
    assert "- **涉及人物**：林舟、顾晚" in volume_text
    assert "## 三、伏笔埋设检查" in volume_text
    assert "宗门印记与旧案残卷的关联" in volume_text
    assert "## 四、卷尾衔接检查" in volume_text
    assert "✅ 下卷开局场景：携带线索进入内门继续追查" in volume_text
    assert re.search(r"###\s*第31章[：:]", volume_text)
    assert result["chapter_count"] == 2
    assert result["chapters_start"] == 31
    assert result["chapters_end"] == 32
    assert result["validation_passed"] is True


def test_expand_volume_detail_normalizes_malformed_table_fields_before_return(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _QueueAgent(
        [
            """## 一、故事概述
- 苏璃与顾长庚闯入黑门试炼，开始接触封印室外围。

## 二、第2卷详细规划（预计2-3章，从第31章开始）

### 第31章：《黑门试炼》
| 字段 | 内容 |
| --- | --- |
| 场景目标 | 解开关于苏璃家族债务的石碑试炼并穿透迷宫，抵达封印室前最后一区域 |
| 冲突设计 | 苏璃内心对家族罪感的毁灭性崩塌 vs 以逻辑漏洞绕过天庄规则完成通透 |
| 关键事件 | ① 碑文清楚写明苏璃所在家族曾出力开发系统 |
| **涉及人物】 顾长庚、苏璃、丹丘生 | |
| 人物推进 | 苏璃开始主动承担家族秘密带来的代价 |
| **情节作用】 第二道试炼完结；直通封印室进入多路争夺 | |
| **结尾钩子】 丹丘生推开黑门，从二人视线中消失 | |

### 第32章：《夜潮回响》
- **场景目标**：顾长庚与苏璃进入封印室外围，确认多方势力已经逼近。
- **冲突设计**：丹丘生消失后留下的误导痕迹，让二人必须在信任与怀疑之间做出选择。
- **关键事件**：
1. 顾长庚在封印纹路中找到旧案坐标
2. 苏璃意识到家族隐瞒的不只是债务
- **涉及人物**：顾长庚、苏璃
- **人物推进**：顾长庚开始把关键线索主动共享给苏璃。
- **情节作用**：把卷级主线从试炼推进到封印室争夺战前夜。
- **结尾钩子**：封印室深处传来第三次钟鸣。

## 三、伏笔埋设检查
- 黑塔钟声第二次广播，暗示追讨范围进一步扩大。

## 四、卷尾衔接检查
- 结尾必须把内城议会的追索线索抛给下一卷。
"""
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="""## 一、整体叙事节奏
- 前期（第1-2卷）：黑门试炼与封印室争夺并行推进

## 三、2卷概要
【第2卷】黑门回响
- 核心：试炼推进至封印室外围，旧案线索开始与家族隐秘交叉
""",
        target_volume_index=2,
        world_setting="修真世界，多方势力围绕封印室与旧案残卷展开争夺。",
        characters="### 【姓名】：顾长庚\n【角色定位】：主角\n\n### 【姓名】：苏璃\n【角色定位】：核心同伴\n\n### 【姓名】：丹丘生\n【角色定位】：搅局者",
        start_chapter_num=31,
        chapters_count_range=(2, 3),
        prev_volume_summary={
            "core_plot_completed": "主角确认黑门试炼与旧案线索相关",
            "ending_hook": "黑门背后通向封印室外围",
            "next_volume_target": "进入封印室外围并确认争夺各方",
            "character_status_update": "顾长庚与苏璃建立脆弱同盟",
            "new_foreshadowings": ["丹丘生的真实目的"],
        },
        pending_foreshadowings=[
            {"action": "plant", "content": "黑塔钟声与封印室追索同步升级", "reveal_volume": 3},
        ],
    )

    volume_text = result["expanded_outline"]
    assert "| 字段 | 内容 |" not in volume_text
    assert "**涉及人物】" not in volume_text
    assert "**情节作用】" not in volume_text
    assert "### 第31章：《黑门试炼》" in volume_text
    assert "- **涉及人物**：顾长庚、苏璃、丹丘生" in volume_text
    assert "- **情节作用**：第二道试炼完结；直通封印室进入多路争夺" in volume_text
    assert "- **结尾钩子**：丹丘生推开黑门，从二人视线中消失" in volume_text
    assert volume_text.count("## 三、伏笔埋设检查") == 1
    assert volume_text.count("## 四、卷尾衔接检查") == 1
    assert result["chapter_count"] == 2
    assert result["validation_passed"] is True


def test_story_count_rendered_volume_detail_chapters_supports_emphasized_markdown_headings():
    volume_text = """## 二、第2卷详细规划（预计2-3章，从第31章开始）

#### **第31章：入局宗门**
- **场景目标**：主角进入外门并拿到通行资格

#### **第32章：旧阁夜探**
- **场景目标**：夜探旧阁并找到残缺案卷
"""

    assert OutlineExpander._story_count_rendered_volume_detail_chapters(volume_text) == 2


def test_story_normalize_volume_detail_response_strips_preamble_before_story_heading():
    normalized = OutlineExpander._story_normalize_volume_detail_response(
        """好的，作为精通叙事的情节架构师，我将开始规划本卷内容。

## 一、故事概述
- 第二卷承接上一卷的旧案线索，继续推进宗门调查。

## 二、第2卷详细规划（预计2-3章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：潜入宗门
""",
        target_volume_index=2,
        start_chapter_num=31,
        chapters_count_range=(2, 3),
    )

    assert normalized.startswith("## 一、故事概述")
    assert "好的，作为精通叙事的情节架构师" not in normalized


def test_expand_volume_detail_backfills_tail_sections_when_model_omits_them(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _QueueAgent(
        [
            """## 一、故事概述
- 第二卷承接上一卷，转入宗门旧案调查。

## 二、第2卷详细规划（预计2-3章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：主角潜入宗门并锁定旧阁入口
- **冲突设计**：执事临时盘查，主角必须补齐身份漏洞
- **关键事件**：取得外门通行资格
- **涉及人物**：林舟、顾晚
- **人物推进**：两人从试探转向初步默契
- **情节作用**：打开宗门旧案调查入口
- **结尾钩子**：旧阁方向传来异常钟声

### 第32章：《旧阁夜探》
- **场景目标**：夜探旧阁并找到残缺案卷
- **冲突设计**：旧阁内部存在延迟警报节点
- **关键事件**：确认卷宗缺页指向内门暗线
- **涉及人物**：林舟、顾晚
- **人物推进**：顾晚开始主动接管撤离节奏
- **情节作用**：将调查线推进到内门旧案层
- **结尾钩子**：缺页卷宗提到了更深层的旧案入口
"""
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="【第2卷】青石余烬\n- 核心：宗门旧案调查升级",
        target_volume_index=2,
        world_setting="修仙世界，宗门与旧案暗线交织。",
        characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
        start_chapter_num=31,
        chapters_count_range=(2, 3),
        pending_foreshadowings=[
            {"action": "埋设", "content": "旧阁缺页与内门旧案的关联", "reveal_volume": 3},
        ],
    )

    volume_text = result["expanded_outline"]
    assert "## 三、伏笔埋设检查" in volume_text
    assert "- 待定章节：埋设 旧阁缺页与内门旧案的关联" in volume_text
    assert "## 四、卷尾衔接检查" in volume_text
    assert "✅ 本卷任务完成：" in volume_text
    assert "✅ 下卷开局场景：" in volume_text
    assert "✅ 卷尾钩子：缺页卷宗提到了更深层的旧案入口" in volume_text


def test_estimate_volume_detail_model_always_prefers_deepseek_v4_pro():
    assert OutlineExpander.estimate_volume_detail_model((60, 100)) == "deepseek-pro"
    assert OutlineExpander.estimate_volume_detail_model((20, 80)) == "deepseek-pro"


def test_story_should_chunk_volume_detail_when_upper_bound_reaches_80():
    assert OutlineExpander._story_should_chunk_volume_detail((60, 79)) is False
    assert OutlineExpander._story_should_chunk_volume_detail((60, 80)) is True


def test_story_resolve_volume_detail_chunk_size_uses_larger_default_for_large_volume():
    assert OutlineExpander._story_resolve_volume_detail_chunk_size((20, 20)) == 20
    assert OutlineExpander._story_resolve_volume_detail_chunk_size((60, 80)) == 36
    assert OutlineExpander._story_resolve_volume_detail_chunk_size((60, 100)) == 36


def test_story_resolve_volume_detail_primary_target_count_uses_midpoint_in_range():
    assert OutlineExpander._story_resolve_volume_detail_primary_target_count((60, 100)) == 80
    assert OutlineExpander._story_resolve_volume_detail_primary_target_count((20, 80)) == 50


def test_story_build_volume_detail_chunk_ranges_split_explicit_target_count():
    assert OutlineExpander._story_build_volume_detail_chunk_ranges(
        start_chapter_num=31,
        target_chapter_count=60,
        chunk_size=36,
    ) == [(31, 66), (67, 90)]


def test_outline_expander_initializes_dynamic_timeouts(monkeypatch):
    import backend.app.services.agents.outline_expansion._base as base_module

    captured_calls = []

    class _DummyKnowledgeBase:
        pass

    class _DummyMemoryManager:
        def __init__(self):
            self.persist_directory = ""

    class _DummyAgent:
        def __init__(self, _knowledge_base=None, memory_manager=None, llm=None):
            self.memory_manager = memory_manager or _DummyMemoryManager()
            self.llm = llm

    class _DummySummarizer:
        def __init__(self, *_args, **_kwargs):
            return None

    class _DummyRecognizer:
        pass

    class _DummyPlotValidator:
        pass

    def fake_create_task_llm(*, task_type=None, model=None, max_tokens=None, timeout=None, **kwargs):
        runtime_options = dict(kwargs)
        runtime_options["timeout"] = timeout
        llm = type("DummyLLM", (), {})()
        llm.model_name = model or task_type
        llm.max_tokens = max_tokens
        llm.runtime_options = runtime_options
        captured_calls.append(
            {
                "task_type": task_type,
                "model": model,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )
        return llm

    def fake_estimate_timeout(model_id, requested_max_tokens, minimum_timeout=None):
        _ = requested_max_tokens, minimum_timeout
        return 480 if model_id == "deepseek-pro" else 240

    monkeypatch.setattr(base_module, "NovelKnowledgeBase", _DummyKnowledgeBase)
    monkeypatch.setattr(base_module, "NovelMemoryManager", _DummyMemoryManager)
    monkeypatch.setattr(base_module, "CreativeDirectorAgent", _DummyAgent)
    monkeypatch.setattr(base_module, "PlotArchitectAgent", _DummyAgent)
    monkeypatch.setattr(base_module, "CharacterDesignerAgent", _DummyAgent)
    monkeypatch.setattr(base_module, "LayeredSummarizer", _DummySummarizer)
    monkeypatch.setattr(base_module, "CharacterRecognizer", _DummyRecognizer)
    monkeypatch.setattr(base_module, "CharacterPlotValidator", _DummyPlotValidator)
    monkeypatch.setattr(base_module, "create_task_llm", fake_create_task_llm)
    monkeypatch.setattr(base_module, "estimate_model_timeout_seconds", fake_estimate_timeout)

    expander = OutlineExpander()

    assert expander.llm.runtime_options["timeout"] == 240
    assert expander.plot_architect_plus.llm.runtime_options["timeout"] == 480
    assert expander.plot_architect_large.llm.runtime_options["timeout"] == 480
    assert expander.plot_architect_r1.llm.runtime_options["timeout"] == 480
    assert any(call["task_type"] == "outline_expand" and call["timeout"] == 240 for call in captured_calls)
    assert any(call["task_type"] == "volume_detail_expand" and call["timeout"] == 480 for call in captured_calls)
    assert any(call["model"] == "deepseek-pro" and call["timeout"] == 480 for call in captured_calls)


def test_expand_volume_detail_uses_chunked_generation_when_volume_is_large(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_plus = _QueueAgent([])
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """
            {
              "story_overview": "第二卷承接黑门试炼余波，前半段先完成撤离与整编，后半段把主线推进到封印室外围争夺前夜。",
              "volume_positioning": {
                "stage_goal": "完成黑狱脱身并建立下一阶段潜入条件",
                "main_conflict": "重伤撤离压力与外部清扫追索同时逼近"
              },
              "chapter_groups": [
                {
                  "arc": "撤离与整编",
                  "chapter_span": "31-34",
                  "stage_task": "完成黑狱撤离并接入外部支援",
                  "conflict_upgrade": "从内场崩塌升级到外部清扫追索",
                  "character_focus": "顾长庚、苏璃",
                  "foreshadowing_task": "把封印室争夺线索前置"
                }
              ],
              "chapters": [
                {
                  "chapter_number": 31,
                  "title": "引爆之决",
                  "scene_goal": "借铁面的爆破窗口脱离黑狱主结构",
                  "conflict_design": "铁面必须用牺牲换取生路，顾长庚被迫接受撤离现实",
                  "key_events": "铁面引爆支撑柱；顾长庚带着苏璃冲入排污管；陆南柯被坍塌吞没",
                  "character_progress": "顾长庚第一次正面接过铁面留下的责任与日志",
                  "plot_function": "完成黑狱篇章的爆点收束并打开逃亡段落",
                  "ending_hook": "排污管道在爆炸余波中整体失衡",
                  "involved_characters": ["顾长庚", "苏璃", "铁面"]
                },
                {
                  "chapter_number": 32,
                  "title": "管道逃亡",
                  "scene_goal": "在失控排污通道中保住苏璃并找到出口",
                  "conflict_design": "重伤、缺氧与追兵扫描残波同步逼近，顾长庚必须一边护人一边辨认路线",
                  "key_events": "顾长庚拆开维护闸门；苏璃短暂苏醒指认旧标识；二人被激流卷出暗潭",
                  "character_progress": "苏璃开始主动参与逃亡决策，不再只被动依赖顾长庚",
                  "plot_function": "把卷内主线从黑狱内场切换到外部荒野求生",
                  "ending_hook": "远处天庄净化白光开始覆盖整片山域",
                  "involved_characters": ["顾长庚", "苏璃"]
                }
              ],
              "foreshadowing_checks": [
                {
                  "chapter": "第31章",
                  "action": "埋设",
                  "content": "铁面日志中藏有倒悬之塔中继站结构图"
                }
              ],
              "volume_connection_check": {
                "core_task_completion": "完成黑狱脱身并带出关键日志",
                "next_volume_opening": "借外部支援整编后转入封印室外围潜入",
                "ending_hook": "日志里的结构图指向更大的监控核心"
              }
            }
            """,
            """### 第33章：《天降净罚》
- **场景目标**：在荒山净化打击中找到临时掩体并避开追索扫描
- **冲突设计**：白光净化覆盖地形，顾长庚必须顶着伤势拖着苏璃绕开扫描波峰
- **关键事件**：净化白光抹平黑狱周边；顾长庚躲入塌陷废坑；苏璃记录净化节奏漏洞
- **涉及人物**：顾长庚、苏璃
- **人物推进**：顾长庚对“活下去”从被动坚持转为主动规划，苏璃开始补位技术侧判断
- **情节作用**：把卷内逃亡压力升级为体系级追索，并埋下后续利用扫描漏洞的抓手
- **结尾钩子**：灵盟旧频段在废坑中闪过极弱回应

### 第34章：《沉默之履》
- **场景目标**：沿结晶荒野转移并接入第一支可信外援
- **冲突设计**：顾长庚必须判断求援信号真假，避免把自己和苏璃送进第二个包围圈
- **关键事件**：两人穿越结晶荒野；顾长庚用铁面留下的密钥校验信号；魏青率47队接应成功
- **涉及人物**：顾长庚、苏璃、魏青
- **人物推进**：顾长庚开始把“孤身硬扛”转为有选择地建立协作链，苏璃重新建立对外沟通信心
- **情节作用**：完成逃亡段落收束，把剧情送入整编与反击筹备阶段
- **结尾钩子**：魏青带来万寿殿寿宴与续命丹的最新情报
""",
        ]
    )
    expander._story_should_chunk_volume_detail = lambda _chapters_count_range: True
    expander._story_resolve_volume_detail_chunk_size = lambda _chapters_count_range: 2

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="【第2卷】黑门回响\n- 核心：黑狱脱身后转入外部荒野逃亡与整编。",
        target_volume_index=2,
        world_setting="修真世界，天庄以净化舰队执行高压清扫，外部荒野遍布结晶污染区。",
        characters="### 【姓名】：顾长庚\n【角色定位】：主角\n\n### 【姓名】：苏璃\n【角色定位】：核心同伴\n\n### 【姓名】：魏青\n【角色定位】：外部接应者",
        start_chapter_num=31,
        chapters_count_range=(4, 4),
        prev_volume_summary={
            "core_plot_completed": "主角与苏璃闯入黑狱深层并逼近核心试炼",
            "ending_hook": "铁面决定启动最终爆破预案",
            "next_volume_target": "借爆破窗口逃出黑狱并活着把日志带出去",
        },
        pending_foreshadowings=[
            {"action": "plant", "content": "倒悬之塔中继站结构图将在后续潜入中起关键作用", "reveal_volume": 3},
        ],
    )

    assert len(expander.plot_architect_r1.prompts) == 2
    assert "本次只展开第31章到第32章" in expander.plot_architect_r1.prompts[0]
    assert "本次只补写第33章到第34章" in expander.plot_architect_r1.prompts[1]
    assert "系统当前按约 4 章" in expander.plot_architect_r1.prompts[0]
    assert "严禁重写第33章之前的任何章节" in expander.plot_architect_r1.prompts[1]
    assert "不得重新从第31章起叙述" in expander.plot_architect_r1.prompts[1]
    assert result["chapter_count"] == 4
    assert result["chapters_start"] == 31
    assert result["chapters_end"] == 34
    assert "### 第31章：《引爆之决》" in result["expanded_outline"]
    assert "### 第32章：《管道逃亡》" in result["expanded_outline"]
    assert "### 第33章：《天降净罚》" in result["expanded_outline"]
    assert "### 第34章：《沉默之履》" in result["expanded_outline"]
    assert "## 三、伏笔埋设检查" in result["expanded_outline"]
    assert "## 四、卷尾衔接检查" in result["expanded_outline"]


def test_expand_volume_detail_uses_r1_chunk_supplement_after_large_volume_range_summary(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_plus = _CapturingQueueAgent(
        [
            """## 一、故事概述
- 第二卷推进宗门旧案调查。

## 二、第2卷详细规划（预计2-3章，从第31章开始）
- 本卷剧情段落：
  - 潜入旧阁（章节：31-33；任务：完成夜探并锁定核心证据）

## 三、伏笔埋设检查
- 第31-33章：铺垫 旧阁缺页案卷与内门旧案相关

## 四、卷尾衔接检查
✅ 本卷任务完成：摸清旧阁暗线
""",
            """## 一、故事概述
- 第二卷推进宗门旧案调查。

## 二、第2卷详细规划（预计2-3章，从第31章开始）
- 本卷剧情段落：
  - 潜入旧阁（章节：31-33；任务：完成夜探并锁定核心证据）

## 三、伏笔埋设检查
- 第31-33章：铺垫 旧阁缺页案卷与内门旧案相关

## 四、卷尾衔接检查
✅ 本卷任务完成：摸清旧阁暗线
""",
            """## 一、故事概述
- 第二卷推进宗门旧案调查。

## 二、第2卷详细规划（预计2-3章，从第31章开始）
- 本卷剧情段落：
  - 潜入旧阁（章节：31-33；任务：完成夜探并锁定核心证据）

## 三、伏笔埋设检查
- 第31-33章：铺垫 旧阁缺页案卷与内门旧案相关

## 四、卷尾衔接检查
✅ 本卷任务完成：摸清旧阁暗线
""",
        ]
    )
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """### 第31章：《入局宗门》
- **场景目标**：潜入宗门外门并锁定旧阁入口
- **冲突设计**：外门执事临时盘查，林舟必须现场补齐身份漏洞
- **关键事件**：顾晚远程协助伪造手续，林舟成功混入外门
- **涉及人物**：林舟、顾晚
- **人物推进**：林舟开始主动信任顾晚的判断
- **情节作用**：为后续旧阁夜探打开入口
- **结尾钩子**：旧阁方向传来不合时宜的钟声

### 第32章：《旧阁踩点》
- **场景目标**：摸清旧阁附近暗哨与撤离路线
- **冲突设计**：巡逻队临时换班，主角必须快速改线
- **关键事件**：确认旧阁存在双层监视圈
- **涉及人物**：林舟、顾晚
- **人物推进**：顾晚从远程支援转向主动控场
- **情节作用**：为正式夜探提供环境信息
- **结尾钩子**：旧阁窗内闪过诡异蓝光

### 第33章：《夜探旧阁》
- **场景目标**：潜入旧阁内部并找到关键证据
- **冲突设计**：旧阁内部布有延迟触发的警报节点
- **关键事件**：林舟发现被抽走的卷宗缺页位置
- **涉及人物**：林舟、顾晚
- **人物推进**：两人从临时配合转为稳定协作
- **情节作用**：把旧案调查推进到核心证据层
- **结尾钩子**：警报日志显示有人比他们更早来过
""",
        ]
    )
    expander.estimate_volume_detail_model = lambda _chapters_count_range: "qwen-plus"

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="【第2卷】青石余烬\n- 核心：宗门暗线调查升级",
        target_volume_index=2,
        world_setting="修仙世界，宗门与旧案暗线交织。",
        characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
        start_chapter_num=31,
        chapters_count_range=(2, 3),
        pending_foreshadowings=[
            {"action": "plant", "content": "宗门印记与旧案残卷的关联", "reveal_volume": 3},
        ],
    )

    assert result["chapter_count"] == 3
    assert "### 第31章：《入局宗门》" in result["expanded_outline"]
    assert "章节：31-33" not in result["expanded_outline"]
    assert OutlineExpander._story_find_volume_detail_range_shortcuts(
        result["expanded_outline"],
        start_chapter_num=31,
        chapters_count_range=(2, 3),
    ) == []
    assert len(expander.plot_architect_plus.prompts) == 3
    assert len(expander.plot_architect_r1.prompts) == 1


def test_expand_volume_detail_falls_back_when_structured_json_has_too_few_chapters(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """
            {
              "story_overview": "第二卷开始调查宗门旧案。",
              "chapters": [
                {
                  "chapter_number": 31,
                  "title": "入局宗门",
                  "scene_goal": "主角潜入外门，锁定旧阁入口",
                  "conflict_design": "执事有意刁难，主角借线索反制",
                  "key_events": "取得外门通行资格",
                  "character_progress": "与顾晚建立初步默契",
                  "plot_function": "打开宗门暗线调查入口",
                  "ending_hook": "旧阁坐标指向禁区",
                  "involved_characters": ["林舟", "顾晚"]
                }
              ]
            }
            """,
            """```json
{
  "story_overview": "第二卷承接上一卷线索，正式潜入宗门旧案。",
  "chapter_groups": [
    {
      "arc": "潜入与夜探",
      "chapter_span": "第31-32章",
      "stage_task": "潜入宗门并锁定旧阁暗线",
      "conflict_upgrade": "从外门阻拦升级到夜探禁制",
      "character_focus": "林舟、顾晚",
      "foreshadowing_task": "埋设宗门印记与旧案残卷的关联"
    }
  ],
  "chapters": [
    {
      "chapter_number": 31,
      "title": "入局宗门",
      "scene_goal": "主角进入外门并拿到通行资格",
      "conflict_design": "执事故意设卡，主角借线索反制",
      "key_events": "进入宗门并确认旧阁坐标",
      "character_progress": "两人建立更稳定的协作关系",
      "plot_function": "开启第二卷主调查线",
      "ending_hook": "夜探旧阁的机会已经出现",
      "involved_characters": ["林舟", "顾晚"]
    },
    {
      "chapter_number": 32,
      "title": "旧阁夜探",
      "scene_goal": "夜探旧阁并找到残缺案卷",
      "conflict_design": "禁制与巡查同步逼近",
      "key_events": "找到缺页案卷并锁定内门入口",
      "character_progress": "顾晚确认继续深挖旧案",
      "plot_function": "把第二卷推进到更深层调查",
      "ending_hook": "监查使主动现身试探",
      "involved_characters": ["林舟", "顾晚"]
    }
  ],
  "foreshadowing_checks": [
    {
      "chapter": "第31章",
      "action": "埋设",
      "content": "宗门印记与旧案残卷的关联"
    }
  ],
  "volume_connection_check": {
    "core_task_completion": "完成入宗试探并拿到夜探线索",
    "next_volume_opening": "携带残卷进入内门继续追查",
    "ending_hook": "监查使现身，真正敌人开始试探主角"
  }
}
```""",
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="【第2卷】青石余烬\n- 核心：宗门暗线调查升级",
        target_volume_index=2,
        world_setting="修仙世界，宗门与旧案暗线交织。",
        characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
        start_chapter_num=31,
        chapters_count_range=(2, 3),
        prev_volume_summary={
            "core_plot_completed": "主角锁定宗门方向",
            "ending_hook": "残卷印记指向外门旧阁",
        },
        pending_foreshadowings=[
            {"action": "plant", "content": "宗门印记与旧案残卷的关联", "reveal_volume": 3},
        ],
    )

    assert len(expander.plot_architect_r1.prompts) == 2
    assert "补充纠偏" in expander.plot_architect_r1.prompts[1]
    assert result["chapter_count"] == 2
    assert result["chapters_start"] == 31
    assert result["chapters_end"] == 32
    assert "### 第31章：《入局宗门》" in result["expanded_outline"]
    assert "### 第32章：《旧阁夜探》" in result["expanded_outline"]


def test_expand_volume_detail_appends_missing_chapters_when_only_short_by_tail(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """
            {
              "story_overview": "第二卷承接上一卷，继续调查宗门旧案。",
              "chapters": [
                {
                  "chapter_number": 31,
                  "title": "入局宗门",
                  "scene_goal": "主角潜入外门并锁定旧阁入口",
                  "conflict_design": "执事有意刁难，主角借线索反制",
                  "key_events": "取得外门通行资格",
                  "character_progress": "与顾晚建立初步默契",
                  "plot_function": "打开宗门暗线调查入口",
                  "ending_hook": "旧阁坐标指向禁区",
                  "involved_characters": ["林舟", "顾晚"]
                }
              ]
            }
            """,
            """## 一、故事概述
- 仍旧只写到第32章。

## 二、第2卷详细规划（预计3-4章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：主角潜入外门并锁定旧阁入口

### 第32章：《旧阁夜探》
- **场景目标**：夜探旧阁并找到残缺案卷

## 三、伏笔埋设检查
- 第31章：埋设 旧案入口

## 四、卷尾衔接检查
- 本卷核心任务完成情况：暂时只推进到夜探
""",
            """## 一、故事概述
- 修复后仍旧只写到第32章。

## 二、第2卷详细规划（预计3-4章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：主角潜入外门并锁定旧阁入口

### 第32章：《旧阁夜探》
- **场景目标**：夜探旧阁并找到残缺案卷

## 三、伏笔埋设检查
- 第31章：埋设 旧案入口

## 四、卷尾衔接检查
- 本卷核心任务完成情况：暂时只推进到夜探
""",
            """### 第33章：《内门借路》
- **场景目标**：主角借内门名义突破封锁
- **冲突设计**：巡查长老与外门执事双重逼问
- **关键事件**：顾晚伪造调令，林舟抢先进入内门通道
- **涉及人物**：林舟、顾晚
- **人物推进**：两人从试探转为正式协作
- **情节作用**：补齐本卷中段推进并把调查线推向内门
- **结尾钩子**：通道尽头传来旧案卷宗翻动声
""",
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="【第2卷】青石余烬\n- 核心：宗门暗线调查升级",
        target_volume_index=2,
        world_setting="修仙世界，宗门与旧案暗线交织。",
        characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
        start_chapter_num=31,
        chapters_count_range=(3, 4),
        prev_volume_summary={
            "core_plot_completed": "主角锁定宗门方向",
            "ending_hook": "残卷印记指向外门旧阁",
        },
    )

    assert len(expander.plot_architect_r1.prompts) == 4
    assert "强制纠偏" in expander.plot_architect_r1.prompts[2]
    assert "只补写缺失的后续章节" in expander.plot_architect_r1.prompts[3]
    assert "从第33章开始连续输出" in expander.plot_architect_r1.prompts[3]
    assert result["chapter_count"] == 3
    assert result["chapters_start"] == 31
    assert result["chapters_end"] == 33
    assert "### 第33章：《内门借路》" in result["expanded_outline"]
    assert "## 三、伏笔埋设检查" in result["expanded_outline"]


def test_expand_volume_detail_rewrites_when_range_summary_replaces_missing_middle_chapters(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """
            {
              "story_overview": "第二卷继续推进宗门旧案调查。",
              "chapter_groups": [
                {
                  "arc": "潜入与夜探",
                  "chapter_span": "31-36",
                  "stage_task": "潜入宗门并摸清旧阁线索",
                  "conflict_upgrade": "从外门试探升级到旧阁暗哨追踪",
                  "character_focus": "林舟、顾晚",
                  "foreshadowing_task": "埋下内门旧案的更深线索"
                }
              ],
              "chapters": [
                {
                  "chapter_number": 31,
                  "title": "入局宗门",
                  "scene_goal": "主角拿到外门临时身份",
                  "conflict_design": "执事临时设卡，顾晚远程解围",
                  "key_events": "林舟成功混入外门",
                  "character_progress": "林舟开始适应单线潜入压力",
                  "plot_function": "打开宗门调查入口",
                  "ending_hook": "旧阁夜间巡逻路线浮出水面",
                  "involved_characters": ["林舟", "顾晚"]
                },
                {
                  "chapter_number": 32,
                  "title": "旧阁踩点",
                  "scene_goal": "提前摸清旧阁周边暗哨",
                  "conflict_design": "巡逻队提前换班，主角险些暴露",
                  "key_events": "锁定旧阁的两条撤离路径",
                  "character_progress": "顾晚开始主动补位支援",
                  "plot_function": "为夜探旧阁铺垫环境信息",
                  "ending_hook": "旧阁窗内闪过不正常的蓝光",
                  "involved_characters": ["林舟", "顾晚"]
                },
                {
                  "chapter_number": 35,
                  "title": "内门借道",
                  "scene_goal": "借路进入更深区域",
                  "conflict_design": "内门令牌来源遭到盘查",
                  "key_events": "两人拿到进入内门的短暂窗口",
                  "character_progress": "顾晚承担更直接的执行风险",
                  "plot_function": "把调查线推进到内门",
                  "ending_hook": "暗处有人先一步清理了现场",
                  "involved_characters": ["林舟", "顾晚"]
                },
                {
                  "chapter_number": 36,
                  "title": "暗哨现身",
                  "scene_goal": "确认盯梢者身份",
                  "conflict_design": "暗哨反向布置诱捕点",
                  "key_events": "林舟锁定对方来自诺顿情报线",
                  "character_progress": "林舟判断力进一步成熟",
                  "plot_function": "把敌对势力正式拉入当前卷",
                  "ending_hook": "旧案卷宗的缺页内容终于现身",
                  "involved_characters": ["林舟", "顾晚"]
                }
              ],
              "foreshadowing_checks": [
                {
                  "chapter": "第31章",
                  "action": "埋设",
                  "content": "旧阁暗哨与内门旧案存在关联"
                }
              ],
              "volume_connection_check": {
                "core_task_completion": "完成潜入并找到旧案入口",
                "next_volume_opening": "沿内门暗线继续追查",
                "ending_hook": "缺页卷宗的真实内容出现"
              }
            }
            """,
            """## 一、故事概述
- 第二卷继续推进宗门旧案调查，补齐旧阁夜探的完整细纲。

## 二、第2卷详细规划（预计4-4章，从第31章开始）
- 本卷剧情段落：
  - 潜入与夜探（章节：31-34；任务：潜入宗门并完成旧阁夜探；冲突升级：从外门设卡升级到旧阁暗哨追踪；人物焦点：林舟、顾晚；伏笔任务：埋下内门旧案线索）

### 第31章：《入局宗门》
- **场景目标**：主角拿到外门临时身份，为后续夜探创造条件
- **冲突设计**：执事临时设卡，顾晚远程递送伪造手续帮林舟过关
- **关键事件**：林舟混入外门并锁定旧阁位置
- **涉及人物**：林舟、顾晚
- **人物推进**：林舟开始适应独立潜入的压力
- **情节作用**：打开本卷调查入口
- **结尾钩子**：旧阁巡逻路线在深夜发生异常变动

### 第32章：《旧阁踩点》
- **场景目标**：摸清旧阁周边暗哨和撤离路径
- **冲突设计**：巡逻队提前换班，主角必须临场调整路线
- **关键事件**：确认旧阁存在两层监视圈
- **涉及人物**：林舟、顾晚
- **人物推进**：顾晚从支援者变成更主动的协作者
- **情节作用**：为正式夜探提供环境信息
- **结尾钩子**：旧阁窗内闪过不正常的蓝光

### 第33章：《夜探旧阁》
- **场景目标**：趁换班空档潜入旧阁内部
- **冲突设计**：旧阁内部存在延迟触发的警报节点
- **关键事件**：林舟找到被刻意抽走的卷宗缺页位置
- **涉及人物**：林舟、顾晚
- **人物推进**：林舟开始信任顾晚的临场判断
- **情节作用**：把旧案调查推进到核心证据层
- **结尾钩子**：警报日志显示有人比他们更早到过

### 第34章：《缺页回声》
- **场景目标**：带着线索撤离并确认幕后势力方向
- **冲突设计**：暗哨沿撤离路线反向设伏，逼迫主角冒险变道
- **关键事件**：两人成功带出缺页信息并锁定内门暗线
- **涉及人物**：林舟、顾晚
- **人物推进**：两人协作从试探进入稳定互信
- **情节作用**：完成本卷阶段任务并打开下阶段入口
- **结尾钩子**：缺页卷宗提到了更深层的内门旧案

## 三、伏笔埋设检查
- 第31章：埋设 旧阁暗哨与内门旧案存在关联

## 四、卷尾衔接检查
- 本卷任务完成情况：完成潜入并拿到旧案缺页线索
- 下卷开局场景：借内门暗线继续追查幕后势力
- 卷尾钩子：缺页卷宗指出真正的旧案入口
""",
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    result = expander.expand_volume_detail(
        framework_content="【第2卷】青石余烬\n- 核心：宗门暗线调查升级",
        target_volume_index=2,
        world_setting="修仙世界，宗门与旧案暗线交织。",
        characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
        start_chapter_num=31,
        chapters_count_range=(4, 4),
        prev_volume_summary={
            "core_plot_completed": "主角锁定宗门方向",
            "ending_hook": "残卷印记指向外门旧阁",
        },
    )

    assert len(expander.plot_architect_r1.prompts) == 2
    assert "禁止使用“第A-B章 / A-B章 / 第A至B章”这种写法概括多章" in expander.plot_architect_r1.prompts[1]
    assert "第31-36章" in expander.plot_architect_r1.prompts[1]
    assert result["chapter_count"] == 4
    assert result["chapters_start"] == 31
    assert result["chapters_end"] == 34
    assert "### 第31章：《入局宗门》" in result["expanded_outline"]
    assert "### 第32章：《旧阁踩点》" in result["expanded_outline"]
    assert "### 第33章：《夜探旧阁》" in result["expanded_outline"]
    assert "### 第34章：《缺页回声》" in result["expanded_outline"]


def test_expand_volume_detail_raises_when_range_summary_shortcut_persists_after_repair(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """
            {
              "story_overview": "第二卷继续推进宗门旧案调查。",
              "chapter_groups": [
                {
                  "arc": "潜入与夜探",
                  "chapter_span": "31-36",
                  "stage_task": "潜入宗门并摸清旧阁线索",
                  "conflict_upgrade": "从外门试探升级到旧阁暗哨追踪",
                  "character_focus": "林舟、顾晚",
                  "foreshadowing_task": "埋下内门旧案的更深线索"
                }
              ],
              "chapters": [
                {"chapter_number": 31, "title": "入局宗门"},
                {"chapter_number": 32, "title": "旧阁踩点"},
                {"chapter_number": 35, "title": "内门借道"},
                {"chapter_number": 36, "title": "暗哨现身"}
              ]
            }
            """,
            """## 一、故事概述
- 第二卷继续推进宗门旧案调查。

## 二、第2卷详细规划（预计4-4章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：主角拿到外门临时身份

### 第32章：《旧阁踩点》
- **场景目标**：摸清旧阁周边暗哨

(第33-34章，第二段：旧阁夜探，内容聚焦于林舟潜入旧阁并带出缺页线索。)

### 第35章：《内门借道》
- **场景目标**：借路进入更深区域

### 第36章：《暗哨现身》
- **场景目标**：确认盯梢者身份

## 三、伏笔埋设检查
- 第31章：埋设 旧阁暗哨与内门旧案存在关联

## 四、卷尾衔接检查
- 本卷任务完成情况：完成潜入并找到旧案入口
""",
            """(第33-34章，第二段：仍然不展开，只保留范围摘要。)""",
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    with pytest.raises(ValueError, match="单卷细化未逐章展开"):
        expander.expand_volume_detail(
            framework_content="【第2卷】青石余烬\n- 核心：宗门暗线调查升级",
            target_volume_index=2,
            world_setting="修仙世界，宗门与旧案暗线交织。",
            characters="### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
            start_chapter_num=31,
            chapters_count_range=(4, 4),
        )

    assert len(expander.plot_architect_r1.prompts) == 3
    assert "禁止使用“第A-B章 / A-B章 / 第A至B章”这种写法概括多章" in expander.plot_architect_r1.prompts[1]
    assert "只补写这段缺失章节" in expander.plot_architect_r1.prompts[2]
    assert "第33章到第34章" in expander.plot_architect_r1.prompts[2]


def test_expand_volume_detail_raises_when_retries_still_have_too_few_chapters(monkeypatch):
    expander = _make_base_expander()
    expander.llm = object()
    expander.plot_architect = _QueueAgent([])
    expander.creative_director = _QueueAgent([])
    expander.plot_architect_r1 = _CapturingQueueAgent(
        [
            """
            {
              "story_overview": "第二卷开始调查宗门旧案。",
              "chapters": [
                {
                  "chapter_number": 31,
                  "title": "入局宗门"
                }
              ]
            }
            """,
            """## 一、故事概述
- 仍然只有一章。

## 二、第2卷详细规划（预计2-3章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：潜入宗门

## 三、伏笔埋设检查
- 第31章：埋设 旧案入口

## 四、卷尾衔接检查
✅ 本卷任务完成：进入宗门
""",
            """## 一、故事概述
- 仍然只有一章。

## 二、第2卷详细规划（预计2-3章，从第31章开始）

### 第31章：《入局宗门》
- **场景目标**：潜入宗门

            ## 三、伏笔埋设检查
- 第31章：埋设 旧案入口

## 四、卷尾衔接检查
✅ 本卷任务完成：进入宗门
""",
            "仍旧没有新增章节。",
            "仍旧没有新增章节。",
        ]
    )
    expander.plot_architect_plus = _QueueAgent([])

    monkeypatch.setattr(
        outline_expander_module,
        "get_chapter_renumberer",
        lambda: _DummyRenumberer(),
    )
    monkeypatch.setattr(
        outline_expander_module,
        "get_consistency_validator",
        lambda strict_mode=True: _DummyConsistencyValidator(),
    )

    with pytest.raises(ValueError, match="单卷细化生成章节数不足"):
        expander.expand_volume_detail(
            framework_content="【第2卷】青石余烬\n- 核心：宗门暗线调查升级",
            target_volume_index=2,
            world_setting="修仙世界，宗门与旧案暗线交织。",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            start_chapter_num=31,
            chapters_count_range=(2, 3),
            pending_foreshadowings=[
                {"action": "plant", "content": "宗门印记与旧案残卷的关联", "reveal_volume": 3},
            ],
        )

    assert len(expander.plot_architect_r1.prompts) == 5
    assert "补充纠偏" in expander.plot_architect_r1.prompts[1]
    assert "强制纠偏" in expander.plot_architect_r1.prompts[2]
    assert "只补写缺失的后续章节" in expander.plot_architect_r1.prompts[3]
    assert "第32-32章仍缺失" in expander.plot_architect_r1.prompts[4]
