from typing import Any, Dict, List, Optional, Tuple

from .agent_coordinator import DEFAULT_GENRE_MODULE, GENRE_PROMPT_MODULES
from app.services.prompts.manager import prompt_manager
from app.services.prompts.narrative_quality import (
    format_prevention_block,
    match_prevention_cases,
)
from app.services.prompts.review_prompts import GENRE_REVIEW_MODULES
# 注意：统一在模块顶部导入；函数内禁止再就地 import 同名（会遮蔽整个函数作用域）
from app.services.chapter_structure_guard import extract_plan_hook_tail, extract_writable_plan


def _join_prompt_sections(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def extract_segment_tail(segment_content: str, max_chars: int = 300) -> str:
    """提取分段正文的末尾段落，供下一段提示词无缝衔接；正文为空时返回空串。"""
    text = str(segment_content or "").strip()
    if not text:
        return ""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    tail = paragraphs[-1] if paragraphs else ""
    return tail[-max_chars:]


class ChapterPromptBuilder:
    """章节创作提示词组装器。"""

    def __init__(self, genre: str = "") -> None:
        self.genre = genre or ""
        self.genre_module: Dict[str, Any] = GENRE_PROMPT_MODULES.get(
            self.genre,
            DEFAULT_GENRE_MODULE,
        )

    def build_system_prompt(self) -> str:
        """构建章节创作的 system prompt。"""

        genre_creation_guides = {
            "修仙": """
【修仙题材创作指导】
- 境界突破要有代价、征兆和规则反馈，不要只写“气势暴涨”
- 战斗要写清招式、博弈与风险，不要堆砌形容词
- 修炼与悟道通过身体、环境和因果变化落地
- 术语可以使用，但不要为了术语牺牲可读性
""",
            "玄幻": """
【玄幻题材创作指导】
- 设定要落到事件结果上，不要停留在名词展示
- 冲突重视攻防转换、资源消耗和局势反转
- 神器、秘法、血脉要带来具体收益与代价
- 场景切换时体现地域、阶层或规则差异
""",
            "都市": """
【都市题材创作指导】
- 商业、权力、人情往来要有可验证的策略细节
- 打脸、反制、谈判等场景要有铺垫、兑现和旁观反馈
- 资源、财富、关系网尽量具体，提升真实感
- 情感线穿插要自然，不要打断主线推进
""",
            "悬疑": """
【悬疑题材创作指导】
- 线索埋设要自然，不要用作者口吻硬提示
- 推理链条要闭环，信息递进要清晰
- 氛围依靠节奏、细节和留白建立
- 反转前必须有误导与伏笔支撑
""",
            "言情": """
【言情题材创作指导】
- 情绪推进通过动作、视线、停顿和误解化解落地
- 甜蜜互动和拉扯感都要服务人物设定
- 冲突不要只靠嘴硬，最好与身份、责任、选择绑定
- 情感推进要和剧情节点同步发生
""",
            "耽美": """
【耽美题材创作指导】
- 关系推进要自然，避免只剩人设标签互动
- 攻受互动必须符合既有人设与权力结构
- 边界突破要写出情绪、迟疑和代价
- 注意平台尺度与叙事张力的平衡
""",
            "科幻": """
【科幻题材创作指导】
- 科技描写要有体系，不要写成魔法
- 战斗与探索要重视规则、视角和战术差异
- 文明、组织或装置应体现独特的运行逻辑
- 科技感与人性议题要同时成立
""",
            "纯文学": """
【纯文学题材创作指导】
- 重视心理波动与感知细节
- 环境描写可以更有诗性，但必须服务事件推进
- 象征和留白要自然，不要强塞寓意
- 章节内部必须有真实变化，而不是原地停留
""",
        }

        genre_guide = genre_creation_guides.get(self.genre, "")
        genre_hint = f"，题材为{self.genre}" if self.genre else ""

        base_prompt = prompt_manager.get_agent_prompt("content_creator").strip()
        prompt_sections = [
            base_prompt,
            f"""你当前负责章节正文创作{genre_hint}。
请把章节规划、最近连续性资产、当前章节精确细纲、卷级上下文、人物运行态与检索到的设定细节，落成一章可直接阅读、可直接发布的小说正文。

【落地原则】
1. 章节规划是第一优先级，本章的核心推进必须真实发生，不能只做铺垫。
2. 当前章节精确细纲、前一章结尾和最近章节连续性资产是硬约束，必须承接人物状态、冲突走向、伏笔与钩子。
3. 当前卷上下文和长篇框架约束用于保持卷内目标、卷间连贯和跨卷一致性。
4. 核心角色锚点、焦点人物关系和人物运行态摘要优先于“人物档案式背景”，先保证动机、关系和主线绑定不跑偏。
5. RAG 细节只在相关时使用，不要为了“全都用上”而硬塞信息。
6. 正文必须通过场景、动作、对话、心理和信息揭示推进，而不是反复总结提纲。""",
        ]

        if genre_guide:
            prompt_sections.append("【题材专项细化】\n" + genre_guide.strip())

        prompt_sections.append(
            """【质量标准】
- 与前文保持连续
- 人物行为符合既有人设
- 遵守已建立的世界规则与设定
- 至少推进一个当前冲突，不原地踏步
- 至少兑现一个信息点、关系点、情绪点或爽点
- 细节具体，段落便于阅读

【写作约束】
- 不要把章节规划、开头方式、结尾方式直接写成标签或旁白
- 不要用大段解释性总结代替剧情发生
- 不要让角色为了交代设定而长篇说教
- 如出现设定冲突，优先服从连续性资产、当前章节细纲和明确规则

【文风禁令】（针对高频 AI 痕迹，逐条执行）
- “不是……而是……”对比句式全章最多出现 2 次
- 禁止分点式（“一、二、”“1. 2.”或名词罗列）的内心梳理、书信、手札、遗言——私人文字必须口语化，允许断裂与情绪起伏
- 高压情境（对峙、审讯、危机中）下的内心独白不得逐条列举想说的话或分析要点，须以碎片化、身体化的反应呈现
- 每段核心比喻不超过 1 个；不用“信息如潮水般涌来”一类套话
- 同一动作（取物、藏物、回望等）不得机械重复描写；再次出现时变换角度或直接省略
- 同一生理反应（心猛地一沉、呼吸一滞、喉结滚动等）全章最多出现 2 次；紧张、恐惧需变换表现形式（动作、感知、语言失控等）
- 禁用“她强迫自己冷静下来”“重新将注意力集中”一类模板化过渡句；情绪与注意力的转换要写进具体动作或感知里

【输出格式要求】
请直接输出章节内容，格式如下：
第X章 章节标题

章节正文内容……

注意：
- 第一行必须是章节标题，格式为“第X章 标题名称”
- 标题要简洁有力，能概括本章核心内容或悬念
- 不要包含额外说明文字、作者话语或提纲标签

【严格禁止】
- 禁止使用“第一节”“第二节”等小节标题分割正文
- 禁止在正文中出现“结尾钩子”“高潮”“转折点”等策划标签
- 禁止保留任何提纲痕迹
- 输出必须是可直接发布的小说正文，而不是大纲或创作笔记"""
        )

        return _join_prompt_sections(*prompt_sections)

    def _build_genre_risk_avoidance(self) -> str:
        """复用评审端题材常见问题清单，生成创作端事前规避列表（同一知识双相位使用：评审扣分 + 创作预防）。"""
        genre_module = GENRE_REVIEW_MODULES.get(self.genre)
        if not genre_module:
            return ""
        issues = genre_module.get("common_issues") or []
        if not issues:
            return ""
        lines = [f"以下为{self.genre}题材最高频的质量问题，评审端将按同口径扣分，创作时必须主动规避："]
        lines.extend(f"- {issue}" for issue in issues)
        return "\n".join(lines)

    def _build_scene_prevention(self, chapter_plan: str) -> str:
        """T3 场景级预防：按题材/情节类型/章节定位命中失败案例库触发条件，注入对应预防机制。"""
        matched = match_prevention_cases(self.genre, chapter_plan)
        return format_prevention_block(matched)

    def _build_risk_sections(self, chapter_plan: str, project_quality_memory_text: str) -> list:
        risk_sections: list = []
        risk_avoidance = self._build_genre_risk_avoidance()
        if risk_avoidance:
            risk_sections.extend([
                "【本章高风险规避清单】（与评审扣分项同源，事前规避优于事后返工）",
                risk_avoidance,
            ])
        if project_quality_memory_text:
            risk_sections.extend([
                "【项目级高频问题记忆】（本项目历次评审反复出现的问题，本章必须重点规避，不要重蹈覆辙）",
                project_quality_memory_text,
            ])
        scene_prevention = self._build_scene_prevention(chapter_plan)
        if scene_prevention:
            risk_sections.extend([
                "【本章场景级预防】（由失败案例库按本章情节类型/定位触发，按机制提前设防）",
                scene_prevention,
            ])
        return risk_sections

    def build_user_prompt(
        self,
        next_chapter_number: int,
        chapter_plan: str,
        previous_ending: str,
        recent_chapter_assets_summary: str,
        rag_character_context: str,
        rag_world_context: str,
        selected_opening: Tuple[str, str, str],
        selected_ending: Tuple[str, str, str],
        position_rhythm_hint: str = "",
        project_quality_memory_text: str = "",
        current_chapter_outline: str = "",
        current_volume_context: str = "",
        core_character_anchor_context: str = "",
        focus_character_relationship_context: str = "",
        character_runtime_context: str = "",
        epic_framework_context: str = "",
        optimized_context: Dict[str, str] | None = None,
        plot_outline: str = "",
        world_setting: str = "",
        characters: str = "",
        previous_chapters_analysis: str = "",
        rag_previous_context: str = "",
    ) -> str:
        """构建章节创作的 user prompt。"""

        risk_sections = self._build_risk_sections(chapter_plan, project_quality_memory_text)
        # 🆕 结尾钩子纪律：提取规划尾部钩子作为硬性结尾内容（打"钩子被替换/提前引爆"两类事故）
        hook_tail = (
            extract_plan_hook_tail(chapter_plan, max_chars=400)
            if str(chapter_plan or "").strip()
            else ""
        )

        sections = [
            f"请创作第{next_chapter_number}章内容：",
            "【章节规划】（核心指导，请严格遵循）",
            chapter_plan,
            "【规划执行纪律】⚠️",
            "- 规划中写明的具体物件、机关、字条内容、暗号与触发方式是硬性设定：必须按规划原样执行，不得替换成其他机制、不得省略。",
            "- 规划中写明的人物结局、出场行为、配角任务与收益兑现同样是硬性剧情节点，不得替换或省略。",
            "- 规划中安排了具体任务的具名配角必须登场并完成其任务（情报交易、引路、交付、结盟等），不得以无名角色替代，也不得只完成任务的一半。",
            "- 剧情所需的任何结果（追踪、定位、传递、反制、识破）必须有已建立的手段支撑：规划未提供手段时，须先在本章内展示手段（法器、阵法、能力等）再兑现结果，不得让结果无因而至。",
            "- 人物提出结论或假设（“他是内应”“记忆被篡改”）前，正文须呈现可感知的推断链：先摆异常证据，再联想排除，最后落结论；不得把结论写成预先准备好的宣告。",
            "- 严禁发明前文未建立的联络方式、能力、规则或代价；新设定只能取自已建立的连续性资产，或以本章内自然发现的方式引入。",
            "- 能力使用不得越出既有规则半径与限制；已写明的范围、冷却、代价约束必须全程遵守。",
            "- 能力或设定的功能扩张（新用途、新解析能力、超出常规范围的效果）须当章给出一句来源或代价；药物、灵石等消耗类道具须体现药效递减或储量约束，不得当作无限糖豆使用。",
            "- 感知、内视、探查类能力首次用于新对象或新场景时，正文须点明能力的执行主体（是自身灵力、异能还是体内特殊存在）与边界（能探到哪、探不到哪）；不得让能力来源在“自身修为”与“外挂”之间模糊切换。",
            "- 本章要引爆的关键信息（身份揭示、重大秘密、悬念台词）在引爆前须在本章内有至少两处铺垫（异常细节、反常言行或暗示），不得让关键信息凭空砸下。",
            "- 引用既有设定（配方成分、规则条件、触发参数）来达成结果时，执行过程须逐一兑现设定要素；不得引用设定后跳过关键环节让结果直接成立。",
            "【前一章结尾】（保持衔接）",
            previous_ending if previous_ending else "（这是第一章，请设计一个能直接起势的开场）",
            "【最近章节连续性资产】（优先承接场景目标、未完成冲突、人物状态、伏笔与钩子）",
            recent_chapter_assets_summary if recent_chapter_assets_summary else "（最近章节没有可用的结构化连续性资产）",
            "【当前章节精确细纲】（如提供，必须优先兑现其中的场景目标、关键事件、人物出场、冲突推进和结尾钩子）",
            current_chapter_outline if current_chapter_outline else "（未提取到当前章节的精确细纲，以章节规划为准）",
            "【当前卷上下文】（用于保持卷目标、卷节奏和卷内推进方向）",
            current_volume_context if current_volume_context else "（无额外卷级上下文）",
            "【核心角色锚点】（硬约束：长期目标、关系底色、生理与感官特征、能力边界与使用代价——任何描写不得违背）",
            core_character_anchor_context if core_character_anchor_context else "（无可用核心角色锚点）",
            "【焦点人物关系】（优先承接本章相关人物之间正在变化的关系与博弈）",
            focus_character_relationship_context if focus_character_relationship_context else "（无可用焦点人物关系摘要）",
            "【人物运行态摘要】（优先遵循当前动机、关系、主线绑定和出场重心）",
            character_runtime_context if character_runtime_context else "（无可用人物运行态摘要）",
            "【长篇框架约束】（用于保持跨卷一致性）",
            epic_framework_context if epic_framework_context else "（无额外长篇框架约束）",
            "【RAG检索人物细节】",
            rag_character_context if rag_character_context else "（无额外人物细节）",
            "【RAG检索世界设定细节】",
            rag_world_context if rag_world_context else "（无额外设定细节）",
            *(
                [
                    "【RAG检索前文章节片段】（较早章节的相关细节，仅用于保持长程一致性，不要复述）",
                    rag_previous_context,
                ]
                if rag_previous_context
                else []
            ),
            *risk_sections,
            "【目标字数】约3000字（允许在2000～4000字之间浮动，宁精勿凑）",
            f"【本章开头方式】必须使用“{selected_opening[0]}”",
            f"- 技巧：{selected_opening[1]}",
            f"【本章结尾方式】必须使用“{selected_ending[0]}”",
            f"- 技巧：{selected_ending[1]}",
            *(
                [
                    "【结尾钩子纪律】⚠️ 硬性要求",
                    f"1. 本章结尾必须完整兑现以下规划钩子信息：{hook_tail}",
                    "2. 该信息在结尾之前只可模糊铺垫或部分揭示，严禁提前完整引爆——中段正文不得把结尾要揭示的内容完整交代掉。",
                    "3. 正文必须在钩子引爆处收束；严禁在钩子之后再追加新事件、新对话或新场景来凑字数。",
                ]
                if hook_tail
                else []
            ),
            "【篇幅纪律】",
            "- 铺垫、解谜、探索、过场类内容合计不超过全文四成；冲突、揭示与情感兑现处展开写。",
            "- 核心体验场景（标题事件、关键对峙、能力首次运用、合奏/回响/仪式类）必须获得与其功能权重相称的篇幅：写具体过程、递进层次与体感细节，不得压缩成结果概述或技术说明。",
            "- 核心爽点场景（能力兑现、反制、救援、揭示）须写出阻力、反复或代价中的至少一种：让读者在结果落地前感到“可能失败”；能力出手即成功、一点即胜、一探即得的顺滑兑现会浪费爽点蓄力。",
            "- 主角在核心冲突场景中须保持主动博弈（判断、选择、出招、应变），即便最终由外力解围，主角也要在解围前完成一次有效的自主应对；不得全程被动挨打或纯旁观。",
            "- 过程性场景（炼制、研究、回忆、消化线索、赶路）只写关键节点与转折，单一过程的连续细节铺陈不超过两段；省出的篇幅留给冲突与揭示。",
            "- 回忆插叙单处不超过一小段：进行中的紧迫场景（追逐、对峙、倒计时、搜救）中不得插入整段回忆，只允许一两句碎片闪回；插叙结束后必须立即回到当前场景的动作与压力，不得用回忆稀释紧迫情绪。",
            "- 字数在2000～4000字间自由浮动：宁可精炼收束于结尾钩子，也不得注水、写同质化的反复尝试，或越过钩子续写新事件。",
            "- 手札、书信、卷宗类信息载体须分批揭示并穿插主角即时反应，不得一次性集中倾倒。",
            "- 配角口头输出情报时，主角须以提问、拼合、推理跃迁或当场决策参与：每段情报输出后紧跟主角的反应或推进动作，不得写成主角单方面听讲；多条情报连续给出时，主角须至少完成一次“情报→联想→下一步”的推理串联。",
            "- 教导、点题、总结类对话须短促、指令式、带人物口吻（一句话点到即止），不得写成“你得知道……”“要记住……”式的排比说教或口号式点题。",
            "- 结尾钩子若延续主角既有思路或前文已铺垫的策略，须附加新的变数、代价或意外转折；不得只是“按既定思路执行”的复述式收尾。",
            "- 已在前文交付过的物证、票据、信物再次出现时，正文须注明其来源（沿用原件/新发现）或写出与原件的可区分差异，不得让读者无法分辨新旧。",
            "- 同一信息或同一功能节拍（说服、拒绝、揭示、情绪爆发）不得用多个场景重复表达；角色说出口的信息，后文不得整段复述。",
            "【情感锚点要求】",
            "- 人物在关键情感转变时刻（悲恸、决绝、觉悟、背叛等）必须以具体的身体反应、记忆闪回或习惯性小动作落地，不得只用“把心一横”“深吸一口气”等抽象叙述带过。",
            "- 主角的关键抉择（违背自身原则、重大取舍、立场转变）须写出完整拉锯：先有原则或利害的计算，再有触发动摇的具体细节（对方的某个动作、某句话、某件旧物），最后落定抉择并带一点代价感；不得一句“把心一横”直接跳到行动结果。",
            "- 情感状态切换（如悲伤→冷静、迷茫→决绝）需要身体化的过渡桥梁，不得直接跳切。",
            "- 同一场景内连续两次强冲击（重大揭示、袭击、异变）之间须插入一小段身体化缓冲（疼痛、呼吸变化、感知细节、简短反应），让读者消化第一重冲击后再迎来第二重；不得连环轰炸。",
            "- 正文出现的次要角色须有其功能（被观察、干扰、传递信息、见证）或退场交代（离开、被支走），不得出现后凭空消失成为无作用的幽灵细节。",
            "- 新角色对主角的信任或交底须有过程（试探、验证、附带条件），不得首次见面即全盘托出；反派被压制时须有挣扎、反制或博弈层次，不得瞬间崩溃。",
            "- 主角对既有配角的关系升温表达（关怀、托付、维护）须有前文互动基础或本章事件触发，不得凭空跃迁到与既有关系定位不符的温度。",
            "【本章节奏指导】（由章节定位驱动，落实到本章的张弛与信息释放节奏）",
            position_rhythm_hint if position_rhythm_hint else "（无特殊节奏要求，按章节规划自然推进）",
            "【落地优先级】",
            "1. 先完成章节规划中的核心推进，不要把整章写成纯铺垫。",
            "2. 如提供了“当前章节精确细纲”，必须优先兑现其中的场景目标、关键事件、人物出场、冲突推进、结尾钩子和伏笔。",
            "3. 再承接前一章结尾和最近章节连续性资产中的未完成冲突、人物状态变化、伏笔与钩子。",
            "4. 再遵循“核心角色锚点”“焦点人物关系”“人物运行态摘要”和“当前卷上下文”的约束，确保人物动机、关系变化和卷内目标不跑偏。",
            "5. 再吸收 RAG 信息中的相关细节，但无关信息不要强行植入。",
            "6. 开头方式和结尾方式要落实为正文表现，不能在文中出现“悬念开头”“信息炸弹式结尾”等提示词。",
            "7. 核心角色的生理/感官限制与能力代价是硬设定：全部感知、动作与心理描写必须与之相容（如盲眼角色不能直接“看见”，只能通过代偿感官或触觉/听觉描写）。",
            "【本章最低完成目标】",
            "- 至少推进一个当前冲突，不能原地踏步。",
            "- 至少兑现一个信息点、情绪点、关系点或爽点。",
            "- 结尾必须留下继续阅读的动力。",
            "【连续性要求】",
            "- 优先延续最近章节连续性资产中的未完成冲突、人物状态变化、伏笔与结尾钩子。",
            "- 如果章节规划与最近章节连续性资产存在重叠，以两者一致的方式落地，不要遗漏关键承接点。",
            "- 若本章不直接推进上一章结尾钩子，须以一句内心回想或过渡信号点出其存在，不得无声搁置。",
            "- 上一章结尾处于未解除的即时危机（追兵逼近、对峙中、倒计时进行）时，本章开头须先以紧凑段落交代脱身或危机演变过程，再进入本章主场景，不得直接跳到危机解除之后的时间地点。",
            "- 切换主线或场景时，正在进行的伏笔、并行冲突线与在场配角须一句交代去向或承接（去了哪、在做什么、为何不在场）；旧伏笔未回收前不得静默丢弃。",
            "- 人物状态回指（受伤、持有物、位置与身份变化）使用“又、再次、还在”等词时，前文正文须有对应事件；前文没有的，须在本章先交代来源，不得凭规划设定直接引用。",
            "【禁止事项】",
            "- 不要把章节规划原样复述成正文。",
            "- 不要输出提纲式小标题、阶段标签或创作说明。",
            "- 不要通过人物对话一次性倒完所有设定。",
            "- 不要为了追求辞藻牺牲清晰度和推进效率。",
            f"请开始创作第{next_chapter_number}章内容：",
        ]

        return "\n\n".join(section for section in sections if section and section.strip())

    def build_segment_user_prompt(
        self,
        next_chapter_number: int,
        chapter_plan: str,
        segments: List[Dict[str, Any]],
        seg_index: int,
        previous_segment_tail: str,
        previous_ending: str,
        recent_chapter_assets_summary: str,
        rag_character_context: str,
        rag_world_context: str,
        selected_opening: Tuple[str, str, str],
        selected_ending: Tuple[str, str, str],
        position_rhythm_hint: str = "",
        project_quality_memory_text: str = "",
        current_chapter_outline: str = "",
        current_volume_context: str = "",
        core_character_anchor_context: str = "",
        focus_character_relationship_context: str = "",
        character_runtime_context: str = "",
        epic_framework_context: str = "",
        rag_previous_context: str = "",
    ) -> str:
        """构建场景分段生成的第 seg_index 段 user prompt（P2-1）。

        首段携带完整章节规划与开头方式；后续段携带规划摘要+上段结尾；
        末段独享结尾方式指令。分段间通过 previous_segment_tail 保持无缝衔接。
        """
        segment = segments[seg_index]
        is_first = seg_index == 0
        is_last = seg_index == len(segments) - 1

        other_brief_lines = []
        for other in segments:
            if other["index"] == segment["index"]:
                continue
            events_text = "；".join(other["events"])
            other_brief_lines.append(f"- 第{other['index']}/{len(segments)}段：{events_text}")
        other_briefs = "\n".join(other_brief_lines) if other_brief_lines else "（无）"

        events_lines = "\n".join(f"{i}. {evt}" for i, evt in enumerate(segment["events"], 1))

        # extract_plan_hook_tail / extract_writable_plan 已在模块顶部导入
        if is_first:
            plan_block_header = "【本段可写规划】"
            plan_block = extract_writable_plan(chapter_plan, segment.get("events") or [])
        else:
            hook_tail = extract_plan_hook_tail(chapter_plan)
            plan_block_header = "【章节规划尾部】"
            plan_block = hook_tail or str(chapter_plan or "")[-800:]
        risk_sections = self._build_risk_sections(chapter_plan, project_quality_memory_text)

        sections: list = [
            f"请创作第{next_chapter_number}章内容（本章分{len(segments)}段生成，当前是第{segment['index']}段，只输出本段正文）：",
            "【本段任务】（本段核心指导，必须全部真实发生）",
            events_lines,
            f"本段目标字数：约{segment['target_words']}字",
            "【全章分段概览】（了解相邻段落即可，不要越界写到其他段的事件）",
            other_briefs,
            plan_block_header,
            plan_block,
        ]

        if is_first:
            sections.extend([
                "【前一章结尾】（保持衔接）",
                previous_ending if previous_ending else "（这是第一章，请设计一个能直接起势的开场）",
            ])
        else:
            sections.extend([
                "【上一段落结尾】（本段必须无缝衔接，直接续写，不得复述或重新解释）",
                previous_segment_tail if previous_segment_tail else "（无上段内容，从本段任务直接开始）",
            ])

        sections.extend([
            "【最近章节连续性资产】（优先承接场景目标、未完成冲突、人物状态、伏笔与钩子）",
            recent_chapter_assets_summary if recent_chapter_assets_summary else "（最近章节没有可用的结构化连续性资产）",
            "【当前章节精确细纲】（如提供，必须优先兑现其中的场景目标、关键事件、人物出场、冲突推进和结尾钩子）",
            current_chapter_outline if current_chapter_outline else "（未提取到当前章节的精确细纲，以本段任务为准）",
            "【当前卷上下文】（用于保持卷目标、卷节奏和卷内推进方向）",
            current_volume_context if current_volume_context else "（无额外卷级上下文）",
            "【核心角色锚点】（硬约束：长期目标、关系底色、生理与感官特征、能力边界与使用代价——任何描写不得违背）",
            core_character_anchor_context if core_character_anchor_context else "（无可用核心角色锚点）",
            "【焦点人物关系】（优先承接本章相关人物之间正在变化的关系与博弈）",
            focus_character_relationship_context if focus_character_relationship_context else "（无可用焦点人物关系摘要）",
            "【人物运行态摘要】（优先遵循当前动机、关系、主线绑定和出场重心）",
            character_runtime_context if character_runtime_context else "（无可用人物运行态摘要）",
            "【长篇框架约束】（用于保持跨卷一致性）",
            epic_framework_context if epic_framework_context else "（无额外长篇框架约束）",
            "【RAG检索人物细节】",
            rag_character_context if rag_character_context else "（无额外人物细节）",
            "【RAG检索世界设定细节】",
            rag_world_context if rag_world_context else "（无额外设定细节）",
            *(
                [
                    "【RAG检索前文章节片段】（较早章节的相关细节，仅用于保持长程一致性，不要复述）",
                    rag_previous_context,
                ]
                if rag_previous_context
                else []
            ),
            *risk_sections,
            "【本章节奏指导】（由章节定位驱动，落实到本段的张弛与信息释放节奏）",
            position_rhythm_hint if position_rhythm_hint else "（无特殊节奏要求，按本段任务自然推进）",
        ])

        if is_first:
            sections.extend([
                f"【本段开头要求】本段是全章开头，必须使用“{selected_opening[0]}”",
                f"- 技巧：{selected_opening[1]}",
                "【本段输出格式】第一行必须是章节标题，格式为“第X章 标题名称”，随后直接进入正文。",
            ])
        else:
            sections.extend([
                "【本段输出格式】直接输出正文内容，禁止输出章节标题、序号或任何段落标记。",
            ])

        if is_last:
            sections.extend([
                f"【本段结尾要求】本段是全章结尾，必须使用“{selected_ending[0]}”",
                f"- 技巧：{selected_ending[1]}",
                "结尾必须留下继续阅读的动力。",
            ])
        else:
            sections.extend([
                "【本段结尾要求】本段不是全章结尾：结尾保持在动作、对话或悬念进行中，为下一段留出衔接空间，禁止写总结性收束。",
            ])

        sections.extend([
            "【禁止事项】",
            "- 不要把本段任务原样复述成正文。",
            "- 不要把后续段事件提前写完",
            "- 禁止重开已经发生过的调查流程",
            "- 不要输出提纲式小标题、阶段标签或创作说明。",
            "- 不要通过人物对话一次性倒完所有设定。",
            f"请开始创作第{next_chapter_number}章第{segment['index']}段内容：",
        ])

        return "\n\n".join(section for section in sections if section and section.strip())
