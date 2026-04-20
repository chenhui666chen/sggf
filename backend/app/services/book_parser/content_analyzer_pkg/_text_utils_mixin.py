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

class TextUtilsMixin:
    async def _analyze_by_type(
        self,
        chapters: List[ChapterInfo],
        analysis_type: AnalysisType
    ) -> AnalysisResult:
        """
        执行特定类型的分析
        """
        if analysis_type == AnalysisType.CHARACTERS:
            return await self.analyze_characters(chapters)
        elif analysis_type == AnalysisType.WORLDVIEW:
            return await self.analyze_worldview(chapters)
        elif analysis_type == AnalysisType.PLOT:
            return await self.analyze_plot(chapters)
        elif analysis_type == AnalysisType.STYLE:
            return await self.analyze_style(chapters)
        elif analysis_type == AnalysisType.CONCEPTS:
            return await self.analyze_concepts(chapters)
        else:
            raise ValueError(f"不支持的分析类型: {analysis_type}")
    
    def _get_type_name(self, analysis_type: AnalysisType) -> str:
        """获取分析类型的中文名称"""
        names = {
            AnalysisType.CHARACTERS: "人物体系",
            AnalysisType.WORLDVIEW: "世界观设定",
            AnalysisType.PLOT: "情节脉络",
            AnalysisType.STYLE: "写作风格",
            AnalysisType.CONCEPTS: "关键概念",
            AnalysisType.THEMES: "主题思想",
        }
        return names.get(analysis_type, analysis_type.value)

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """按中文语义边界粗切句子，供无模型兜底使用。"""
        if not text:
            return []

        raw_parts = re.split(r'(?<=[。！？!?])\s*|\n+', text)
        sentences: List[str] = []
        for part in raw_parts:
            cleaned = str(part or "").strip()
            if not cleaned:
                continue
            if re.fullmatch(r'[-=*_#\s]{3,}', cleaned):
                continue
            cleaned = re.sub(r'\s+', ' ', cleaned)
            if len(cleaned) >= 6:
                sentences.append(cleaned)
        return sentences

    @staticmethod
    def _normalize_character_text(value: Any, separator: str = "、") -> str:
        """将人物字段统一整理为单行文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            items: List[str] = []
            for item in value:
                text = ContentAnalyzer._normalize_character_text(item, separator=separator)
                if text:
                    items.append(text)
            return separator.join(list(dict.fromkeys(items)))
        if isinstance(value, dict):
            return ""
        return str(value).strip()

    @classmethod
    def _is_placeholder_character_text(
        cls,
        value: Any,
        *,
        allow_not_mentioned: bool = False,
    ) -> bool:
        """判断人物字段是否仅为占位值。"""
        text = cls._normalize_character_text(value)
        if not text:
            return True

        compact = re.sub(r"\s+", "", text).lower()
        placeholders = {
            "待补充",
            "未知",
            "不详",
            "暂无",
            "暂无信息",
            "暂无描写",
            "未说明",
            "未交代",
            "未明确提及",
            "未明确说明",
            "none",
            "null",
            "n/a",
            "na",
        }
        if not allow_not_mentioned:
            placeholders.add("未提及")

        if compact in placeholders:
            return True

        return bool(re.fullmatch(r"[?？.。·•…]+", text))

    @classmethod
    def _first_meaningful_character_text(
        cls,
        *values: Any,
        allow_not_mentioned: bool = False,
        separator: str = "、",
    ) -> str:
        """返回第一个有实际信息量的人物字段文本。"""
        for value in values:
            text = cls._normalize_character_text(value, separator=separator)
            if text and not cls._is_placeholder_character_text(
                text,
                allow_not_mentioned=allow_not_mentioned,
            ):
                return text
        return ""

