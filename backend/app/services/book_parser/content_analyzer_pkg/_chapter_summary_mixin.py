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



class ChapterSummaryMixin:
    async def _extract_all_chapter_summaries(
        self,
        chapters: List[ChapterInfo],
        on_progress: Optional[ProgressCallback] = None
    ) -> List[Dict[str, Any]]:
        """
        逐章提取摘要（每章独立分析，不超限）
        
        提取内容与创作流程对齐：
        - 章节摘要
        - 出场人物
        - 关键事件
        - 场景/地点
        - 冲突/悬念
        - 情感基调
        """
        summaries = []
        total = len(chapters)
        
        # 并发控制：每批最多5章
        batch_size = 5
        
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_chapters = chapters[batch_start:batch_end]
            
            # 并发提取这一批
            tasks = [
                self._extract_single_chapter_summary(ch)
                for ch in batch_chapters
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"第{batch_start + i + 1}章提取失败: {result}")
                    # 创建空摘要
                    summaries.append({
                        "chapter_number": batch_chapters[i].number,
                        "title": batch_chapters[i].title,
                        "summary": "提取失败",
                        "characters_appeared": [],
                        "key_events": [],
                        "setting": "",
                        "character_clues": [],
                        "conflict": "",
                        "emotion_tone": ""
                    })
                else:
                    summaries.append(result)
            
            # 更新进度
            if on_progress:
                progress = int((batch_end / total) * 45)  # 阶段1占总进度的45%
                await on_progress(
                    "chapter_extraction", 
                    progress, 
                    f"已提取 {batch_end}/{total} 章..."
                )
            
            # 防止API限流
            if batch_end < total:
                await asyncio.sleep(0.5)
        
        return summaries
    
    async def _extract_single_chapter_summary(
        self,
        chapter: ChapterInfo
    ) -> Dict[str, Any]:
        """
        提取单章摘要（增强版 - 支持细纲生成）
        
        输入：单章内容（最多3000字，确保信息完整）
        输出：结构化摘要 + 细纲关键要素
        """
        # 截取章节内容（增加到3000字以获取更完整信息）
        content = self._smart_truncate(chapter.content or "", 3000)
        
        prompt = f"""请深度分析以下章节内容，提取完整的情节要素（用于续写参考）。

【第{chapter.number}章 {chapter.title}】
{content}

请以JSON格式输出（每个字段都很重要，请认真填写）：
{{
    "summary": "章节摘要（300-400字，详细概括本章完整情节发展，包括起因、经过、结果、人物状态变化）",
    "characters_appeared": ["本章出场的人物姓名"],
    "key_events": [
        "关键事件1（30字以内，包含谁做了什么、结果如何）",
        "关键事件2",
        "关键事件3",
        "关键事件4",
        "关键事件5"
    ],
    "setting": "主要场景/地点（20字以内）",
    
    "character_clues": [
        {{
            "name": "人物姓名",
            "story_stance": "故事立场（主角方/反派方/中立方/亦正亦邪/未提及）",
            "faction": "所属势力/组织/门派（未提及则写未提及）",
            "evidence": "原文证据片段（20-40字，包含明确指向的词句）"
        }}
    ],
    
    "scene_goal": "场景目标（40字以内，格式：[地点] + [人物] + [要达成什么]）",
    
    "conflict_arc": {{
        "trigger": "冲突起因（30字以内）",
        "escalation": "冲突升级（30字以内，主角陷入困境或发现转机）",
        "resolution": "冲突结果（30字以内，本章如何收尾）"
    }},
    
    "emotion_curve": "情绪曲线（格式：起点情绪→转折情绪→终点情绪，如：平静→紧张→释然）",
    
    "highlight": {{
        "type": "本章爽点/高潮类型（打脸/升级/获得/反转/危机/无）",
        "description": "爽点具体内容（30字以内）",
        "intensity": "强度（1-5星）"
    }},
    
    "ending_hook": {{
        "type": "结尾钩子类型（悬念/危机/反转/机遇/无）",
        "content": "钩子具体内容（30字以内）"
    }},
    
    "gains": {{
        "character_gains": "主角收获（能力/物品/关系/信息，30字以内）",
        "plot_progress": "主线推进（埋设/揭示了什么伏笔或线索，30字以内）"
    }},
    
    "foreshadowing": ["本章埋设或回收的伏笔（可选，最多3个）"]
}}

注意：
1. 摘要要完整详细，包含故事的来龙去脉和人物状态变化
2. 人物只列出明确出场的，不要猜测
3. 关键事件最多5个，按重要性排序
4. 若本章无明显爽点/钩子，type填"无"，其他字段填"本章为过渡/铺垫章节"
5. 冲突发展要体现起承转合
6. 情绪曲线要准确反映读者阅读时的情感变化
7. 故事立场/所属势力必须有明确文本证据，否则写“未提及”"""

        try:
            result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
            parsed = self._parse_json_response(result)

            if parsed.get("parse_error"):
                raise ValueError("章节摘要 JSON 解析失败")

            # 确保必要字段存在（兼容旧格式 + 新增细纲字段）
            return {
                "chapter_number": chapter.number,
                "title": chapter.title,
                "summary": parsed.get("summary", ""),
                "characters_appeared": parsed.get("characters_appeared", []),
                "key_events": parsed.get("key_events", []),
                "setting": parsed.get("setting", ""),
                "character_clues": parsed.get("character_clues", []),
                # 🆕 细纲关键字段
                "scene_goal": parsed.get("scene_goal", ""),
                "conflict_arc": parsed.get("conflict_arc", {"trigger": "", "escalation": "", "resolution": ""}),
                "emotion_curve": parsed.get("emotion_curve", ""),
                "highlight": parsed.get("highlight", {"type": "无", "description": "", "intensity": "1"}),
                "ending_hook": parsed.get("ending_hook", {"type": "无", "content": ""}),
                "gains": parsed.get("gains", {"character_gains": "", "plot_progress": ""}),
                "foreshadowing": parsed.get("foreshadowing", []),
                # 兼容旧字段
                "conflict": parsed.get("conflict", ""),
                "emotion_tone": parsed.get("emotion_tone", "")
            }
        except Exception as exc:
            return self._build_fallback_chapter_summary(chapter, reason=str(exc))
    
    # ==================== 阶段2: 基于摘要汇总分析 ====================
    
