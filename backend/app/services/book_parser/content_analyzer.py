"""
书籍内容分析器

使用AI提取书籍中的核心要素：
- 人物体系
- 世界观设定
- 情节脉络
- 写作风格
"""
import os
import json
import asyncio
import logging
import httpx
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
from openai import AsyncOpenAI

from app.services.llm_client import get_llm_client, OptimizedLLMClient
from app.services.model_optimizer import TaskType
from .chapter_splitter import ChapterInfo, ChapterType

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
    CHAPTER_SUMMARY = "chapter_summary"  # 🆕 章节摘要


@dataclass
class ChapterSummary:
    """章节摘要（与创作流程对齐）"""
    chapter_number: int
    title: str
    summary: str                    # 章节摘要（200-300字）
    characters_appeared: List[str]  # 出场人物
    key_events: List[str]           # 关键事件（每个30字，最多5个）
    setting: str                    # 场景/地点
    conflict: str                   # 冲突/悬念（50字）
    emotion_tone: str               # 情感基调


@dataclass
class AnalysisResult:
    """分析结果"""
    analysis_type: AnalysisType
    content: Dict[str, Any]
    confidence: float
    chapter_range: tuple  # (start, end)
    model_used: str
    token_used: int = 0


# 进度回调类型
ProgressCallback = Callable[[str, int, str], Awaitable[None]]  # (stage, progress, message)


