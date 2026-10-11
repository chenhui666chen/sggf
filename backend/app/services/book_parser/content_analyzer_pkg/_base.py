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
    chapter_range: tuple
    model_used: str
    token_used: int = 0
    extra_data: Optional[Dict[str, Any]] = None

class ContentAnalyzerBase:
    def __init__(self, llm_client: Optional[UnifiedLLMClient] = None):
        """
        初始化分析器
        
        Args:
            llm_client: LLM客户端实例，不传则使用全局单例
        """
        self.llm = llm_client or get_llm_client()

    def _build_analysis_result(
        self,
        *,
        analysis_type: AnalysisType,
        content: Dict[str, Any],
        confidence: float,
        chapter_range: tuple,
        model_used: str,
        token_used: int = 0,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> AnalysisResult:
        """统一构造分析结果，并对低质量结果做显式降级。"""
        normalized_content = content if isinstance(content, dict) else {}
        normalized_extra = dict(extra_data or {})

        if normalized_content.get("parse_error"):
            raw_response = str(normalized_content.get("raw_response") or "")
            normalized_extra["parse_error"] = True
            normalized_extra["quality_warning"] = "LLM 响应未能成功解析为 JSON，当前分析结果已降级，不建议直接导入创作链路。"
            normalized_extra["raw_response_preview"] = raw_response[:500]
            normalized_content = {
                "parse_error": True,
                "quality_warning": normalized_extra["quality_warning"],
            }
            confidence = min(confidence, 0.15)

        return AnalysisResult(
            analysis_type=analysis_type,
            content=normalized_content,
            confidence=confidence,
            chapter_range=chapter_range,
            model_used=model_used,
            token_used=token_used,
            extra_data=normalized_extra or None,
        )
    
    async def analyze_all(
        self,
        chapters: List[ChapterInfo],
        on_progress: Optional[ProgressCallback] = None,
        analysis_types: Optional[List[AnalysisType]] = None,
        use_two_stage: bool = True  # 🆕 是否使用两阶段分析
    ) -> tuple[List[AnalysisResult], List[Dict[str, Any]]]:
        """
        执行全面分析
        
        两阶段流程：
        1. 阶段1: 逐章提取摘要（每章独立分析，不超限）
        2. 阶段2: 基于摘要汇总分析大纲/世界观/人物体系
        
        Args:
            chapters: 章节列表
            on_progress: 进度回调
            analysis_types: 要执行的分析类型，默认全部
            use_two_stage: 是否使用两阶段分析（默认开启）
            
        Returns:
            (分析结果列表, 章节摘要列表) - 章节摘要包含完整细纲数据
        """
        if analysis_types is None:
            analysis_types = [
                AnalysisType.CHARACTERS,
                AnalysisType.WORLDVIEW,
                AnalysisType.PLOT,
                AnalysisType.STYLE,
                AnalysisType.CONCEPTS,
            ]
        
        results = []
        chapter_summaries = []  # 🆕 保存章节摘要用于返回
        
        if use_two_stage and len(chapters) > 5:
            # 🆕 两阶段分析流程
            results, chapter_summaries = await self._two_stage_analysis(
                chapters, analysis_types, on_progress
            )
        else:
            if chapters:
                if on_progress:
                    await on_progress("chapter_extraction", 0, "正在提取章节摘要...")

                chapter_summaries = await self._extract_all_chapter_summaries(
                    chapters, on_progress
                )
                logger.info(f"✅ 小体量作品章节摘要提取完成: {len(chapter_summaries)} 章")

            # 原有采样分析流程（适用于少量章节）
            results = await self._sampling_analysis(
                chapters,
                analysis_types,
                on_progress,
                progress_start=50 if chapter_summaries else 0,
                progress_end=100,
            )
        
        if on_progress:
            await on_progress("complete", 100, "分析完成")
        
        return results, chapter_summaries
    
    async def _two_stage_analysis(
        self,
        chapters: List[ChapterInfo],
        analysis_types: List[AnalysisType],
        on_progress: Optional[ProgressCallback] = None
    ) -> tuple[List[AnalysisResult], List[Dict[str, Any]]]:
        """
        两阶段分析流程
        
        阶段1: 逐章提取摘要
        阶段2: 基于摘要汇总分析
        
        Returns:
            (分析结果列表, 章节摘要列表)
        """
        results = []
        
        # ========== 阶段1: 逐章提取摘要 ==========
        if on_progress:
            await on_progress("chapter_extraction", 0, "正在逐章提取摘要...")
        
        chapter_summaries = await self._extract_all_chapter_summaries(
            chapters, on_progress
        )
        
        logger.info(f"✅ 阶段1完成: 提取了 {len(chapter_summaries)} 章摘要")
        
        # ========== 阶段2: 基于摘要汇总分析 ==========
        if on_progress:
            await on_progress("synthesis", 50, "正在汇总分析...")
        
        for i, analysis_type in enumerate(analysis_types):
            progress = 50 + int((i / len(analysis_types)) * 50)
            
            if on_progress:
                await on_progress(
                    analysis_type.value, 
                    progress, 
                    f"正在汇总分析{self._get_type_name(analysis_type)}..."
                )
            
            try:
                result = await self._synthesize_from_summaries(
                    chapters, chapter_summaries, analysis_type
                )
                results.append(result)
                logger.info(f"✅ {analysis_type.value} 汇总分析完成")
            except Exception as e:
                logger.error(f"❌ {analysis_type.value} 汇总分析失败: {e}")
        
        return results, chapter_summaries  # 🆕 同时返回章节摘要
    
    async def _sampling_analysis(
        self,
        chapters: List[ChapterInfo],
        analysis_types: List[AnalysisType],
        on_progress: Optional[ProgressCallback] = None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> List[AnalysisResult]:
        """原有采样分析流程（适用于少量章节）"""
        results = []
        total_steps = len(analysis_types)
        
        for i, analysis_type in enumerate(analysis_types):
            progress = progress_start + int((i / total_steps) * (progress_end - progress_start))
            
            if on_progress:
                await on_progress(
                    analysis_type.value, 
                    progress, 
                    f"正在分析{self._get_type_name(analysis_type)}..."
                )
            
            try:
                result = await self._analyze_by_type(chapters, analysis_type)
                results.append(result)
                logger.info(f"✅ {analysis_type.value} 分析完成")
            except Exception as e:
                logger.error(f"❌ {analysis_type.value} 分析失败: {e}")
        
        return results
