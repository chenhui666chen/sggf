
from typing import Optional, Dict, Any
import logging

from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from .agents import CreativeDirectorAgent, WorldArchitectAgent, CharacterDesignerAgent, ContentCreatorAgent, QualityReviewerAgent
from .llm_singleton import create_deepseek_llm

logger = logging.getLogger(__name__)


class CreativeDirectorCoordinator:
    """
    真实协调器（简版实现）：提供五阶段方法与必要的上下文接口，
    以满足系统的调用约定并避免导入失败。
    """

    def __init__(
        self,
        knowledge_base: Optional[NovelKnowledgeBase] = None,
        memory_manager: Optional[NovelMemoryManager] = None,
        enable_communication: bool = True,
        enable_conflict_detection: bool = True,
        enable_detailed_logging: bool = True,
    ) -> None:
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()

        self.enable_communication = enable_communication
        self.enable_conflict_detection = enable_conflict_detection
        self.enable_detailed_logging = enable_detailed_logging
        
        # 初始化真实Agent
        self.creative_director = CreativeDirectorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.world_architect = WorldArchitectAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.character_designer = CharacterDesignerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.content_creator = ContentCreatorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.quality_reviewer = QualityReviewerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)

        # 项目上下文
        self.project_id: Optional[int] = None
        self.project_context: Dict[str, Any] = {
            "concept": "",
            "world_setting": "",
            "characters": "",
            "plot_outline": "",
            "content": "",
            "chapters": [],
            "review": "",
        }

        # 长篇创作配置
        self.target_chapter_count: Optional[int] = None

        # 进度回调（可选）
        self._progress_cb = None
        self._progress_task_id = None
        self._progress_project_id = None

    # ---- 基础接口 ----
    def set_project_context(self, project_id: int) -> None:
        self.project_id = project_id

    def set_longform_config(self, target_chapter_count: Optional[int] = None) -> None:
        self.target_chapter_count = target_chapter_count

    def set_progress_callback(self, cb, task_id: str, project_id: int) -> None:
        self._progress_cb = cb
        self._progress_task_id = task_id
        self._progress_project_id = project_id

    # ---- 阶段方法 ----
    def _stage_one_concept_development(self, requirement: str) -> Dict[str, Any]:
        """
        阶段1：概念开发 - 调用真实Agent生成
        返回 keys：concept, world_setting, characters
        """
        logger.info(f"🎯 开始真实Agent概念开发，需求: {requirement[:100]}...")
        
        # 🔧 获取重生信息（在创意总监执行前就读取）
        regenerate_targets = self.project_context.get("regenerate_targets", [])
        is_regenerate = self.project_context.get("regenerate", False)
        
        # 1. 创意总监生成故事概念（按 regenerate_targets 条件执行）
        should_generate_concept = not is_regenerate or "story" in regenerate_targets
        
        if should_generate_concept:
            logger.info("📝 创意总监正在生成故事概念...")
            # 🔧 重生时的特别提示
            regenerate_hint = ""
            if is_regenerate and "story" in regenerate_targets:
                regenerate_hint = "\n\n【重生成说明】\n这是一次重新生成，请基于用户反馈进行优化与调整，确保有明显改进。若用户未提供具体反馈，则从以下角度进行轻微优化：\n1. 增强核心标签的差异化锐度\n2. 优化Logline的吸引力\n3. 调整核心冲突的层次感"
            concept_prompt = f"""你是一名擅长网文结构设计的"创意总监"，需要为一个新项目生成【故事概念】和初步【世界观设定】。{regenerate_hint}

【已知信息】
- 项目题目：{self.project_context.get("title") or self.project_context.get("project_title") or "未命名项目"}
- 题材类型：{self.project_context.get("genre") or self.project_context.get("project_genre") or "通用题材"}
- 用户提供的初始想法（如有）：{requirement or "暂无"}

【总体要求】
1. 先完成“故事概念”六段标准输出，再给出一个与之匹配的高度概括版世界观（可简略）。
2. 保持网文向：强调爽点潜力、冲突强度和持续升级空间。
3. 若 context 中提供了已有大纲或人物设定（重生成场景），须确保新概念与它们在世界观与核心矛盾上相容。

——————————
一、请先生成【故事概念】，严格按以下六个部分输出（用 Markdown 粗体标记小标题）：

1. **一句话卖点（Logline）**：
- 用一句极具吸引力的网文式概括，包含主角类型、核心能力/优势、主要对手/系统，以及最具爽感的长期目标或爆点。
- 优先使用“主角行动 + 意外结果”句式，例如：“废柴掌控修真流水线，反手碾压宗门大佬”，而不是单纯罗列设定。
- 控制在 30–60 字之间。

2. **日志标题（短标题）**：
- 用 4–10 个字给出一个便于读者记忆的项目名，偏网文风格。

3. **概念摘要（80–150字）**：
- 简要交代主角身份、初始困境、长期目标、主要阻力，以及世界观的一个独特钩子。
- 语气偏“介绍本书卖点”，而不是平铺剧情。

4. **题材与流派（主题材/子流派）**：
- 主题材例如：玄幻修真 / 反乌托邦科幻 / 历史权谋 / 都市奇能 等；
- 子流派例如：系统流 / 科技修仙流 / 穿越流 / 言情权谋 / 无限流 等；
- 用“主题材 / 子流派1+子流派2”的形式表述，保持网文分类习惯。

5. **核心标签（3–6个）**：
- 提炼最能体现本书差异化的关键词，如“末法时代、格物修真、底层逆袭、技术流打脸”；
- 必须至少包含 1 个“反套路/细分创新”标签（例如：“修真+工业流水线”“系统是反派”“主角不想飞升只想活下去”），避免全是常规标签；
- 避免只出现“热血、成长”这类无区分度的词语。

6. **核心冲突与情感基调**：
- 用 2–3 句话说明：
  - 主线冲突是谁对谁，是什么利益/观念/系统矛盾；
  - 整体情绪是偏爽文逆袭、黑暗现实、甜宠成长还是悬疑惊悚等（可以混合）。

——————————
二、在完成六段“故事概念”之后，请追加一个小节：

7. **世界观高概摘要（可简略）**：
- 用 3–5 句简要说明故事发生的时代背景、主要势力格局和核心规则特点；
- 此处只做高度概括，详细世界观将在后续阶段展开。

请严格按照上述顺序与小标题输出，不要添加其他额外说明。"""
            concept_result = self.creative_director.process(concept_prompt)
            concept = concept_result if isinstance(concept_result, str) else concept_result.get("output", requirement)
            logger.info(f"✅ 故事概念生成完成，长度: {len(concept)}")
        else:
            # 重生时不重生story，沿用旧概念
            concept = self.project_context.get("concept") or ""
            logger.info("⏭ 跳过故事概念生成，沿用现有故事概念。")
        
        # 2. 世界观架构师生成世界观设定（按 regenerate_targets 条件执行）
        # 判断是否需要重生世界观
        should_generate_world = not is_regenerate or "world" in regenerate_targets
        
        if should_generate_world:
            logger.info("🌍 世界观架构师正在生成世界观...")
            world_prompt = f"""你是一名"世界观架构师"，需要为一个网文项目生成结构化的【世界观设定】。

【已知内容】
- 故事概念：{concept[:500] if concept else '无'}
- 题材类型：{self.project_context.get("genre") or self.project_context.get("project_genre") or "通用题材"}
- 用户在世界观上的特别要求：{requirement or "暂无特别要求"}

【总体要求】
1. 世界观必须服务于故事概念中的核心冲突与设定线索，不做与主线无关的堆砌；
2. 设定要有层次感与延展性，既能支撑卷一剧情，又能为后续升级预留空间；
3. 必须标注至少1个"势力薄弱点"作为卷一冲突的直接触发点；
4. 规则体系需支持题材适配替换（如都市题材可用"经济金融体系"替代"修真体系"）。

——————————
请按以下七个部分输出（用 Markdown 粗体标记小标题，各节标题请保留）：

1. **时间线与时代背景**
- 说明这是一个怎样的时代（例如:末法晚期、星际殖民后期、盛唐权谋鼎盛期等）；
- 标出 2–4 个关键历史节点，用"过去的转折 → 当前状态"的方式交代。

2. **关键地点与地理结构**
- 列出 3–6 个核心地点（宗门/城市/阵区/组织基地等），每个用 2–4 句介绍其功能和故事潜力；
- 明确哪些地点适合成为长期舞台，哪些适合作为阶段性副本。

3. **社会结构与势力格局**
- 概括上层权力结构（宗门/公司/帝国/AI系统等）、中层组织（联盟/工会/技术联盟）与底层群体；
- 指出至少 2 条清晰的"阶层矛盾线"或"势力对立线"，为后续冲突服务；
- **必须标注至少 1 个"最容易被主角撬动"的势力薄弱点**（例如:旧势力的资源垄断漏洞、中层组织的利益分配矛盾、监管盲区），为卷一冲突提供直接抓手。

4. **规则体系（物理 / 修真 / 科技）**
- 说明核心能力体系（如境界体系、科技体系、规则系统），特别是"本书与同类作品不同的点"；
- 指出明确的限制和代价，避免"无成本外挂"。

5. **文化风俗与伦理禁忌**
- 描述本世界的人们如何看待修行/科技/交易/记忆/灵魂等关键要素；
- 列出 2–3 条重要禁忌（法律的、宗教的或潜规则的），为剧情提供红线。

6. **科技 / 工程与能力体系的融合水平（或其它适配本题材的结构）**
- 若题材涉及科技/工程/系统，请说明传统力量（修真/魔法/神秘）与现代技术（工程/AI/科学）之间的关系:冲突?互补?利用与被利用?
- **题材适配规则**:如果题材是纯历史权谋、都市言情等弱超自然类型，则可以将本节替换为更相关的结构，例如:"权力规则体系""经济金融体系"等，选择一个最支撑主线冲突的体系来展开。

7. **资源体系与代价机制**
- 列出主要资源（灵石、记忆、水晶、功德值、系统点数等）的来源与流向；
- 指出底层人物在该体系中的典型生存路径和陷阱。

请用清晰的段落和小标题组织内容，避免长篇大段不分段的纯文字，严格按照上述七个部分输出。"""
            world_context = {"concept": concept, "requirement": requirement}
            world_result = self.world_architect.process(world_prompt, context=world_context)
            world = world_result if isinstance(world_result, str) else world_result.get("output", "世界观设定")
            logger.info(f"✅ 世界观生成完成，长度: {len(world)}")
        else:
            # 重生时不重生world，沿用旧世界观
            world = self.project_context.get("world_setting") or ""
            logger.info("⏭ 跳过世界观生成，沿用现有世界观设定。")
        
        # 3. 人物设计师生成人物设定（按 regenerate_targets 条件执行）
        # 判断是否需要重生人物（目前 UI 只有 story/world，没有人物，所以重生时不该跳过）
        should_generate_characters = not is_regenerate or "characters" in regenerate_targets
        
        if should_generate_characters:
            logger.info("👥 人物设计师正在生成人物...")
            char_prompt = f"""你是一名擅长网文人物塑造的"人物设计师"，需要为一个网文项目生成结构化的【主要人物设定】。

【已知内容】
- 故事概念：{concept[:500] if concept else '无'}
- 世界观设定：{world[:300] if world else '无'}
- 用户对人物的特别要求：{requirement or "暂无特别要求"}

【总体要求】
1. 围绕主线冲突与世界观设定，设计至少 3–5 个核心人物（主角 + 核心盟友 + 主要对手 + 关键NPC）；
2. 人物要立体、有层次、有成长空间，避免脸谱化；
3. 每个人物都要与故事概念中的核心冲突、势力格局或世界观规则有明确联系；
4. 必须设计"人物关系网络"与"成长弧光"，服务于网文的爽点节奏与长期升级感。

——————————
请按以下格式为每个核心人物输出完整档案（用 Markdown 三级标题标记人物名）：

## 一、核心主角

### 【姓名】：林浩（示例）

【年龄/性别】：25岁/男

【角色定位】：主角

【所属势力】：青玄宗（或"无"/"散修"/具体组织名）

【重要性】：主角（可选：主角/重要角色/次要角色/群众角色）

【外貌特征】：2–3 句简要描述，突出与性格或经历相关的细节（如眼神、体态、标志性特征）。

【性格特点】：
- 表层（初期）：对外展现的性格（如隐忍、谨慎、自卑）
- 中层（核心驱动）：获得力量或机遇后的转变（如理性、务实、探索欲）
- 内核（贯穿始终）：深层价值观与情感底色（如慈悲、孤独、对底层的共情）

【背景故事】：3–5 句交代出身、过去经历、关键转折（如何绑定系统/获得金手指）。

【世界观/价值观立场】：说明对本世界核心规则/秩序/自由/科技等的态度，1-2句。

【核心动机】：
1. 生存与证明（前期）：…
2. 探索与创造（中期）：…
3. 真相与责任（后期）：…

【能力/特长】：在故事中的核心优势与独特能力。

【弱点/缺陷】：性格或能力上的短板，1-2句。

【在情节中的作用】：作为故事核心驱动力的具体体现，2-3句。

【人物成长线】：用 2–3 条"从……到……"句式，描述人物在力量、认知、心性上的关键转变。

【关键关系】：列出与3-5个主要角色的关系（如：老周-启蒙导师，小灵-技术搭档→情感伴侣）。

【关联线索】：本角色主要参与的情节线（如：主线-破解天道AI，支线A-技能成长）。

---

（如有其他主角，请继续按同样格式）

——————————

## 二、核心盟友（2–3 人）

### 【姓名】：苏婉儿（示例）

【年龄/性别】：23岁/女

【角色定位】：核心盟友

【所属势力】：青玄宗内门

【重要性】：重要角色

【外貌特征】：…

【性格特点】：…（如：外冷内热，原则性强，内心对旧体制有所不满）

【背景故事】：…

【世界观/价值观立场】：…

【核心动机】：…

【能力/特长】：…

【弱点/缺陷】：…

【在情节中的作用】：…

【人物成长线】：…（如：从坚信"个人天赋"到理解"标准化与协作"）

【关键关系】：…（如：与主角-始于好奇，历经共患难，成为最信任的伙伴）

【关联线索】：…

---

（如有其他核心盟友，请继续按同样格式）

——————————

## 三、核心对手/复杂关系者（2–3 人）

### 【姓名】：赵坤（示例）

【年龄/性别】：26岁/男

【角色定位】：初期对手

【所属势力】：青玄宗外门执事派系

【重要性】：次要角色

【外貌特征】：…

【性格特点】：…（如：傲慢、狭隘、睚眦必报）

【背景故事】：…

【世界观/价值观立场】：…

【核心动机】：…

【能力/特长】：…

【弱点/缺陷】：…

【在情节中的作用】：…（如：提供初期打脸爽点，推动主角立威）

【人物成长线】：…

【关键关系】：…

【关联线索】：…

---

### 【姓名】：柳清风（示例）

【年龄/性别】：外表40岁/男（实际年龄未知）

【角色定位】：终极反派观察者

【所属势力】：仙界巡天使

【重要性】：重要角色

【外貌特征】：…

【性格特点】：…（如：绝对理性，视下界众生为资源）

【背景故事】：…（如：仙界派往下界的"巡天使"）

【世界观/价值观立场】：…

【核心动机】：…

【能力/特长】：…

【弱点/缺陷】：…

【在情节中的作用】：…（如：悬疑线牵引者，终极矛盾具象化）

【人物成长线】：…

【关键关系】：…

【关联线索】：…

——————————

## 四、人物关系网络与动态演变（可选）

请用简洁的图示或列表，说明：

**初期（蛰伏期）**：
- 主角 ← [欺凌/鄙视] → 恶少
- 主角 ↑ [偶然交集] → 高层盟友
- 主角 + 忠诚同伴

**中期（崛起期）**：
- 主角 ← [理念冲突/利益受损] → 传统权威
- 主角 ↑ [支持/信赖] ← 核心团队
- 阴影观察者 → [监控/评估] → 主角

**后期（对抗期）**：
- 主角 ← [根本性对立] → 仙界代言
- 主角 ↑ [联盟/追随] ← 新势力
- 传统势力 ↑ [操控/利用] ← 反派

——————————

【关键规则】
1. 每个人物**必须包含完整的14个字段**（姓名、年龄/性别、角色定位、所属势力、重要性、外貌特征、性格特点、背景故事、世界观/价值观立场、核心动机、能力/特长、弱点/缺陷、在情节中的作用、人物成长线、关键关系、关联线索）；
2. 【所属势力】必须填写具体组织名或"无"/"散修"，避免空白；
3. 【重要性】必须从以下选项中选择：主角/重要角色/次要角色/群众角色；
4. 人物要与世界观核心紧密勾连，服务于"逆袭爽点"、"理念碰撞"与"终极揭秘"；
5. 避免纯粹的"好人/坏人"二元对立，给对手合理动机；
6. 盟友与对手都要有自己的成长线，不能沦为"工具人"。

请严格按照上述格式输出完整的主要人物设定，每个字段后必须换行。"""
            char_context = {"concept": concept, "world_setting": world, "requirement": requirement}
            char_result = self.character_designer.process(char_prompt, context=char_context)
            chars = char_result if isinstance(char_result, str) else char_result.get("output", "人物设定")
            logger.info(f"✅ 人物生成完成，长度: {len(chars)}")
        else:
            # 重生时不重生人物，沿用旧人物设定
            chars = self.project_context.get("characters") or ""
            logger.info("⏭ 跳过人物生成，沿用现有人物设定。")
        
        # 更新上下文
        self.project_context.update({
            "concept": concept,
            "world_setting": world,
            "characters": chars,
        })
        
        logger.info("🎉 概念开发阶段完成！")
        return {"concept": concept, "world_setting": world, "characters": chars}

    def _stage_two_structure_design(self, concept_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段2：结构设计 - 调用真实Agent生成
        返回 keys：plot_outline
        """
        logger.info(f"🎯 开始真实Agent结构设计...")
        
        concept = concept_result.get("concept") or self.project_context.get("concept")
        world_setting = concept_result.get("world_setting") or self.project_context.get("world_setting")
        characters = concept_result.get("characters") or self.project_context.get("characters")
        
        logger.info("📝 创意总监正在生成网文卷结构大纲...")
        structure_prompt = f"""你是一名擅长网文结构的“情节架构师”，需要在已有【故事概念 + 世界观设定 + 主要人物】的基础上，规划一部长篇网文的【情节大纲】。

【故事概念】
{concept[:500] if concept else '无'}

【世界观设定】
{world_setting[:300] if world_setting else '无'}

【主要人物】
{characters[:300] if characters else '无'}

【总体要求】
1. 采用“按卷/阶段 + 起承转合骨架 + 网文爽点节奏”的混合结构。
2. 每一卷/阶段都要明确：阶段目标、主要矛盾、爆点与升级节点。
3. 不写细节对白，只写“发生什么事 + 冲突方向 + 爽点类型”。

请按以下结构输出：

1. **总体结构概览**
- 用 3–5 行概括全书走向（例如：底层生存 → 技术崛起 → 撼动旧秩序 → 新范式成型）；
- 标明本书更偏“爽文逆袭”“权谋智斗”“悬疑走向”“慢热成长”等（可组合）；
- 明确整体“情绪起伏节奏”，例如：“小爽 → 压抑 → 中爽 → 再压抑 → 爆爽 → 余韵”，避免全程同强度爽点导致疲劳。

2. **卷一：XXXX（起）**
- **阶段目标**：主角要达成的阶段性目标（例如：活下来、保住家人、摆脱债务、进入学院等）；
- **核心矛盾**：这一卷持续的主要矛盾；
- **关键节点建议**（建议 4–8 个），每个节点必须包含：
  - 场景（简短描述发生在哪里）；
  - 冲突（谁 vs 谁，矛盾点是什么）；
  - 爽点/转折：说明这是“打脸、越级、技术降维打击、关系反转、真相片段”等哪一类爽点；
  - **爽点强度：小爽 / 中爽 / 爆爽**（必须标注）；
  - 建议章节范围（如“第1–3章”“第4–6章”），可参考“约每3章一个小高潮”的节奏（例如：第3章、第6章设小爽点，第10章左右设卷内爆点）。

3. **卷二：XXXX（承）**
- 同卷一格式：阶段目标 + 核心矛盾 + 关键节点列表；
- 注意承接卷一的未解矛盾，并引入新的升级点（更大格局、更强对手或更深真相）。

4. **卷三：XXXX（转）**
- 侧重重大转折与价值观/世界观层面的冲突升级，可以有一段“压抑期”，为后续爆爽做铺垫。

5. **卷四：XXXX（合）**（或后续多卷）
- 交代主线收束方式，安排终极爆点与情绪“余韵”。

【节奏与爽点规则】
- 保证每 5–10 章至少有一个明确爽点（反杀、升级、打脸、关系反转、真相片段等）；
- 在每卷内，爽点强度建议遵循“小爽 → 中爽 → 小缓冲 → 爆爽”的节奏结构；
- 不要在前期一次性暴露所有终极秘密，要保留后续升级与反转空间；
- 若是系统流/科技流，每卷引入一个新的“工具/规则应用方式”，形成能力或玩法上的升级感。

请根据以上要求输出完整的卷结构大纲。"""
        
        structure_context = {
            "concept": concept,
            "world_setting": world_setting,
            "characters": characters
        }
        # 🔄 临时切换创意总监到 R1（deepseek-reasoner）用于结构阶段
        orig_llm = getattr(self.creative_director, "llm", None)
        try:
            r1_llm = create_deepseek_llm(task_type="quality_review")  # 选择R1模型
            logger.info("⚙️ [生效日志] 结构阶段启用R1模型：task_type=quality_review, model=deepseek-reasoner")
            self.creative_director.llm = r1_llm
            structure_result = self.creative_director.process(structure_prompt, context=structure_context)
        finally:
            if orig_llm is not None:
                self.creative_director.llm = orig_llm
                logger.info("🔄 [生效日志] 结构阶段结束，创意总监恢复原模型配置")
        
        outline = structure_result if isinstance(structure_result, str) else structure_result.get("output", "结构大纲")
        logger.info(f"✅ 结构大纲生成完成，长度: {len(outline)}")
        
        self.project_context.update({"plot_outline": outline})
        return {"plot_outline": outline}

    def _stage_three_content_creation(self, structure_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段3：内容创作 - 调用真实Agent生成
        返回 keys：content 或 chapters
        """
        logger.info(f"🎯 开始真实Agent内容创作...")
        
        plot_outline = structure_result.get("plot_outline") or self.project_context.get("plot_outline")
        concept = self.project_context.get("concept")
        world_setting = self.project_context.get("world_setting")
        characters = self.project_context.get("characters")
        target = self.target_chapter_count or 1
        
        logger.info(f"✍️ 内容创作师正在生成第1章草稿（目标{target}章）...")
        content_prompt = f"""请根据提供的情节大纲、世界观设定和人物设定，创作精彩的第1章内容。

【结构大纲】
{plot_outline[:500] if plot_outline else '无'}

【故事概念】
{concept[:300] if concept else '无'}

【世界观设定】
{world_setting[:200] if world_setting else '无'}

【主要人物】
{characters[:200] if characters else '无'}

【创作要求】
1. **语言风格**：语言生动，描写细腻，符合网文风格
2. **对话要求**：对话自然，符合人物性格
3. **情节节奏**：情节紧凑，引人入胜，注意爭点节奏
4. **场景描写**：场景描写要有画面感
5. **段落分隔**：注意段落分隔，便于阅读
6. **开篇建立**：第一章要快速建立世界观和主角形象
7. **多种手法**：使用场景描写、对话、心理描写等多种手法

【质量标准】
- ✅ 人物性格和行为符合设定
- ✅ 遵循已建立的世界观规则
- ✅ 注重细节的合理性和真实感
- ✅ 开头要有吸引力，结尾要有悬念

【禁止事项】
❌ 禁止使用：用"XXX醒来/睁开眼睛/阳光照进房间"开头
❌ 禁止使用：总结式内心独白 + 对未来的展望（如"他知道，从这一刻起..."）

【目标字数】约2000-3000字

请开始创作第1章内容，直接输出章节正文，不要包含任何额外的说明文字。"""
        
        content_context = {
            "plot_outline": plot_outline,
            "concept": concept,
            "world_setting": world_setting,
            "characters": characters,
            "chapter_number": 1,
            "total_chapters": target
        }
        content_result = self.content_creator.process(content_prompt, context=content_context)
        content = content_result if isinstance(content_result, str) else content_result.get("output", "章节内容")
        logger.info(f"✅ 第1章创作完成，长度: {len(content)}")
        
        self.project_context.update({"content": content, "chapters": [content]})
        return {"content": content}

    def _stage_four_quality_review(self, content_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段4：质量评审 - 调用真实Agent生成
        返回 keys：review, needs_revision
        """
        logger.info(f"🎯 开始真实Agent质量评审...")
        
        content = (
            content_result.get("content")
            or self.project_context.get("content")
            or self.project_context.get("plot_outline")
            or ""
        )
        
        if not content:
            logger.warning("⚠️ 无内容可评审，返回占位符")
            return {"review": "无可评审内容", "needs_revision": False}
        
        logger.info("🔍 质量评审官正在评审内容...")
        review_prompt = f"""你是一位专业的网络小说质量评审官。请使用【网文6维度评审体系】对以下内容进行评审：

【待评审内容】
{content[:3000]}

## 📊 网文6维度评审体系

### 1. 爽点效果（权重25%）
- 本章是否有明确的爽点或为后续爽点做了铺垫？
- 是否成功吸引读者？

### 2. 节奏把控（权重20%）
- 信息密度是否适中？
- 场景转换是否流畅？
- 对话与叙述比例是否合理（建议30-50%对话）？

### 3. 钩子效果（权重15%）
- 章节开头是否吸引人？
- 章节结尾是否有悬念/钩子？
- 读者是否有“想点下一章”的冲动？

### 4. 代入感（权重15%）
- 主角视角是否清晰？
- 是否有强烈的画面感与情感渲染？

### 5. 文笔流畅度（权重10%）
- 是否存在明显AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 描写是否生动有画面感？

### 6. 内容一致性（权重15%）
- 与人物设定、世界观规则是否一致？

【输出格式】
请使用以下格式输出评审报告：

## 📊 网文质量评审报告

**综合评分**：X/10分

### 1. 爽点效果 ⭐⭐⭐
- 评价：...
- 问题：...

### 2. 节奏把控 ⭐⭐⭐
- 评价：...
- 问题：...

### 3. 钩子效果 ⭐⭐⭐
- 开头评价：...
- 结尾评价：...
- 问题：...

### 4. 代入感 ⭐⭐⭐
- 评价：...
- 问题：...

### 5. 文笔流畅度 ⭐⭐⭐
- 评价：...
- 问题：...

### 6. 内容一致性 ⭐⭐⭐
- 评价：...
- 问题：...

### 🔧 具体修改建议（按优先级排序）
1. 【必改】...
2. 【建议】...
3. 【可选】..."""
        
        review_context = {"content": content}
        review_result = self.quality_reviewer.process(review_prompt, context=review_context)
        review = review_result if isinstance(review_result, str) else review_result.get("output", "评审报告")
        logger.info(f"✅ 质量评审完成，长度: {len(review)}")
        
        # 简单判断是否需要修订（基于关键词）
        needs_revision = any(keyword in review for keyword in ["需要修订", "建议修改", "必须改进", "严重问题"])
        logger.info(f"📋 是否需要修订: {needs_revision}")
        
        self.project_context.update({"review": review})
        return {"review": review, "needs_revision": needs_revision}

    def _stage_five_iteration_optimization(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段5：迭代优化 - 调用真实Agent生成
        返回 keys：revised_content, final_review
        """
        logger.info(f"🎯 开始真实Agent迭代优化...")
        
        original_content = self.project_context.get("content") or ""
        review = review_result.get("review") or self.project_context.get("review") or ""
        needs_revision = review_result.get("needs_revision", False)
        
        if not needs_revision:
            logger.info("✅ 内容无需修订，直接通过")
            return {"revised_content": original_content, "final_review": "内容质量达标，无需修订"}
        
        logger.info("✏️ 内容创作师正在根据评审意见优化内容...")
        revision_prompt = f"""请根据以下评审意见优化内容：

【原始内容】
{original_content[:2000]}

【评审意见】
{review[:1000]}

优化要求：
1. 保持故事主线和人物设定不变
2. 针对评审中指出的具体问题进行修改
3. 优化语言表达和叙事节奏
4. 增强细节描写和情感渲染
5. 确保逻辑连贯性

请输出优化后的完整内容。"""
        
        revision_context = {
            "original_content": original_content,
            "review": review
        }
        revision_result = self.content_creator.process(revision_prompt, context=revision_context)
        revised_content = revision_result if isinstance(revision_result, str) else revision_result.get("output", original_content)
        logger.info(f"✅ 内容优化完成，长度: {len(revised_content)}")
        
        # 最终评审
        logger.info("🔍 质量评审官进行最终评审...")
        final_review_prompt = f"""请对优化后的内容进行最终评审：

【优化后内容】
{revised_content[:2000]}

Please confirm：
1. 是否解决了之前指出的问题
2. 整体质量是否达标
3. 是否可以发布

给出简短的最终评审意见。"""
        
        final_review_result = self.quality_reviewer.process(final_review_prompt, context={"content": revised_content})
        final_review = final_review_result if isinstance(final_review_result, str) else final_review_result.get("output", "最终评审完成")
        logger.info(f"✅ 最终评审完成，长度: {len(final_review)}")
        
        self.project_context.update({"content": revised_content})
        return {"revised_content": revised_content, "final_review": final_review}
