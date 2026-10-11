from __future__ import annotations

import os
import json
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from core.unified_llm_client import get_llm_client, UnifiedLLMClient
from core.model_resolution import TaskType
from ..chapter_splitter import ChapterInfo, ChapterType
from ._base import AnalysisResult

logger = logging.getLogger(__name__)

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]


class AnalysisType(str, Enum):
    """分析类型"""
    CHARACTERS = "characters"
    WORLDVIEW = "worldview"
    PLOT = "plot"
    STYLE = "style"
    CONCEPTS = "concepts"
    THEMES = "themes"
    CHAPTER_SUMMARY = "chapter_summary"


@dataclass
class ChapterSummary:
    chapter_index: int
    title: str
    summary: str
    characters: List[str]
    key_events: List[str]



class TypeAnalysisMixin:
    async def analyze_characters(
        self,
        chapters: List[ChapterInfo],
    ) -> AnalysisResult:
        """
        分析人物体系
        
        提取主要人物、配角、人物关系等
        """
        # 智能采样配置
        config = self._get_smart_sample_config(chapters)
        
        # 选择样本章节（开头、中间、结尾）
        samples = self._select_sample_chapters(chapters, config['sample_chapters'])
        
        # 构建分析内容
        content_for_analysis = self._build_chapter_summary(samples, config['words_per_chapter'])
        
        prompt = f"""请分析以下小说内容，提取完整的人物体系。

【小说片段】
{content_for_analysis}

请以JSON格式输出分析结果，严格遵循以下结构：
{{
    "characters": [
        {{
            "name": "人物姓名",
            "aliases": ["别名1", "别名2"],
            "role_position": "角色定位（如主角/盟友/导师/对手/情报角色）",
            "description": "人物简介（50字以内）",
            "story_stance": "故事立场（主角方/反派方/中立方/亦正亦邪/未提及）",
            "faction": "所属势力/组织/门派（未提及则写未提及）",
            "age_gender": "年龄/性别（如青年男性/中年女性，无法判断写未提及）",
            "appearance_anchor": "外貌锚点（20字内，无法判断写未提及）",
            "personality_anchor": ["性格锚点1", "性格锚点2"],
            "background_status": "背景/当前处境（25字内，无法判断写未提及）",
            "worldview": "价值倾向/处事原则（20字内，用于补足性格锚点）",
            "ability_outline": ["能力与限制中的优势部分"],
            "motivation": "核心动机（20字内，无法判断写未提及）",
            "limitation": "能力与限制中的代价/短板（20字内，无法判断写未提及）",
            "growth_direction": "成长方向（30字以内）",
            "mainline_role": "主线绑定中的剧情职责（25字内）",
            "mainline_clues": "主线绑定中的关联线索/证据（30字内，无法判断写未提及）",
            "first_appearance_chapter": 1,
            "importance_score": 0.9,
            "importance_level": "主角/核心角色/重要角色/次要角色/边缘角色/群众角色"
        }}
    ],
    "character_relationships": [
        {{
            "character1": "人物1",
            "character2": "人物2", 
            "relationship": "关系类型",
            "description": "关系描述"
        }}
    ],
    "factions": [
        {{
            "name": "势力/组织名",
            "members": ["成员1", "成员2"],
            "description": "势力描述"
        }}
    ]
}}

注意：
1. 主角importance_score应为0.9-1.0
2. 只提取明确出现的人物，不要猜测
3. 人物关系要基于文本证据
4. 故事立场/所属势力必须有明确文本证据，否则写“未提及”
5. 禁止输出 ???、TBD 等占位值
6. 对主要人物优先补全年龄/性别、外貌锚点、性格锚点、主线绑定
7. 优先输出 limitation / growth_direction / mainline_role / mainline_clues 这些新语义键
8. 统一输出 role_position，禁止输出旧字段 role"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)

        if not isinstance(parsed, dict):
            parsed = {}

        characters = self._normalize_character_entries(parsed)
        counts_sorted = sorted(
            [char.get("appearance_count", 0) for char in characters if char.get("appearance_count", 0) > 0],
            reverse=True
        )
        max_count = counts_sorted[0] if counts_sorted else 0

        def importance_level_for_count(count: int) -> str:
            if not counts_sorted or count <= 0:
                return "边缘角色"
            try:
                rank_index = counts_sorted.index(count)
            except ValueError:
                rank_index = len(counts_sorted) - 1
            ratio = rank_index / max(len(counts_sorted), 1)
            if ratio < 0.1:
                return "核心角色"
            if ratio < 0.3:
                return "重要角色"
            if ratio < 0.6:
                return "次要角色"
            return "边缘角色"

        for char in characters:
            if not isinstance(char, dict):
                continue
            if self._is_placeholder_character_text(char.get("story_stance"), allow_not_mentioned=True):
                char["story_stance"] = "未提及"
            if self._is_placeholder_character_text(char.get("faction"), allow_not_mentioned=True):
                char["faction"] = "未提及"
            if self._is_placeholder_character_text(char.get("importance_level"), allow_not_mentioned=True):
                char["importance_level"] = importance_level_for_count(char.get("appearance_count", 0))
            if max_count > 0 and not char.get("importance_score"):
                char["importance_score"] = round(char.get("appearance_count", 0) / max_count, 2)
            self._infer_character_defaults(char)
            if char.get("role_position") == "主角":
                char["importance_level"] = "主角"

        parsed = self._replace_character_entries(parsed, characters)

        return self._build_analysis_result(
            analysis_type=AnalysisType.CHARACTERS,
            content=parsed,
            confidence=0.85,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )
    
    # ==================== 世界观分析 ====================
    
    async def analyze_worldview(
        self,
        chapters: List[ChapterInfo],
        sample_chapters: int = 15
    ) -> AnalysisResult:
        """
        分析世界观设定
        
        提取世界类型、地点、势力、规则体系等
        """
        samples = self._select_sample_chapters(chapters, sample_chapters)
        content_for_analysis = self._build_chapter_summary(samples)
        
        prompt = f"""请分析以下小说内容，提取世界观设定。

