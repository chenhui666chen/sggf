import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.services.agents.outline_expander import OutlineExpander
from app.services.story_expansion_coordinator import parse_outline_blocks


def test_story_extract_volume_block_supports_markdown_wrapped_bracket_headings() -> None:
    framework_content = """
## 故事总览

### 【第1卷】灰烬启程
- 第一卷摘要

### 【第2卷】迷城深潜
- 第二卷摘要
- 第二卷继续展开

## 六、关键伏笔布局
- 尾部约束
""".strip()

    extracted = OutlineExpander._story_extract_volume_block(framework_content, 2)

    assert "【第2卷】迷城深潜" in extracted
    assert "第二卷继续展开" in extracted
    assert "【第1卷】灰烬启程" not in extracted
    assert "关键伏笔布局" not in extracted


def test_story_extract_volume_block_supports_plain_volume_headings_and_parseable_indexes() -> None:
    framework_content = """
## 世界观
- 统一约束

## 第1卷：霜桥初醒
- 第一卷摘要

## 第2卷：镜城暗潮
- 第二卷摘要

第3卷 终夜回廊
- 第三卷摘要

## 七、核心人物生命周期
- 尾部约束
""".strip()

    extracted = OutlineExpander._story_extract_volume_block(framework_content, 2)
    indexes = OutlineExpander._story_list_parseable_volume_indexes(framework_content)

    assert "第2卷：镜城暗潮" in extracted
    assert "第二卷摘要" in extracted
    assert "第3卷 终夜回廊" not in extracted
    assert indexes == [1, 2, 3]


def test_story_render_outline_overview_supports_nested_novel_plan_chapters() -> None:
    payload = {
        "novel_plan": {
            "title": "测试规划",
            "chapters": [
                {
                    "chapter_number": 4,
                    "title": "转折初现",
                    "scene_goal": "推进主线",
                    "conflict_design": "冲突升级",
                    "key_events": ["遭遇追兵", "获得线索"],
                    "characters_involved": ["叶清尘", "墨丹心"],
                    "plot_function": "承上启下",
                    "ending_hook": "新的危机出现",
                },
                {
                    "chapter_number": 5,
                    "title": "死局破局",
                    "scene_goal": "完成突围",
                    "conflict_design": "绝境反杀",
                    "key_events": ["设局反击", "脱离包围"],
                    "characters_involved": ["叶清尘", "陆明霄"],
                    "plot_function": "阶段高潮",
                    "ending_hook": "引出新地图",
                },
            ],
        }
    }

    rendered = OutlineExpander._story_render_outline_overview(payload)
    _, blocks = parse_outline_blocks(rendered)

    assert "## 章节规划" in rendered
    assert "#### 第4章" in rendered
    assert len(blocks) == 2
    assert [block.original_number for block in blocks] == [4, 5]


def test_expand_plot_outline_incremental_uses_chapter_only_prompt_and_accepts_nested_novel_plan() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    prompts: list[tuple[str, str]] = []
    responses = [
        {
            "novel_plan": {
                "summary": "主角需要先熬过追捕期，再进入地下遗迹线。",
                "chapters": [
                    {
                        "chapter_number": 4,
                        "title": "转折初现",
                        "scene_goal": "推进主线",
                        "conflict_design": "冲突升级",
                        "key_events": ["遭遇追兵", "获得线索"],
                        "characters_involved": ["叶清尘", "墨丹心"],
                        "plot_function": "承上启下",
                        "ending_hook": "新的危机出现",
                    },
                    {
                        "chapter_number": 5,
                        "title": "死局破局",
                        "scene_goal": "完成突围",
                        "conflict_design": "绝境反杀",
                        "key_events": ["设局反击", "脱离包围"],
                        "characters_involved": ["叶清尘", "陆明霄"],
                        "plot_function": "阶段高潮",
                        "ending_hook": "引出新地图",
                    },
                ],
            }
        },
        {"should_continue": False, "reason": "已得到可用章节"},
    ]

    def fake_invoke(_llm, system_prompt, user_prompt, fallback):
        prompts.append((system_prompt, user_prompt))
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]

    current_outline = """
### 第1章：黑岩集·染血石

**场景目标**：觉醒古印。

### 第2章：律纹初试·墨影叩门

**场景目标**：验证规则可改写。

### 第3章：律纹为刃·巷战初鸣

**场景目标**：完成第一次反杀。
""".strip()

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline=current_outline,
        world_setting="律衡界规则森严。",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心",
        current_chapter_count=3,
        increment=15,
        target_total_chapters=18,
    )

    assert len(prompts) == 2
    assert "禁止使用卷级结构" in prompts[0][1]
    assert "不要输出 `volumes`" in prompts[0][1]
    assert "第4章" in result["chapter_breakdown"]
    assert "第5章" in result["chapter_breakdown"]
    assert result["current_chapter_count"] == 5
    assert result["should_continue"] is False


