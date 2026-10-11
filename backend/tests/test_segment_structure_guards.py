"""分段生成结构守卫与短稿回退测试（P2）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
from app.services.chapter_structure_guard import should_revert_short_revision
from app.services.prompts.stages.content_creation import split_scene_segments
from app.services.prompts.workflow_runtime import build_iteration_revision_user_prompt


PLAN = """
## 2. \u6838\u5fc3\u4e8b\u4ef6
- \u963f\u4e5d\u627e\u8001\u9648\u5934\u6253\u542c\u767d\u4e8b\u94dc\u94b1
- \u738b\u9ebb\u5b50\u7a9d\u70b9\u88ab\u56f4\u5835
- \u9ed1\u8896\u7ae0\u4eba\u51fa\u73b0\uff0c\u963f\u4e5d\u9003\u8131
## 5. \u7ed3\u5c3e\u94a9\u5b50\u8bbe\u8ba1
- \u94a9\u5b50\u5177\u4f53\u5185\u5bb9\uff1a\u7eb8\u94b1\u80cc\u9762\u5199\u7740\u4e00\u4e2a\u5730\u5740\uff0c\u6b63\u662f\u987e\u6c89\u821f\u4fa6\u63a2\u793e\u9644\u8fd1\u7684\u5e9f\u5f03\u620f\u53f0\u5750\u6807\uff0c\u4ee5\u53ca\u4e00\u884c\u5c0f\u5b57\uff1a\u201c\u542c\u98ce\u8005\uff0c\u5165\u5c40\u3002\u201d
"""


def _opening():
    return ("\u60ac\u5ff5\u5f00\u5934", "\u629b\u51fa\u5f02\u5e38", "")


def _ending():
    return ("\u60ac\u5ff5\u5f0f", "\u5173\u952e\u4fe1\u606f\u63ed\u9732\u4e00\u534a", "")


def _base_kwargs(plan, segments, index, **extra):
    kwargs = dict(
        next_chapter_number=14,
        chapter_plan=plan,
        segments=segments,
        seg_index=index,
        previous_segment_tail="\u4ed6\u8e29\u5230\u4e86\u6811\u679d\u3002",
        previous_ending="\u7a97\u5916\u5531\u8154",
        recent_chapter_assets_summary="",
        rag_character_context="",
        rag_world_context="",
        selected_opening=_opening(),
        selected_ending=_ending(),
    )
    kwargs.update(extra)
    return kwargs


def test_first_segment_hides_later_plan_events():
    segments = split_scene_segments(PLAN)
    assert len(segments) >= 2
    prompt = ChapterPromptBuilder("\u7384\u5e7b").build_segment_user_prompt(
        **_base_kwargs(PLAN, segments, 0)
    )
    assert "\u963f\u4e5d\u627e\u8001\u9648\u5934" in prompt
    assert "\u9ed1\u8896\u7ae0\u4eba\u51fa\u73b0" in prompt  # overview may mention later beats
    # full later climax must not sit inside the first-segment plan body as writable events
    plan_header = "本段可写规划"
    assert plan_header in prompt
    plan_body = prompt.split(plan_header, 1)[1]
    assert "\u542c\u98ce\u8005\uff0c\u5165\u5c40" not in plan_body.split("\u3010", 1)[0]


def test_last_segment_keeps_ending_hook_from_plan_tail():
    segments = split_scene_segments(PLAN)
    prompt = ChapterPromptBuilder("\u7384\u5e7b").build_segment_user_prompt(
        **_base_kwargs(PLAN, segments, len(segments) - 1)
    )
    assert "\u542c\u98ce\u8005\uff0c\u5165\u5c40" in prompt
    assert "\u5e9f\u5f03\u620f\u53f0" in prompt


def test_short_structural_cut_is_not_reverted():
    original = "\u91cd\u590d\u6d41\u7a0bA" * 400
    revised = "\u5355\u7ebf\u6d41\u7a0bB" * 180
    assert should_revert_short_revision(
        original,
        revised,
        has_structural_failure=True,
    ) is False
    assert should_revert_short_revision(original, revised) is True


def test_revision_prompt_for_struct_broken_allows_cutting_half():
    prompt = build_iteration_revision_user_prompt(
        chapter_number=14,
        chapter_content="初稿",
        review_text="STRUCT_BROKEN|HIGH|整章重复",
        revision_mode_hint="heavy",
        chapter_plan=PLAN,
    )
    assert "结构重复时允许大幅删减" in prompt or "不得因字数回滚" in prompt or "删掉重复线" in prompt


def test_extract_structural_failure_codes_filters_structural_only():
    from app.api.v1.workflow.routes_chapter import _extract_structural_failure_codes

    review = (
        "STRUCT_BROKEN|HIGH|同一场景被写两遍，荆陌两次进场\n"
        "STALL_NO_PROGRESS|MED|情节原地踏步\n"
        "CONTINUITY_BREAK|HIGH|病蛊与阵图共频消失\n"
        "PACING_DRAG|LOW|节奏拖沓\n"
    )
    codes = _extract_structural_failure_codes(review)
    assert codes == {"STRUCT_BROKEN", "STALL_NO_PROGRESS"}


def test_foreshadow_field_regex_accepts_markdown_bold():
    """伏笔字段解析契约：兼容 markdown 加粗标签（**伏笔事项**：），否则闸门 A2 误判未声明回收。"""
    from app.services.pre_generation_gate import parse_foreshadow_items, _is_reveal_declaration

    plan = """## 7. 伏笔事项
