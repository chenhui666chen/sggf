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

class LegacyOutlineMixin:
    def _legacy_expand_plot_outline(self, current_outline: str, world_setting: str,
                          characters: str, target_chapters: int = 50) -> Dict[str, Any]:
        """扩展情节大纲

        将简短大纲扩展为适合长篇小说的详细章节规划

        Args:
            current_outline: 当前的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            target_chapters: 目标章节数（默认50章，约150万字）

        Returns:
            扩展后的大纲字典，包含:
            - expanded_outline: 扩展后的完整大纲
            - chapter_breakdown: 章节分解（每章简要说明）
            - plot_arcs: 情节线索分析
            - expansion_suggestions: 扩展建议
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【情节大纲扩展器】启动大纲扩展，目标章节数: {target_chapters}")
        logger.debug(f"{'='*70}\n")

        # 第一步：分析当前大纲的可扩展点
        analysis_prompt = f"""你是一位资深小说策划师。请分析以下简短大纲的扩展潜力。

【当前大纲】
{current_outline}

【世界观】
{world_setting}

【人物设定】
{characters}

请分析：
1. **主线情节可扩展点**：识别可以深入展开的情节环节
2. **支线剧情机会**：可以添加哪些有价值的支线故事
3. **情节转折点**：需要增加哪些铺垫和转折
4. **节奏分布建议**：如何分配高潮、低潮、过渡章节
5. **伏笔埋设点**：可以在哪些地方设置伏笔

Please给出具体分析，为扩展到{target_chapters}章提供依据。"""

        logger.debug("【第一步】分析大纲扩展潜力...")
        expansion_analysis = self.creative_director.process(analysis_prompt, {})
        logger.debug("✅ 扩展潜力分析完成\n")

        # 第二步：生成情节线索
        plot_arcs_prompt = f"""基于以下分析，设计长篇小说的情节线索体系。

【扩展分析】
{expansion_analysis}

【原始大纲】
{current_outline}

Please design：
1. **主线情节**：整本书的核心故事线（占比40%）
2. **A支线**：与主线紧密相关的次要故事线（占比25%）
3. **B支线**：人物成长或感情线（占比20%）
4. **C支线**：世界观探索或社会背景线（占比15%）

每条线索需要包括：
- 起始章节范围
- 核心冲突
- 关键转折点
- 与其他线索的交织点
- 高潮和解决方案

目标章节数：{target_chapters}章"""

        logger.debug("【第二步】设计多线索情节体系...")
        plot_arcs = self.plot_architect.process(plot_arcs_prompt, {})
        logger.debug("✅ 情节线索设计完成\n")

        # 第三步：生成章节分解
        chapter_breakdown_prompt = f"""基于以下情节线索，生成详细的章节分解（{target_chapters}章）。

【情节线索】
{plot_arcs}

【原始设定】
- 世界观: {world_setting}
- 人物: {characters}

请为每一章生成结构清晰的简要说明，统一使用当前细纲字段，格式如下：

第1章：[标题]
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

第2章：[标题]
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

...（直到第{target_chapters}章）

要求：
1. 确保情节发展节奏合理（避免前松后紧）
2. 适当分布高潮章节（每10-15章一个小高潮）
3. 支线穿插自然，不影响主线推进
4. 伏笔和回收配对明确
5. 确保所有主要角色在不同阶段都有出场与推进，避免长时间“消失”。
"""

        logger.debug(f"【第三步】生成{target_chapters}章详细分解...")
        chapter_breakdown = self.plot_architect.process(chapter_breakdown_prompt, {})
        logger.debug("✅ 章节分解完成\n")

        # 第四步：生成完整扩展大纲
        expanded_outline_prompt = f"""基于以下信息，撰写完整的长篇小说情节大纲。

【章节分解】
{chapter_breakdown}

【情节线索】
{plot_arcs}

Please撰写一份完整的情节大纲，包括：
1. **故事概述**（500字）
2. **情节发展**（按起承转合分四部分）
3. **重要转折点**（列出5-8个关键转折）
4. **高潮设计**（中期高潮 + 最终高潮）
5. **结局规划**（开放式/封闭式，是否留续集空间）

