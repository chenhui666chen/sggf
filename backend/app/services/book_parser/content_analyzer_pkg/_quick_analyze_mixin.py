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


@dataclass
class AnalysisResult:
    analysis_type: AnalysisType
    content: Dict[str, Any]
    confidence: float
    chapter_summaries: Optional[List[ChapterSummary]] = None

class QuickAnalyzeMixin:
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)