def test_expand_plot_outline_incremental_uses_rendered_chapter_numbers_instead_of_planned_total_text() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    responses = [
        {
            "novel_plan": {
                "summary": "全书预计 200 章，当前阶段先完成第 4-5 章。",
                "chapters": [
                    {
                        "chapter_number": 4,
                        "title": "新章一",
                        "scene_goal": "推进主线",
                        "conflict_design": "首轮冲突升级",
                        "key_events": ["线索浮现", "敌人试探"],
                        "involved_characters": ["叶清尘"],
                        "character_progress": "主角开始主动反击",
                        "plot_function": "承上启下",
                        "ending_hook": "引出下一章危机",
                    },
                    {
                        "chapter_number": 5,
                        "title": "新章二",
                        "scene_goal": "接住危机",
                        "conflict_design": "局势进一步恶化",
                        "key_events": ["追兵逼近", "被迫破局"],
                        "involved_characters": ["叶清尘", "墨丹心"],
                        "character_progress": "两人形成阶段协作",
                        "plot_function": "阶段升级",
                        "ending_hook": "第二阶段入口开启",
                    },
                ],
            }
        },
        {"should_continue": True, "reason": "当前仅完成到第 5 章，还需要继续扩展。"},
    ]

    def fake_invoke(_llm, _system_prompt, _user_prompt, fallback):
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]
    expander.count_chapters_in_outline = lambda text: 200 if "200 章" in str(text) else 3  # type: ignore[method-assign]

    current_outline = """
#### 第1章：《黑岩集》
- **场景目标**：觉醒古印

#### 第2章：《墨影叩门》
- **场景目标**：验证规则

#### 第3章：《巷战初鸣》
- **场景目标**：完成第一次反杀
""".strip()

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline=current_outline,
        world_setting="灵纹世界",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心",
        current_chapter_count=3,
        increment=15,
        target_total_chapters=18,
    )

    assert result["current_chapter_count"] == 5
    assert result["should_continue"] is True


def test_expand_plot_outline_incremental_supports_top_level_chapter_plans() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    responses = [
        {
            "planning_metadata": {
                "current_arc_name": "黑岩逃遁与天工初探",
            },
            "chapter_plans": [
                {
                    "chapter_number": 4,
                    "title": "新章三",
                    "scene_goal": "推进逃亡线",
                    "conflict_design": "追兵逼近",
                    "key_events": ["潜入矿道", "强行破局"],
                    "characters_involved": ["叶清尘", "墨丹心"],
                    "plot_function": "承接上一章",
                    "ending_hook": "引出地下遗迹",
                },
                {
                    "chapter_number": 5,
                    "title": "新章四",
                    "scene_goal": "打开新地图",
                    "conflict_design": "环境反噬",
                    "key_events": ["发现遗迹", "拿到线索"],
                    "characters_involved": ["叶清尘", "凌虚子"],
                    "plot_function": "阶段推进",
                    "ending_hook": "导向下一段冲突",
                },
            ],
        },
        {"should_continue": True, "reason": "当前仅完成到第 5 章，还需要继续扩展。"},
    ]

    def fake_invoke(_llm, _system_prompt, _user_prompt, fallback):
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]

    current_outline = """
#### 第1章：《黑岩集》
- **场景目标**：觉醒古印

#### 第2章：《墨影叩门》
- **场景目标**：验证规则

#### 第3章：《巷战初鸣》
- **场景目标**：完成第一次反杀
""".strip()

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline=current_outline,
        world_setting="灵纹世界",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心",
        current_chapter_count=3,
        increment=15,
        target_total_chapters=18,
        overall_target_chapters=40,
    )

    assert result["current_chapter_count"] == 5
    assert "第4章" in result["chapter_breakdown"]
    assert "第5章" in result["chapter_breakdown"]
    assert "本轮阶段摘要" in result["expanded_outline"]


