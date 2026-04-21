"""工作流运行时提示词组装器。

集中管理主工作流中仍需动态拼接的提示词，避免在路由层散落硬编码大段字符串。
"""

from typing import Tuple

from app.services.prompts.manager import prompt_manager
from app.services.prompts.stages.structure_design import StructureDesignPrompts
from app.services.prompts.stages.world_building import (
    CharacterDesignPrompts,
    WorldBuildingPrompts,
    get_genre_character_fields,
)


def _join_prompt_sections(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


_DEFAULT_CONCEPT_HARD_CONSTRAINTS = """- 除非用户明确要求，否则不要使用“林尘”作为主角名。
- 除非用户明确要求，不要把世界命名为“九寰界 / 九寰界域”。
- 除非用户明确要求，不要直接复用“飞升骗局 / 高维收割 / 天外监察者 / 养蛊游戏”作为终局真相模板。"""


_DEFAULT_CONCEPT_SOFT_AVOIDANCE_RULES = """- 对“宗门杂役 / 杂役弟子 / 废灵根 / 无灵根少年濒死觉醒”这类标准开局优先避免直接照搬，只有当它确实服务于本项目的差异化卖点时再使用。
- 对“吞噬灵根 / 逆修系统 / 反向修炼系统 / 越被羞辱越变强”这类高频机制优先避免直接套用；如果采用，必须同时给出明确的反转或结构创新。
- 对“九大仙宗 / 九大仙域 / 上中下三界”这类常见世界骨架优先避免整套复刻；如果沿用局部元素，必须提供新的规则压力或势力关系。
- 软避重的目标是减少套路回流，不是把方案写得保守平淡；若某个高频元素能显著增强卖点，可在做出创新改写后谨慎使用。"""


def _build_concept_novelty_guardrails(
    *,
    recent_project_avoidance: str = "",
    recent_project_signatures: str = "",
) -> str:
    return _join_prompt_sections(
        f"""【硬约束】
{_DEFAULT_CONCEPT_HARD_CONSTRAINTS}""",
        f"""【软避重提醒】
{recent_project_avoidance or "（暂无近期项目避重清单，可优先从主角身份、核心机制、世界骨架上主动做区分。）"}
{_DEFAULT_CONCEPT_SOFT_AVOIDANCE_RULES}""",
        f"""【生成后自检】
1. 生成完成后，再检查方案与近期项目在“主角名、起点身份、核心能力、世界名称、势力骨架、终局真相”六项中的重合度。
2. 如果重合达到 3 项及以上，不要直接输出初稿，请先在内部重想一个更有区分度的版本。
3. 自检的目标是避免同质化，但不能以牺牲爽点强度、冲突张力和可读性为代价。

{recent_project_signatures or "（暂无近期项目关键避重锚点，可直接围绕当前项目卖点展开。）"}""",
    )


def _build_concept_execution_preferences(*, has_variation_profile: bool) -> str:
    lines = ["【执行偏好】"]
    if has_variation_profile:
        lines.append("- 在不违背用户需求的前提下，优先把上述“项目级差异化锚点”落实到主角驱动、世界机制、核心冲突中。")
    lines.append("- 先做出足够强的卖点、冲突和情绪抓手，再处理避重细节；不要为了规避套路而把方案写得过于保守。")
    return "\n".join(lines)


def _build_concept_output_requirements(*, compatibility_note: str = "") -> str:
    compatibility_line = (
        f"3. {compatibility_note}"
        if compatibility_note
        else ""
    )
    return _join_prompt_sections(
        f"""【总体要求】
1. 先完成“故事概念”六段标准输出，再给出一个与之匹配的高度概括版世界观（可简略）。
2. 保持网文向：强调爽点潜力、冲突强度和持续升级空间。
{compatibility_line}""",
        """【输出格式】
一、先生成【故事概念】，严格按以下六个部分输出（用 Markdown 粗体标记小标题）：
1. **一句话卖点（Logline）**
2. **日志标题（短标题）**
3. **概念摘要（80-150字）**
4. **题材与流派（主题材/子流派）**
5. **核心标签（3-6个）**
6. **核心冲突与情感基调**

二、再生成【世界观设定】（简略版）：
- 用 100-200 字给出世界背景、基本规则、主要势力。

请严格按照上述顺序与小标题输出，不要添加其他额外说明。""",
    )


def build_streaming_concept_prompts(
    *,
    project_title: str,
    project_genre: str,
    requirement: str,
    recent_project_avoidance: str = "",
    recent_project_signatures: str = "",
    regenerate_hint: str = "",
    variation_profile: str = "",
    compatibility_note: str = "",
) -> Tuple[str, str]:
    base_prompt = prompt_manager.get_agent_prompt("creative_director").strip()
    user_requirement = requirement or "暂无"
    system_prompt = _join_prompt_sections(
        base_prompt,
        "你当前负责概念开发阶段，需要为一个新项目生成【故事概念】和初步【世界观设定】。",
        """【阶段边界】
- 你当前只负责概念底盘，不负责分配 Agent、描述流程日志或模拟后续协作。
- 优先把卖点、核心冲突、情绪抓手、持续升级空间讲清楚，再处理包装措辞。
- 不要提前代写人物卡、卷纲或章节正文，只提供足够强且可扩展的概念。""",
        regenerate_hint,
        f"""【已知信息】
- 项目题目：{project_title}
- 题材类型：{project_genre}
- 用户提供的初始想法（如有）：{user_requirement}""",
        variation_profile,
        _build_concept_execution_preferences(has_variation_profile=bool(variation_profile.strip())),
        _build_concept_novelty_guardrails(
            recent_project_avoidance=recent_project_avoidance,
            recent_project_signatures=recent_project_signatures,
        ),
        _build_concept_output_requirements(compatibility_note=compatibility_note),
    )
    user_prompt = f"""请为以下项目生成故事概念：

【项目题目】：{project_title}
【题材类型】：{project_genre}
【用户初始想法】：{user_requirement}"""
    return system_prompt, user_prompt


def build_streaming_world_prompts(*, concept_text: str) -> Tuple[str, str]:
    base_prompt = WorldBuildingPrompts.get_system_prompt()
    system_prompt = _join_prompt_sections(
        base_prompt,
        """你当前负责概念阶段的世界观扩展任务。

【要求】
1. 基于已有故事概念中的设定线索进行扩展。
2. 保持与故事概念的一致性，不要引入破坏主冲突的新规则。
3. 输出详细的世界观设定，包括世界背景、基本规则、主要势力等。
4. 只输出世界观正文，不要附加解释。""",
    )
    user_prompt = f"""请基于以下故事概念生成世界观设定：

{concept_text}"""
    return system_prompt, user_prompt


def build_runtime_world_prompts(
    *,
    genre: str,
    concept_text: str,
    requirement: str = "",
    genre_constraint: str = "",
    genre_extra_sections: str = "",
) -> Tuple[str, str]:
    system_prompt = _join_prompt_sections(
        WorldBuildingPrompts.get_system_prompt(genre or ""),
        f"当前题材聚焦：{genre}" if genre else "",
        """【本阶段补充要求】
- 世界观必须先服务当前主线和卷一冲突，再谈远期扩张。
- 至少给出一个主角可以撬动的漏洞、盲区或利益裂缝。
- 不要引入会稀释主角驱动力或破坏既有核心冲突的万能设定。""",
    )
    base_user_prompt = WorldBuildingPrompts.get_world_prompt(
        genre=genre or "通用题材",
        requirement=requirement or "暂无特别要求",
        genre_constraint=genre_constraint,
        genre_extra_sections=genre_extra_sections,
    )
    user_prompt = _join_prompt_sections(
        base_user_prompt,
        f"""【故事概念】
{concept_text}""",
    )
    return system_prompt, user_prompt


def build_streaming_character_prompts(
    *,
    project_genre: str,
    requirement: str,
    concept_text: str,
    world_setting_text: str,
) -> Tuple[str, str]:
    genre_extra_fields = get_genre_character_fields(project_genre or "")
    system_prompt = CharacterDesignPrompts.get_system_prompt(project_genre or "")
    base_user_prompt = CharacterDesignPrompts.get_character_prompt(
        requirement=requirement or "暂无特别要求",
        genre_extra_fields=genre_extra_fields,
    )
    user_prompt = f"""{base_user_prompt}

【故事概念】
{concept_text}

【世界观设定】
{world_setting_text}"""
    return system_prompt, user_prompt


def build_runtime_structure_prompts(
    *,
    genre: str,
    genre_rhythm_guide: str = "",
) -> Tuple[str, str]:
    system_prompt = _join_prompt_sections(
        prompt_manager.get_agent_prompt("plot_architect").strip(),
        f"当前题材聚焦：{genre}" if genre else "",
        """【阶段边界】
- 你当前只负责卷结构与章节推进设计，不要写正文，不要扩写人物卡。
- 输出必须服务长篇网文连载：卷一可落地、卷尾有钩子、后续有升级空间。
- 重点设计可拆成章节的事件节点，而不是抽象主题概括。""",
    )
    user_prompt = StructureDesignPrompts.get_structure_prompt(
        genre_rhythm_guide=genre_rhythm_guide,
        genre=genre or "通用",
    )
    return system_prompt, user_prompt


def build_streaming_structure_prompts(
    *,
    concept_text: str,
    world_setting: str,
    characters: str,
    requirement: str,
) -> Tuple[str, str]:
    base_prompt = prompt_manager.get_agent_prompt("plot_architect").strip()
    system_prompt = _join_prompt_sections(
        base_prompt,
        """你当前负责结构设计阶段，需要基于故事概念、世界观和人物设定，产出可直接用于章节创作的情节大纲。

【要求】
1. 保持与前期设定的一致性。
2. 设计清晰的主线冲突、升级路线和章节推进关系。
3. 为第一章提供具体的落地指引。
4. 每个关键节点都尽量写清“发生什么 / 冲突指向什么 / 爽点或反转是什么 / 为什么值得拆章”。
5. 输出必须包含以下部分：

## 一、主线情节
- 描述主要情节线索和发展脉络

## 二、第一章大纲
- 章节标题建议
- 开场设定
- 主要情节
- 关键冲突
- 章节结尾

## 三、后续章节规划（可选）
- 概述后续几章的大致发展方向""",
    )
    user_prompt = f"""请基于以下设定生成情节大纲：

【故事概念】
{concept_text}

【世界观设定】
{world_setting}

【人物设定】
{characters}

【用户需求】
{requirement}"""
    return system_prompt, user_prompt


def build_first_chapter_review_prompts(*, chapter_draft: str) -> Tuple[str, str]:
    base_prompt = prompt_manager.get_agent_prompt("quality_reviewer").strip()
    system_prompt = _join_prompt_sections(
        base_prompt,
        """请使用【网文6维度评审体系】对第一章内容进行评审。

## 网文6维度评审体系
1. 爽点效果（权重25%）
2. 节奏把控（权重20%）
3. 钩子效果（权重15%）
4. 代入感（权重15%）
5. 文笔流畅度（权重10%）
6. 内容一致性（权重15%）

请给出结构化评审结果，不要省略综合评分。
- 你当前只做评审，不要直接改写正文。
- 反馈必须可执行，避免“增强张力”“优化文笔”这类空泛建议。""",
    )
    user_prompt = f"""请评审以下第一章内容：

【章节内容】
{chapter_draft}

---

【输出格式】
请使用以下格式输出评审报告：

## 网文质量评审报告

**综合评分**：X/10分

### 1. 爽点效果
- 评价：...
- 问题：...

### 2. 节奏把控
- 评价：...
- 问题：...

### 3. 钩子效果
- 开头评价：...
- 结尾评价：...
- 问题：...

### 4. 代入感
- 评价：...
- 问题：...

### 5. 文笔流畅度
- 评价：...
- 问题：...

### 6. 内容一致性
- 评价：...
- 问题：...

### 具体修改建议（按优先级排序）
1. 【必改】...
2. 【建议】...
3. 【可选】...

### 亮点
- ...

请严格按上述结构输出，不要额外写总论或寒暄。"""
    return system_prompt, user_prompt


def get_default_first_chapter_opening_and_ending() -> Tuple[Tuple[str, str, str], Tuple[str, str, str]]:
    opening_styles = {
        "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
    }
    ending_styles = {
        "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
    }
    return opening_styles["悬念开头"], ending_styles["悬念式"]


def build_first_chapter_iteration_prompts(
    *,
    chapter_draft: str,
    review_report: str,
) -> Tuple[str, str]:
    system_prompt = get_iteration_revision_system_prompt()
    user_prompt = build_iteration_revision_user_prompt(
        chapter_number=1,
        chapter_content=chapter_draft,
        review_text=review_report,
    )
    return system_prompt, user_prompt


def get_iteration_coordination_system_prompt() -> str:
    base_prompt = prompt_manager.get_agent_prompt("iteration_coordinator").strip()
    return _join_prompt_sections(
        base_prompt,
        """你当前负责迭代优化阶段的协调规划，不直接改写正文，而是先把评审意见整理为可执行的修订计划。

输出要求：
1. 必须输出结构化计划，至少包含“核心问题 / 优先级排序 / 本轮必做项 / 连续性承接点 / 禁止改动项”。
2. 本轮必做项必须是可直接执行的修改动作，按照优先级编号。
3. 如果多轮评审意见之间存在冲突，必须明确指出冲突并给出取舍原则。
4. 不要输出章节正文，只输出本轮协调计划。
5. 优先把“当前章一定要修”的问题和“绝对不能误改”的内容分开写清楚。""",
    )


def build_iteration_coordination_user_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    review_text: str,
    recent_chapter_assets_summary: str = "",
    include_history_hint: bool = False,
) -> str:
    base_prompt = prompt_manager.get_user_prompt(
        "iteration_coordinator_coordinate",
        variables={"feedback": review_text, "content": chapter_content},
    ).strip()
    continuity_block = (
        recent_chapter_assets_summary
        if recent_chapter_assets_summary
        else "（最近章节没有可用的结构化连续性资产）"
    )
    review_hint = (
        "以下评审意见已经包含多轮历史反馈，请优先提炼重复出现的问题与仍未解决的问题。"
        if include_history_hint
        else "请围绕当前评审意见生成本轮修订计划。"
    )
    return _join_prompt_sections(
        base_prompt,
        f"""当前目标章节：第{chapter_number}章

【最近章节连续性资产】（必须识别并承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

【补充要求】
{review_hint}
- 只围绕当前章节生成计划，不要扩展到整本书重构。
- 如果某条建议已经在当前稿中解决，应在内部判别后避免重复下达。

请严格按照以下结构输出：
## 核心问题
## 优先级排序
## 本轮必做项
## 连续性承接点
## 禁止改动项""",
    )


