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



class SynthesisMixin:
    async def _synthesize_from_summaries(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]],
        analysis_type: AnalysisType
    ) -> AnalysisResult:
        """
        基于章节摘要汇总分析
        
        输入：所有章节的摘要信息
        输出：对应类型的分析结果
        """
        if analysis_type == AnalysisType.CHARACTERS:
            return await self._synthesize_characters(chapters, summaries)
        elif analysis_type == AnalysisType.WORLDVIEW:
            return await self._synthesize_worldview(chapters, summaries)
        elif analysis_type == AnalysisType.PLOT:
            return await self._synthesize_plot(chapters, summaries)
        elif analysis_type == AnalysisType.STYLE:
            return await self._synthesize_style(chapters, summaries)
        elif analysis_type == AnalysisType.CONCEPTS:
            return await self._synthesize_concepts(chapters, summaries)
        else:
            raise ValueError(f"不支持的汇总分析类型: {analysis_type}")
    
    async def _synthesize_characters(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析人物体系"""
        # 统计人物出场频次
        character_appearances = {}
        for s in summaries:
            for char in s.get("characters_appeared", []):
                if char not in character_appearances:
                    character_appearances[char] = {
                        "count": 0,
                        "first_chapter": s["chapter_number"],
                        "chapters": []
                    }
                character_appearances[char]["count"] += 1
                character_appearances[char]["chapters"].append(s["chapter_number"])

        # 汇总人物线索（故事立场/所属势力）
        character_clues: Dict[str, Dict[str, List[str]]] = {}
        for s in summaries:
            for clue in s.get("character_clues", []) or []:
                name = str(clue.get("name") or "").strip()
                if not name:
                    continue
                story_stance = str(clue.get("story_stance") or "").strip()
                faction = str(clue.get("faction") or "").strip()
                evidence = str(clue.get("evidence") or "").strip()
                entry = character_clues.setdefault(name, {"story_stance": [], "faction": [], "evidence": []})
                if story_stance and story_stance != "未提及":
                    entry["story_stance"].append(story_stance)
                if faction and faction != "未提及":
                    entry["faction"].append(faction)
                if evidence:
                    entry["evidence"].append(evidence)

        character_clues_summary = {
            name: {
                "story_stance": list(dict.fromkeys(values["story_stance"]))[:3],
                "faction": list(dict.fromkeys(values["faction"]))[:3],
                "evidence": list(dict.fromkeys(values["evidence"]))[:3],
            }
            for name, values in character_clues.items()
        }
        
        # 构建汇总提示词
        char_stats = json.dumps(
            {k: v["count"] for k, v in sorted(
                character_appearances.items(), 
                key=lambda x: x[1]["count"], 
                reverse=True
            )[:20]},
            ensure_ascii=False
        )
        
        # 提取关键事件中的人物关系线索
        key_events_text = "\n".join([
            f"第{s['chapter_number']}章: " + ", ".join(s.get("key_events", [])[:2])
            for s in summaries[:50]  # 取前50章的事件
        ])
        
        prompt = f"""基于以下全书统计信息，分析人物体系。

【人物出场统计（姓名: 出场次数）】
{char_stats}

【人物线索（故事立场/所属势力/证据）】
{json.dumps(character_clues_summary, ensure_ascii=False)}

【关键事件线索】
{key_events_text}

【全书信息】
总章数: {len(chapters)}章

请分析并输出JSON:
{{
    "characters": [
        {{
            "name": "人物姓名",
            "role_position": "角色定位（如主角/盟友/导师/对手/情报角色）",
            "description": "人物简介（50字）",
            "story_stance": "故事立场（主角方/反派方/中立方/亦正亦邪/未提及）",
            "faction": "所属势力/组织/门派（未提及则写未提及）",
            "age_gender": "年龄/性别（如青年男性/中年女性，无法判断写未提及）",
            "appearance_anchor": "外貌锚点（20字内，无法判断写未提及）",
            "personality_anchor": "性格锚点（20字内，概括最稳定的处事特征）",
            "background_status": "背景/当前处境（25字内，无法判断写未提及）",
            "worldview": "价值倾向/处事原则（20字内，用于补足性格锚点）",
            "motivation": "核心动机（20字内，无法判断写未提及）",
            "ability_outline": "能力与限制中的优势部分（20字内，无法判断写未提及）",
            "limitation": "能力与限制中的代价/短板（20字内，无法判断写未提及）",
            "growth_direction": "成长方向（25字内，无法判断写未提及）",
            "mainline_role": "主线绑定中的剧情职责（25字内）",
            "mainline_clues": "主线绑定中的关联线索/证据（30字内，无法判断写未提及）",
            "first_appearance_chapter": 1,
            "appearance_count": 出场次数,
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
    ]
}}

注意：
1. 出场次数最多的通常是主角
2. 主角importance_score为0.9-1.0
3. 故事立场/所属势力必须有明确文本证据，否则写“未提及”
4. 关系基于事件线索推断
5. 人物字段必须尽量补全，禁止输出 ???、TBD 等占位值
6. 对主要人物优先补全年龄/性别、外貌锚点、性格锚点、主线绑定
7. 优先输出 limitation / growth_direction / mainline_role / mainline_clues 这些新语义键
8. 统一输出 role_position，禁止输出旧字段 role"""

        # 使用汇总分析模型
        try:
            result = await self._call_synthesis_llm(prompt)
            parsed = self._parse_json_response(result)
            if parsed.get("parse_error"):
                raise ValueError("人物汇总 JSON 解析失败")
        except Exception as exc:
            logger.warning(f"人物汇总分析失败，回退到规则模式: {exc}")
            parsed = self._build_fallback_character_analysis(character_appearances)
        
        counts_sorted = sorted(
            [value["count"] for value in character_appearances.values() if value.get("count", 0) > 0],
            reverse=True
        )
        max_count = counts_sorted[0] if counts_sorted else 0

        def importance_level_for(name: str) -> str:
            count = character_appearances.get(name, {}).get("count", 0)
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

        def fill_character_fields(char: Dict[str, Any]) -> None:
            name = str(char.get("name") or "").strip()
            if not name:
                return
            if name in character_appearances:
                char.setdefault("appearance_count", character_appearances[name].get("count", 0))
                char.setdefault("first_appearance_chapter", character_appearances[name].get("first_chapter"))
                if max_count > 0 and not char.get("importance_score"):
                    char["importance_score"] = round(character_appearances[name].get("count", 0) / max_count, 2)
            char["importance_level"] = importance_level_for(name)
            if self._is_placeholder_character_text(char.get("story_stance"), allow_not_mentioned=True):
                char["story_stance"] = "未提及"
            if self._is_placeholder_character_text(char.get("faction"), allow_not_mentioned=True):
                char["faction"] = "未提及"
            clues = character_clues_summary.get(name, {})
            if clues:
                if self._is_placeholder_character_text(char.get("story_stance"), allow_not_mentioned=True) and clues.get("story_stance"):
                    char["story_stance"] = clues["story_stance"][0]
                if self._is_placeholder_character_text(char.get("faction"), allow_not_mentioned=True) and clues.get("faction"):
                    char["faction"] = clues["faction"][0]
                evidence_text = self._build_character_clues(
                    evidence=clues.get("evidence") or [],
                    first_appearance_chapter=char.get("first_appearance_chapter"),
                    appearance_count=char.get("appearance_count"),
                )
                if evidence_text and self._is_placeholder_character_text(char.get("mainline_clues")):
                    char["mainline_clues"] = evidence_text

            self._infer_character_defaults(char)
            if char.get("role_position") == "主角":
                char["importance_level"] = "主角"
        if isinstance(parsed, dict):
            characters = self._normalize_character_entries(parsed)
            for char in characters:
                fill_character_fields(char)
            parsed = self._replace_character_entries(parsed, characters)

        # 补充统计信息
        parsed["character_statistics"] = character_appearances
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.CHARACTERS,
            content=parsed,
            confidence=0.90,  # 基于全书统计，可信度更高
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )
    
    async def _synthesize_worldview(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析世界观"""
        # 统计场景出现频次
        settings = {}
        for s in summaries:
            setting = s.get("setting", "")
            if setting and setting != "":
                settings[setting] = settings.get(setting, 0) + 1
        
        # 按出现频次排序
        top_settings = sorted(settings.items(), key=lambda x: x[1], reverse=True)[:15]
        
        # 提取前20章的详细信息（开篇世界观建立）
        opening_summaries = "\n".join([
            f"第{s['chapter_number']}章 {s['title']}: {s['summary']} [场景: {s.get('setting', '')}]"
            for s in summaries[:20]
        ])
        
        prompt = f"""基于以下全书统计信息，分析世界观设定。

【场景统计（场景: 出现次数）】
{json.dumps(dict(top_settings), ensure_ascii=False)}

【开篇世界观建立（前20章）】
{opening_summaries}

请分析并输出JSON:
{{
    "world_type": "世界类型（玄幻/仙侠/都市/科幻等）",
    "time_period": "时代背景",
    "world_description": "世界整体描述（100字）",
    "locations": [
        {{
            "name": "地点名称",
            "type": "地点类型",
            "description": "地点描述",
            "appearance_count": 出现次数,
            "importance": "high/medium/low"
        }}
    ],
    "power_systems": [
        {{
            "name": "体系名称",
            "description": "体系描述",
            "levels": ["等级1", "等级2"]
        }}
    ]
}}

注意：
1. 出现次数最多的场景通常是核心地点
2. 从开篇提取世界观基础设定"""

        # 使用汇总分析模型
        result = await self._call_synthesis_llm(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["setting_statistics"] = dict(top_settings)
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.WORLDVIEW,
            content=parsed,
            confidence=0.85,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )
    
    async def _synthesize_plot(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析情节脉络"""
        # 构建全书情节线
        plot_timeline = []
        for s in summaries:
            plot_timeline.append({
                "chapter": s["chapter_number"],
                "title": s["title"],
                "summary": s["summary"],
                "events": s.get("key_events", []),
                "conflict": s.get("conflict", ""),
                "tone": s.get("emotion_tone", "")
            })
        
        # 分段发送（防止超限）
        total = len(plot_timeline)
        chunk_size = 50
        
        if total <= chunk_size:
            timeline_text = json.dumps(plot_timeline, ensure_ascii=False, indent=1)
        else:
            # 采样关键节点
            sampled = (
                plot_timeline[:20] +  # 开篇
                plot_timeline[total//3:total//3+10] +  # 中间
                plot_timeline[-15:]  # 结尾
            )
            timeline_text = json.dumps(sampled, ensure_ascii=False, indent=1)
        
        prompt = f"""基于以下全书情节线，分析整体情节架构并提取故事概念。

【情节时间线（共{total}章）】
{timeline_text}

请分析并输出JSON（包含故事概念六部分 + 情节架构）:
{{
    "concept": {{
        "logline": "一句话卖点（30-60字，概括主角类型+核心能力+主要对手+最具爽感的目标）",
        "short_title": "日志标题（4-10字的简短名称）",
        "summary": "概念摘要（80-150字，介绍主角身份、困境、目标、阻力、世界观钩子）",
        "genre": "主题材（如：玄幻修真/都市奇能/科幻末世）",
        "sub_genre": "子流派（如：系统流/穿越流/无限流）",
        "core_tags": ["标签1", "标签2", "标签3"],
        "core_conflict": "核心冲突描述（谁对谁，什么利益/观念矛盾）",
        "emotional_tone": "情感基调（爽文逆袭/黑暗现实/甜宠成长/悬疑惊悚）"
    }},
    "main_plot": "主线剧情概述（200字）",
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
            "description": "冲突描述",
            "status": "进行中/已解决"
        }}
    ]
}}

注意：
1. 故事概念部分要突出卖点和吸引力
2. 核心标签至少包含1个反套路/细分创新标签
3. 根据情感基调变化识别剧情节奏
4. 转折点通常伴随冲突升级"""

        # 使用汇总分析模型
        result = await self._call_synthesis_llm(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["total_chapters"] = total
        parsed["chapter_summaries"] = [s["summary"] for s in summaries]
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.PLOT,
            content=parsed,
            confidence=0.88,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )
    
    async def _synthesize_style(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析写作风格"""
        # 统计情感基调分布
        emotion_dist = {}
        for s in summaries:
            tone = s.get("emotion_tone", "未知")
            emotion_dist[tone] = emotion_dist.get(tone, 0) + 1
        
        # 采样原文片段用于风格分析
        sample_chapters = self._select_sample_chapters(chapters, 10)
        style_samples = []
        for ch in sample_chapters:
            if ch.content:
                # 取每章前500字
                style_samples.append(f"【第{ch.number}章】{ch.content[:500]}")
        
        prompt = f"""基于以下信息，分析写作风格。

【情感基调分布（全书{len(summaries)}章）】
{json.dumps(emotion_dist, ensure_ascii=False)}

【文风样本】
{chr(10).join(style_samples[:5])}

请分析并输出JSON:
{{
    "writing_style": "整体文风描述（50字）",
    "narrative_voice": "叙事视角（第一/第三人称）",
    "tone_distribution": {{"情感1": "比例%", "情感2": "比例%"}},
    "pacing": "叙事节奏（快/中/慢）",
    "dialogue_style": "对话风格描述",
    "description_style": "描写风格描述",
    "strengths": ["写作优点1", "写作优点2"],
    "genre_conventions": "是否遵循类型惯例"
}}"""

        # 使用汇总分析模型
        result = await self._call_synthesis_llm(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["emotion_statistics"] = emotion_dist
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.STYLE,
            content=parsed,
            confidence=0.82,
            chapter_range=(1, len(chapters)),
            model_used="qwen-plus",
        )

    async def _synthesize_concepts(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于章节摘要汇总关键概念/术语。"""
        summary_payload = [
            {
                "chapter_number": summary.get("chapter_number"),
                "title": summary.get("title"),
                "summary": summary.get("summary"),
                "key_events": summary.get("key_events", []),
                "setting": summary.get("setting", ""),
                "scene_goal": summary.get("scene_goal", ""),
                "foreshadowing": summary.get("foreshadowing", []),
            }
            for summary in summaries
        ]

        prompt = f"""基于以下章节摘要，提取适合小说续写复用的关键概念、专有名词、重要物品与术语。

【章节摘要】
{json.dumps(summary_payload[:80], ensure_ascii=False, indent=2)}

请输出JSON：
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
1. 只保留对续写稳定有用的专有内容，不要提取普通常用词
2. 优先提取反复出现或推动剧情的概念
3. 若无法确认定义，请基于摘要做保守描述，不要过度脑补"""

        result = await self._call_synthesis_llm(prompt)
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

    # ==================== 人物分析 ====================
    