class ContentAnalyzer:
    """
    书籍内容分析器
    
    使用AI模型提取书籍中的核心要素
    """
    
    # Token估算：中文约 1.5字/token
    CHARS_PER_TOKEN = 1.5
    
    # qwen-long的安全限制（留一些余量给响应）
    MAX_INPUT_TOKENS = 50000  # 实际支持更多，保守估算
    
    # 情节分析批次大小
    BATCH_SIZE = 10
    
    # 最大重试次数
    MAX_RETRIES = 3
    
    def __init__(self, llm_client: Optional[OptimizedLLMClient] = None):
        """
        初始化分析器
        
        Args:
            llm_client: LLM客户端实例，不传则使用全局单例
        """
        self.llm = llm_client or get_llm_client()
        
        # 🛡️ 创建禁用代理的httpx客户端
        aliyun_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=30.0),
            trust_env=False  # 不读取环境变量中的代理配置
        )
        
        # 🆕 初始化阿里云API客户端（用于qwen-long）
        self.aliyun_client = AsyncOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=180.0,  # 长文本需要更长超时
            http_client=aliyun_http_client  # 🛡️ 使用禁用代理的客户端
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
            ]
        
        results = []
        chapter_summaries = []  # 🆕 保存章节摘要用于返回
        
        if use_two_stage and len(chapters) > 5:
            # 🆕 两阶段分析流程
            results, chapter_summaries = await self._two_stage_analysis(
                chapters, analysis_types, on_progress
            )
        else:
            # 原有采样分析流程（适用于少量章节）
            results = await self._sampling_analysis(
                chapters, analysis_types, on_progress
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
        on_progress: Optional[ProgressCallback] = None
    ) -> List[AnalysisResult]:
        """原有采样分析流程（适用于少量章节）"""
        results = []
        total_steps = len(analysis_types)
        
        for i, analysis_type in enumerate(analysis_types):
            progress = int((i / total_steps) * 100)
            
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
    
    # ==================== 阶段1: 逐章提取摘要 ====================
    
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
6. 情绪曲线要准确反映读者阅读时的情感变化"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        # 确保必要字段存在（兼容旧格式 + 新增细纲字段）
        return {
            "chapter_number": chapter.number,
            "title": chapter.title,
            "summary": parsed.get("summary", ""),
            "characters_appeared": parsed.get("characters_appeared", []),
            "key_events": parsed.get("key_events", []),
            "setting": parsed.get("setting", ""),
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
    
    # ==================== 阶段2: 基于摘要汇总分析 ====================
    
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

【关键事件线索】
{key_events_text}

【全书信息】
总章数: {len(chapters)}章

请分析并输出JSON:
{{
    "main_characters": [
        {{
            "name": "人物姓名",
            "role": "protagonist/antagonist/deuteragonist",
            "description": "人物简介（50字）",
            "first_appearance_chapter": 1,
            "appearance_count": 出场次数,
            "importance_score": 0.9
        }}
    ],
    "supporting_characters": [
        {{
            "name": "人物姓名",
            "role": "配角类型",
            "relationship_to_main": "与主角关系"
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
3. 关系基于事件线索推断"""

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["character_statistics"] = character_appearances
        
        return AnalysisResult(
            analysis_type=AnalysisType.CHARACTERS,
            content=parsed,
            confidence=0.90,  # 基于全书统计，可信度更高
            chapter_range=(1, len(chapters)),
            model_used="qwen-long"  # 🆕 更新模型标识
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

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["setting_statistics"] = dict(top_settings)
        
        return AnalysisResult(
            analysis_type=AnalysisType.WORLDVIEW,
            content=parsed,
            confidence=0.85,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long"  # 🆕 更新模型标识
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

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["total_chapters"] = total
        parsed["chapter_summaries"] = [s["summary"] for s in summaries]
        
        return AnalysisResult(
            analysis_type=AnalysisType.PLOT,
            content=parsed,
            confidence=0.88,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long"  # 🆕 更新模型标识
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

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["emotion_statistics"] = emotion_dist
        
        return AnalysisResult(
            analysis_type=AnalysisType.STYLE,
            content=parsed,
            confidence=0.82,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long"  # 🆕 更新模型标识
        )
    
    # ==================== 人物分析 ====================
    
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
    "main_characters": [
        {{
            "name": "人物姓名",
            "aliases": ["别名1", "别名2"],
            "role": "protagonist/antagonist/deuteragonist",
            "description": "人物简介（50字以内）",
            "personality": ["性格特点1", "性格特点2"],
            "abilities": ["能力/技能"],
            "faction": "所属势力/门派/组织（如有）",
            "arc": "人物发展轨迹描述（30字以内）",
            "first_appearance_chapter": 1,
            "importance_score": 0.9
        }}
    ],
    "supporting_characters": [
        {{
            "name": "人物姓名",
            "role": "配角类型",
            "description": "人物简介",
            "faction": "所属势力（如有）",
            "relationship_to_main": "与主角的关系"
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
4. 每个人物的faction字段很重要，请仔细提取"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        return AnalysisResult(
            analysis_type=AnalysisType.CHARACTERS,
            content=parsed,
            confidence=0.85,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max"
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
        
        return AnalysisResult(
            analysis_type=AnalysisType.WORLDVIEW,
            content=parsed,
            confidence=0.80,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max"
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
        
        return AnalysisResult(
            analysis_type=AnalysisType.PLOT,
            content=parsed,
            confidence=0.75,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max"
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
        
        return AnalysisResult(
            analysis_type=AnalysisType.STYLE,
            content=parsed,
            confidence=0.80,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max"
        )
    
    # ==================== 辅助方法 ====================
    
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
            if 'main_characters' in prior_analysis:
                chars = prior_analysis['main_characters'][:3]  # 取前3个主角
                char_names = [c.get('name', '') for c in chars if isinstance(c, dict)]
                if char_names:
                    anchor_parts.append(f"- 已识别主角: {', '.join(char_names)}")
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
                result = await self.llm.chat(
                    messages=messages,
                    task_type=task_type,
                    temperature=0.3,  # 低温度保证一致性
                    max_tokens=4000
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
                response = await self.aliyun_client.chat.completions.create(
                    model="qwen-long",
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.3,
                    max_tokens=8000  # 输出可以多一些
                )
                
                content = response.choices[0].message.content
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
