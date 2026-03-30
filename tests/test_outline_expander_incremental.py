import re
import sys
from pathlib import Path

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
            "selected_model": "qwen-long",
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
                  "role_type": "情报盟友",
                  "appearance": "短发利落，目光冷静。",
                  "personality": "克制敏锐，做事果断。",
                  "background": "出身旧案相关家族，长期追查真相。",
                  "worldview_stance": "相信秩序需要被纠正，而不是被盲从。",
                  "motivation": "查清家族旧事并阻止灭口。",
                  "abilities": "擅长潜入与情报梳理。",
                  "weakness": "过度戒备，不轻易信任他人。",
                  "plot_role": "协助主角补齐调查线的情报缺口。",
                  "growth_arc": "从单独追查到主动结盟。",
                  "key_relationships": "与林舟从试探转为盟友。",
                  "related_clues": "旧案残卷、夜市暗号"
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
                  "related_clues_patch": "旧案残卷",
                  "plot_role_patch": "从独自追查转向双线配合",
                  "growth_arc_patch": "开始尝试信任新盟友"
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
    assert "## 已有角色关系更新" in result["all_characters"]
    assert "【关键关系·补充】：" in result["all_characters"]
    assert "顾晚：开始共享旧案线索" in result["all_characters"]
    assert "**主角阵营内部**：" in result["character_relationships"]
    assert "- 林舟 ↔ 顾晚：盟友（共同调查旧案）" in result["character_relationships"]
    assert result["role_distribution"]["支持角色"] == 1
    assert result["current_character_count"] == 2
    assert result["should_continue"] is False


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

    assert "## 故事概述" in result["expanded_outline"]
    assert "### 【第1卷】「青石初局」" in result["expanded_outline"]
    assert "#### 第1章：《雨夜入城》 [已写]" in result["chapter_breakdown"]
    assert "- 主要内容：主角抵达青石城。" in result["chapter_breakdown"]
    assert "#### 第2章：《旧案浮现》" in result["chapter_breakdown"]
    assert "- **场景目标**：衙门查档 + 林舟 + 锁定调查入口" in result["chapter_breakdown"]
    assert "- **爽点类型**：信息反转 + ⭐⭐⭐" in result["chapter_breakdown"]
    assert "## 故事概述" not in result["chapter_breakdown"]
    assert result["current_chapter_count"] == 2
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

    result = expander.generate_epic_framework(
        world_setting="修仙世界，旧案牵动宗门暗线。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        total_volumes=2,
        total_chapters_range=(120, 160),
    )

    framework_text = result["expanded_outline"]
    assert "## 一、整体叙事节奏" in framework_text
    assert "## 二、境界/实力体系进阶" in framework_text
    assert "## 三、2卷概要" in framework_text
    assert "【第1卷】星火入局" in framework_text
    assert "【第2卷】天关试炼" in framework_text
    assert "## 四、关键伏笔布局" in framework_text
    assert "## 五、核心人物生命周期" in framework_text

    volumes_data = parse_framework_to_volumes(framework_text, 2)
    assert volumes_data["framework_header"]
    assert volumes_data["framework_footer"]
    assert volumes_data["volumes"]["1"]["title"] == "星火入局"
    assert volumes_data["volumes"]["2"]["title"] == "天关试炼"
    assert result["framework_type"] == "epic"


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