def test_expand_plot_outline_incremental_supports_nested_volume_plan_chapters() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    responses = [
        {
            "volume_plan": {
                "volume_title": "第二卷：九宗风云与律外棋局",
                "plot_arc_summary": "主角深入天律城，推进新阶段冲突。",
                "chapters": [
                    {
                        "chapter_number": 19,
                        "title": "新章五",
                        "scene_goal": "进入新地图",
                        "conflict_design": "高压盘查",
                        "key_events": ["潜入城池", "躲过筛查"],
                        "involved_characters": ["叶清尘", "凌虚子"],
                        "plot_function": "开启新阶段",
                        "ending_hook": "拍卖会开启",
                    },
                    {
                        "chapter_number": 20,
                        "title": "新章六",
                        "scene_goal": "发现阴谋",
                        "conflict_design": "线索真假难辨",
                        "key_events": ["潜入黑市", "发现诱饵"],
                        "involved_characters": ["叶清尘", "墨丹心"],
                        "plot_function": "加深冲突",
                        "ending_hook": "导向地下密室",
                    },
                ],
            }
        },
        {"should_continue": True, "reason": "当前仅完成到第 20 章，还需要继续扩展。"},
    ]

    def fake_invoke(_llm, _system_prompt, _user_prompt, fallback):
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]

    current_outline = """
#### 第1章：《黑岩集》
- **场景目标**：觉醒古印

#### 第2章：《墨影叩门》
- **场景目标**：验证规则

#### 第3章：《巷战初鸣》
- **场景目标**：完成第一次反杀
""".strip()

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline=current_outline,
        world_setting="灵纹世界",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心\n### 【姓名】：凌虚子",
        current_chapter_count=18,
        increment=15,
        target_total_chapters=33,
        overall_target_chapters=40,
    )

    assert result["current_chapter_count"] == 20
    assert "第19章" in result["chapter_breakdown"]
    assert "第20章" in result["chapter_breakdown"]


def test_expand_plot_outline_incremental_retries_when_first_pass_returns_no_chapters() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    responses = [
        {"story_overview": "仅给出阶段摘要，没有章节。", "chapters": []},
        {
            "chapter_plans": [
                {
                    "chapter_number": 4,
                    "title": "新章七",
                    "scene_goal": "推进逃亡线",
                    "conflict_design": "追兵逼近",
                    "key_events": ["潜入矿道", "强行破局"],
                    "characters_involved": ["叶清尘", "墨丹心"],
                    "plot_function": "承接上一章",
                    "ending_hook": "引出地下遗迹",
                },
                {
                    "chapter_number": 5,
                    "title": "新章八",
                    "scene_goal": "打开新地图",
                    "conflict_design": "环境反噬",
                    "key_events": ["发现遗迹", "拿到线索"],
                    "characters_involved": ["叶清尘", "凌虚子"],
                    "plot_function": "阶段推进",
                    "ending_hook": "导向下一段冲突",
                },
            ],
        },
        {"should_continue": True, "reason": "当前仅完成到第 5 章，还需要继续扩展。"},
    ]

    def fake_invoke(_llm, _system_prompt, _user_prompt, fallback):
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]

    current_outline = """
#### 第1章：《黑岩集》
- **场景目标**：觉醒古印

#### 第2章：《墨影叩门》
- **场景目标**：验证规则

#### 第3章：《巷战初鸣》
- **场景目标**：完成第一次反杀
""".strip()

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline=current_outline,
        world_setting="灵纹世界",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心\n### 【姓名】：凌虚子",
        current_chapter_count=3,
        increment=15,
        target_total_chapters=18,
        overall_target_chapters=40,
    )

    assert result["current_chapter_count"] == 5
    assert "第4章" in result["chapter_breakdown"]
    assert "第5章" in result["chapter_breakdown"]


