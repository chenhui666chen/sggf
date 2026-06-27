"""Outline expansion mixin."""
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..agents import CreativeDirectorAgent, PlotArchitectAgent, CharacterDesignerAgent
from core.langchain_bridge import create_task_llm, create_model_llm
from ..knowledge_base import NovelKnowledgeBase
from ..memory_manager import NovelMemoryManager
from ..agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE, REALM_SPAN_WARNING_THRESHOLD, REALM_SPAN_RECOMMEND_SUBDIVISION
from ..layered_summarizer import LayeredSummarizer
from ...volume_connector import VolumeConnector
from ...foreshadowing_tracker import ForeshadowingTracker
from ...consistency_validator import ConsistencyValidator, get_consistency_validator, get_chapter_renumberer
from ..character_recognizer import CharacterRecognizer
from ..character_plot_validator import CharacterPlotValidator
from ...character_parser import (
    CharacterTextParser,
    ParsedCharacter,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    _merge_parsed_character,
    normalize_character_name,
)
from ...character_runtime_context import build_character_prompt_context_from_text
from ._constants import *

class CharacterExpansionMixin:
    def _legacy_expand_plot_outline_incremental(self, current_outline: str, world_setting: str,
                                       characters: str, current_chapter_count: int,
                                       increment: int = 15,
                                       target_total_chapters: Optional[int] = None) -> Dict[str, Any]:
        """渐进式扩展情节大纲

        每次增加约15章，直到AI判断不再需要扩展

        Args:
            current_outline: 当前的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            current_chapter_count: 当前已有的章节数（如为0则自动识别）
            increment: 本次扩展的章节数（默认15章）
            target_total_chapters: 长篇小说目标总章节数（如未提供则按100章进行规划判断）

        Returns:
            扩展后的大纲字典，包含:
            - expanded_outline: 扩展后的完整大纲
            - chapter_breakdown: 章节分解
            - plot_arcs: 情节线索分析
            - current_chapter_count: 当前总章节数
            - should_continue: AI判断是否还需要继续扩展
            - continue_reason: 继续扩展的原因（如果需要）
        """
        # 🆕 智能识别当前章节数
        if current_chapter_count == 0:
            logger.debug("🔍 检测到 current_chapter_count=0，开始自动识别当前大纲的章节数...")
            detected_count = self.count_chapters_in_outline(current_outline)
            if detected_count > 0:
                current_chapter_count = detected_count
                logger.debug(f"🎯 识别成功！当前大纲已有 {current_chapter_count} 章\n")
            else:
                logger.debug("🆕 未识别到章节，从 0 章开始扩展\n")

        logger.debug(f"\n{'='*70}")
        logger.debug(f"【渐进式大纲扩展】从 {current_chapter_count} 章扩展到 {current_chapter_count + increment} 章")
        logger.debug(f"{'='*70}\n")

        target_chapters = current_chapter_count + increment

        # 🎯 任务6.1：修仙题材境界跨度检查
        realm_suggestion = self.check_realm_span_and_suggest()

        # 🎆 启用分层摘要策略 - 智能准备上下文
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【分层摘要器】准备上下文")
        logger.debug(f"{'='*70}\n")
        
        context_result = self.layered_summarizer.prepare_context_for_expansion(
            outline=current_outline,
            characters=characters,
            worldview=world_setting,
            scenario="outline_expand",
            current_count=target_chapters,  # 使用目标章节数选择模型
            focus_range=None,  # 大纲扩展不需要聚焦特定范围
            project_id=self.project_id,
        )
        
        # 🔥 使用智能选择的模型
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        memory_text = context_result.get("memory_text", "")
        structured_memory = context_result.get("structured_memory", {})
        stats = context_result["stats"]
        
        logger.debug(f"\n📊 上下文优化结果:")
        logger.debug(f"   - 选择模型: {selected_model}")
        logger.debug(f"   - 原始总长: {len(current_outline) + len(characters) + len(world_setting):,}字符")
        logger.debug(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        logger.debug(f"   - 结构化记忆: {len(memory_text):,}字符 / {len(structured_memory)}类")
        logger.debug(f"   - Token使用: {stats['total_tokens']:,} / {stats['target_tokens']:,} ({stats['total_tokens']/stats['target_tokens']*100:.1f}%)\n")
        
        # 🎆 更新LLM：使用智能选择的模型
        dynamic_llm = create_model_llm(model=selected_model, temperature=0.7)
        logger.debug(f"🔄 动态创建 LLM: {selected_model}\n")

        # 🔥 修改：先执行扩展，再判断是否继续
        # 🆕 计算卷数和每卷章节数（网文通常每卷20-30章）
        chapters_per_volume = 25  # 每卷约25章
        volume_count = max(2, (target_chapters + chapters_per_volume - 1) // chapters_per_volume)

        # 第一步：执行扩展（网文卷结构）
        # 🎆 使用优化后的上下文替换原始内容
        expansion_prompt = f"""基于以下优化后的上下文，进行整体性扩展到{target_chapters}章。

{optimized_context}

【结构化记忆约束】
{memory_text or '（无可用结构化记忆）'}

请优先遵循上述结构化记忆中的主线弧线、人物状态、关系边、待回收伏笔和世界规则硬约束。

【网文结构设计原则】
⚠️ 网络小说不同于传统文学，需要特别注意：
1. **卷结构**：按"卷"划分，每卷有独立的小高潮和阶段性目标
2. **爽点密度**：每3-5章必须有一个爽点（打脸/升级/获得/反转）
3. **钩子设计**：每章结尾必须有悬念，让读者想点下一章
4. **节奏控制**：紧张-舒缓交替，避免长时间铺垫
5. **金手指展示**：定期展示主角的优势，给读者爽感
{self.genre_module.get('outline_rhythm_guide', '')}
{realm_suggestion}

【扩展要求】
🔥 重要：这不是简单增加章节，而是整体重新规划为网文卷结构

1. **整体视角**：从第1章到第{target_chapters}章的完整规划
2. **卷结构划分**：
   - 本书规划为**约{target_chapters}章**，分为**{volume_count}卷**
   - 每卷约{chapters_per_volume}章，有独立的阶段性高潮
   - 各卷章节数可灵活调整，但总数应接近{target_chapters}章

3. **人物全覆盖**：
   - 确保参考所有已生成的人物（主角、对手、支持、中立阵营）
   - 每个重要角色都有充分的出场和发展
   - 避免角色在后续章节中消失

4. **爽点节奏规划**：
   - 每5章一个小爽点（打脸/升级/获得宝物）
   - 每25章（卷末）一个大爽点（击败Boss/重大突破）
   - 爽点类型：打脸/升级/获得宝物/装逼成功/反转翻盘/美人倾心/万众瞩目

5. **钩子设计**：
   - 每章结尾必须有悬念或钩子
   - 钩子类型：悬念式/危机式/反转式/升级式/对决式

Please生成完整的{target_chapters}章规划（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[基于扩展后的完整故事，概述核心概念、主线冲突、主角成长轨迹，300-500字]

---

## 二、卷结构与章节详情（共{volume_count}卷，约{target_chapters}章）

### 【第一卷】「卷名」

**卷概述**：
- **章节范围**：第1-{chapters_per_volume}章
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

**章节详情**：

#### 第1章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}

#### 第2章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

#### 第3章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}
（以下第4章、第5章直到本卷最后一章，全部完整输出，禁止使用"...略"、"继续输出"、"其余省略"等占位符）

⚠️ 【极重要】必须逐章完整输出，每章包含所有字段，不可跳过任何章节！

---

### 【第二卷】「卷名」

**卷概述**：
- **章节范围**：...
- **阶段目标**：...

**章节详情**：

#### 第N章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}
（后续章节全部完整输出，禁止省略）

---

（后续各卷，直到第{volume_count}卷的最后一章，每卷每章都必须完整输出）

---

## 三、爽点节奏总览

| 卷 | 章节 | 爽点类型 | 爽点描述 | 强度 |
|----|------|----------|----------|------|
| 一 | 第3章 | 首秀 | 首次展示金手指 | ⭐⭐ |
| 一 | 第{chapters_per_volume}章 | 卷末大爽 | 击败本卷Boss | ⭐⭐⭐⭐⭐ |
| ... | ... | ... | ... | ... |

---

## 四、情节线索总览

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | 第X章转折 | 第{target_chapters}章 |
| 支线A | 感情 | 第X章 | 第Y章 | 第Z章 |

---

## 五、人物出场统计

| 角色 | 阵营 | 首次登场 | 关键章节 | 角色弧光 |
|------|------|----------|----------|----------|
| 主角 | 主角 | 第1章 | 1,X,Y,Z | 成长轨迹 |
| ... | ... | ... | ... | ... |"""

        logger.debug(f"【第一步】整体性扩展章节（重新规划第1-{target_chapters}章）...")
        logger.debug(f"   📌 参考优化后的上下文（{len(optimized_context):,}字符）")
        logger.debug(f"   🔄 从{current_chapter_count}章整体扩展到{target_chapters}章")
        logger.debug(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="你是一位杰出的情节架构师，精通网络小说结构设计与爽点节奏规划。"),
            HumanMessage(content=expansion_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        expansion_content = response.content
        logger.debug("✅ 章节扩展完成\n")

        # 第二步：整合更新大纲（不是简单追加，而是整体重构）
        integration_prompt = f"""基于当前大纲和新扩展的章节规划，生成一份完整的、结构清晰的大纲。

【原有大纲】
{current_outline}

【新扩展的章节规划】
{expansion_content}

【整合要求】
🔥 重要：这是整体重构，不是简单拼接

1. **不要简单堆码**：
   - 不要直接把新内容追加在后面
   - 不要保留重复的章节
   - 不要有“原有章节”和“新增章节”的分隔

2. **网文卷结构**：
   - 按"卷"划分，每卷{chapters_per_volume}章左右
   - 共{volume_count}卷，总计{target_chapters}章
   - 每卷有独立的阶段性高潮和爽点设计

3. **章节信息完整**：
   - 🔥 每章必须包含统一核心字段，并可按需要补充【爽点类型】【伏笔事项】等增强字段
   - 确保第1章到第{target_chapters}章都有详细规划
   - 所有人物都有合理出场和发展

4. **爽点和钩子集成**：
   - 爽点和钩子信息直接写在每章内，不要分离成单独表格
   - 同时在末尾提供爽点总览表便于快速查看

Please输出完整的、重新整合后的网文大纲（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[整合后的完整故事概述，300-500字]

---

## 二、卷结构与章节详情（共{volume_count}卷，约{target_chapters}章）

### 【第一卷】「卷名」

**卷概述**：
- **章节范围**：第1-{chapters_per_volume}章
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

**章节详情**：

#### 第1章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}

#### 第2章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

#### 第3章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}
（以下第4章、第5章直到本卷最后一章，全部完整输出，禁止使用"...略"、"继续输出"、"其余省略"等占位符）

⚠️ 【极重要】必须逐章完整输出，每章包含所有字段，不可跳过任何章节！

---

### 【第二卷】「卷名」

**卷概述**：
- **章节范围**：...
- **阶段目标**：...

**章节详情**：

#### 第N章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}
（后续章节全部完整输出，禁止省略）

---

## 三、爽点节奏总览

| 卷 | 章节 | 爽点类型 | 爽点描述 | 强度 |
|----|------|----------|----------|------|
| 一 | 第3章 | 首秀 | ... | ⭐⭐ |
| ... | ... | ... | ... | ... |

---

## 四、情节线索总览

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | 第X章 | 第{target_chapters}章 |

---

## 五、人物出场统计

| 角色 | 阵营 | 首次登场 | 关键章节 | 角色弧光 |
|------|------|----------|----------|----------|
| 主角 | 主角 | 第1章 | ... | ... |"""

        logger.debug(f"【第二步】整体重构大纲（最佳格式：章节详情+总览表）...")
        logger.debug(f"   🔄 重新组织所有{target_chapters}章的内容")
        logger.debug(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        messages = [
            SystemMessage(content="你是一位杰出的情节架构师，精通网络小说结构设计与卷结构整合。"),
            HumanMessage(content=integration_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        integrated_outline = response.content
        logger.debug("✅ 大纲整体重构完成\n")
        # 🆕 长篇小说目标章节数（用于判断是否继续扩展）
        long_novel_target = target_total_chapters or 100
        lower_threshold = int(long_novel_target * 0.5)
        upper_threshold = int(long_novel_target * 0.9)


        # 🔥 第三步：AI判断是否需要继续扩展（简化提示词，只传递统计信息）
        analysis_prompt = f"""你是一位资深小说策划师。Please analyze以下大纲是否 needs继续扩展。

【当前状态】
- 当前已有章节数：{target_chapters}
- 刚完成扩展：从{current_chapter_count}章扩展到{target_chapters}章
- 长篇目标总章节数：{long_novel_target}章

Please analyze：
1. **当前大纲的完整性**：是否已经覆盖了完整的故事线（开端、发展、高潮、结局）
2. **情节密度**：每章的情节容量是否合适，是否需要更多的过渡或详细描写
3. **支线发展**：是否有未展开的支线故事或人物关系
4. **伏笔和回收**：是否需要更多的伏笔铺垫

最后，以JSON格式回答：
{{
  "should_continue": true/false,
  "reason": "原因说明（100字以内）"
}}

判断标准（面向长篇小说）：
- 如果当前章节数 < {lower_threshold}，通常建议继续扩展（重点补充主线和支线）
- 如枟 {lower_threshold}-{upper_threshold} 章，根据故事完整性和情节复杂度判断
- 如果 > {upper_threshold} 章，需要非常充分的理由才继续扩展（例如仍有重要支线或伏笔尚未完成）
- 如果已有完整的故事结构，应该停止扩展"""

        logger.debug("【第三步】AI判断是否需要继续扩展...")
        logger.debug(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        messages = [
            SystemMessage(content="你是一位资深小说策划师，擅长分析大纲完整性与判断是否需要继续扩展。"),
            HumanMessage(content=analysis_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        analysis_result = response.content

        # 解析JSON结果
        import json
        import re

        # 提取JSON内容
        json_match = re.search(r'\{[\s\S]*?"should_continue"[\s\S]*?\}', analysis_result)
        should_continue = True
        continue_reason = ""

        if json_match:
            try:
                decision = json.loads(json_match.group())
                should_continue = decision.get('should_continue', True)
                continue_reason = decision.get('reason', '')
                logger.debug(f"✅ AI决策：{'继续扩展' if should_continue else '停止扩展'}")
                logger.debug(f"   原因：{continue_reason}")
            except Exception:
                logger.debug("⚠️  无法解析AI结果，默认继续扩展")
        else:
            logger.debug("⚠️  无法解析AI结果，默认继续扩展")

        logger.debug(f"{'='*70}")
        logger.debug(f"【渐进式大纲扩展】本轮完成！")
        logger.debug(f"{'='*70}\n")

        return {
            "expanded_outline": integrated_outline,  # 🔥 返回整合后的大纲
            "chapter_breakdown": expansion_content,
            "plot_arcs": {},  # 🔥 前端会智能提取摘要
            "current_chapter_count": target_chapters,
            "should_continue": should_continue,
            "continue_reason": continue_reason
        }

    def _expand_characters_incremental_with_layered_context(self, main_characters: str, world_setting: str,
                                                            plot_outline: str, current_character_count: int,
                                                            increment: int = 5,
                                                            target_total_characters: Optional[int] = None) -> Dict[str, Any]:
        """渐进式扩展人物体系

        每次增加3-6个角色，直到AI判断不再需要扩展

        Args:
            main_characters: 当前主要人物设定
            world_setting: 世界观设定
            plot_outline: 情节大纲
            current_character_count: 当前已有的人物数（如为0则自动识别）
            increment: 本次扩展的人物数（默认5个）
            target_total_characters: 长篇小说目标人物总数（如未提供则按25人进行规划判断）

        Returns:
            扩展后的人物体系字典，包含:
            - all_characters: 完整人物列表
            - character_relationships: 人物关系网络
            - role_distribution: 角色定位分布
            - current_character_count: 当前总人物数
            - should_continue: AI判断是否还需要继续扩展
            - continue_reason: 继续扩展的原因（如果需要）
        """
        # 🆕 智能识别当前人物数
        if current_character_count == 0:
            logger.debug("🔍 检测到 current_character_count=0，开始自动识别当前人物数...")
            detected_count = self.count_characters_in_text(main_characters)
            if detected_count > 0:
                current_character_count = detected_count
                logger.debug(f"🎯 识别成功！当前已有 {current_character_count} 个人物\n")
            else:
                logger.debug("🆕 未识别到人物，从 0 个开始扩展\n")

        # 🔥 新增：验证人物-情节匹配度
        if current_character_count > 0 and main_characters and plot_outline:
            logger.debug("🔍 开始验证人物-情节匹配度...")
            validation = self.character_plot_validator.validate_character_plot_alignment(
                characters=main_characters,
                plot_outline=plot_outline,
                world_setting=world_setting
            )

            logger.debug(f"📊 人物-情节匹配度: {validation['score']}/100")

            # 如果匹配度过低，建议先优化
            if validation['score'] < 60:
                logger.debug("⚠️ 匹配度较低，建议先优化现有人物与情节的关联")
                logger.debug(f"   冗余人物: {len(validation['redundant_characters'])}个")
                logger.debug(f"   缺失人物: {len(validation['missing_characters'])}个")
                logger.debug(f"   关系问题: {len(validation['relationship_issues'])}个")

                # 返回优化建议
                return {
                    "should_optimize_first": True,
                    "validation_score": validation['score'],
                    "validation_details": validation,
                    "current_character_count": current_character_count,
                    "optimization_suggestions": validation['suggestions'],
                    "message": "建议先优化现有人物与情节的关联，再进行扩展"
                }
            else:
                logger.debug(f"✅ 匹配度良好，可以继续扩展")
                if validation['missing_characters']:
                    logger.debug(f"💡 建议优先补充: {', '.join(validation['missing_characters'][:3])}")

        logger.debug(f"\n{'='*70}")
        logger.debug(f"【渐进式人物扩展】从 {current_character_count} 个扩展到 {current_character_count + increment} 个")
        logger.debug(f"{'='*70}\n")

        target_count = current_character_count + increment

        # 🎆 启用分层摘要策略 - 智能准备上下文
        context_result = self.layered_summarizer.prepare_context_for_expansion(
            outline=plot_outline,
            characters=main_characters,
            worldview=world_setting,
            scenario="character_expand",
            current_count=target_count,  # 使用目标人物数选择模型
            focus_range=None,  # 人物扩展不需要聚焦特定范围
            project_id=self.project_id,
        )
        
        # 🔥 使用智能选择的模型
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        memory_text = context_result.get("memory_text", "")
        structured_memory = context_result.get("structured_memory", {})
        stats = context_result["stats"]
        
        # 打印优化结果日志
        logger.debug(f"\n📊 上下文优化结果:")
        logger.debug(f"   - 选择模型: {selected_model}")
        logger.debug(f"   - 原始总长: {len(plot_outline) + len(main_characters) + len(world_setting):,}字符")
        logger.debug(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        logger.debug(f"   - 结构化记忆: {len(memory_text):,}字符 / {len(structured_memory)}类")
        logger.debug(f"   - Token使用: {stats['total_tokens']:,} / {stats['target_tokens']:,}\n")

        # 🎆 更新LLM：使用智能选择的模型
        dynamic_llm = create_model_llm(model=selected_model, temperature=0.8, max_tokens=4000)
        
        # 临时替换LLM
        original_llm = self.character_designer.llm
        self.character_designer.llm = dynamic_llm
        
        try:
            # 🆕 获取题材专属人物字段
            character_extra_fields = self.genre_module.get('character_extra_fields', '')
            genre_specific_hint = f"\n\n🎯 【题材专属细化】（以下为人物设定的补充字段，请结合使用）\n{character_extra_fields}" if character_extra_fields else ""

            # 🔥 修改：先执行扩展，再判断是否继续
            # 第一步：执行扩展（使用优化后的上下文）
            expansion_prompt = f"""基于以下优化后的上下文，扩展到{target_count}个角色。

{optimized_context}

【结构化记忆约束】
{memory_text or '（无可用结构化记忆）'}

请优先保持现有人物状态、关系边和待回收伏笔的一致性，新角色必须围绕这些约束补位，而不是破坏它们。

【扩展要求】
- 新增 {increment} 个角色（从第{current_character_count + 1}个开始）
- 每个新角色需要完整的人物卡信息，至少覆盖：
  * 姓名、年龄/性别
  * 故事立场：主角方/反派方/中立方/亦正亦邪
  * 角色定位、所属势力
  * 外貌锚点、性格锚点
  * 背景/当前处境、核心动机
  * 能力与限制（必须同时写优势和短板）
  * 关键关系、主线绑定
  * 成长方向（能明确再写）

🔥 重要输出格式要求：
Please直接按阵营分类输出，格式如下（每个人物必须包含完整人物卡字段，**每个字段后必须换行**）：

⚠️ 【重要：姓名创作要求】
- **必须创作独特姓名**：不要使用常见、普通的名字
- **符合题材风格**：修仙题材用古风名字，科幻题材用现代或未来感名字，西幻题材用西式名字
- **避免重复**：每个人物的名字必须不同，不要使用如“林墨”、“苏娜”、“陈朔”、“老周”、“张伟”等示例名
- **富有意境**：名字应该有寃意或符号意义，与角色性格或命运相关

## 主角阵营

### 【姓名】：（请生成独特姓名）

【年龄/性别】：...

【故事立场】：主角方

【角色定位】：...

【所属势力】：...

【外貌锚点】：...

【性格锚点】：性格：...
价值倾向：...

【背景/当前处境】：...

【核心动机】：...

【能力与限制】：能力：...
限制：...

【关键关系】：...

【主线绑定】：剧情职责：...
关联线索：...

【成长方向】：...

---

### 【姓名】：（请生成独特姓名）

【年龄/性别】：...

...

---

## 对手阵营

### 【姓名】：（请生成独特姓名）
...

## 支持角色

### 【姓名】：（请生成独特姓名）
...

## 中立角色

### 【姓名】：（请生成独特姓名）
...

注意：
1. **关键：每个字段后必须有两个换行符**，保证排版清晰
2. 不要单独列出“新增角色列表”，直接合并到各阵营中
3. 使用【姓名】格式，方便识别和统计
4. 每个阵营的角色按重要性排序
5. 人物之间使用 --- 分隔线
6. 确保所有{target_count}个角色都包含在内{genre_specific_hint}"""

            logger.debug(f"【第一步】扩展角色（{current_character_count + 1}-{target_count}个）...")
            try:
                expansion_content = self.character_designer.process(expansion_prompt, {})
                logger.debug("✅ 角色扩展完成\n")
            except Exception as e:
                logger.debug(f"❌ 角色扩展失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 第二步：整合更新人物体系（🔥 优化：仅传递现有角色摘要，避免上下文溢出）
            # 🔥 从 main_characters 中提取现有角色名单（避免传递完整上下文）
            existing_characters_summary = self._extract_character_names_summary(main_characters)

            integration_prompt = f"""Please将新扩展的角色整合到现有人物体系中，生成一份完整的、结构清晰的人物档案。

【现有角色名单】（共{current_character_count}个）
{existing_characters_summary}

【结构化记忆约束】
{memory_text or '（无可用结构化记忆）'}

【新增角色】
{expansion_content}

【整合要求】
1. **不要简单堆码**：不要直接把新内容追加在后面
2. **按阵营重新组织**：所有角色按阵营分类（主角、对手、支持、中立）
3. **信息完整但避免胖字段**：保留角色的可用信息密度，但把冗余字段折叠进“性格锚点 / 能力与限制 / 主线绑定”等核心字段
4. **统一档案格式**：所有角色使用相同的精简档案格式，直接服务后续大纲扩展和章节生成
5. **去重去重复**：如果有重复的角色，只保留一份最完整的
6. **规模控制**：在保证角色完整性的前提下，尽量让总人数接近{target_count}个（允许±2人的浮动）

Please输出完整的、重新整合后的人物档案，**每个字段后必须有两个换行符**，格式如下：

## 主角阵营

### 【姓名】：[姓名]

【年龄/性别】：...

【故事立场】：...

【角色定位】：主角/核心配角 等

【所属势力】：...

【外貌锚点】：...

【性格锚点】：性格：...
价值倾向：...

【背景/当前处境】：...

【核心动机】：...

【能力与限制】：能力：...
限制：...

【关键关系】：（仅保留当前阶段最关键的3-5条关系）

【主线绑定】：剧情职责：...
关联线索：...

【成长方向】：...

---

...（所有主角阵营角色）

## 对手阵营

### 【姓名】：[姓名]
...

## 支持角色

### 【姓名】：[姓名]
...

## 中立角色

### 【姓名】：[姓名]
...

确保所有{target_count}个角色都包含在内，按重要性排序。人物之间使用 --- 分隔。"""

            logger.debug(f"【第二步】整合更新人物体系（不进行简单堆码）...")
            try:
                integrated_characters = self.character_designer.process(integration_prompt, {})
                logger.debug("✅ 人物体系整合完成\n")
            except Exception as e:
                logger.debug(f"❌ 人物体系整合失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 第三步：生成人物关系网络
            relationship_prompt = f"""基于以下完整的人物体系，生成完整的人物关系网络。

【所有人物】
{integrated_characters}

Please以下列格式生成人物关系网络：

### 人物关系网络

**主角阵营内部**：
- [角色A] ↔ [角色B]：[关系类型]（[关系描述]）

**对手阵营内部**：
- [角色C] ↔ [角色D]：[关系类型]（[关系描述]）

**跨阵营关系**：
- [主角] ↔ [对手]：[关系类型]（[关系描述]）

**支持角色关系**：
- [支持角色] ↔ [主要角色]：[关系类型]（[关系描述]）

Please确保：
1. 包含所有{target_count}个角色
2. 关系类型包括：师徒、盟友、对手、亲人、同事、竞争等
3. 每个关系都有简短描述（20字以内）"""

            logger.debug(f"【第三步】生成人物关系网络...")
            relationships = self.character_designer.process(relationship_prompt, {})
            logger.debug("✅ 关系网络生成完成\n")

            # 第四步：统计角色分布
            distribution_input = integrated_characters
            max_chars_raw = os.getenv("CHARACTER_DISTRIBUTION_MAX_CHARS", "60000")
            try:
                max_chars = max(10000, int(max_chars_raw))
            except Exception:
                max_chars = 60000
            if len(distribution_input) > max_chars:
                distribution_input = distribution_input[:max_chars].rstrip() + "\n\n[已截断：内容过长]"
                logger.debug(f"⚠️  角色体系统计超长，已截断到 {max_chars} 字符用于分布统计")

            distribution_prompt = f"""基于以下完整的人物体系，统计角色分布。

【所有人物】
{distribution_input}

Please以以下格式输出JSON：
{{
  "主角": 数量,
  "配角": 数量,
  "对手": 数量,
  "支持角色": 数量,
  "中立角色": 数量
}}

Please确保所有数量加起来等于{target_count}。
只返回JSON，不要其他文字。"""

            logger.debug(f"【第四步】统计角色分布...")
            distribution_result = self.character_designer.process(distribution_prompt, {})
            logger.debug("✅ 角色分布统计完成\n")

            # 解析角色分布JSON
            import json
            import re

            distribution_dict = {}
            json_match = re.search(r'\{[\s\S]*?\}', distribution_result)
            if json_match:
                try:
                    distribution_dict = json.loads(json_match.group())
                    logger.debug(f"✅ 角色分布：{distribution_dict}")
                except Exception:
                    logger.debug("⚠️  无法解析角色分布JSON")


            # 🆕 长篇小说目标人物数量（用于判断是否继续扩展）
            character_target = target_total_characters or 25
            lower_threshold = max(15, character_target - 10)
            upper_threshold = character_target + 5

            # 🔥 第五步：AI判断是否需要继续扩展（在扩展完成后判断）
            # 🔥 优化：只传递统计信息，不传递完整文本，避免超过token限制
            analysis_prompt = f"""你是一位资深人物设计师。Please analyze以下人物体系是否 needs继续扩展。

【当前状态】
- 当前已有人物数：{target_count}
- 刚完成扩展：从{current_character_count}个扩展到{target_count}个
- 长篇目标人物数：{character_target}个
- 角色分布：{distribution_dict}

Please analyze：
1. **主要角色覆盖**：主角、配角、对手、师友等关键角色是否齐全
2. **角色均衡**：正面、负面、中立角色的比例是否合适

最后，以JSON格式回答：
{{
  "should_continue": true/false,
  "reason": "原因说明（100字以内）"
}}

判断标准（面向长篇小说人物体系）：
- 如果当前人物数 < {lower_threshold}，通常建议继续扩展，补足主要角色和关键配角
- 如果 {lower_threshold}-{character_target} 个，根据角色分布情况判断
- 如果 {character_target}-{upper_threshold} 个，偏向于收束人物，只在确有需要时少量补充
- 如果 > {upper_threshold} 个，需要非常充分的理由才继续扩展，避免角色过多导致人物形象被稀释"""

            logger.debug("【第五步】AI判断是否需要继续扩展...")
            analysis_result = self.character_designer.process(analysis_prompt, {})

            # 解析JSON结果
            import json
            import re

            json_match = re.search(r'\{[\s\S]*?"should_continue"[\s\S]*?\}', analysis_result)
            should_continue = True
            continue_reason = ""

            if json_match:
                try:
                    decision = json.loads(json_match.group())
                    should_continue = decision.get('should_continue', True)
                    continue_reason = decision.get('reason', '')
                    logger.debug(f"✅ AI决策：{'继续扩展' if should_continue else '停止扩展'}")
                    logger.debug(f"   原因：{continue_reason}")
                except Exception:
                    logger.debug("⚠️  无法解析AI结果，默认继续扩展")
            else:
                logger.debug("⚠️  无法解析AI结果，默认继续扩展")

            # 🔥 新增：扩展后二次验证
            post_validation_score = 0
            post_validation_details = {}

            if plot_outline:
                logger.debug("🔍 开始扩展后验证...")
                post_validation = self.character_plot_validator.validate_character_plot_alignment(
                    characters=integrated_characters,
                    plot_outline=plot_outline,
                    world_setting=world_setting
                )
                post_validation_score = post_validation['score']
                post_validation_details = post_validation

                logger.debug(f"📊 扩展后匹配度: {post_validation_score}/100")

                if post_validation_score >= 70:
                    logger.debug("✅ 人物与情节匹配良好")
                elif post_validation_score >= 60:
                    logger.debug("⚠️ 匹配度一般，建议关注以下问题：")
                    if post_validation['redundant_characters']:
                        logger.debug(f"   - 冗余人物: {', '.join(post_validation['redundant_characters'][:3])}")
                    if post_validation['missing_characters']:
                        logger.debug(f"   - 缺失人物: {', '.join(post_validation['missing_characters'][:3])}")
                else:
                    logger.debug("❌ 匹配度较低，强烈建议优化")

            logger.debug(f"{'='*70}")
            logger.debug(f"【渐进式人物扩展】本轮完成！")
            logger.debug(f"{'='*70}\n")

            return {
                "all_characters": integrated_characters,  # 🔥 返回整合后的人物体系
                "character_relationships": relationships,  # 🔥 现在生成完整的关系网络
                "role_distribution": distribution_dict,  # 🔥 现在生成角色分布
                "current_character_count": target_count,
                "should_continue": should_continue,
                "continue_reason": continue_reason,
                "post_validation_score": post_validation_score,  # 🔥 新增：扩展后匹配度
                "post_validation_details": post_validation_details  # 🔥 新增：详细验证结果
            }
        finally:
            # 🔄 恢复原始 LLM
            self.character_designer.llm = original_llm