- **伏笔事项**：回收——柳慎言利用青玄门作为探路棋子的策略，呼应第4章荆陌的登场。
- **说明**：第4章中，荆陌作为青玄门执法长老登场。
"""
    items = parse_foreshadow_items(plan)
    assert any(_is_reveal_declaration(i) for i in items), f"加粗格式的回收声明未被识别: {items}"
    # 传统非加粗格式仍可解析
    assert parse_foreshadow_items("伏笔事项：埋设——新的暗线")


def test_extract_structural_failure_codes_empty_on_clean_review():
    from app.api.v1.workflow.routes_chapter import _extract_structural_failure_codes

    assert _extract_structural_failure_codes("综合评分：9.2，无明显结构问题") == set()
    assert _extract_structural_failure_codes("") == set()


def _single_pass_kwargs(plan):
    return dict(
        next_chapter_number=3,
        chapter_plan=plan,
        previous_ending="上一章结尾。",
        recent_chapter_assets_summary="",
        rag_character_context="",
        rag_world_context="",
        selected_opening=_opening(),
        selected_ending=_ending(),
    )


def test_single_pass_prompt_contains_hook_discipline():
    prompt = ChapterPromptBuilder("悬疑").build_user_prompt(**_single_pass_kwargs(PLAN))
    assert "【结尾钩子纪律】" in prompt
    # 规划钩子尾部（"听风者，入局"）必须作为硬性结尾内容注入
    assert "听风者，入局" in prompt
    assert "严禁提前完整引爆" in prompt
    assert "严禁在钩子之后再追加新事件" in prompt


def test_single_pass_prompt_contains_plan_and_style_disciplines():
    prompt = ChapterPromptBuilder("悬疑").build_user_prompt(**_single_pass_kwargs(PLAN))
    assert "【规划执行纪律】" in prompt
    assert "不得替换成其他机制" in prompt
    assert "严禁发明前文未建立的联络方式" in prompt
    # 剧情节点硬性 + 结果必须有手段（O11/O12）+ 推断链（O36）
    assert "人物结局、出场行为、配角任务与收益兑现" in prompt
    assert "必须有已建立的手段支撑" in prompt
    assert "先摆异常证据，再联想排除，最后落结论" in prompt
    assert "不得把结论写成预先准备好的宣告" in prompt
    assert "不得越出既有规则半径" in prompt
    # 字数浮动区间（宁精勿凑）
    assert "2000～4000字" in prompt
    assert "【篇幅纪律】" in prompt
    # 信息载体分批揭示（O9）+ 同功能节拍去重（O13）+ 核心场景篇幅保底（O16）
    assert "不得一次性集中倾倒" in prompt
    assert "不得用多个场景重复表达" in prompt
    assert "核心体验场景" in prompt
    assert "不得压缩成结果概述或技术说明" in prompt
    # 设定功能扩张须有来源（O18）
    assert "功能扩张" in prompt
    assert "无限糖豆" in prompt
    # 能力执行主体与边界（O25）+ 关键信息前置铺垫（O26）
    assert "能力的执行主体" in prompt
    assert "不得让能力来源在" in prompt
    assert "至少两处铺垫" in prompt
    # 爽点阻力/代价 + 主角主动博弈（O27）
    assert "阻力、反复或代价" in prompt
    assert "顺滑兑现会浪费爽点蓄力" in prompt
    assert "不得全程被动挨打或纯旁观" in prompt
    # 插叙纪律（O29：紧迫场景中禁止整段回忆）
    assert "不得插入整段回忆" in prompt
    assert "不得用回忆稀释紧迫情绪" in prompt
    # O30 情报对话推理参与 + O31 物证来源注明 + O34 禁说教 + O35 钩子变数
    assert "不得写成主角单方面听讲" in prompt
    assert "情报→联想→下一步" in prompt
    assert "不得让读者无法分辨新旧" in prompt
    assert "排比说教或口号式点题" in prompt
    assert "不得只是“按既定思路执行”的复述式收尾" in prompt


def test_single_pass_prompt_contains_emotional_anchor_discipline():
    prompt = ChapterPromptBuilder("悬疑").build_user_prompt(**_single_pass_kwargs(PLAN))
    assert "【情感锚点要求】" in prompt
    assert "身体反应、记忆闪回或习惯性小动作" in prompt
    assert "不得直接跳切" in prompt
    # 前章钩子过渡信号（O10）+ 场景切换伏笔/配角承接（O17）+ 危机跨章桥接（O20）
    assert "不得无声搁置" in prompt
    assert "不得静默丢弃" in prompt
    assert "未解除的即时危机" in prompt
    assert "不得直接跳到危机解除之后" in prompt
    # 信任过程 + 反派层次（O19）+ 具名配角落地（O22）+ 并行冲突线承接（O17 扩展）
    # + 状态回指须有前文对应（O23）+ 关系升温须有基础（O24）
    assert "不得首次见面即全盘托出" in prompt
    assert "不得瞬间崩溃" in prompt
    assert "不得以无名角色替代" in prompt
    assert "并行冲突线" in prompt
    assert "不得凭规划设定直接引用" in prompt
    assert "不得凭空跃迁" in prompt
    # 关键抉择心理拉锯（O28）
    assert "完整拉锯" in prompt
    assert "不得一句“把心一横”直接跳到行动结果" in prompt
    # O33 双重冲击缓冲 + O32 幽灵细节
    assert "不得连环轰炸" in prompt
    assert "凭空消失" in prompt
    # 高压独白碎片化（O21，文风禁令）
    system_prompt = ChapterPromptBuilder("悬疑").build_system_prompt()
    assert "高压情境" in system_prompt
    assert "逐条列举想说的话或分析要点" in system_prompt


def test_single_pass_prompt_without_plan_has_no_hook_discipline():
    prompt = ChapterPromptBuilder("悬疑").build_user_prompt(**_single_pass_kwargs(""))
    assert "【结尾钩子纪律】" not in prompt


def test_system_prompt_contains_style_bans():
    system_prompt = ChapterPromptBuilder("修仙").build_system_prompt()
    assert "【文风禁令】" in system_prompt
    assert "不是……而是……" in system_prompt
    assert "分点式" in system_prompt
    # 模板化过渡句禁令（O8）+ 生理反应限次（O14）
    assert "模板化过渡句" in system_prompt
    assert "生理反应" in system_prompt


def test_chapter_planning_prompt_contains_beat_exclusivity():
    from app.services.prompts.stages.chapter_planning import ChapterPlanningPrompts

    template = ChapterPlanningPrompts.get_user_prompt_template()
    # 关键事件功能互斥 + 重要结果注明手段（O15）+ 危机闭合首事件 + 常驻任务推进（P4）
    # + 具名配角进关键事件（P5）+ 禁止规则扩容（P6）+ 人物状态一致（P7）+ 配角线轮转（P8）
    assert "功能互斥" in template
    assert "注明其达成手段" in template
    assert "列为首个关键事件" in template
    assert "不得无声跳过" in template
    assert "必须同时列入关键事件" in template
    assert "不得临时扩容既有规则" in template
    assert "不得安排与其状态冲突的行动" in template
    assert "不得长期悬置" in template
    # 章节定位与实质内容匹配（P9：空间转移/阵营变更不构成"关键转折"）
    assert '不足以支撑"关键转折"定位' in template
    assert '定位为"普通推进"或"伏笔回收"' in template
    # P10 跨章身体状态延续 + P11 大纲节奏保护 + P12 抉择兑现 + P13 才智型脱身
    # + P14 前章钩子/威胁人物呼应
    assert "不得无声恢复满状态" in template
    assert "不得提前完整引爆" in template
    assert "不得用纯逃亡、跳过或时间跳跃回避选择" in template
    assert "才智型手段" in template
    assert "不得无声消失" in template


def test_revision_system_prompt_contains_style_and_rewrite_discipline():
    from app.services.prompts.workflow_runtime import get_iteration_revision_system_prompt

    prompt = get_iteration_revision_system_prompt()
    # R1：修订侧镜像纪律（分点式禁令直接打"第一息…第二息"列条式清算）
    assert "【修订文风与情感纪律】" in prompt
    assert "第一息…第二息" in prompt
    assert "生理反应" in prompt
    assert "不得直接跳切" in prompt
    # R2：重写类必改须整段重写
    assert "必须整段重写相关段落" in prompt
    assert "不得只插入单句证据应付" in prompt
    # R1 高压独白镜像（O21）+ R4 补写防退化 + R5 情绪单点聚焦
    assert "逐条列举想说的话或分析要点" in prompt
    assert "不得扩写成条理化技术分析" in prompt
    assert "不得引入新的节奏拖沓" in prompt
    assert "单点聚焦" in prompt
    assert "不得在同一段叠加多重情绪" in prompt
    # R6 补写净增量控制：口径已从“以删定补、不得变长”改为“局部润色三句内 + 结构性重写不受限”，
    # 防止为了控篇幅而削减本应整段重写兑现的因果/情绪过程
    assert "每处补写以三句内为宜" in prompt
    assert "控制净增量" in prompt
    assert "结构性重写不受三句限制" in prompt
    assert "不以堆砌细节替代推进" in prompt
    # R7：抉择拉锯/爽点过程类必改须整段重写
    assert "计算→动摇细节→落定带代价" in prompt
    assert "不得只补一句心理描写应付" in prompt


def test_revision_user_prompt_clean_and_complete():
    """改稿用户提示词完整性契约：无乱码残留、修订要求 1-9 条齐全（曾发生编码损坏）。"""
    prompt = build_iteration_revision_user_prompt(
        chapter_number=3,
        chapter_content="正文内容。",
        chapter_plan="规划",
        review_text="评审意见",
        recent_chapter_assets_summary="",
        iteration_plan="",
        revision_mode_hint="",
        repair_hints="",
    )
    # 无 latin-1 区间乱码字符
    assert not any(0x80 <= ord(c) <= 0xFF for c in prompt)
    # 修订要求九条齐全（第 7 条曾因编码损坏丢失）
    assert "如果原稿已有可用亮点" in prompt
    assert "只保留一条叙事" in prompt
    assert "两遍各留一点" in prompt


def test_review_rubric_calibration_and_discipline():
    """评审校准契约：8 分档锚点 + 问题栏允许写"无" + 评审低温。"""
    from app.services.prompts.workflow_runtime import STANDARD_CHAPTER_REVIEW_RUBRIC

    assert "8-8.5分" in STANDARD_CHAPTER_REVIEW_RUBRIC
    assert "无任何【必改】项；仅存在【建议】级小瑕疵" in STANDARD_CHAPTER_REVIEW_RUBRIC
    assert "不得高于7.5分" in STANDARD_CHAPTER_REVIEW_RUBRIC
    assert "不得反向压低综合分" in STANDARD_CHAPTER_REVIEW_RUBRIC

    from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts

    system_prompt = GenreAdaptiveReviewPrompts.get_review_system_prompt("悬疑")
    assert "## 评审纪律" in system_prompt
    assert "确无问题时" in system_prompt
    assert "不得虚构原文细节" in system_prompt
    user_prompt = GenreAdaptiveReviewPrompts.get_review_user_prompt(
        chapter_number=1, chapter_plan="规划", chapter_content="正文", genre="悬疑"
    )
    assert '确无问题写"无"' in user_prompt


def test_calibrate_review_score_to_rubric():
    """评分锚点程序化校准：零必改低分上调、带必改高分下调、合规分数不动。"""
    from app.services.prompts.narrative_quality import calibrate_review_score_to_rubric

    # 病例：六维全"无"+零失败码+仅建议级意见，却给 7 分（万毒 ch12 实测）
    clean_low = """## 📊 网文质量评审报告