【小说片段】
{content_for_analysis}

请以JSON格式输出分析结果：
{{
    "world_type": "世界类型（如：玄幻、仙侠、都市、科幻等）",
    "time_period": "时代背景",
    "world_description": "世界整体描述（100字以内）",
    "locations": [
        {{
            "name": "地点名称",
            "type": "地点类型（城市/门派/国家/位面等）",
            "description": "地点描述",
            "importance": "high/medium/low"
        }}
    ],
    "power_systems": [
        {{
            "name": "体系名称（如：修仙、斗气、魔法等）",
            "description": "体系描述",
            "levels": ["等级1", "等级2", "等级3"],
            "rules": ["规则1", "规则2"]
        }}
    ],
    "factions": [
        {{
            "name": "势力名称",
            "type": "势力类型",
            "description": "势力描述",
            "alignment": "正派/反派/中立"
        }}
    ],
    "special_items": [
        {{
            "name": "物品名称",
            "type": "物品类型",
            "description": "物品描述"
        }}
    ],
    "world_rules": [
        "世界运行的重要规则1",
        "世界运行的重要规则2"
    ]
}}

注意：
1. 只提取文本中明确提到的设定
2. 不要添加未出现的内容
3. 地点和势力按重要性排序"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.WORLDVIEW,
            content=parsed,
            confidence=0.80,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )
    
    # ==================== 情节分析 ====================
    
    async def analyze_plot(
        self,
        chapters: List[ChapterInfo]
    ) -> AnalysisResult:
        """
        分析情节脉络
        
        提取主线剧情、关键事件、冲突节点等
        """
        # 使用所有章节的摘要信息
        chapter_summaries = []
        for ch in chapters:
            summary = f"第{ch.number}章 {ch.title}"
            if ch.content:
                # 取每章开头和结尾的片段
                content = ch.content[:500] + "..." + ch.content[-300:] if len(ch.content) > 800 else ch.content
                summary += f"\n{content[:800]}"
            chapter_summaries.append(summary)
        
        # 分批处理
        batch_results = []
        for i in range(0, len(chapter_summaries), self.BATCH_SIZE):
            batch = chapter_summaries[i:i + self.BATCH_SIZE]
            batch_text = "\n\n---\n\n".join(batch)
            
            prompt = f"""请分析以下章节内容，提取情节要点。

【章节内容】
{batch_text}

请提取这些章节中的关键情节事件，以JSON格式输出：
{{
    "events": [
        {{
            "chapter": 章节号,
            "event": "事件描述（30字以内）",
            "type": "转折点/冲突/高潮/伏笔/日常",
            "characters_involved": ["涉及人物"],
            "impact": "事件影响（20字以内）"
        }}
    ]
}}"""

            result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
            parsed = self._parse_json_response(result)
            if "events" in parsed:
                batch_results.extend(parsed["events"])
        
        # 合并并识别主线
        main_plot_prompt = f"""基于以下事件列表，分析整体情节结构。

【事件列表】
{json.dumps(batch_results[:50], ensure_ascii=False, indent=2)}

请以JSON格式输出完整的情节分析：
{{
    "main_plot": "主线剧情概述（200字以内）",
    "plot_arcs": [
        {{
            "name": "剧情弧名称",
            "description": "剧情弧描述",
            "chapters": [起始章, 结束章],
            "type": "开篇/发展/高潮/收尾"
        }}
    ],
    "turning_points": [
        {{
            "chapter": 章节号,
            "event": "转折事件",
            "significance": "重要性说明"
        }}
    ],
    "conflicts": [
        {{
            "type": "冲突类型",
            "parties": ["冲突方1", "冲突方2"],
            "description": "冲突描述",
            "status": "进行中/已解决"
        }}
    ],
    "key_events": {json.dumps(batch_results[:20], ensure_ascii=False)}
}}"""

        result = await self._call_llm_with_retry(main_plot_prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        # 确保key_events存在
        if "key_events" not in parsed:
            parsed["key_events"] = batch_results[:30]
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.PLOT,
            content=parsed,
            confidence=0.75,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )
    
    # ==================== 写作风格分析 ====================
    
    async def analyze_style(
        self,
        chapters: List[ChapterInfo],
        sample_chapters: int = 10
    ) -> AnalysisResult:
        """
        分析写作风格
        
        提取叙事视角、语言特点、对话风格等
        """
        samples = self._select_sample_chapters(chapters, sample_chapters)
        
        # 提取纯文本片段用于风格分析
        text_samples = []
        for ch in samples:
            if ch.content:
                # 取随机片段
                content = ch.content
                if len(content) > 1000:
                    start = len(content) // 4
                    text_samples.append(content[start:start + 800])
                else:
                    text_samples.append(content)
        
        sample_text = "\n\n---\n\n".join(text_samples[:5])
        
        prompt = f"""请分析以下小说文本的写作风格。

【文本样本】
{sample_text}

请以JSON格式输出风格分析结果：
{{
    "narrative_perspective": "叙事视角（第一人称/第三人称限知/第三人称全知）",
    "narrative_style": "叙事风格描述",
    "tone": "整体基调（如：轻松幽默/严肃深沉/热血激昂等）",
    "pacing": "节奏特点（快节奏/慢热/张弛有度等）",
    "language_features": {{
        "vocabulary_level": "词汇水平（通俗/文雅/专业术语多等）",
        "sentence_style": "句式特点（长句为主/短句有力/混合等）",
        "rhetoric": ["常用修辞手法1", "常用修辞手法2"],
        "dialogue_style": "对话风格描述"
    }},
    "description_style": {{
        "scene_description": "场景描写特点",
        "character_description": "人物描写特点",
        "action_description": "动作描写特点",
        "psychological_description": "心理描写特点"
    }},
    "strengths": ["写作优点1", "写作优点2"],
    "unique_features": ["独特风格特征1", "独特风格特征2"],
    "similar_authors": ["风格相似的作者（如有）"],
    "genre_conventions": "是否遵循类型惯例及程度"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.STYLE,
            content=parsed,
            confidence=0.80,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )

    async def analyze_concepts(
        self,
        chapters: List[ChapterInfo],
        sample_chapters: int = 15
    ) -> AnalysisResult:
        """
        分析关键概念/术语

        提取续写阶段最需要复用的专有名词、规则、物品与能力。
        """
        samples = self._select_sample_chapters(chapters, sample_chapters)
        content_for_analysis = self._build_chapter_summary(samples, 1000)

        prompt = f"""请分析以下小说内容，提取适合后续续写使用的关键概念与专有名词。

【小说片段】
{content_for_analysis}

请以JSON格式输出：
{{
    "terms": [
        {{
            "term": "术语/概念名",
            "definition": "简明定义（40字以内）",
            "category": "术语/组织/物品/能力/地点/规则",
            "first_mention_chapter": 1
        }}
    ],
    "special_items": [
        {{
            "name": "重要物品名",
            "description": "物品作用（30字以内）"
        }}
    ],
    "techniques": [
        {{
            "name": "能力/技巧名",
            "description": "能力说明（30字以内）"
        }}
    ]
}}

要求：
1. 仅提取明确出现且对世界观/剧情推进有价值的概念
2. 普通称呼、泛化名词不要纳入 terms
3. first_mention_chapter 尽量依据文本判断，无法确认时填首次明显出现的章节
4. definition 要面向续写使用，强调“是什么、有什么用”"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)

        if "terms" not in parsed:
            parsed["terms"] = []
        if "special_items" not in parsed:
            parsed["special_items"] = []
        if "techniques" not in parsed:
            parsed["techniques"] = []

        return self._build_analysis_result(
            analysis_type=AnalysisType.CONCEPTS,
            content=parsed,
            confidence=0.78,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )

    # ==================== 辅助方法 ====================
    
