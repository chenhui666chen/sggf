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

class HelpersMixin:
    def _estimate_tokens(self, text: str) -> int:
        """估算文本的token数"""
        return int(len(text) / self.CHARS_PER_TOKEN)
    
    def _get_smart_sample_config(self, chapters: List[ChapterInfo]) -> dict:
        """
        智能计算采样配置
        
        根据书籍规模动态调整采样策略
        """
        total_chapters = len(chapters)
        total_words = sum(ch.word_count for ch in chapters)
        avg_chapter_words = total_words // max(total_chapters, 1)
        
        logger.info(f"📊 书籍统计: {total_chapters}章, {total_words}字, 平均{avg_chapter_words}字/章")
        
        # 目标：每个分析任务的输入控制在安全范围内
        target_chars = int(self.MAX_INPUT_TOKENS * self.CHARS_PER_TOKEN * 0.7)  # 70%安全边界
        
        if total_words <= 50000:  # 小书(≤ 5万字)
            # 可以分析大部分内容
            sample_chapters = min(total_chapters, 30)
            words_per_chapter = min(avg_chapter_words, 1500)
        elif total_words <= 200000:  # 中等(5-20万字)
            # 适度采样
            sample_chapters = min(total_chapters, 25)
            words_per_chapter = min(avg_chapter_words, 1000)
        elif total_words <= 500000:  # 较大(20-50万字)
            # 重点采样
            sample_chapters = min(total_chapters, 20)
            words_per_chapter = 800
        else:  # 超大(> 50万字)
            # 精简采样
            sample_chapters = min(total_chapters, 15)
            words_per_chapter = 600
        
        # 验证估算
        estimated_chars = sample_chapters * words_per_chapter
        estimated_tokens = self._estimate_tokens(str(estimated_chars))  # 粗略估算
        
        logger.info(f"🎯 采样配置: {sample_chapters}章 x {words_per_chapter}字 ≈ {estimated_chars}字")
        
        return {
            'sample_chapters': sample_chapters,
            'words_per_chapter': words_per_chapter,
            'total_words': total_words,
            'total_chapters': total_chapters,
            'avg_chapter_words': avg_chapter_words,
        }
    
    def _build_context_anchor(self, chapters: List[ChapterInfo], prior_analysis: Dict[str, Any] = None) -> str:
        """
        构建上下文锚点（保持分析连贯性）
        
        锚点包含：
        - 全书核心信息
        - 前序分析结果摘要
        - 本次分析定位
        """
        anchor_parts = []
        
        # 1. 全书核心锚点
        total_chapters = len(chapters)
        total_words = sum(ch.word_count for ch in chapters)
        first_chapter_title = chapters[0].title if chapters else "未知"
        
        anchor_parts.append(f"""【全书信息】
- 总章节: {total_chapters}章
- 总字数: {total_words}字
- 开篇标题: {first_chapter_title}""")
        
        # 2. 前序分析锚点（如果有）
        if prior_analysis:
            if 'genre' in prior_analysis:
                anchor_parts.append(f"- 已识别类型: {prior_analysis['genre']}")
            if 'characters' in prior_analysis:
                chars = prior_analysis['characters'][:3]  # 取前3个关键人物
                char_names = [c.get('name', '') for c in chars if isinstance(c, dict)]
                if char_names:
                    anchor_parts.append(f"- 已识别关键人物: {', '.join(char_names)}")
            if 'world_type' in prior_analysis:
                anchor_parts.append(f"- 世界观类型: {prior_analysis['world_type']}")
        
        return "\n".join(anchor_parts)
    
    def _select_sample_chapters(
        self,
        chapters: List[ChapterInfo],
        count: int
    ) -> List[ChapterInfo]:
        """
        选择样本章节（小说专用策略）
        
        策略：
        - 开篇精读（50%）：建立人物、世界观、故事起点
        - 中段抽样（25%）：情节发展、冲突升级
        - 结尾细读（25%）：高潮、结局走向
        """
        if len(chapters) <= count:
            return chapters
        
        total = len(chapters)
        
        # 小说专用分配比例：开篇50% + 中段25% + 结尾25%
        head_count = int(count * 0.5)  # 开篇重要，多采样
        middle_count = int(count * 0.25)
        tail_count = count - head_count - middle_count
        
        # 开篇：前 N 章（人物出场、世界观建立）
        head = chapters[:head_count]
        
        # 中段：均匀抽样（情节发展）
        middle_start = int(total * 0.3)
        middle_end = int(total * 0.7)
        if middle_count > 0 and middle_end > middle_start:
            middle_step = max(1, (middle_end - middle_start) // middle_count)
            middle = [chapters[i] for i in range(middle_start, middle_end, middle_step)][:middle_count]
        else:
            middle = []
        
        # 结尾：最后 N 章（高潮、结局）
        tail = chapters[-tail_count:] if tail_count > 0 else []
        
        selected = head + middle + tail
        
        logger.info(f"📚 小说采样: 开篇{len(head)}章 + 中段{len(middle)}章 + 结尾{len(tail)}章 = {len(selected)}章")
        
        return selected
    
    def _build_chapter_summary(
        self,
        chapters: List[ChapterInfo],
        max_words_per_chapter: int = 800
    ) -> str:
        """
        构建章节摘要文本（语义边界切分）
        
        策略：
        - 不在对话中间截断
        - 不在句子中间截断
        - 优先在段落结束处切分
        """
        summaries = []
        for ch in chapters:
            header = f"【第{ch.number}章 {ch.title}】"
            if ch.content:
                content = self._smart_truncate(ch.content, max_words_per_chapter)
                summaries.append(f"{header}\n{content}")
            else:
                summaries.append(header)
        
        return "\n\n".join(summaries)
    
    def _smart_truncate(self, text: str, max_length: int) -> str:
        """
        智能截断文本（语义边界优先）
        
        优先级：段落结束 > 句号结束 > 逗号 > 强制截断
        """
        if len(text) <= max_length:
            return text
        
        # 在max_length附近寻找最佳切分点
        search_start = int(max_length * 0.8)  # 从80%位置开始找
        search_text = text[search_start:max_length + 100]  # 允许少量超出
        
        # 优先级切分点
        cut_points = [
            ('\n\n', '段落'),      # 段落结束
            ('。', '句号'),       # 中文句号
            ('。"', '对话结束'),   # 对话结束
            ('”', '引号结束'),   # 引号结束
            ('！', '感叹号'),     # 感叹号
            ('？', '问号'),       # 问号
            ('，', '逗号'),       # 逗号（次优先）
        ]
        
        for marker, name in cut_points:
            pos = search_text.rfind(marker)
            if pos != -1:
                cut_pos = search_start + pos + len(marker)
                return text[:cut_pos].rstrip() + "..."
        
        # 实在找不到，强制截断
        return text[:max_length] + "..."
    
    async def _call_llm_with_retry(
        self,
        prompt: str,
        task_type: TaskType,
        max_retries: int = 3
    ) -> str:
        """
        带重试的LLM调用
        
        实现指数退避策略
        """
        messages = [
            {"role": "system", "content": "你是一个专业的小说分析助手，擅长从文本中提取结构化信息。请始终以有效的JSON格式输出结果。"},
            {"role": "user", "content": prompt}
        ]
        
        last_error = None
        for attempt in range(max_retries):
            try:
                result = await asyncio.wait_for(
                    self.llm.chat(
                        messages=messages,
                        task_type=task_type,
                        temperature=0.3,  # 低温度保证一致性
                        max_tokens=4000,
                        timeout=self.LLM_REQUEST_TIMEOUT_SECONDS,
                    ),
                    timeout=self.LLM_REQUEST_TIMEOUT_SECONDS + 5,
                )
                return result
            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                logger.warning(f"LLM调用失败(尝试 {attempt + 1}/{max_retries}): {e}，{wait_time}秒后重试")
                await asyncio.sleep(wait_time)
        
        raise Exception(f"LLM调用失败，已重试{max_retries}次: {last_error}")
    
    async def _call_qwen_long(
        self,
        prompt: str,
        max_retries: int = 3
    ) -> str:
        """
        调用阿里云 qwen-long 模型（用于汇总分析）
        
        支持超长输入（1000万tokens）
        """
        messages = [
            {"role": "system", "content": "你是一个专业的小说分析助手，擅长从大量文本中提取结构化信息。请始终以有效的JSON格式输出结果。"},
            {"role": "user", "content": prompt}
        ]
        
        last_error = None
        for attempt in range(max_retries):
            try:
                logger.info(
                    "🚀 开始调用 qwen-long | 输入: %s字 | 尝试: %s/%s",
                    len(prompt),
                    attempt + 1,
                    max_retries,
                )
                content = await asyncio.wait_for(
                    self.llm.chat(
                        messages=messages,
                        model="qwen-long",
                        temperature=0.3,
                        max_tokens=8000,
                        timeout=self.QWEN_LONG_REQUEST_TIMEOUT_SECONDS,
                    ),
                    timeout=self.QWEN_LONG_REQUEST_TIMEOUT_SECONDS + 5,
                )

                logger.info(f"✅ qwen-long调用成功 | 输入: {len(prompt)}字 | 输出: {len(content)}字")
                return content
                
            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(f"qwen-long调用失败(尝试 {attempt + 1}/{max_retries}): {e}，{wait_time}秒后重试")
                await asyncio.sleep(wait_time)
        
        raise Exception(f"qwen-long调用失败，已重试{max_retries}次: {last_error}")
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        解析LLM的JSON响应
        
        处理可能的格式问题
        """
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取JSON块
        import re
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试提取花括号内容
        brace_match = re.search(r'\{[\s\S]*\}', response)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # 返回原始文本包装
        logger.warning("无法解析JSON响应，返回原始文本")
        return {"raw_response": response, "parse_error": True}
    
    # ==================== 快速分析方法 ====================
    