def build_iteration_revision_user_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    review_text: str,
    iteration_plan: str = "",
    recent_chapter_assets_summary: str = "",
    include_history_hint: bool = False,
) -> str:
    review_section_title = "【必须执行的所有评审意见（包含历史轮次）】" if include_history_hint else "【评审意见】"
    intro = (
        f"【重要提示】请严格按照以下所有评审意见逐条修订第{chapter_number}章，不要遗漏高优先级问题。"
        if include_history_hint
        else f"请根据以下要求优化第{chapter_number}章："
    )
    continuity_block = (
        recent_chapter_assets_summary
        if recent_chapter_assets_summary
        else "（最近章节没有可用的结构化连续性资产）"
    )
    iteration_plan_block = (
        iteration_plan
        if iteration_plan
        else "（本轮未提供单独的协调计划，请直接依据评审意见中的高优先级问题修订。）"
    )
    return f"""{intro}

【当前章节内容】
{chapter_content}

【最近章节连续性资产】（必须承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

{review_section_title}
{review_text}

【本轮迭代协调计划】（优先执行“本轮必做项”）
{iteration_plan_block}

【修订要求】
1. 必须优先执行本轮迭代协调计划中的“本轮必做项”。
2. 必须逐条落实评审意见中的高优先级问题，避免只修表面文笔。
3. 优先承接最近章节连续性资产中的未完成冲突、人物状态变化、结尾钩子与伏笔。
4. 不得删改会影响后续章节衔接的关键细节。
5. 如果原稿已有可用亮点，修订时要保留并强化，而不是全部推翻重写。
6. 成稿篇幅不得少于原稿字数的90%。
7. 直接输出优化后的完整章节正文（第一行为章节标题），不要附加修订说明。

请立即输出优化后的章节："""


