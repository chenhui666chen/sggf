
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
        
        # 1. 创意总监生成故事概念
        logger.info("📝 创意总监正在生成故事概念...")
        concept_result = self.creative_director.process(requirement)
        concept = concept_result if isinstance(concept_result, str) else concept_result.get("output", requirement)
        logger.info(f"✅ 故事概念生成完成，长度: {len(concept)}")
        
        # 2. 世界观架构师生成世界观设定
        logger.info("🌍 世界观架构师正在生成世界观...")
        world_context = {"concept": concept, "requirement": requirement}
        world_result = self.world_architect.process(f"基于以下概念生成世界观设定：\n{concept}", context=world_context)
        world = world_result if isinstance(world_result, str) else world_result.get("output", "世界观设定")
        logger.info(f"✅ 世界观生成完成，长度: {len(world)}")
        
        # 3. 人物设计师生成人物设定
        logger.info("👥 人物设计师正在生成人物...")
        char_context = {"concept": concept, "world_setting": world, "requirement": requirement}
        char_result = self.character_designer.process(f"基于以下概念和世界观生成主要人物：\n概念：{concept[:200]}\n世界观：{world[:200]}", context=char_context)
        chars = char_result if isinstance(char_result, str) else char_result.get("output", "人物设定")
        logger.info(f"✅ 人物生成完成，长度: {len(chars)}")
        
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
        structure_prompt = f"""基于以下故事要素，生成符合网络小说风格的详细大纲：

【故事概念】
{concept[:500] if concept else '无'}

【世界观设定】
{world_setting[:300] if world_setting else '无'}

【主要人物】
{characters[:300] if characters else '无'}

【网文结构设计原则】
⚠️ 网络小说不同于传统文学，需要特别注意：
1. **卷结构**：按“卷”划分，每卷有20-30章，有独立的小高潮和阶段性目标
2. **爭点密度**：每3-5章必须有一个爭点（打脸/升级/获得/反转）
3. **钩子设计**：每章结尾必须有悬念，让读者想点下一章
4. **节奏控制**：紧张-舒缓交替，避免长时间铺垫
5. **金手指展示**：定期展示主角的优势，给读者爭感

【要求】
请生成包含以下要素的完整大纲：

## 一、故事概述
[基于故事概念，概述核心冲突、主角成长轨迹、主要矛盾，300-500字]

## 二、卷结构规划（建议3-5卷）

### 【第一卷】「卷名」
- **章节范围**：第1-25章（示例）
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

### 【第二卷】...
（继续规划后续卷）

## 三、主线情节线索

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | ... | ... |
| 支线A | 次要 | ... | ... | ... |

## 四、爽点节奏规划

- 每5章一个小爽点（打脸/升级/获得宝物）
- 每25章（卷末）一个大爽点（击败Boss/重大突破）
- 爽点类型：打脸/升级/获得宝物/装逼成功/反转翻盘/美人倾心/万众瞩目

## 五、核心转折点

明确整个故事的几个重大转折点及其在哪一卷/章发生。"""
        
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

请确认：
1. 是否解决了之前指出的问题
2. 整体质量是否达标
3. 是否可以发布

给出简短的最终评审意见。"""
        
        final_review_result = self.quality_reviewer.process(final_review_prompt, context={"content": revised_content})
        final_review = final_review_result if isinstance(final_review_result, str) else final_review_result.get("output", "最终评审完成")
        logger.info(f"✅ 最终评审完成，长度: {len(final_review)}")
        
        self.project_context.update({"content": revised_content})
        return {"revised_content": revised_content, "final_review": final_review}