**综合评分**：7/10分

### 1. 爽点效果 ⭐⭐⭐⭐
- 问题：无

### 6.1 连续性专项检查 ⭐⭐⭐⭐
- 问题：无

### 失败码清单
无

### 🔧 具体修改建议
1. 【建议】补充细节。
2. 【可选】调整措辞。
"""
    calibrated = calibrate_review_score_to_rubric(clean_low)
    assert "8/10分" in calibrated
    assert "原评 7 分" in calibrated

    # 病例：有必改项却给 8.5 分 → 下调至 7.5
    must_fix_high = """**综合评分**：8.5/10分

### 失败码清单
```
LOGIC_BREAK|HIGH|因果链断裂
```

### 🔧 具体修改建议
1. 【必改】重写结尾。
"""
    calibrated2 = calibrate_review_score_to_rubric(must_fix_high)
    assert "7.5/10分" in calibrated2
    assert "原评 8.5 分" in calibrated2

    # 合规：有 MED 码+7 分（建议级集中）→ 不动
    legit = """**综合评分**：7/10分

### 失败码清单
```
EMOTION_FLAT|MED|情感层次偏薄
```

### 🔧 具体修改建议
1. 【建议】补情感细节。
"""
    assert calibrate_review_score_to_rubric(legit) == legit

    # 合规：无必改+8.5 分 → 不动
    legit2 = clean_low.replace("7/10分", "8.5/10分")
    assert calibrate_review_score_to_rubric(legit2) == legit2

    # 无评分行 → 原样返回
    assert calibrate_review_score_to_rubric("纯文本无评分") == "纯文本无评分"


def test_narrative_debts_sorted_newest_first_within_priority():
    """叙事债务排序契约：高优先级内新债在前（旧债曾挤占前4名截断活跃常驻目标）。"""
    from app.services.narrative_state_extractor import format_narrative_state_section

    review_meta = {
        "narrative_state_v1": {
            "chapters": {"8": {"character_changes": []}},
            "open_debts": [
                {"content": "旧债A(ch3)", "priority": "high", "since_chapter": 3},
                {"content": "旧债B(ch4)", "priority": "high", "since_chapter": 4},
                {"content": "活跃目标(ch6)", "priority": "high", "since_chapter": 6},
                {"content": "低优债(ch7)", "priority": "normal", "since_chapter": 7},
            ],
        }
    }
    section = format_narrative_state_section(review_meta, 9)
    assert section.index("活跃目标(ch6)") < section.index("旧债A(ch3)")
    assert section.index("旧债B(ch4)") < section.index("旧债A(ch3)")
    # 低优先级债务排在全部高优先级之后
    assert section.index("低优债(ch7)") > section.index("旧债A(ch3)")


def test_is_likely_truncated_chapter_heuristic():
    """截断守卫启发式：以非句末标点收尾视为疑似截断（如'离她二十'）。"""
    from app.api.v1.workflow.routes_chapter import _is_likely_truncated_chapter

    body = "他推开门。夜风灌进来。" * 30
    # 正常句末标点收尾 → 不截断
    assert not _is_likely_truncated_chapter(body + "他刚走不远。")
    assert not _is_likely_truncated_chapter(body + "那第四起，会在什么时候？")
    assert not _is_likely_truncated_chapter(body + "像一只眼睛，正在缓缓睁开。")
    # 引号/括号收口 → 不截断
    assert not _is_likely_truncated_chapter(body + "他说完便走了。")
    # 截断（苏念慈章实际病例）→ 命中
    assert _is_likely_truncated_chapter(body + "她死死盯着那道身影，离她二十")
    assert _is_likely_truncated_chapter(body + "他猛地转身，却发现")
    # 空稿/极短稿不在此启发式管辖
    assert not _is_likely_truncated_chapter("")
    assert not _is_likely_truncated_chapter("短文本")


def test_truncation_guard_wiring_in_generate_next_chapter():
    """截断守卫接线契约：初稿与每轮改稿生成后均检查，命中即静默重试一次。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "workflow" / "routes_chapter.py").read_text(
        encoding="utf-8"
    )
    # 初稿守卫 + 改稿守卫
    assert "章节初稿疑似截断" in src
    assert "轮改稿疑似截断" in src
    # 静默重试不向前端重复推送流式块
    assert "_silent_retry_chunk" in src
    # 降级路径：重试失败/仍截断保留原稿
    assert "保留原初稿进入后续流程" in src
    assert "保留原改稿" in src


def test_editorial_review_wiring_in_generate_next_chapter():
    """终稿编辑评审接线契约：仅迭代循环正常执行后触发，失败降级不阻断产出。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "workflow" / "routes_chapter.py").read_text(
        encoding="utf-8"
    )
    # 循环正常完成才置位（异常/跳过路径不触发）
    assert "iteration_loop_ran = False" in src
    assert "iteration_loop_ran = True" in src
    # 终稿编辑评审块存在且受标志守卫，评审对象是 final_version
    assert "if iteration_loop_ran and final_version" in src
    assert "终稿编辑评审" in src
    assert "chapter_draft=final_version" in src
    # 失败降级：保留循环复评，不抛出（展示增强不得让已生成章节整体失败）
    assert "保留循环复评作为终稿评审" in src
