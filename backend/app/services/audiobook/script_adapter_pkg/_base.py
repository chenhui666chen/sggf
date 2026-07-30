"""
AudiobookScriptAgent 基类

包含初始化和主入口方法
"""
import logging
from typing import List, Dict, Any, Optional, Callable

from ._dataclasses import ScriptSegment, ChapterStructure
from ._llm_review import review_script_segments_with_llm
from app.services.audiobook.llm_config import is_audiobook_script_review_enabled
from app.services.chapter_adaptation_assets import format_audio_adaptation_brief

logger = logging.getLogger(__name__)


class AudiobookScriptAgentBase:
    """
    有声剧本编剧Agent基类
    
    基于专业编剧工作流程，将小说文本改编为适合音频化的剧本
    """
    
    def __init__(self, llm_client=None, tts_model: str = "qwen3-tts-instruct-flash", strategy: Optional[Any] = None):
        """
        Args:
            llm_client: LLM客户端（必需，支持UnifiedLLMClient或自定义）
            tts_model: 当前使用的TTS模型（如 qwen3-tts-instruct-flash / cosyvoice-v3.5-plus）
            strategy: AudioDirector的AdaptationStrategy（包含语义完整性约束）
        """
        if llm_client is None:
            raise ValueError("AudiobookScriptAgent必须提供llm_client参数")
        self.llm_client = llm_client
        self.tts_model = tts_model
        self.audio_engine_mode = "legacy_stems"
        self.strategy = strategy
        self.last_script_review: Optional[Dict[str, Any]] = None
        # 最近一次转化的降级统计（LLM转化失败回退原文旁白的批次）
        self.last_transform_degradation: Optional[Dict[str, Any]] = None
    
    async def adapt_chapter(
        self,
        chapter_content: str,
        character_list: Optional[List[str]] = None,
        chapter_title: str = "",
        genre: str = "科幻",
        chapter_number: int = 1,
        enable_chapter_structure: bool = True,
        adaptation_context: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[float, Optional[Dict[str, Any]]], None]] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        enable_llm_script_review: Optional[bool] = None,
    ) -> List[ScriptSegment]:
        """
        将章节改编为有声剧本
        
        Args:
            chapter_content: 原始章节文本
            character_list: 角色列表
            chapter_title: 章节标题
            genre: 小说类型
            chapter_number: 章节序号
            enable_chapter_structure: 是否生成完整章节结构（片头/片尾）
            character_profiles: 完整角色档案（包含性别、年龄、角色定位、关系网络等）
        
        Returns:
            如果enable_chapter_structure=False: 返回剧本片段列表
            如果enable_chapter_structure=True: 返回ChapterStructure对象
        """
        logger.info(f"开始改编章节: {chapter_title}")
        logger.info(f"   原文长度: {len(chapter_content)} 字符")
        if character_profiles:
            logger.info(f"   角色档案数量: {len(character_profiles)}")

        audio_adaptation_brief = format_audio_adaptation_brief(adaptation_context)
        self.last_transform_degradation = None
        
        def report_progress(progress: float, metrics: Optional[Dict[str, Any]] = None) -> None:
            if not progress_callback:
                return
            try:
                progress_callback(progress, metrics)
            except Exception as exc:
                logger.warning("进度回调失败: %s", exc)

        report_progress(0.02, {"phase": "analysis"})
        analysis = await self._analyze_chapter(
            chapter_content,
            chapter_title,
            genre,
            audio_adaptation_brief=audio_adaptation_brief,
            character_profiles=character_profiles,
        )
        report_progress(0.12, {"phase": "analysis_done"})
        logger.info(f"   分析完成: {analysis.get('theme', 'N/A')}")
        
        transform_base = 0.12
        transform_span = 0.80

        def on_transform_progress(batch_index: int, batch_total: int) -> None:
            if batch_total <= 0:
                report_progress(transform_base, {"phase": "transform", "batch": "0/0"})
                return
            progress_value = transform_base + transform_span * (batch_index / batch_total)
            report_progress(progress_value, {"phase": "transform", "batch": f"{batch_index}/{batch_total}"})

        script_segments = await self._transform_to_script(
            chapter_content,
            character_list or [],
            analysis,
            audio_adaptation_brief=audio_adaptation_brief,
            progress_callback=on_transform_progress,
            character_profiles=character_profiles,
        )
        report_progress(0.94, {"phase": "transform_done"})
        logger.info(f"   转化完成: {len(script_segments)} 个片段")

        self.last_script_review = None
        configured_review_enabled = is_audiobook_script_review_enabled()
        should_review = (
            configured_review_enabled
            if enable_llm_script_review is None
            else bool(enable_llm_script_review) and configured_review_enabled
        )
        if should_review and script_segments:
            report_progress(0.945, {"phase": "llm_script_review"})
            review_result = await review_script_segments_with_llm(
                self.llm_client,
                script_segments,
                source_text=chapter_content,
                audio_engine_mode=self.audio_engine_mode,
            )
            self.last_script_review = review_result.report
            if review_result.report.get("applied"):
                logger.info(
                    "   LLM审稿已应用: %s -> %s 个片段, coverage=%.3f",
                    review_result.report.get("original_count"),
                    review_result.report.get("reviewed_count"),
                    float(review_result.report.get("coverage_ratio") or 0.0),
                )
                script_segments = review_result.segments
            else:
                logger.info("   LLM审稿未改动: %s", review_result.report.get("reason"))
        elif not should_review:
            self.last_script_review = {"attempted": False, "applied": False, "reason": "disabled"}
        
        if enable_chapter_structure:
            chapter_structure = self._build_chapter_structure(
                chapter_title=chapter_title,
                chapter_number=chapter_number,
                genre=genre,
                body_segments=script_segments,
                analysis=analysis,
                character_list=character_list or []
            )
            logger.info(f"   结构化完成: 片头{'Y' if chapter_structure.opening else 'N'} + {len(script_segments)}片段 + 片尾{'Y' if chapter_structure.closing else 'N'}")
            logger.info(f"   预估时长: {chapter_structure.estimate_duration() / 60:.1f} 分钟")
            report_progress(0.96, {"phase": "structure"})
            return chapter_structure
        
        report_progress(0.96, {"phase": "segments_ready"})
        return script_segments