def test_expand_plot_outline_incremental_repairs_premature_finale_signals_before_final_round() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    prompts: list[tuple[str, str]] = []
    responses = [
        {
            "story_overview": "主线进入终局阶段。",
            "chapters": [
                {
                    "chapter_number": 4,
                    "title": "大结局前夜",
                    "scene_goal": "收束全书矛盾",
                    "conflict_design": "终局大战前夕",
                    "key_events": ["主角集结最终战力", "准备终局决战"],
                    "involved_characters": ["叶清尘", "墨丹心"],
                    "character_progress": "主角准备终局一战",
                    "plot_function": "全书收官前置",
                    "ending_hook": "下一章进入大结局",
                }
            ],
        },
        {
            "story_overview": "主线进入阶段性高潮。",
            "chapters": [
                {
                    "chapter_number": 4,
                    "title": "危局临界点",
                    "scene_goal": "推进阶段性高潮",
                    "conflict_design": "敌我双方完成第二阶段对垒",
                    "key_events": ["主角集结阶段战力", "新线索指向更深层敌手"],
                    "involved_characters": ["叶清尘", "墨丹心"],
                    "character_progress": "主角确认下一阶段战略",
                    "plot_function": "阶段高潮与后续升级接口",
                    "ending_hook": "下一章引出更高层危机",
                }
            ],
        },
        {"should_continue": False, "reason": "已得到可用章节"},
    ]

    def fake_invoke(_llm, system_prompt, user_prompt, fallback):
        prompts.append((system_prompt, user_prompt))
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]

    current_outline = """
#### 第1章：《黑岩集》
- **场景目标**：觉醒古印

#### 第2章：《墨影叩门》
- **场景目标**：验证规则

#### 第3章：《巷战初鸣》
- **场景目标**：完成第一次反杀
""".strip()

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline=current_outline,
        world_setting="灵纹世界",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心",
        current_chapter_count=3,
        increment=1,
        target_total_chapters=4,
        overall_target_chapters=40,
    )

    assert len(prompts) == 3
    assert "严禁出现“终章 / 大结局 / 完结 / 终局 / 尾声 / 最终决战”等提前收官字样" in prompts[0][1]
    assert "请修正下面这份“常规协同”的章节 JSON" in prompts[1][1]
    assert "危局临界点" in result["chapter_breakdown"]
    assert "大结局前夜" not in result["chapter_breakdown"]


def test_expand_plot_outline_incremental_normalizes_continue_reason_for_non_final_rounds() -> None:
    expander = OutlineExpander.__new__(OutlineExpander)
    expander.llm = object()

    responses = [
        {
            "chapters": [
                {
                    "chapter_number": 4,
                    "title": "阶段推进",
                    "scene_goal": "推进当前阶段",
                    "conflict_design": "冲突升级",
                    "key_events": ["发现新线索", "敌人试探"],
                    "involved_characters": ["叶清尘", "墨丹心"],
                    "character_progress": "主角确定下一步方向",
                    "plot_function": "阶段推进",
                    "ending_hook": "引出下一轮危机",
                }
            ],
        },
        {"should_continue": False, "reason": "当前可确认章节数（4）已达目标章节数（4），且第 4 章已是全书大结局。"},
    ]

    def fake_invoke(_llm, _system_prompt, _user_prompt, fallback):
        return responses.pop(0)

    expander._story_invoke_llm_json = fake_invoke  # type: ignore[attr-defined]

    result = OutlineExpander.expand_plot_outline_incremental(
        expander,
        current_outline="#### 第1章：《黑岩集》\n- **场景目标**：觉醒古印",
        world_setting="灵纹世界",
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心",
        current_chapter_count=3,
        increment=1,
        target_total_chapters=4,
        overall_target_chapters=40,
    )

    assert result["should_continue"] is False
    assert result["continue_reason"] == "当前可确认章节数（4）已达本轮目标章节数（4），本轮阶段性细纲已完成，后续仍需继续朝全书目标 40 章推进。"