这份大纲将指导{target_chapters}章的创作。"""

        logger.debug("【第四步】生成完整扩展大纲...")
        expanded_outline = self.creative_director.process(expanded_outline_prompt, {})
        logger.debug("✅ 完整大纲生成完成\n")

        logger.debug(f"{'='*70}")
        logger.debug(f"【情节大纲扩展器】扩展完成！")
        logger.debug(f"{'='*70}\n")

        return {
            "expanded_outline": expanded_outline,
            "chapter_breakdown": chapter_breakdown,
            "plot_arcs": plot_arcs,
            "expansion_analysis": expansion_analysis,
            "target_chapters": target_chapters
        }

    def _legacy_expand_characters(self, main_characters: str, world_setting: str,
                        plot_outline: str, target_count: int = 15) -> Dict[str, Any]:
        """扩展人物体系

        基于主要人物自动生成配角、对手、辅助角色等

        Args:
            main_characters: 当前主要人物设定
            world_setting: 世界观设定
            plot_outline: 情节大纲
            target_count: 目标人物总数（默认15个）

        Returns:
            扩展后的人物体系字典，包含:
            - all_characters: 完整人物列表
            - character_relationships: 人物关系网络
            - character_arcs: 人物成长线
            - role_distribution: 角色定位分布
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【人物体系扩展器】启动人物扩展，目标人物数: {target_count}")
        logger.debug(f"{'='*70}\n")

        # 第一步：分析现有人物和需求
        analysis_prompt = f"""你是一位资深人物设计师。请分析以下人物体系的扩展需求。

【当前主要人物】
{main_characters}

【世界观】
{world_setting}

【情节大纲】
{plot_outline}

Please分析：
1. **现有人物数量**：当前有几个主要人物
2. **角色类型缺口**：缺少哪些类型的角色（对手、导师、辅助者、中立者等）
3. **情节需求分析**：根据情节发展，需要增加哪些角色
4. **人物关系机会**：可以设计哪些有趣的人物关系
5. **多样性建议**：如何增加人物的多样性和丰富性

目标人物总数：{target_count}个（包括主角、配角、次要角色）"""

        logger.debug("【第一步】分析人物扩展需求...")
        character_analysis = self.character_designer.process(analysis_prompt, {})
        logger.debug("✅ 人物需求分析完成\n")

        # 第二步：设计角色定位分布
        primary_character = main_characters.splitlines()[0] if main_characters else "待定"
        role_distribution_prompt = f"""基于以下分析，设计人物角色定位体系。

【人物需求分析】
{character_analysis}

【现有主角】
{main_characters}

Please design{target_count}个人物的角色定位， including：

1. **主角阵营**（3-5人）
   - 主角：{primary_character}
   - 核心盟友：...
   - 导师/引路人：...

2. **对手阵营**（2-4人）
   - 主要反派：...
   - 次要对手：...
   - 中期敌人（后期可能转化）：...

3. **中立/辅助角色**（5-8人）
   - 信息提供者：...
   - 技能支持者：...
   - 情感陪伴者：...
   - 社会背景人物：...

每个角色需要注明：
- 姓名和基本设定（1句话）
- 在故事中的作用
- 与主角的关系
"""

        logger.debug("【第二步】设计角色定位体系...")
        role_distribution = self.character_designer.process(role_distribution_prompt, {})
        logger.debug("✅ 角色定位设计完成\n")

        # 第三步：生成完整人物档案
        character_profiles_prompt = f"""基于以下角色定位，为每个人物生成完整档案。

【角色定位】
{role_distribution}

【世界观】
{world_setting}

Please为{target_count}个人物生成详细档案，每个人物包括：

**格式模板**：
---
【姓名】：...
【年龄/性别】：...
【故事立场】：（主角方/反派方/中立方/亦正亦邪）
【角色定位】：（主角/盟友/对手/支持角色/中立角色等）
【所属势力】：（具体组织或无）
【外貌锚点】：（2-3句）
【性格锚点】：（可写成“性格：... / 价值倾向：...”）
【背景/当前处境】：（3-5句，简要说明过去经历与当前局面）
【核心动机】：（为什么参与故事，想要什么）
【能力与限制】：（可写成“能力：... / 限制：...”）
【关键关系】：（仅保留当前阶段最关键的3-5条关系）
【主线绑定】：（只写当前仍驱动剧情的“剧情职责：... / 关联线索：...”）
【成长方向】：（在故事中的变化，尽量用“从……到……”描述）
---

要求：
1. 人物要立体，有优点也有缺点
2. 避免脸谱化和刻板印象
3. 确保人物之间有化学反应
4. 每个人物都要有存在的价值
5. 【关键关系】不要累加已解决、已击杀、已退场或纯背景关系
6. 【主线绑定】不要写成跨阶段总账，只保留当前可直接调度的职责与线索
"""

        logger.debug(f"【第三步】生成{target_count}个人物完整档案...")
        all_characters = self.character_designer.process(character_profiles_prompt, {})
        logger.debug("✅ 人物档案生成完成\n")

        # 第四步：生成人物关系网络
        relationships_prompt = f"""基于以下人物档案，设计人物关系网络图。

【所有人物】
{all_characters}

Please design人物关系网络， including：

1. **核心关系链**
   - 主角 ↔ 盟友
   - 主角 ↔ 对手
   - 主角 ↔ 导师

2. **三角关系**
   - 人物A ↔ 人物B ↔ 人物C
   - 可以是友情、爱情、竞争等

3. **隐藏关系**
   - 在故事中后期揭示的关系
   - 意想不到的联系

4. **关系演变线**
   - 敌人→盟友
   - 陌生→亲密
   - 信任→背叛

格式示例：
- 主角 ⇄ 盟友A：战友关系，相互信任（第1章建立）
- 主角 → 导师B：单向崇拜，导师引导（第5章出现）
- 主角 ⇄ 反派C：宿敌关系，理念冲突（第10章首次交锋）
"""

        logger.debug("【第四步】生成人物关系网络...")
        character_relationships = self.character_designer.process(relationships_prompt, {})
        logger.debug("✅ 人物关系网络完成\n")

        logger.debug(f"{'='*70}")
        logger.debug(f"【人物体系扩展器】扩展完成！")
        logger.debug(f"{'='*70}\n")

        return {
            "all_characters": all_characters,
            "character_relationships": character_relationships,
            "role_distribution": role_distribution,
            "character_analysis": character_analysis,
            "target_count": target_count
        }

    def _legacy_generate_expansion_summary(self, outline_expansion: Dict[str, Any],
                                  character_expansion: Dict[str, Any]) -> str:
        """生成扩展总结报告

        Args:
            outline_expansion: 情节扩展结果
            character_expansion: 人物扩展结果

        Returns:
            格式化的扩展总结报告
        """
        summary = f"""
{'='*70}
【长篇小说扩展总结报告】
{'='*70}

## 一、情节大纲扩展

### 目标章节数
{outline_expansion.get('target_chapters', 'N/A')} 章

### 扩展策略
{outline_expansion.get('expansion_analysis', 'N/A')[:300]}...

### 情节线索
{outline_expansion.get('plot_arcs', 'N/A')[:300]}...

### 章节分解（示例前5章）
{outline_expansion.get('chapter_breakdown', 'N/A')[:500]}...

---

## 二、人物体系扩展

### 目标人物数
{character_expansion.get('target_count', 'N/A')} 个

### 角色定位
{character_expansion.get('role_distribution', 'N/A')[:300]}...

### 人物关系网络
{character_expansion.get('character_relationships', 'N/A')[:300]}...

---

## 三、实施建议

### 创作顺序
1. 使用扩展后的大纲更新 project_settings.plot_outline
2. 将扩展后的人物档案更新到 project_settings.characters
3. 保存章节分解到知识库，作为后续创作参考
4. 保存人物关系网络到知识库
5. 开始按章节顺序创作

### 注意事项
⚠️ 扩展后的内容较长，建议分阶段实施
⚠️ 在创作过程中可以根据实际情况调整细节
⚠️ 定期检查情节和人物的一致性

{'='*70}
"""
        return summary