def get_iteration_revision_system_prompt() -> str:
    base_prompt = prompt_manager.get_agent_prompt("content_reviser").strip()
    return _join_prompt_sections(
        base_prompt,
        """你当前负责迭代优化阶段，请根据评审意见对章节内容进行优化修改。

优化要求：
1. 保持原有故事框架和主要情节不变。
2. 改进语言表达，使文笔更加流畅。
3. 增强细节描写，提升画面感。
4. 优化对话内容，使其更符合人物性格。
5. 提升整体可读性和爽感。
6. 修正任何语病或不连贯之处。
7. 优化后的章节应完整保留原有情节发展，篇幅不应少于原稿字数的90%。
8. 如果提供了最近章节连续性资产，必须优先承接其中的场景目标、冲突推进、人物状态、结尾钩子与伏笔。
9. 如果提供了协调计划，优先落实其中的“本轮必做项”和“禁止改动项”。

【输出格式要求】
请直接输出优化后的章节内容，格式必须如下：

第X章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为“第X章 标题名称”。
- 如果原稿有章节标题则保留或优化，如果没有则根据内容新增一个。
- 不要包含任何评论、解释、优化说明等额外文字。
- 只输出：章节标题 + 章节正文内容。""",
    )


def build_iteration_loop_review_user_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    chapter_plan: str = "",
    recent_chapter_assets_summary: str = "",
) -> str:
    continuity_block = (
        recent_chapter_assets_summary
        if recent_chapter_assets_summary
        else "（最近章节没有可用的结构化连续性资产）"
    )
    chapter_plan_block = chapter_plan if chapter_plan else "（未提供章节规划，请根据当前正文自行判断达标度。）"
    return f"""请复评以下第{chapter_number}章：

【章节规划】
{chapter_plan_block}

【最近章节连续性资产】（重点检查是否承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

【章节内容】
{chapter_content}

【复评要求】
1. 先判断关键问题是否被解决，再评估整体是否达标。
2. 仍按网文6维度给出简洁但明确的结论。
3. 如果未达标，只保留最影响通过的3条问题。
4. 明确给出“通过 / 继续修改 / 风险较高”结论。"""


def get_iteration_loop_review_system_prompt() -> str:
    base_prompt = prompt_manager.get_agent_prompt("final_reviewer").strip()
    return _join_prompt_sections(
        base_prompt,
        """请使用网文6维度对上面的章节进行评审，并特别检查它是否承接了最近章节连续性资产中的场景目标、冲突推进、人物状态、结尾钩子与伏笔。

输出要求：
1. 必须包含一行：综合评分：X/10分
2. 必须包含一行：结论：通过 / 继续修改 / 风险较高
3. 给出最重要的3条剩余问题或修改建议
4. 如已达标，可用1-2条说明本轮已解决的关键点
5. 不要输出与评分无关的冗余说明""",
    )
