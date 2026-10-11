"""工作流运行时提示词组装器。

集中管理主工作流中仍需动态拼接的提示词，避免在路由层散落硬编码大段字符串。
"""

from typing import Tuple

from app.services.prompts.manager import prompt_manager
from app.services.prompts.narrative_quality import FAILURE_CODE_OUTPUT_SPEC
from app.services.prompts.stages.structure_design import StructureDesignPrompts
from app.services.prompts.stages.world_building import (
    CharacterDesignPrompts,
    WorldBuildingPrompts,
    get_genre_character_fields,
)


def _join_prompt_sections(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


STANDARD_CHAPTER_REVIEW_RUBRIC = """## 网文6维度评审体系（统一评分口径）
1. 爽点效果（权重25%）
2. 节奏把控（权重20%）
3. 钩子效果（权重15%）
4. 代入感（权重15%）
5. 文笔流畅度（权重10%）
6. 内容一致性（权重15%）

综合评分必须按以上六个维度及权重裁决。初评、复评、最终验收都使用同一套评分口径，不能把“是否执行修改”混入综合评分。

## 综合评分分档锚点（防止评分趋中与通胀）
- 9-10分：可直接发布水平。六维全部达标，且至少两个维度突出（如爽点兑现有力且钩子强烈），无任何【必改】项。
- 8-8.5分：六维全部达标，无任何【必改】项；仅存在【建议】级小瑕疵，不影响任何维度的成立。
- 7-7.5分：整体成立但有明确短板。存在1个【必改】项（可通过局部修改解决），或多个【建议】级问题集中拖累阅读体验，但不影响主线框架与核心推进。
- 5-6分：框架勉强成立但执行乏力。存在结构性问题（核心推进未发生、钩子断裂、大段注水）或2个以上【必改】项，需要实质性重写部分段落。
- 3-4分：不达标。存在人设漂移、逻辑硬伤或整章原地踏步，需要整体重写。
- 评分纪律：评分只取决于实际列出的问题的有无与严重度——某维度"问题"栏为"无"时不得反向压低综合分，也不得因"找不到明显问题但感觉不够惊艳"而扣分；只要问题列表存在【必改】项，综合评分不得高于7.5分；评分必须与所列问题的严重度一致。"""


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


def build_first_chapter_review_prompts(
    *, chapter_draft: str, chapter_plan: str = "", world_setting: str = "", characters: str = "",
) -> Tuple[str, str]:
    base_prompt = prompt_manager.get_agent_prompt("quality_reviewer").strip()
    system_prompt = _join_prompt_sections(
        base_prompt,
        f"""请使用【网文6维度评审体系】对第一章内容进行评审。

{STANDARD_CHAPTER_REVIEW_RUBRIC}

请给出结构化评审结果，不要省略综合评分。
- 你当前只做评审，不要直接改写正文。
- 反馈必须可执行，避免“增强张力”“优化文笔”这类空泛建议。""",
    )
    user_prompt = f"""请评审以下第一章内容：

【本章规划】
{chapter_plan or '（未提供，不得自行补造规划要求）'}

【世界观约束】
{world_setting or '（未提供，只检查正文内部一致性）'}

【人物设定】
{characters or '（未提供，不得假设前文人设）'}

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

{FAILURE_CODE_OUTPUT_SPEC}

必改项按 R0-MUST-1、R0-MUST-2 编号，每项写明位置或短引文、影响、修复动作、验收条件；没有必改项时明确写“无”，不要复制示例占位符。
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
    revision_mode_hint: str = "",
    repair_hints: str = "",
    chapter_plan: str = "",
    current_chapter_outline: str = "",
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
    outline_block = current_chapter_outline.strip() if current_chapter_outline else "（未提供本章精确细纲，保情节时以本章规划为准）"
    plan_block = chapter_plan.strip() if chapter_plan else "（未提供本章创作规划）"
    iteration_plan_block = (
        iteration_plan
        if iteration_plan
        else "（本轮未提供单独的协调计划，请直接依据评审意见中的高优先级问题修订。）"
    )
    revision_mode_block = (
        f"【修订模式指令】（由失败码路由自动判定，必须遵守）\n{revision_mode_hint}"
        if revision_mode_hint
        else ""
    )
    repair_hints_block = (
        f"【失败码机制修复指引】（按失败类型对应的模型机制修复，优先于个人经验的改法）\n{repair_hints}"
        if repair_hints
        else ""
    )
    return f"""{intro}

【当前章节内容】
{chapter_content}

【本章精确细纲】（保情节以本章细纲和本章规划为准，不是以初稿注水桥段为准）
{outline_block}

【本章创作规划】
{plan_block}

【最近章节连续性资产】（必须承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

{review_section_title}
{review_text}

【本轮迭代协调计划】（优先执行“本轮必做项”）
{iteration_plan_block}

{revision_mode_block}

{repair_hints_block}

【修订要求】
1. 必须优先执行本轮迭代协调计划中的“本轮必做项”。
2. 必须逐条落实评审意见中的【必改】/R0-MUST 项，避免只修表面文笔。
3. 保情节以本章细纲和本章规划为准；初稿里被评审判定为注水、重播前章的桥段必须压缩或改写。
4. 【必改】要求删减时，删减优先、压缩优先，不得为了保篇幅而保留已被判定为注水的桥段。结构重复时允许大幅删减重复线，不得因字数回滚而保留第二遍流程。
5. 优先延续最近章节连续性资产中的未完成冲突、人物状态变化、结尾钩子与伏笔。
6. 不得删改细纲/规划中会影响后续章节衔接的关键细节。
7. 如果原稿已有可用亮点，修订时要保留并强化；但结构重复时必须先删掉重复线，只保留一条叙事，不得两遍各留一点。
8. 直接输出优化后的完整章节正文（第一行为章节标题），不要附加修订说明。
9. 改稿前必须在内部建立“评审要求执行核验表”，逐条核对 R0-MUST/Rn-MUST 或【必改】项；例如将初评第一条必改项视为 R0-MUST-1。不要输出核验表，但必须据此完成正文修订。

请立即输出优化后的章节："""


def get_iteration_revision_system_prompt() -> str:
    base_prompt = prompt_manager.get_agent_prompt("content_reviser").strip()
    return _join_prompt_sections(
        base_prompt,
        """你当前负责迭代优化阶段，请根据评审意见对章节内容进行优化修改。

优化要求：
1. 保情节以本章细纲和本章规划为准，而不是完整保留初稿所有桥段。
2. 改进语言表达，使文笔更加流畅。
3. 增强细节描写，提升画面感。
4. 优化对话内容，使其更符合人物性格。
5. 提升整体可读性和爽感。
6. 修正任何语病或不连贯之处。
7. 【必改】要求压缩注水或避免重播前章时，删减优先；不得为了保篇幅而保留已被判定为注水的桥段。
8. 如果提供了最近章节连续性资产，必须优先承接其中的场景目标、冲突推进、人物状态、结尾钩子与伏笔。
9. 如果提供了协调计划，优先落实其中的“本轮必做项”和“禁止改动项”。
10. 涉及情绪递进、境界差博弈、多方冲突、清算过程等必改项，必须整段重写相关段落来兑现——含逐拍递进（如“反击→被压制→再挣扎→崩溃”的层级）与同步情绪渲染；不得只插入单句证据应付。
11. 评审报告《一致意见》（多模型交叉印证）点名的每条问题与【必改】同等执行，不得因未带【必改】标签而跳过；只有《最终修改建议》中标为【可选】的条目才允许权衡取舍。

【修订文风与情感纪律】（与初稿同等约束；修订补写、重写的段落同样不得违反）
- 禁止分点式推进：倒计时、清算、对峙、异变等序列段落必须写成带情绪起伏的连续叙述，不得“第一息…第二息…”式列条；高压情境下的内心独白不得逐条列举想说的话或分析要点，须碎片化、身体化；旁观者目睹冲击性场面需同步给出反应细节。
- 同一生理反应（心猛地一沉、呼吸一滞、喉结滚动等）全章最多出现 2 次；紧张、恐惧、崩溃需变换表现形式。
- “不是……而是……”对比句式全章最多 2 次；每段核心比喻不超过 1 个；禁用“她强迫自己冷静下来”“重新将注意力集中”一类模板化过渡句。
- 人物在关键情感时刻（悲恸、决绝、崩溃、觉悟）必须有具体的身体反应、记忆闪回或习惯性小动作落地；情感状态切换不得直接跳切。
- 修订新增或重写的文字必须与原文语域一致，不得比原稿更粗糙。
- 不得新增前文与规划之外的事实来应付必改项（新造回忆、新人物台词、物品去向、时间点）；需要因果支撑时改按现有可溯源素材重写，宁可删去依赖该事实的表述，不得用编造细节圆场。
- 补写关键动作、触碰或对峙场景时，须以感官冲击与动作细节呈现，不得扩写成条理化技术分析或过度理性的认知过程；补写内容不得引入新的节奏拖沓、重复或逻辑问题。
- 补写情绪反应须单点聚焦：一种主导情绪配一笔身体反应即可，不得在同一段叠加多重情绪或层层修饰，避免情绪失焦。
- 仅局部润色时，每处补写以三句内为宜，并删减冗余内容控制净增量；结构性重写不受三句限制，须按必改项完整兑现因果和情绪过程。对已被点名拖沓风险的段落，优先重写或删减，不以堆砌细节替代推进。
- 评审指出关键抉择拉锯不足、爽点顺滑无力时，修订须整段重写兑现“计算→动摇细节→落定带代价”的抉择层次与“阻力/反复/代价”的爽点过程；不得只补一句心理描写应付。

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
    review_text: str = "",
    iteration_plan: str = "",
    recent_chapter_assets_summary: str = "",
    previous_content: str = "",
) -> str:
    continuity_block = (
        recent_chapter_assets_summary
        if recent_chapter_assets_summary
        else "（最近章节没有可用的结构化连续性资产）"
    )
    previous_block = (
        f"""
【修订前正文】（本轮改稿基线，仅用于核对修订稿新增了哪些事实，不参与评分）
{previous_content}
"""
        if previous_content
        else ""
    )
    # 溯源核验只在拿到改稿基线时生效，没有上一版正文就不得要求模型无据比对
    traceability_rule = (
        "\n7. 新增事实溯源（一票否决）：必须把修订稿新增的关键事实（人物此前采取的行动、"
        "物品来源与去向、时间点、他人台词、现场细节）逐条与修订前正文、本章规划、"
        "最近章节连续性资产比对；查无出处即判为编造，在核验表补一行「新增事实溯源 | 未执行 | "
        "无出处事实原文 | 前文与规划均无出处」，并输出 `NEW_FACT_UNSOURCED|HIGH|<无出处事实原文>`；"
        "靠该事实才成立的必改项不得判为“已执行”，结论不得为“通过”。"
        if previous_content
        else ""
    )
    chapter_plan_block = chapter_plan if chapter_plan else "（未提供章节规划，请根据当前正文自行判断达标度。）"
    review_block = review_text if review_text else "（未提供上一轮评审要求，仅按统一评分口径复评。）"
    iteration_plan_block = iteration_plan if iteration_plan else "（未提供本轮迭代计划。）"
    return f"""请复评以下第{chapter_number}章：

{STANDARD_CHAPTER_REVIEW_RUBRIC}

【章节规划】
{chapter_plan_block}

【最近章节连续性资产】（重点检查是否承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

【上一轮评审要求 / 历史评审要求】（用于逐条验收，不得替代统一评分口径）
{review_block}

【本轮迭代协调计划】（用于逐条验收）
{iteration_plan_block}
{previous_block}
【章节内容】
{chapter_content}

【复评要求】
1. 必须先按统一6维度评分口径重新评分，综合评分不得因“是否执行修改”单独加减分。
2. 必须逐条核验上一轮评审要求和本轮必做项是否已执行；上一轮报告《一致意见》段点名的跨模型印证问题同样逐条验收，不得只看带【必改】标签的条目。
3. 如果未达标，只保留最影响通过的3条剩余问题。
4. 明确给出“通过 / 继续修改 / 风险较高”中的唯一结论；存在必改项部分执行、未执行或 HIGH 失败码时不得判为通过。
5. 核验表沿用原要求ID，已执行必须引用当前正文证据，不得引用计划承诺；缺少证据时不得标为已执行。
6. 失败码清单仅列当前稿仍存在的问题；已解决项留在核验表，无剩余问题写“无”，不要照抄历史失败码。{traceability_rule}

{FAILURE_CODE_OUTPUT_SPEC}

【输出格式】
综合评分：X/10分
六维评分：
- 爽点效果：X/10
- 节奏把控：X/10
- 钩子效果：X/10
- 代入感：X/10
- 文笔流畅度：X/10
- 内容一致性：X/10

## 评审要求执行核验表
| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |
|---|---|---|---|

## 失败码清单
失败码|严重度|位置或证据
（逐行列出，无问题时输出：无）

## 剩余关键问题
1. ...
2. ...
3. ...

结论：通过 / 继续修改 / 风险较高"""


def get_iteration_loop_review_system_prompt() -> str:
    base_prompt = prompt_manager.get_agent_prompt("final_reviewer").strip()
    return _join_prompt_sections(
        base_prompt,
        f"""请使用统一网文6维度评分口径对上面的章节进行评审，并特别检查它是否承接了最近章节连续性资产中的场景目标、冲突推进、人物状态、结尾钩子与伏笔。

{STANDARD_CHAPTER_REVIEW_RUBRIC}

输出要求：
1. 必须包含一行：综合评分：X/10分
2. 必须输出六维评分，且综合评分使用同一套权重口径
3. 必须输出“评审要求执行核验表”，逐条核验上一轮评审要求和本轮必做项
4. 必须包含一行：结论：通过 / 继续修改 / 风险较高
5. 给出最重要的3条剩余问题或修改建议
6. 如已达标，可用1-2条说明本轮已解决的关键点
7. 不要输出与评分和执行核验无关的冗余说明""",
    )
