"""
有声书生成引擎 - 专业多Agent协作模式

核心流程：
1. AudioDirector制定改编策略
2. AudiobookScriptAdapter剧本改编
3. VoiceDesigner/SoundEffectDesigner/MusicComposer并行设计
4. TTS合成（批量并行）
5. AudioMixer音频混合
"""
import asyncio
import logging
import time
import math
import json
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import asdict, is_dataclass

from .script_adapter import AudiobookScriptAgent, ScriptSegment, ChapterStructure
from .voice_manager_factory import create_voice_manager
from .audio_mixer import AudioMixer
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from core.unified_media_runtime import create_tts_engine

# 导入专业Agent
from .agents import (
    AudioDirector,
    VoiceDesigner,
    SoundEffectDesigner,
    MusicComposer,
    AudioQualityReviewer
)

# 导入任务追踪和消息总线
from .task_tracker import TaskTracker, StageType
from .agent_message import MessageBus, AgentType, StrategyMessage

# 导入WebSocket管理器（用于实时进度推送）
try:
    from app.websocket.manager import ws_manager
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    ws_manager = None  # type: ignore

logger = logging.getLogger(__name__)


class AudiobookEngine:
    """
    有声书生成引擎 - 专业多Agent协作模式
    
    复用现有能力：
    - CharacterDesignerAgent: 角色识别
    - MultiLayerCache: 缓存系统
    - BatchProcessor: 批量处理
    """
    
    def __init__(
        self,
        enable_cache: bool = True,
        max_concurrent: int = 1,  # 降低并发，避免阿里云限流（从5改为1）
        llm_client=None,  # LLM客户端（用于专业Agent + 智能音色推断）
        tts_model: str = "qwen3-tts-flash",  # TTS 模型（qwen3-tts-flash / cosyvoice-v3-plus）
        progress_handler: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        # 检查LLM客户端
        if llm_client is None:
            raise ValueError("有声书引擎必须提供llm_client参数，用于剧本改编和质量评审")
        
        # 初始化任务追踪和消息总线
        self.task_tracker = TaskTracker()
        self._progress_handler: Optional[Callable[[Dict[str, Any]], None]] = progress_handler
        self.task_tracker.add_observer(self._handle_task_progress)
        self.message_bus = MessageBus()
        
        # 初始化专业Agent
        logger.info("🎬 启用专业LLM驱动的多Agent协作模式")
        self.audio_director = AudioDirector(llm_client=llm_client)
        self.script_adapter = AudiobookScriptAgent(llm_client=llm_client, tts_model=tts_model)
        self.voice_designer = VoiceDesigner()
        self.sound_effect_designer = SoundEffectDesigner(llm_client=llm_client)
        self.music_composer = MusicComposer()
        self.audio_quality_reviewer = AudioQualityReviewer(llm_client=llm_client)
        
        # 初始化基础组件
        self.tts_model = tts_model
        # 🆕 VoiceManager自动启用智能推断：
        # - 用户已配置的角色 → 使用用户配置
        # - 用户未配置的角色 → LLM智能推断 (如果有llm_client)
        # - LLM推断失败 → 增强版规则推断
        self.voice_manager = create_voice_manager(tts_model=tts_model, llm_client=llm_client)
        self.tts_engine = create_tts_engine(
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
            model=tts_model  # 支持 qwen3-tts-flash / cosyvoice-v3-plus
        )
        self.audio_mixer = AudioMixer()
        # 存储最近一次音效时间线（用于混音）
        self._last_effect_timeline: Optional[Dict[str, Any]] = None
        # 存储最近一次配乐时间线（用于混音）
        self._last_music_timeline: Optional[Dict[str, Any]] = None
        # 项目级音效/BGM 配置（来自 Project.audio_config.audio_fx）
        self._audio_fx_config: Optional[Dict[str, Any]] = None
        
        # 🆕 智能化模块
        from .intelligence import ClimaxDetector, EmotionCurveAnalyzer
        self.climax_detector = ClimaxDetector()
        self.emotion_analyzer = EmotionCurveAnalyzer()
        
        logger.info("🎶 有声书生成引擎初始化完成")
    
    def set_progress_handler(self, handler: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """设置外部进度回调（用于持久化阶段状态）"""
        self._progress_handler = handler

    def _handle_task_progress(self, snapshot: Dict[str, Any]) -> None:
        if not self._progress_handler:
            return
        try:
            self._progress_handler(snapshot)
        except Exception as exc:  # pragma: no cover - 避免进度回调影响主流程
            logger.warning("⚠️ 分发任务进度失败: %s", exc)
    
    def apply_audio_fx_config(self, audio_fx: Dict[str, Any]) -> None:
        """应用项目级音效/BGM 配置（来自 Project.audio_config['audio_fx']）。"""
        try:
            self._audio_fx_config = audio_fx or {}
            theme = str(self._audio_fx_config.get("bgm_theme") or "").strip() or None
            style = str(self._audio_fx_config.get("bgm_style") or "").strip() or None
            if hasattr(self.music_composer, "apply_project_style"):
                self.music_composer.apply_project_style(theme=theme, style=style)
            logger.info(f"🎚 已应用项目级音效/BGM 配置: {self._audio_fx_config}")
        except Exception as e:
            logger.warning(f"⚠️ 设置音效/BGM 配置失败: {e}")
    
    def _apply_audio_fx_to_strategy(self, strategy) -> None:
        """根据项目级音效/BGM 配置调整导演策略中的 sound_effect_density / music_density。"""
        cfg = getattr(self, "_audio_fx_config", None)
        if not cfg:
            return
        try:
            enable_sfx = cfg.get("enable_sound_effects", True)
            enable_music = cfg.get("enable_music", True)
            sfx_density = str(cfg.get("sound_effect_density") or "").lower()
            music_density = str(cfg.get("music_density") or "").lower()
            allowed = {"low", "medium", "high", "off"}
            if not enable_sfx:
                strategy.sound_effect_density = "off"
            elif sfx_density in allowed:
                strategy.sound_effect_density = sfx_density
            if not enable_music:
                strategy.music_density = "off"
            elif music_density in allowed:
                strategy.music_density = music_density
        except Exception as e:
            logger.warning(f"⚠️ 应用项目级音效/BGM 策略失败: {e}")

    def _build_review_segments(self, script_segments: List[ScriptSegment]) -> List[Dict[str, Any]]:
        """构造评审所需的片段结构。"""
        return [
            {
                "type": seg.type,
                "text": seg.text,
                "speaker": seg.speaker,
                "emotion": seg.emotion,
                "performance_notes": seg.performance_notes if hasattr(seg, "performance_notes") else "",
                "pause_before": getattr(seg, "pause_before", 0.0),
                "pause_after": getattr(seg, "pause_after", 0.0),
                "voice_params": seg.voice_params if hasattr(seg, "voice_params") else {},
                "instruct_emotion": getattr(seg, "instruct_emotion", ""),
                "instruct_scene": getattr(seg, "instruct_scene", ""),
                "instruct_role": getattr(seg, "instruct_role", ""),
                "instruct_identity": getattr(seg, "instruct_identity", ""),
                "sound_effects": seg.sound_effects if seg.sound_effects is not None else [],
                "music_cue": seg.music_cue if hasattr(seg, "music_cue") and seg.music_cue is not None else "",
                "sound_effects_simple": getattr(seg, "sound_effects_simple", []) or [],
                "music_cue_simple": getattr(seg, "music_cue_simple", "") or "",
                "original_text": getattr(seg, "original_text", ""),
                "adaptation_reason": getattr(seg, "adaptation_reason", ""),
            }
            for seg in script_segments
        ]

    @staticmethod
    def _select_evenly_indices(total: int, keep: int) -> List[int]:
        if keep <= 0:
            return []
        if keep >= total:
            return list(range(total))
        if keep == 1:
            return [0]

        step = (total - 1) / (keep - 1)
        selected = [int(round(i * step)) for i in range(keep)]
        unique = []
        used = set()
        for idx in selected:
            if idx in used:
                continue
            used.add(idx)
            unique.append(idx)
        if len(unique) < keep:
            for idx in range(total):
                if idx in used:
                    continue
                unique.append(idx)
                used.add(idx)
                if len(unique) == keep:
                    break
        unique.sort()
        return unique

    def _auto_balance_script_audio_cues(
        self,
        script_segments: List[ScriptSegment],
        standards: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据评审标准自动收敛音效/配乐密度。"""
        if not script_segments:
            return {"applied": False}

        total_text_length = sum(len(getattr(seg, "text", "") or "") for seg in script_segments)
        if total_text_length <= 0:
            return {"applied": False}

        estimated_minutes = total_text_length / 10 / 60
        audio_fx = getattr(self, "_audio_fx_config", None) or {}
        sfx_density = str(audio_fx.get("sound_effect_density") or "").lower()
        music_density = str(audio_fx.get("music_density") or "").lower()

        min_sfx_per_min = standards.get("min_sound_effects_per_minute", 2)
        max_sfx_per_min = standards.get("max_sound_effects_per_minute", 6)
        hard_max_sfx_per_min = standards.get("hard_max_sound_effects_per_minute", max_sfx_per_min)

        target_sfx_per_min = max_sfx_per_min
        if sfx_density == "off":
            target_sfx_per_min = 0
        elif sfx_density == "low":
            target_sfx_per_min = min_sfx_per_min
        elif sfx_density == "high":
            target_sfx_per_min = hard_max_sfx_per_min

        target_music_min = standards.get("music_coverage_target_min", 0.15)
        target_music_max = standards.get("music_coverage_target_max", 0.40)
        max_music_coverage = standards.get("max_music_coverage", 0.60)

        target_music_coverage = target_music_max
        if music_density == "off":
            target_music_coverage = 0.0
        elif music_density == "low":
            target_music_coverage = target_music_min
        elif music_density == "high":
            target_music_coverage = max_music_coverage

        max_effects = int(math.floor(target_sfx_per_min * estimated_minutes))
        if target_sfx_per_min > 0 and max_effects == 0:
            max_effects = 1

        max_music_segments = int(math.floor(target_music_coverage * len(script_segments)))
        if target_music_coverage > 0 and max_music_segments == 0:
            max_music_segments = 1

        effect_entries: List[tuple[int, int]] = []
        for seg_idx, seg in enumerate(script_segments):
            effects = seg.sound_effects or []
            for effect_idx, _ in enumerate(effects):
                effect_entries.append((seg_idx, effect_idx))

        total_effects = len(effect_entries)
        total_music_segments = sum(1 for seg in script_segments if seg.music_cue)
        summary = {
            "applied": False,
            "estimated_minutes": round(estimated_minutes, 2),
            "sound_effects_before": total_effects,
            "sound_effects_after": total_effects,
            "music_cues_before": total_music_segments,
            "music_cues_after": total_music_segments,
            "targets": {
                "sound_effects_per_minute": target_sfx_per_min,
                "music_coverage": target_music_coverage,
            },
        }

        if total_effects > max_effects:
            keep_indices = set(self._select_evenly_indices(total_effects, max_effects))
            new_effects_by_segment: List[List[Any]] = [[] for _ in script_segments]
            for flat_idx, (seg_idx, effect_idx) in enumerate(effect_entries):
                if flat_idx in keep_indices:
                    new_effects_by_segment[seg_idx].append(script_segments[seg_idx].sound_effects[effect_idx])
            for seg_idx, seg in enumerate(script_segments):
                seg.sound_effects = new_effects_by_segment[seg_idx]
            summary["sound_effects_after"] = max_effects
            summary["applied"] = True

        if total_music_segments > max_music_segments:
            music_indices = [idx for idx, seg in enumerate(script_segments) if seg.music_cue]
            keep_music = set(self._select_evenly_indices(len(music_indices), max_music_segments))
            for keep_idx, seg_idx in enumerate(music_indices):
                if keep_idx in keep_music:
                    continue
                script_segments[seg_idx].music_cue = None
            summary["music_cues_after"] = max_music_segments
            summary["applied"] = True

        if summary["applied"]:
            for seg in script_segments:
                effects = seg.sound_effects or []
                names = []
                for effect in effects:
                    if isinstance(effect, dict):
                        name = effect.get("name") or effect.get("id") or effect.get("effect_id") or ""
                    else:
                        name = getattr(effect, "name", "") or str(effect)
                    if name:
                        names.append(name)
                seg.sound_effects_simple = names

                if seg.music_cue:
                    if isinstance(seg.music_cue, dict):
                        seg.music_cue_simple = seg.music_cue.get("style") or seg.music_cue.get("name") or ""
                    else:
                        seg.music_cue_simple = getattr(seg.music_cue, "style", "") or str(seg.music_cue)
                else:
                    seg.music_cue_simple = ""

        return summary
    
    async def generate_chapter_audio(
        self,
        chapter_content: str,
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        output_path: Optional[str] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题",
        enable_quality_review: bool = True,
        quality_threshold: float = 70.0,
        audiobook_project_id: Optional[int] = None,  # 新增：用于WebSocket推送
        chapter_title: str = "",
        chapter_summary: str = "",
        summary_data: Any = None,
    ) -> Dict[str, Any]:
        """
        生成单章节有声书
        
        Args:
            chapter_content: 章节文本
            chapter_id: 章节ID
            character_list: 角色列表（可选）
            output_path: 输出路径（可选）
            novel_genre: 小说类型
            novel_theme: 小说主题
        
        Returns:
            {
                "success": True/False,
                "audio_data": bytes,
                "duration": 秒,
                "file_size": 字节,
                "stats": {...}
            }
        """
        start_time = time.time()
        
        # 创建任务追踪
        task_id = self.task_tracker.create_task(
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            metadata={"character_list": character_list}
        )
        
        logger.info(f"{'='*70}")
        logger.info(f"🎬 开始生成章节有声书: Chapter {chapter_id} [TaskID: {task_id[:8]}]")
        logger.info(f"{'='*70}")
        
        try:
            quality_report = None  # 剧本级质量评审结果
            final_audio_review = None  # 最终音频评审结果
            auto_revision: Dict[str, Any] = {"applied": False}
            # ============ 阶段1：制定改编策略 ============
            self.task_tracker.start_stage(task_id, StageType.STRATEGY)
            logger.info("🎭 [1/6] AudioDirector制定改编策略...")
            
            # 📡 WebSocket推送：策略阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='strategy',
                    progress=0,
                    message='正在制定改编策略...'
                )
            
            strategy = self.audio_director.formulate_strategy(
                novel_genre=novel_genre,
                novel_theme=novel_theme,
                target_audience="通用听众"
            )

            # 应用项目级音效/BGM 配置对策略进行微调（如控制音效/配乐密度）
            self._apply_audio_fx_to_strategy(strategy)

            # 将导演策略传递给剧本改编Agent，启用语义完整性控制
            self.script_adapter.strategy = strategy
            
            self.task_tracker.complete_stage(task_id, StageType.STRATEGY, metrics={
                "style": strategy.style.value,
                "sound_density": strategy.sound_effect_density
            })
            logger.info(f"   ✅ 策略: {strategy.style.value}, 音效密度: {strategy.sound_effect_density}")
            
            # 📡 WebSocket推送：策略阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='strategy',
                    progress=100,
                    message=f'策略完成: {strategy.style.value}',
                    stage_metrics={'style': strategy.style.value, 'sound_density': strategy.sound_effect_density}
                )
            
            # ============ 阶段2：剧本改编 ============
            self.task_tracker.start_stage(task_id, StageType.SCRIPT_ADAPTATION)
            logger.info("📝 [2/6] AudiobookScriptAdapter剧本改编...")
            
            # 📡 WebSocket推送：剧本阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='script_adaptation',
                    progress=0,
                    message='正在改编剧本...'
                )
            
            def on_script_progress(progress: float, metrics: Optional[Dict[str, Any]] = None) -> None:
                self.task_tracker.update_stage_progress(
                    task_id,
                    StageType.SCRIPT_ADAPTATION,
                    progress,
                    metrics,
                )

            audio_adaptation_context = build_audio_adaptation_hint(
                summary_data,
                chapter_title=chapter_title,
                chapter_summary=chapter_summary,
            )
            adapted_result = await self.script_adapter.adapt_chapter(
                chapter_content=chapter_content,
                character_list=character_list,
                chapter_title=chapter_title or f"Chapter {chapter_id}",
                genre=novel_genre,
                adaptation_context=audio_adaptation_context,
                progress_callback=on_script_progress,
            )
            
            # 兼容 ChapterStructure 与纯片段列表两种返回形式
            if isinstance(adapted_result, ChapterStructure):
                chapter_structure = adapted_result
                script_segments = self._flatten_chapter_structure(chapter_structure)
                segments_count = chapter_structure.get_total_segments()
            else:
                chapter_structure = None
                script_segments = adapted_result
                segments_count = len(script_segments)
            
            self.task_tracker.complete_stage(task_id, StageType.SCRIPT_ADAPTATION, metrics={
                "segments_count": segments_count,
                "text_length": len(chapter_content)
            })
            logger.info(f"   ✅ 生成 {segments_count} 个剧本片段")
            
            # 📡 WebSocket推送：剧本阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='script_adaptation',
                    progress=100,
                    message=f'剧本改编完成：{len(script_segments)}个片段',
                    stage_metrics={'segments_count': len(script_segments)}
                )
            
            # ============ 阶段3-5：并行设计（音色+音效+音乐） ============
            logger.info("🎵 [3-5/8] 并行设计：音色+音效+音乐...")
            
            # 📡 WebSocket推送：设计阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=0,
                    message='正在并行设计音色、音效、音乐...'
                )
            
            # 并行执行三个设计阶段
            # 👉 关键修复：只为未配置的角色设计音色，避免覆盖用户配置
            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_content,
                preserve_user_config=True,  # 🔥 保留用户配置
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
            )
            
            logger.info(f"   ✅ 并行设计完成")
            logger.info(f"      - 音色: {len(voice_profiles) if voice_profiles else 0} 个角色")
            logger.info(f"      - 音效: {sound_effects_count} 个标注")
            logger.info(f"      - 音乐: {music_cues_count} 个提示")
            
            # 📡 WebSocket推送：设计阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=100,
                    message=f'设计完成：{len(voice_profiles) if voice_profiles else 0}个角色、{sound_effects_count}个音效、{music_cues_count}个配乐',
                    stage_metrics={
                        'voice_count': len(voice_profiles) if voice_profiles else 0,
                        'sound_effects_count': sound_effects_count,
                        'music_cues_count': music_cues_count
                    }
                )

            # ============ 阶段6：剧本质量评审（TTS 前） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.QUALITY_REVIEW)
                logger.info("🔍 [6/8] AudioQualityReviewer剧本质量评审（TTS前）...")
                
                # 转换script_segments为评审格式
                review_segments = self._build_review_segments(script_segments)

                # 为前端评审弹窗准备一份精简的片段列表（只保留前50段）
                sample_segments = [
                    {
                        "index": idx,
                        "type": seg_dict["type"],
                        "speaker": seg_dict["speaker"],
                        "text": seg_dict["text"],
                        "emotion": seg_dict["emotion"],
                    }
                    for idx, seg_dict in enumerate(review_segments[:50])
                ]
                
                quality_report = self.audio_quality_reviewer.review_script(
                    review_segments,
                    novel_genre=novel_genre
                )

                auto_revision = self._auto_balance_script_audio_cues(
                    script_segments,
                    self.audio_quality_reviewer.quality_standards,
                )
                if auto_revision.get("applied"):
                    review_segments = self._build_review_segments(script_segments)
                    quality_report = self.audio_quality_reviewer.review_script(
                        review_segments,
                        novel_genre=novel_genre
                    )
                
                issues_preview = [
                    {
                        "location": issue.location,
                        "severity": issue.severity,
                        "category": issue.category,
                        "description": issue.description,
                        "suggestion": issue.suggestion,
                    }
                    for issue in quality_report.issues[:20]
                ]
                self.task_tracker.complete_stage(task_id, StageType.QUALITY_REVIEW, metrics={
                    "overall_score": quality_report.overall_score,
                    "overall_grade": quality_report.overall_grade,
                    "issues_count": len(quality_report.issues),
                    "script_quality": quality_report.script_quality,
                    "audio_balance": quality_report.audio_balance,
                    "pacing": quality_report.pacing,
                    "revision_suggestions": quality_report.revision_suggestions,
                    "sample_segments": sample_segments,
                    "issues": issues_preview,
                    "auto_revision": auto_revision if auto_revision.get("applied") else None,
                })
                
                logger.info(f"   ✅ 剧本评审完成: {quality_report.overall_grade} ({quality_report.overall_score:.1f}分)")
                logger.info(f"   发现 {len(quality_report.issues)} 个问题")
                
                # 质量预警（不阻断流程，仅日志提示）
                if quality_report.overall_score < quality_threshold:
                    logger.warning(f"⚠️ 剧本质量评分低于阈值 ({quality_report.overall_score:.1f} < {quality_threshold})")
                    logger.warning(f"   修订建议: {', '.join(quality_report.revision_suggestions)}")
                    for issue in quality_report.issues[:5]:
                        logger.warning(f"   - [{issue.severity}] {issue.description}")
                
                # 📡 WebSocket推送：剧本质量评审完成
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=100,
                        message=f'剧本质量评审完成：{quality_report.overall_grade} ({quality_report.overall_score:.1f}分)',
                        stage_metrics={
                            'overall_score': quality_report.overall_score,
                            'overall_grade': quality_report.overall_grade,
                            'issues_count': len(quality_report.issues),
                        }
                    )

                if auto_revision.get("applied"):
                    try:
                        _, sound_effects_count, music_cues_count = await self._parallel_design(
                            task_id,
                            script_segments,
                            chapter_content,
                            preserve_user_config=True,
                            chapter_id=chapter_id,
                            audiobook_project_id=audiobook_project_id,
                            skip_stage_tracking=True,
                            include_voice_design=False,
                        )

                        audio_fx = getattr(self, "_audio_fx_config", None)
                        sound_metrics = {"sound_effects_count": sound_effects_count}
                        if self._last_effect_timeline:
                            sound_metrics["timeline"] = self._last_effect_timeline
                        if audio_fx:
                            enable_sfx = audio_fx.get("enable_sound_effects", True)
                            sfx_density = str(audio_fx.get("sound_effect_density") or "").lower()
                            if (not enable_sfx) or sfx_density == "off":
                                sound_metrics["skipped"] = True
                        self.task_tracker.complete_stage(
                            task_id,
                            StageType.SOUND_DESIGN,
                            metrics=sound_metrics,
                        )

                        music_metrics = {"music_cues_count": music_cues_count}
                        if self._last_music_timeline:
                            music_metrics["timeline"] = self._last_music_timeline
                        if audio_fx:
                            enable_music = audio_fx.get("enable_music", True)
                            music_density = str(audio_fx.get("music_density") or "").lower()
                            if (not enable_music) or music_density == "off":
                                music_metrics["skipped"] = True
                        self.task_tracker.complete_stage(
                            task_id,
                            StageType.MUSIC_COMPOSITION,
                            metrics=music_metrics,
                        )

                        logger.info("Auto revision applied; refreshed sound/music timelines.")
                    except Exception as exc:
                        logger.warning("Auto revision refresh failed: %s", exc)
            else:
                # 跳过质量评审，标记为已完成
                self.task_tracker.complete_stage(task_id, StageType.QUALITY_REVIEW, metrics={
                    "skipped": True
                })
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=100,
                        message='已跳过剧本质量评审（配置关闭）',
                        stage_metrics={'skipped': True}
                    )
            
            # ============ 阶段7：音频提示词审阅 ============
            self._assign_voices(script_segments)
            self.task_tracker.start_stage(task_id, StageType.AUDIO_PROMPT_REVIEW)
            prompt_metrics = {
                "segments_count": len(script_segments),
                "sound_effects_count": sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments),
                "music_cues_count": sum(
                    1
                    for seg in script_segments
                    if getattr(seg, "music_cue", None) or getattr(seg, "music_cue_simple", "")
                ),
                "instruct_count": sum(
                    1
                    for seg in script_segments
                    if (getattr(seg, "instruct_emotion", "") or getattr(seg, "instruct_scene", "") or getattr(seg, "instruct_role", "") or getattr(seg, "instruct_identity", ""))
                ),
            }
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_PROMPT_REVIEW, metrics=prompt_metrics)
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='audio_prompt_review',
                    progress=100,
                    message='音频提示词准备完成，可进入审阅',
                    stage_metrics=prompt_metrics,
                )

            # ============ 阶段8：TTS合成 ============
            self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
            logger.info("🎙️ [8/10] TTS合成中...")
            
            # 📡 WebSocket推送：TTS阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='tts_synthesis',
                    progress=0,
                    message=f'正在合成{len(script_segments)}个音频片段...'
                )
            
            audio_list = await self._synthesize_segments(script_segments)
            
            tts_stats = self.tts_engine.get_cost_stats()
            
            self.task_tracker.complete_stage(task_id, StageType.TTS_SYNTHESIS, metrics={
                "tts_stats": tts_stats
            })
            logger.info(f"   ✅ TTS完成: {tts_stats}")
            
            # 📡 WebSocket推送：TTS阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='tts_synthesis',
                    progress=100,
                    message='音频合成完成',
                    stage_metrics=tts_stats
                )
            
            # 基于真实音频时长对齐音效/配乐时间线
            self._realign_timelines_with_audio(script_segments, audio_list)

            # ============ 阶段9：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [9/10] 音频混合中...")
            
            final_audio = self.audio_mixer.mix_chapter(audio_list)
            
            # 应用音效时间线（如有）
            if self._last_effect_timeline and self._last_effect_timeline.get("timeline"):
                logger.info("🎛 应用音效时间线叠加音效...")
                final_audio = self._apply_sound_effects(final_audio, self._last_effect_timeline)
            
            # 应用配乐时间线（如有）
            if self._last_music_timeline and self._last_music_timeline.get("timeline"):
                logger.info("🎼 应用配乐时间线叠加BGM...")
                final_audio = self._apply_background_music(final_audio, self._last_music_timeline)
            
            # 允许空音频（用于MVP测试）
            if not final_audio:
                logger.warning("⚠️ 音频为空，生成占位数据")
                final_audio = b""  # 空字节
                
            audio_info = self.audio_mixer.get_audio_info(final_audio)
            
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_MIXING, metrics={
                "audio_info": audio_info
            })
            logger.info(f"   ✅ 混合完成: {audio_info}")
            
            # ============ 阶段10：最终音频评审（可选） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.FINAL_AUDIO_REVIEW)
                logger.info("🔎 [10/10] 最终音频评审（基于音频信息）...")
                
                final_audio_review = self._final_audio_review(
                    audio_info=audio_info,
                    file_size=len(final_audio),
                    script_quality_report=quality_report,
                )

                self.task_tracker.complete_stage(task_id, StageType.FINAL_AUDIO_REVIEW, metrics=final_audio_review)
                
                logger.info(f"   ✅ 最终音频评审完成: {final_audio_review.get('summary', '')}")
            else:
                # 跳过音频评审，标记为已完成
                self.task_tracker.complete_stage(task_id, StageType.FINAL_AUDIO_REVIEW, metrics={
                    "skipped": True
                })
            
            # ============ 阶段11：保存文件（可选） ============
            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(final_audio)
                logger.info(f"💾 音频已保存: {output_path}")
            
            # ============ 阶段12：统计结果 ============
            elapsed_time = time.time() - start_time
            
            # 标记任务完成
            self.task_tracker.complete_task(task_id)
            
            # 统计对话和旁白数量（兼容parse_stats）
            dialogue_count = 0
            narration_count = 0
            for seg in script_segments:
                if hasattr(seg, 'type'):
                    if seg.type == "dialogue":
                        dialogue_count += 1
                    elif seg.type == "narration":
                        narration_count += 1
            
            script_segments_payload: List[Dict[str, Any]] = []
            for seg in script_segments:
                if is_dataclass(seg):
                    script_segments_payload.append(asdict(seg))
                elif isinstance(seg, dict):
                    script_segments_payload.append(seg)
                else:
                    script_segments_payload.append(getattr(seg, "__dict__", seg))

            quality_report_payload = asdict(quality_report) if quality_report else None
            if quality_report_payload and auto_revision.get("applied"):
                quality_report_payload["auto_revision"] = auto_revision

            result = {
                "success": True,
                "task_id": task_id,  # 返回任务ID
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
                "script_segments_payload": script_segments_payload,
                "quality_report_detail": quality_report_payload,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "mode": "专业Agent模式",
                    # 兼容旧版API的parse_stats结构
                    "parse_stats": {
                        "total_segments": len(script_segments),
                        "dialogue_count": dialogue_count,
                        "narration_count": narration_count,
                    },
                    "script_segments": len(script_segments),
                    "characters": len(characters_in_script) if 'characters_in_script' in locals() else 0,
                    "sound_effects": sound_effects_count if 'sound_effects_count' in locals() else 0,
                    "music_cues": music_cues_count if 'music_cues_count' in locals() else 0,
                    "tts_stats": tts_stats,
                    "audio_info": audio_info,
                    "quality_report": {
                        "overall_grade": quality_report.overall_grade,
                        "overall_score": quality_report.overall_score,
                        "issues_count": len(quality_report.issues),
                        "revision_suggestions": quality_report.revision_suggestions,
                        "auto_revision": auto_revision if auto_revision.get("applied") else None,
                    } if quality_report else None,
                    "final_audio_review": final_audio_review,
                }
            }
            
            logger.info(f"{'='*70}")
            if len(final_audio) > 0:
                logger.info(f"✅ 章节生成成功!")
            else:
                logger.info(f"⚠️ 章节生成完成（模拟模式，无真实音频）")
                logger.info(f"   提示: 请配置 DASHSCOPE_API_KEY 环境变量以生成真实音频")
            logger.info(f"   - 时长: {audio_info.get('duration_seconds', 0):.1f}秒")
            logger.info(f"   - 大小: {len(final_audio)/1024:.1f}KB")
            logger.info(f"   - 耗时: {elapsed_time:.1f}秒")
            logger.info(f"   - 成本: {tts_stats.get('estimated_cost', '¥0.00')}")
            logger.info(f"{'='*70}\n")
            
            return result
                
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"❌ 章节生成失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 标记任务失败（如果task_id已创建）
            if 'task_id' in locals():
                # 尝试获取当前阶段
                task_status = self.task_tracker.get_task_status(task_id)
                if task_status:
                    for stage_name, stage_info in task_status['stages'].items():
                        if stage_info['status'] == 'running':
                            self.task_tracker.fail_stage(
                                task_id,
                                StageType(stage_name),
                                str(e)
                            )
                            break
            
            return {
                "success": False,
                "task_id": task_id if 'task_id' in locals() else None,
                "error": str(e),
                "audio_data": None,
                "duration": 0,
                "file_size": 0,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒"
                }
            }
    
    def _flatten_chapter_structure(
        self,
        chapter_structure: ChapterStructure,
    ) -> List[ScriptSegment]:
        """将 ChapterStructure 展平为 ScriptSegment 列表，包含片头和片尾"""
        segments: List[ScriptSegment] = []

        # 片头
        opening = chapter_structure.opening
        if opening and opening.intro_text:
            opening_segment = ScriptSegment(
                type="narration",
                text=opening.intro_text,
                speaker=getattr(opening, "intro_narrator", "旁白") or "旁白",
                emotion="calm",
                performance_notes="章节片头",
                pause_before=0.0,
                pause_after=0.5,
                music_cue=getattr(opening, "intro_music", None),
                original_text=opening.intro_text,
                adaptation_reason="自动生成章节片头",
            )
            segments.append(opening_segment)

        # 正文
        segments.extend(chapter_structure.body_segments or [])

        # 片尾
        closing = chapter_structure.closing
        if closing:
            # 🆕 收集片尾各部分文本
            closing_parts = [
                closing.recap_text.strip() if closing.recap_text else "",
                closing.hook_text.strip() if closing.hook_text else "",
                closing.call_to_action.strip() if closing.call_to_action else "",
            ]
            
            # 🔥 关键修复：过滤异常内容（移除包含"旁白"等角色说话引导语的片段）
            import re
            cleaned_parts = []
            for part in closing_parts:
                if not part:
                    continue
                
                # 检测并移除异常的角色说话引导语（如"旁白说："、"旁白怎么怎么样"等）
                # 模式1："旁白说：xxx" → 保留"xxx"
                cleaned = re.sub(r'^旁白[说道讲][:：]\s*', '', part)
                # 模式2："旁白怎么怎么样" → 完全移除这种描述性文本
                if not re.match(r'^旁白[^：:，,。.！!？?\s]+', cleaned):
                    # 只有不是纯粹描述旁白状态的文本才保留
                    cleaned_parts.append(cleaned)
                else:
                    logger.warning(f"⚠️ 片尾检测到异常内容并移除: {part[:50]}")
            
            closing_text = " ".join(cleaned_parts)
            if closing_text:
                closing_segment = ScriptSegment(
                    type="narration",
                    text=closing_text,
                    speaker=getattr(closing, "outro_narrator", "旁白") or "旁白",
                    emotion="calm",
                    performance_notes="章节片尾",
                    pause_before=0.5,
                    pause_after=0.0,
                    music_cue=getattr(closing, "outro_music", None),
                    original_text=closing_text,
                    adaptation_reason="自动生成章节片尾",
                )
                segments.append(closing_segment)

        return segments
    
    def _assign_voices(self, script_segments):
        """为剧本片段分配音色（统一使用VoiceManager）"""
        for segment in script_segments:
            if segment.speaker == "旁白":
                voice_profile = self.voice_manager.get_narrator_voice()
            else:
                voice_profile = self.voice_manager.get_voice(segment.speaker)
                if not voice_profile:
                    # 未知角色，临时分配
                    voice_profile = self.voice_manager.assign_voice(segment.speaker)
            
            # 🔥 重构后：使用 VoiceManager 的默认参数，并合并段落级 voice_params
            segment_emotion = getattr(segment, "emotion", "neutral")
            instruct_emotion = (getattr(segment, "instruct_emotion", "") or "").strip()
            emotion_for_params = instruct_emotion or segment_emotion or "neutral"
            voice_params_dict = voice_profile.get_tts_params(emotion_for_params)

            segment_voice_params = getattr(segment, "voice_params", None) or {}
            for key, value in segment_voice_params.items():
                if value is None or key == "speaker":
                    continue
                voice_params_dict[key] = value

            if "rate" not in voice_params_dict and "speed" in voice_params_dict:
                voice_params_dict["rate"] = voice_params_dict["speed"]

            voice_params_dict["pause_before"] = segment_voice_params.get(
                "pause_before",
                getattr(segment, "pause_before", 0.0),
            )
            voice_params_dict["pause_after"] = segment_voice_params.get(
                "pause_after",
                getattr(segment, "pause_after", 0.0),
            )
            
            # 🔍 调试：输出最终参数
            logger.info(
                f"🎵 [{segment.speaker}] 最终voice_params: "
                f"speaker={voice_params_dict.get('speaker')}, "
                f"pitch={voice_params_dict.get('pitch')}, "
                f"speed={voice_params_dict.get('speed'):.2f}, "
                f"volume={voice_params_dict.get('volume')}"
            )
            
            # 写回到segment
            segment.voice_params = voice_params_dict
            
            # 将片段元信息透传给TTS，用于Instruct模板（场景/角色/身份）
            segment.voice_params["segment_speaker"] = getattr(segment, "speaker", "")
            segment.voice_params["segment_type"] = getattr(segment, "type", "") 
            segment.voice_params["instruct_emotion"] = instruct_emotion
            segment.voice_params["instruct_scene"] = getattr(segment, "instruct_scene", "") or ""
            segment.voice_params["instruct_role"] = getattr(segment, "instruct_role", "") or ""
            segment.voice_params["instruct_identity"] = getattr(segment, "instruct_identity", "") or ""

            if instruct_emotion or segment.voice_params["instruct_scene"] or segment.voice_params["instruct_role"] or segment.voice_params["instruct_identity"]:
                segment.voice_params["use_instruct_mode"] = True
    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None
    ) -> List[bytes]:
        """批量合成剧本片段"""
        # 准备批量数据
        batch_data = [
            {
                "text": seg.text,
                "voice_params": seg.voice_params if hasattr(seg, 'voice_params') else {},
                "emotion": (getattr(seg, "instruct_emotion", "") or getattr(seg, "emotion", "neutral"))
            }
            for seg in script_segments
        ]
        
        # 批量合成（使用分批策略）
        audio_list = await self.tts_engine.synthesize_batch(
            batch_data,
            batch_size=10,  # 每批10个片段
            batch_interval=0,  # 批次间0秒（取消节流）
            debug_save_segments=debug_save_segments,
            debug_output_dir=debug_output_dir
        )
        
        return audio_list

    @staticmethod
    def _parse_scene_index(scene_id: str) -> Optional[int]:
        if not scene_id:
            return None
        for prefix in ("scene_", "climax_", "shift_"):
            if scene_id.startswith(prefix):
                try:
                    return int(scene_id[len(prefix):])
                except ValueError:
                    return None
        return None

    @staticmethod
    def _build_segment_offsets(durations: List[float]) -> List[Dict[str, float]]:
        offsets: List[Dict[str, float]] = []
        current = 0.0
        for duration in durations:
            safe_duration = max(0.0, float(duration))
            offsets.append({"start": current, "duration": safe_duration})
            current += safe_duration
        return offsets

    @staticmethod
    def _estimate_segment_durations(script_segments: List[ScriptSegment]) -> List[float]:
        durations = []
        for seg in script_segments:
            text = getattr(seg, "text", "") or ""
            duration = len(text) / 10.0
            durations.append(max(duration, 0.2))
        return durations

    def _align_timeline_with_audio(
        self,
        timeline: Optional[Dict[str, Any]],
        estimated_offsets: List[Dict[str, float]],
        actual_offsets: List[Dict[str, float]],
        total_actual_duration: float,
        *,
        align_environment: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not timeline or not timeline.get("timeline"):
            return timeline

        adjusted_items: List[Dict[str, Any]] = []
        for item in timeline.get("timeline", []):
            new_item = dict(item)
            scene_id = str(item.get("scene_id") or "")
            idx = self._parse_scene_index(scene_id)
            if idx is not None and idx < len(estimated_offsets) and idx < len(actual_offsets):
                est_start = estimated_offsets[idx]["start"]
                actual_start = actual_offsets[idx]["start"]
                relative = max(0.0, float(item.get("timestamp", 0.0)) - est_start)
                new_item["timestamp"] = actual_start + relative
            elif scene_id == "ending":
                duration = float(item.get("duration") or 0.0)
                new_item["timestamp"] = max(0.0, total_actual_duration - duration)
            elif scene_id == "opening":
                new_item["timestamp"] = 0.0
            adjusted_items.append(new_item)

        if align_environment:
            env_indices = [
                idx for idx, item in enumerate(adjusted_items)
                if item.get("type") == "environment" or item.get("loop")
            ]
            for pos, idx in enumerate(env_indices):
                item = adjusted_items[idx]
                start = float(item.get("timestamp", 0.0))
                next_start = total_actual_duration
                if pos + 1 < len(env_indices):
                    next_start = float(adjusted_items[env_indices[pos + 1]].get("timestamp", total_actual_duration))
                if next_start <= start:
                    continue
                item["duration"] = max(0.0, next_start - start)
                item["loop"] = True

        timeline_copy = dict(timeline)
        timeline_copy["timeline"] = adjusted_items
        return timeline_copy

    def _realign_timelines_with_audio(
        self,
        script_segments: List[ScriptSegment],
        audio_list: List[bytes],
    ) -> None:
        if not audio_list or not script_segments:
            return

        estimated_durations = self._estimate_segment_durations(script_segments)
        actual_durations: List[float] = []
        for idx, audio in enumerate(audio_list):
            if not audio:
                actual_durations.append(estimated_durations[idx] if idx < len(estimated_durations) else 0.2)
                continue
            info = self.audio_mixer.get_audio_info(audio)
            duration = float(info.get("duration_seconds", 0.0) or 0.0)
            if duration <= 0 and idx < len(estimated_durations):
                duration = estimated_durations[idx]
            actual_durations.append(duration)

        estimated_offsets = self._build_segment_offsets(estimated_durations)
        actual_offsets = self._build_segment_offsets(actual_durations)
        total_actual = sum(actual_durations)

        self._last_effect_timeline = self._align_timeline_with_audio(
            self._last_effect_timeline,
            estimated_offsets,
            actual_offsets,
            total_actual,
            align_environment=True,
        )
        self._last_music_timeline = self._align_timeline_with_audio(
            self._last_music_timeline,
            estimated_offsets,
            actual_offsets,
            total_actual,
            align_environment=False,
        )

    def _apply_sound_effects(
        self,
        audio_data: bytes,
        effect_timeline: Dict[str, Any],
    ) -> bytes:
        """根据音效时间线，将音效叠加到音频上"""
        if not audio_data:
            return audio_data
        
        timeline_items = effect_timeline.get("timeline") or []
        if not timeline_items:
            return audio_data
        
        mixed_audio = audio_data
        base_dir = Path(__file__).resolve().parents[3] / "data" / "audio_library"
        audio_fx = getattr(self, "_audio_fx_config", None) or {}
        ducking_enabled = audio_fx.get("sound_effect_ducking", True)
        ducking_priority = audio_fx.get("sound_effect_priority", "dialogue")
        ducking_threshold_dbfs = audio_fx.get("sound_effect_ducking_threshold_dbfs", -35.0)
        ducking_reduction_db = audio_fx.get("sound_effect_ducking_reduction_db", -6.0)
        ducking_chunk_ms = audio_fx.get("sound_effect_ducking_chunk_ms", 250)
        base_dir = Path(__file__).resolve().parents[3] / "data" / "audio_library"
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)

            # 根据时间线中的类型和音量，计算对应的音量衰减（dB）
            effect_type_str = item.get("type", "action")
            # 🔧 已降低所有音效约 5-6dB，使其相对人声更小
            base_gain_map = {
                "environment": -14.0,  # 环境音（降低 6dB）
                "action": -14.0,       # 动作音（降低 6dB）
                "emotion": -16.0,      # 情绪音（降低 6dB）
                "transition": -18.0,   # 过渡音（降低 6dB）
            }
            base_gain = base_gain_map.get(effect_type_str, -16.0)
            duration = item.get("duration")
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            loop = bool(item.get("loop")) or effect_type_str == "environment"

            # timeline volume 约定为 0.0~1.0，0.5 视为“默认音量”
            timeline_volume = item.get("volume", 0.5)
            try:
                timeline_volume = float(timeline_volume)
            except (TypeError, ValueError):
                timeline_volume = 0.5
            # 避免 0 导致 log10 计算错误，做一点下限保护
            timeline_volume = max(0.05, min(1.0, timeline_volume))

            # 以 0.5 为基准做相对音量调整
            relative = timeline_volume / 0.5
            volume_adjust_db = 20 * math.log10(relative)
            effect_volume_offset = base_gain + volume_adjust_db

            if not file_ref:
                continue
            
            effect_path = Path(file_ref)
            if not effect_path.is_absolute():
                # 相对路径：相对于 audio_library 根目录
                effect_path = base_dir / file_ref
            if not effect_path.exists():
                effect_name = Path(file_ref).stem or str(item.get("description") or "").strip()
                if effect_name:
                    for candidate in (base_dir / "sound_effects").rglob(f"{effect_name}.*"):
                        effect_path = candidate
                        break
            if not effect_path.exists():
                logger.warning(f"⚠️ 音效文件不存在: {effect_path}")
                continue
            
            try:
                with effect_path.open("rb") as f:
                    effect_bytes = f.read()
                position_ms = int(timestamp * 1000)
                effect_duration_ms = None
                try:
                    if duration is not None:
                        duration_val = float(duration)
                        if duration_val <= 0:
                            effect_duration_ms = max(0, len(mixed_audio) - position_ms) if loop else None
                        else:
                            effect_duration_ms = int(duration_val * 1000)
                except (TypeError, ValueError):
                    effect_duration_ms = None
                fade_in_ms = int(float(fade_in) * 1000) if fade_in else 0
                fade_out_ms = int(float(fade_out) * 1000) if fade_out else 0
                mixed_audio = self.audio_mixer.add_sound_effect(
                    mixed_audio,
                    effect_bytes,
                    position_ms=position_ms,
                    effect_volume_offset=effect_volume_offset,
                    effect_duration_ms=effect_duration_ms,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                    loop_fill=bool(loop),
                    ducking_enabled=bool(ducking_enabled),
                    ducking_priority=str(ducking_priority or "dialogue"),
                    ducking_threshold_dbfs=float(ducking_threshold_dbfs),
                    ducking_reduction_db=float(ducking_reduction_db),
                    ducking_chunk_ms=int(ducking_chunk_ms),
                )
            except Exception as e:
                logger.warning(f"⚠️ 叠加音效失败 {effect_path}: {e}")
        
        return mixed_audio

    def _resolve_music_path(
        self,
        file_ref: str,
        base_dir: Path,
        *,
        style_hint: str = "",
        mood_hint: str = "",
    ) -> Optional[Path]:
        """解析配乐文件路径（支持索引回退与缓存目录搜索）。"""
        if file_ref:
            music_path = Path(file_ref)
            if not music_path.is_absolute():
                music_path = base_dir / file_ref
            if music_path.exists():
                return music_path

            candidate_name = Path(file_ref).stem
            if candidate_name:
                for candidate in (base_dir / "music_cache").rglob(f"{candidate_name}.*"):
                    return candidate

        style_hint = (style_hint or "").strip()
        mood_hint = (mood_hint or "").strip().lower()
        index_path = base_dir / "music_index.json"
        if index_path.exists():
            try:
                raw = index_path.read_text(encoding="utf-8")
                index_data = json.loads(raw)
            except Exception as exc:
                logger.warning(f"?? 读取配乐索引失败: {exc}")
                index_data = []

            if isinstance(index_data, list):
                if style_hint:
                    for entry in index_data:
                        style = str(entry.get("style") or "").strip()
                        if style and (style_hint in style or style in style_hint):
                            file_path = entry.get("file_path")
                            if file_path and Path(file_path).exists():
                                return Path(file_path)
                if mood_hint:
                    for entry in index_data:
                        if str(entry.get("mood") or "").strip().lower() == mood_hint:
                            file_path = entry.get("file_path")
                            if file_path and Path(file_path).exists():
                                return Path(file_path)
                for entry in index_data:
                    file_path = entry.get("file_path")
                    if file_path and Path(file_path).exists():
                        return Path(file_path)

        for candidate in (base_dir / "music_cache").rglob("*.mp3"):
            return candidate
        return None
    
    def _apply_background_music(
        self,
        audio_data: bytes,
        music_timeline: Dict[str, Any],
    ) -> bytes:
        """根据配乐时间线，将BGM叠加到音频上（🆕 智能音量平衡版）
        
        Args:
            audio_data: 原始音频数据
            music_timeline: 配乐时间线，包含 timeline 列表
        
        Returns:
            叠加BGM后的音频数据
        """
        if not audio_data:
            return audio_data
        
        timeline_items = music_timeline.get("timeline") or []
        if not timeline_items:
            return audio_data
        
        mixed_audio = audio_data
        
        # 🆕 检查是否启用智能音量平衡
        audio_fx = getattr(self, "_audio_fx_config", None) or {}
        intelligent_balance = audio_fx.get("intelligent_balance", False)
        # 将默认配乐基准音量从 -30dB 再降低到 -36dB，避免喧宾夺主
        base_bgm_volume_db = audio_fx.get("base_bgm_volume", -36)
        try:
            bgm_crossfade_ms = int(audio_fx.get("bgm_crossfade_ms") or 0)
        except Exception:
            bgm_crossfade_ms = 0
        if bgm_crossfade_ms < 0:
            bgm_crossfade_ms = 0
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)
            volume = item.get("volume", 0.2)
            sync_with_dialogue = item.get("sync_with_dialogue", True)
            dialogue_volume_reduction = item.get("dialogue_volume_reduction", 0.0)
            mood = item.get("mood", "peaceful")
            music_type = item.get("type", "underscore")
            cue_duration = item.get("duration", None)
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            
            # 🆕 智能音量平衡计算
            if intelligent_balance:
                bgm_volume_offset = self._calculate_intelligent_bgm_volume(
                    base_volume_db=base_bgm_volume_db,
                    music_type=music_type,
                    mood=mood,
                    target_volume=volume
                )
                logger.debug(f"🎚️ 智能音量: {music_type}/{mood} → {bgm_volume_offset:.1f}dB")
            else:
                # 原有逻辑：固定基准音量
                base_gain = base_bgm_volume_db
                try:
                    volume_val = float(volume)
                except (TypeError, ValueError):
                    volume_val = 0.2
                volume_val = max(0.05, min(1.0, volume_val))
                
                # 以 0.2 为基准做相对音量调整
                relative = volume_val / 0.2
                volume_adjust_db = 20 * math.log10(relative) if relative > 0 else -40
                bgm_volume_offset = base_gain + volume_adjust_db

            # 统一再降低 3dB，进一步减弱BGM存在感
            bgm_volume_offset -= 3
            
            if not file_ref:
                continue
            
            music_path = Path(file_ref)
            if not music_path.is_absolute():
                # 相对路径：相对于 audio_library 根目录
                # engine.py 在 backend/app/services/audiobook/ 下，parents[3] = backend/
                base_dir = Path(__file__).resolve().parents[3] / "data" / "audio_library"
                music_path = base_dir / file_ref
            
            if not music_path.exists():
                resolved = self._resolve_music_path(
                    str(file_ref or ""),
                    base_dir,
                    style_hint=str(item.get("description") or ""),
                    mood_hint=str(mood or ""),
                )
                if resolved:
                    music_path = resolved
            if not music_path.exists():
                logger.warning(f"⚠️ 配乐文件不存在: {music_path}")
                continue
            
            try:
                with music_path.open("rb") as f:
                    bgm_bytes = f.read()
                
                logger.info(f"🎼 叠加BGM: {music_path.name} (音量: {bgm_volume_offset:.1f}dB)")
                
                # 使用 AudioMixer.add_background_music 叠加 BGM
                position_ms = max(0, int(float(timestamp or 0.0) * 1000))
                duration_ms = None
                try:
                    if cue_duration is not None:
                        duration_ms = max(0, int(float(cue_duration) * 1000))
                except (TypeError, ValueError):
                    duration_ms = None

                fade_in_ms = max(0, int(float(fade_in or 0.0) * 1000))
                fade_out_ms = max(0, int(float(fade_out or 0.0) * 1000))
                if bgm_crossfade_ms > 0:
                    fade_in_ms = max(fade_in_ms, bgm_crossfade_ms)
                    fade_out_ms = max(fade_out_ms, bgm_crossfade_ms)

                mixed_audio = self.audio_mixer.add_background_music(
                    mixed_audio,
                    bgm_bytes,
                    bgm_volume_offset=int(bgm_volume_offset),
                    position_ms=position_ms,
                    duration_ms=duration_ms,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                    loop_fill=True,
                    sync_with_dialogue=bool(sync_with_dialogue),
                    dialogue_volume_reduction=float(dialogue_volume_reduction or 0.0),
                )
                logger.info(f"✅ 已叠加配乐: {music_path.name}, 音量偏移={bgm_volume_offset:.1f}dB")
            except Exception as e:
                logger.warning(f"⚠️ 叠加配乐失败 {music_path}: {e}")
        
        return mixed_audio
    
    def _calculate_intelligent_bgm_volume(
        self,
        base_volume_db: float,
        music_type: str,
        mood: str,
        target_volume: float
    ) -> float:
        """
        🤖 智能计算BGM音量（根据场景类型、情绪、音乐类型进行动态调整）
        
        Args:
            base_volume_db: 基础音量（dB），默认-30dB
            music_type: 音乐类型 (opening/ending/underscore/theme)
            mood: 情绪 (tense/epic/peaceful/sad/joyful/mysterious/romantic)
            target_volume: 目标音量 (0.0-1.0)
        
        Returns:
            最终BGM音量偏移（dB）
        
        🎯 智能调整规则：
        1. 开场/片尾音乐：可适当提升音量 (+5dB)
        2. 高潮情绪(tense/epic)：提升音量 (+8dB)
        3. 平静情绪(peaceful/sad)：降低音量 (-5dB)
        4. 背景音乐(underscore)：保持基础音量
        5. 角色主题音乐(theme)：稍微提升 (+3dB)
        """
        # 从基础音量开始
        adjusted_volume = base_volume_db
        
        # 1. 根据音乐类型调整
        if music_type == "opening" or music_type == "ending":
            adjusted_volume += 5  # 开场/结尾可以更响亮
            logger.debug(f"  🎬 开场/结尾音乐: +5dB")
        elif music_type == "theme":
            adjusted_volume += 3  # 主题音乐稍微突出
            logger.debug(f"  🎭 主题音乐: +3dB")
        
        # 2. 根据情绪调整
        if mood in ["tense", "epic"]:
            adjusted_volume += 8  # 紧张/史诗场景，配乐加强
            logger.debug(f"  🔥 高潮情绪({mood}): +8dB")
        elif mood in ["peaceful", "sad"]:
            adjusted_volume -= 5  # 平静/悲伤场景，配乐低调
            logger.debug(f"  🌙 平静情绪({mood}): -5dB")
        elif mood in ["joyful", "romantic"]:
            adjusted_volume += 2  # 欢快/浪漫场景，稍微提升
            logger.debug(f"  ✨ 欢快情绪({mood}): +2dB")
        
        # 3. 根据目标音量做相对调整
        try:
            volume_val = float(target_volume)
        except (TypeError, ValueError):
            volume_val = 0.2
        volume_val = max(0.05, min(1.0, volume_val))
        
        # 以 0.2 为基准，计算相对调整
        relative = volume_val / 0.2
        volume_adjust_db = 20 * math.log10(relative) if relative > 0 else -40
        adjusted_volume += volume_adjust_db
        
        # 4. 限制在合理范围内 (-50dB 到 -10dB)
        adjusted_volume = max(-50, min(-10, adjusted_volume))
        
        logger.debug(
            f"  🎶 最终音量: {base_volume_db:.1f}dB → {adjusted_volume:.1f}dB "
            f"(类型={music_type}, 情绪={mood}, 目标={volume_val:.2f})"
        )
        
        return adjusted_volume
    
    def _final_audio_review(
        self,
        audio_info: Dict[str, Any],
        file_size: int,
        script_quality_report: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """对最终混合后的音频做一次轻量评审。

        说明：
        - 主要基于音频时长和基础信息做兜底检查
        - 不做真实波形分析，后续可以接入语音模型进一步增强
        """
        duration = float(audio_info.get("duration_seconds", 0.0) or 0.0)
        bitrate = audio_info.get("bitrate", None)
        sample_rate = audio_info.get("sample_rate", None)

        standards = getattr(self.audio_quality_reviewer, "quality_standards", {})
        max_duration = float(standards.get("max_episode_duration", 0) or 0)
        min_duration = float(standards.get("min_episode_duration", 0) or 0)

        warnings: List[str] = []

        if max_duration and duration > max_duration:
            warnings.append(f"音频时长偏长（约 {duration/60:.1f} 分钟）")
        if min_duration and duration and duration < min_duration * 0.5:
            warnings.append(f"音频时长偏短（约 {duration/60:.1f} 分钟）")

        summary = "通过"
        severity = "info"
        if warnings:
            summary = "存在潜在节奏/时长问题"
            severity = "warning"

        return {
            "duration_seconds": duration,
            "duration_minutes": round(duration / 60.0, 1),
            "file_size_bytes": file_size,
            "bitrate": bitrate,
            "sample_rate": sample_rate,
            "warnings": warnings,
            "summary": summary,
            "severity": severity,
            "script_overall_score": getattr(script_quality_report, "overall_score", None) if script_quality_report else None,
            "script_overall_grade": getattr(script_quality_report, "overall_grade", None) if script_quality_report else None,
        }
    
    async def _parallel_design(
        self,
        task_id: str,
        script_segments: List[Any],
        chapter_content: str = "",
        preserve_user_config: bool = False,  # 🆕 新参数：是否保留用户配置
        chapter_id: Optional[int] = None,
        audiobook_project_id: Optional[int] = None,
        skip_stage_tracking: bool = False,
        include_voice_design: bool = True,
    ) -> tuple:
        """
        并行执行音色、音效、音乐设计
        
        Args:
            task_id: 任务ID
            script_segments: 剧本片段列表
            chapter_content: 章节原文（用于环境音与配乐生成）
            preserve_user_config: 是否保留用户配置（True=只为未配置的角色设计音色）
        
        Returns:
            (voice_profiles, sound_effects_count, music_cues_count)
        """
        # 定义三个并行任务
        allow_asset_generation = False
        async def voice_design_task():
            """ 音色设计任务（已废弃，现统一使用VoiceManager）"""
            if not include_voice_design:
                return {}
            if not skip_stage_tracking:
                self.task_tracker.start_stage(task_id, StageType.VOICE_DESIGN)
            
            # 提取角色列表
            characters_in_script = list(set([
                seg.speaker for seg in script_segments 
                if seg.speaker != "旁白"
            ]))
            
            if characters_in_script:
                # 🔥 重构：VoiceDesigner 不再设计音色，只检查配置完整性
                if preserve_user_config:
                    # 获取已配置的角色列表
                    configured_characters = set(self.voice_manager.voice_profiles.keys())
                    # 找出未配置的角色
                    characters_to_design = [
                        char for char in characters_in_script 
                        if char not in configured_characters
                    ]
                    
                    if configured_characters:
                        logger.info(f"   🛡️ 保留用户配置: {len(configured_characters)} 个角色 {list(configured_characters)}")
                    
                    # 🔥 关键改动：为未配置的角色使用 VoiceManager.assign_voice 而不是 VoiceDesigner
                    if characters_to_design:
                        logger.info(f"   🎭 使用VoiceManager自动分配: {len(characters_to_design)} 个角色 {characters_to_design}")
                        for char_name in characters_to_design:
                            # 使用 VoiceManager 的智能分配逻辑
                            self.voice_manager.assign_voice(char_name)
                        
                    voice_profiles = {}  # 返回空字典，因为已由 VoiceManager 管理
                else:
                    # 不保留用户配置时，也用 VoiceManager 重新分配
                    logger.info(f"   🎭 使用VoiceManager为 {len(characters_in_script)} 个角色分配音色")
                    for char_name in characters_in_script:
                        self.voice_manager.assign_voice(char_name)
                    voice_profiles = {}
                
                if skip_stage_tracking:
                    return voice_profiles
                self.task_tracker.complete_stage(task_id, StageType.VOICE_DESIGN, metrics={
                    "characters_count": len(characters_in_script),
                    "preserved_count": len(configured_characters) if preserve_user_config else 0,
                    "unified_system": "VoiceManager"  # 🔥 标记：已统一到VoiceManager
                })
                
                return voice_profiles
            else:
                if skip_stage_tracking:
                    return []
                self.task_tracker.complete_stage(task_id, StageType.VOICE_DESIGN, metrics={
                    "characters_count": 0
                })
                return []
        
        async def sound_design_task():
            """音效设计任务（增强 Mureka 环境音）"""
            if not skip_stage_tracking:
                self.task_tracker.start_stage(task_id, StageType.SOUND_DESIGN)
            
            # 如果项目配置关闭了音效，直接跳过音效设计阶段
            audio_fx = getattr(self, "_audio_fx_config", None)
            if audio_fx:
                enable_sfx = audio_fx.get("enable_sound_effects", True)
                sfx_density = str(audio_fx.get("sound_effect_density") or "").lower()
                if (not enable_sfx) or sfx_density == "off":
                    logger.info("🎚 项目级配置已关闭音效设计，跳过 SoundEffectDesigner 阶段")
                    self._last_effect_timeline = None
                    if skip_stage_tracking:
                        return 0
                    self.task_tracker.complete_stage(
                        task_id,
                        StageType.SOUND_DESIGN,
                        metrics={"sound_effects_count": 0, "skipped": True}
                    )
                    return 0
            
            # 构造用于音效设计的简化片段结构
            script_dicts = []
            for seg in script_segments:
                text = getattr(seg, "text", "") or ""
                raw_effects = getattr(seg, "sound_effects", None)
                effect_names = []
                if raw_effects:
                    for ef in raw_effects:
                        if not ef:
                            continue
                        if isinstance(ef, dict):
                            name = ef.get("name") or ef.get("effect_id") or ef.get("id")
                        else:
                            name = getattr(ef, "name", None) or str(ef)
                        if name:
                            effect_names.append(name)
                else:
                    effect_names = getattr(seg, "sound_effects_simple", []) or []

                script_dicts.append(
                    {
                        "text": text,
                        "sound_effects": effect_names,
                    }
                )
            
            # 调用音效设计器生成音效时间线
            try:
                effect_cues = self.sound_effect_designer.design_effects(
                    script_dicts,
                    allow_asset_generation=allow_asset_generation,
                )
                
                # 根据音效密度配置优化音效数量
                sfx_density = str(audio_fx.get("sound_effect_density") or "medium").lower() if audio_fx else "medium"
                if sfx_density == "low":
                    max_per_min = 2  # 低密度：每分钟最多2个音效
                elif sfx_density == "high":
                    max_per_min = 6  # 高密度：每分钟最多6个音效
                else:  # medium
                    max_per_min = 4   # 中密度：每分钟最多4个音效
                
                effect_cues = self.sound_effect_designer.optimize_effect_density(max_effects_per_minute=max_per_min)
                logger.info(f"🎧 根据密度配置 ({sfx_density}) 优化后：{len(effect_cues)} 个音效")
                
                self._last_effect_timeline = self.sound_effect_designer.export_effect_timeline()
                sound_effects_count = len(self.sound_effect_designer.effect_cues)
                effect_timeline = self._last_effect_timeline
            except Exception as e:
                logger.warning(f"⚠️ 音效设计阶段异常，将退回到简单计数逻辑: {e}")
                sound_effects_count = sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments)
                self._last_effect_timeline = None
                effect_timeline = None
            
            metrics = {"sound_effects_count": sound_effects_count}
            if effect_timeline:
                metrics["timeline"] = effect_timeline
            if skip_stage_tracking:
                return sound_effects_count
            self.task_tracker.complete_stage(task_id, StageType.SOUND_DESIGN, metrics=metrics)
            
            return sound_effects_count
        
        async def music_composition_task():
            """音乐编曲任务（增强 AI 配乐）"""
            if not skip_stage_tracking:
                self.task_tracker.start_stage(task_id, StageType.MUSIC_COMPOSITION)
            
            # 如果项目配置关闭了配乐，直接跳过配乐设计阶段
            audio_fx = getattr(self, "_audio_fx_config", None)
            if audio_fx:
                enable_music = audio_fx.get("enable_music", True)
                music_density = str(audio_fx.get("music_density") or "").lower()
                if (not enable_music) or music_density == "off":
                    logger.info("🎚 项目级配置已关闭配乐设计，跳过 MusicComposer 阶段")
                    self._last_music_timeline = None
                    if skip_stage_tracking:
                        return 0
                    self.task_tracker.complete_stage(
                        task_id,
                        StageType.MUSIC_COMPOSITION,
                        metrics={"music_cues_count": 0, "skipped": True}
                    )
                    return 0
            
            # 提取音乐标注并设计配乐方案
            try:
                # 构造章节结构用于配乐设计（结合剧本片段的emotion和music_cue）
                total_duration = len(chapter_content) / 10.0 if chapter_content else 600.0

                scenes = []
                current_time = 0.0
                for idx, seg in enumerate(script_segments):
                    text = getattr(seg, "text", "") or ""
                    seg_len = len(text)
                    seg_duration = seg_len / 10.0  # 粗略估算本段时长

                    # 先累加，用上一段累加的 current_time 作为下一段的起点
                    start_time = current_time
                    current_time += seg_duration

                    # 只有在存在 music_cue 或明显的情绪标签时，才认为是需要配乐的场景
                    raw_music_cue = getattr(seg, "music_cue", None)
                    music_cue_text = ""
                    if isinstance(raw_music_cue, str):
                        music_cue_text = raw_music_cue
                    elif isinstance(raw_music_cue, dict):
                        music_cue_text = (
                            raw_music_cue.get("style")
                            or raw_music_cue.get("name")
                            or raw_music_cue.get("cue")
                            or ""
                        )
                    else:
                        # 兼容简洁模式：music_cue_simple 只是一个字符串说明
                        music_cue_text = getattr(seg, "music_cue_simple", "") or ""

                    emotion = (getattr(seg, "emotion", "") or "").lower()

                    has_explicit_music = bool(music_cue_text)
                    has_strong_emotion = any(key in emotion for key in ["tense", "sad", "happy", "excited", "solemn"])

                    if not has_explicit_music and not has_strong_emotion:
                        continue

                    # 将剧本情绪标签映射到音乐情绪
                    mood = "peaceful"
                    if "tense" in emotion or "angry" in emotion:
                        mood = "tense"
                    elif "sad" in emotion:
                        mood = "sad"
                    elif "happy" in emotion or "excited" in emotion:
                        mood = "joyful"
                    elif "tender" in emotion:
                        mood = "romantic"
                    elif "solemn" in emotion:
                        mood = "epic"

                    # 如果 music_cue 文本里带有明显情绪关键词，也参与微调
                    lc_cue = music_cue_text.lower()
                    if any(k in lc_cue for k in ["suspense", "紧张", "心跳", "低频"]):
                        mood = "tense"
                    elif any(k in lc_cue for k in ["romantic", "浪漫"]):
                        mood = "romantic"
                    elif any(k in lc_cue for k in ["sad", "哀伤", "悲伤"]):
                        mood = "sad"

                    scenes.append({
                        "scene_id": f"scene_{idx}",
                        "start_time": start_time,
                        "duration": min(max(seg_duration, 20.0), 120.0),  # 单段配乐时长限制在 20-120 秒
                        "mood": mood,
                        "description": text[:80],
                        "is_climax": "tense" in mood or "epic" in mood,
                        "is_turning_point": False,
                    })

                # 🆕 智能化增强：高潮点检测 + 情绪曲线分析
                audio_fx = getattr(self, "_audio_fx_config", None) or {}
                enable_smart_enhancement = audio_fx.get("auto_climax_detection", False)
                
                if enable_smart_enhancement:
                    logger.info("🤖 启用智能化增强...")
                    
                    # 1. 高潮点检测
                    climax_points = self.climax_detector.detect_climax_points(script_segments)
                    
                    # 2. 情绪曲线分析
                    emotion_flow = self.emotion_analyzer.analyze_chapter_emotion_flow(script_segments)
                    
                    # 3. 为检测到的高潮点添加配乐
                    for climax in climax_points:
                        idx = climax.segment_idx
                        if idx >= len(script_segments):
                            continue
                        
                        seg = script_segments[idx]
                        # 计算时间点（累积前面所有片段的时长）
                        climax_start_time = sum(
                            getattr(script_segments[i], 'estimated_duration', 5.0)
                            for i in range(idx)
                        )
                        
                        scenes.append({
                            "scene_id": f"climax_{idx}",
                            "start_time": climax_start_time,
                            "duration": 45.0,  # 高潮配乐持续45秒
                            "mood": getattr(seg, 'emotion', 'epic'),
                            "description": f"高潮点 - {climax.description}",
                            "is_climax": True,
                            "is_turning_point": climax.climax_type == 'turning_point',
                            "music_prompt_key": "awakening" if climax.climax_type == 'battle' else "faction_intro"
                        })
                        logger.info(
                            f"  ✅ 添加高潮配乐 #{idx}: {climax.description} "
                            f"(强度={climax.intensity:.2f})"
                        )
                    
                    # 4. 为情绪转折点添加转场音乐
                    for shift in emotion_flow.get('emotional_shifts', []):
                        idx = shift.idx
                        if idx >= len(script_segments):
                            continue
                        
                        shift_start_time = sum(
                            getattr(script_segments[i], 'estimated_duration', 5.0)
                            for i in range(idx)
                        )
                        
                        scenes.append({
                            "scene_id": f"shift_{idx}",
                            "start_time": shift_start_time,
                            "duration": 10.0,  # 转场音乐较短
                            "mood": shift.to_emotion,
                            "description": f"情绪转场 - {shift.from_emotion}→{shift.to_emotion}",
                            "is_climax": False,
                            "is_turning_point": True,
                            "music_prompt_key": "suspense" if shift.to_emotion == 'tense' else "daily"
                        })
                        logger.info(f"  ✅ 添加转场音乐 #{idx}: {shift.shift_type}")
                
                # 如果没有任何候选场景，则退回到原来的简单三场景策略
                if not scenes:
                    scenes = [
                        {
                            "scene_id": f"scene_{i}",
                            "start_time": i * 60.0,
                            "duration": 60.0,
                            "mood": "peaceful",
                            "description": getattr(seg, "text", "")[:50],
                            "is_climax": False,
                            "is_turning_point": False,
                        }
                        for i, seg in enumerate(script_segments[:3])
                    ]

                # 选取第一个场景的情绪作为整体基调，否则使用默认值
                overall_mood = scenes[0]["mood"] if scenes else "mysterious"

                chapter_structure = {
                    "total_duration": total_duration,
                    "overall_mood": overall_mood,
                    "scenes": scenes,
                    "chapter_id": chapter_id,
                    "audiobook_project_id": audiobook_project_id,
                }
                
                # 根据密度决定是否跳过开场/结尾音乐
                music_density = str(audio_fx.get("music_density") or "medium").lower() if audio_fx else "medium"
                skip_intro_outro = (music_density == "low")  # 低密度时只保留关键场景配乐
                
                music_cues = await self.music_composer.design_music(
                    chapter_structure,
                    skip_intro_outro=skip_intro_outro,
                    allow_asset_generation=allow_asset_generation,
                )
                
                # 根据音乐密度配置优化配乐数量
                if music_density == "low":
                    max_coverage = 0.15  # 低密度：最多覆盖15%时长
                elif music_density == "high":
                    max_coverage = 0.45  # 高密度：最多覆盖45%时长
                else:  # medium
                    max_coverage = 0.30  # 中密度：最多覆盖30%时长
                
                music_cues = self.music_composer.optimize_music_placement(max_music_coverage=max_coverage)
                logger.info(f"🎼 根据密度配置 ({music_density}) 优化后：{len(music_cues)} 个配乐提示")
                
                self._last_music_timeline = self.music_composer.export_music_timeline()
                music_cues_count = len(music_cues)
                music_timeline = self._last_music_timeline
                logger.info(f"🎼 已设计 {music_cues_count} 个配乐提示")
            except Exception as e:
                logger.warning(f"⚠️ 配乐设计异常（不影响主流程）: {e}")
                music_cues_count = sum(1 for seg in script_segments if seg.music_cue)
                self._last_music_timeline = None
                music_timeline = None
            
            metrics = {"music_cues_count": music_cues_count}
            if music_timeline:
                metrics["timeline"] = music_timeline
            if skip_stage_tracking:
                return music_cues_count
            self.task_tracker.complete_stage(task_id, StageType.MUSIC_COMPOSITION, metrics=metrics)
            
            return music_cues_count
        
        # 并行执行三个任务
        voice_profiles, sound_effects_count, music_cues_count = await asyncio.gather(
            voice_design_task(),
            sound_design_task(),
            music_composition_task()
        )
        
        return voice_profiles, sound_effects_count, music_cues_count
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
        
        Returns:
            任务状态信息，包括各阶段进度
        """
        return self.task_tracker.get_task_status(task_id)
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """
        获取所有任务状态
        
        Returns:
            所有任务的状态列表
        """
        return self.task_tracker.get_all_tasks()
    
    async def prepare_chapter_script(
        self,
        chapter_content: str,
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题",
        enable_quality_review: bool = True,
        quality_threshold: float = 70.0,
        audiobook_project_id: Optional[int] = None,
        chapter_title: str = "",
        chapter_summary: str = "",
        summary_data: Any = None,
    ) -> Dict[str, Any]:
        """仅生成章节剧本与剧本质量评审，不执行TTS和混音。

        用于两阶段流程的第1阶段：先改编+评审，再人工审稿，最后进入TTS。
        """
        start_time = time.time()

        task_id = self.task_tracker.create_task(
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            metadata={"character_list": character_list},
        )

        logger.info(f"{'='*70}")
        logger.info(f"📝 开始生成章节剧本: Chapter {chapter_id} [TaskID: {task_id[:8]}]")
        logger.info(f"{'='*70}")

        try:
            quality_report = None

            # 阶段1：制定改编策略
            self.task_tracker.start_stage(task_id, StageType.STRATEGY)
            logger.info("🎭 [1/7] 制定改编策略...")
            
            # 📡 WebSocket推送：策略阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='strategy',
                    progress=0,
                    message='正在制定改编策略...'
                )
            
            strategy = self.audio_director.formulate_strategy(
                novel_genre=novel_genre,
                novel_theme=novel_theme,
                target_audience="通用听众",
            )
            # 应用项目级音效/BGM 配置对策略进行微调
            self._apply_audio_fx_to_strategy(strategy)
            self.script_adapter.strategy = strategy
            self.task_tracker.complete_stage(
                task_id,
                StageType.STRATEGY,
                metrics={
                    "style": strategy.style.value,
                    "sound_density": strategy.sound_effect_density,
                },
            )
            logger.info(f"   ✅ 策略: {strategy.style.value}, 音效密度: {strategy.sound_effect_density}")
            
            # 📡 WebSocket推送：策略阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='strategy',
                    progress=100,
                    message=f'策略完成: {strategy.style.value}',
                    stage_metrics={'style': strategy.style.value, 'sound_density': strategy.sound_effect_density}
                )

            # 阶段2：剧本改编
            self.task_tracker.start_stage(task_id, StageType.SCRIPT_ADAPTATION)
            logger.info("📝 [2/7] 剧本改编...")
            
            # 📡 WebSocket推送：剧本阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='script_adaptation',
                    progress=0,
                    message='正在改编剧本...'
                )
            
            def on_script_progress(progress: float, metrics: Optional[Dict[str, Any]] = None) -> None:
                self.task_tracker.update_stage_progress(
                    task_id,
                    StageType.SCRIPT_ADAPTATION,
                    progress,
                    metrics,
                )

            audio_adaptation_context = build_audio_adaptation_hint(
                summary_data,
                chapter_title=chapter_title,
                chapter_summary=chapter_summary,
            )
            adapted_result = await self.script_adapter.adapt_chapter(
                chapter_content=chapter_content,
                character_list=character_list,
                chapter_title=chapter_title or f"Chapter {chapter_id}",
                genre=novel_genre,
                adaptation_context=audio_adaptation_context,
                progress_callback=on_script_progress,
            )

            if isinstance(adapted_result, ChapterStructure):
                chapter_structure = adapted_result
                script_segments = self._flatten_chapter_structure(chapter_structure)
                segments_count = chapter_structure.get_total_segments()
            else:
                chapter_structure = None
                script_segments = adapted_result
                segments_count = len(script_segments)

            self.task_tracker.complete_stage(
                task_id,
                StageType.SCRIPT_ADAPTATION,
                metrics={
                    "segments_count": segments_count,
                    "text_length": len(chapter_content),
                },
            )
            logger.info(f"   ✅ 生成 {segments_count} 个剧本片段")
            
            # 📡 WebSocket推送：剧本阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='script_adaptation',
                    progress=100,
                    message=f'剧本改编完成：{segments_count}个片段',
                    stage_metrics={'segments_count': segments_count}
                )

            # ============ 阶段3-5：并行设计（音色+音效+音乐）============
            logger.info("🎵 [3-5/7] 并行设计：音色、音效、音乐...")

            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=0,
                    message='正在并行设计音色、音效、音乐...'
                )

            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_content,
                preserve_user_config=True,
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
            )

            logger.info("   ✅并行设计完成")
            logger.info(f"      - 音色: {len(voice_profiles) if voice_profiles else 0} 个角色")
            logger.info(f"      - 音效: {sound_effects_count} 个标注")
            logger.info(f"      - 音乐: {music_cues_count} 个提示")

            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=100,
                    message=f'设计完成：{len(voice_profiles) if voice_profiles else 0}个角色、{sound_effects_count}个音效、{music_cues_count}个配乐',
                    stage_metrics={
                        'voice_count': len(voice_profiles) if voice_profiles else 0,
                        'sound_effects_count': sound_effects_count,
                        'music_cues_count': music_cues_count
                    }
                )

            # 阶段3：剧本质量评审（可选）
            review_segments = self._build_review_segments(script_segments)
            auto_revision: Dict[str, Any] = {"applied": False}
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.QUALITY_REVIEW)
                logger.info("🔍 [6/7] 剧本质量评审...")
                
                # 📡 WebSocket推送：评审阶段开始
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=0,
                        message='正在评审剧本质量...'
                    )

                quality_report_obj = self.audio_quality_reviewer.review_script(
                    review_segments,
                    novel_genre=novel_genre,
                )

                auto_revision = self._auto_balance_script_audio_cues(
                    script_segments,
                    self.audio_quality_reviewer.quality_standards,
                )
                if auto_revision.get("applied"):
                    review_segments = self._build_review_segments(script_segments)
                    quality_report_obj = self.audio_quality_reviewer.review_script(
                        review_segments,
                        novel_genre=novel_genre,
                    )
                # 序列化为dict，方便存库
                quality_report = {
                    "script_quality": quality_report_obj.script_quality,
                    "audio_balance": quality_report_obj.audio_balance,
                    "pacing": quality_report_obj.pacing,
                    "overall_grade": quality_report_obj.overall_grade,
                    "overall_score": quality_report_obj.overall_score,
                    "revision_suggestions": quality_report_obj.revision_suggestions,
                    "issues": [
                        {
                            "location": i.location,
                            "severity": i.severity,
                            "category": i.category,
                            "description": i.description,
                            "suggestion": i.suggestion,
                        }
                        for i in quality_report_obj.issues
                    ],
                    "auto_revision": auto_revision if auto_revision.get("applied") else None,
                }

                issues_preview = quality_report["issues"][:20]
                stage_metrics = {
                    "overall_score": quality_report_obj.overall_score,
                    "overall_grade": quality_report_obj.overall_grade,
                    "issues_count": len(quality_report_obj.issues),
                    "script_quality": quality_report_obj.script_quality,
                    "audio_balance": quality_report_obj.audio_balance,
                    "pacing": quality_report_obj.pacing,
                    "revision_suggestions": quality_report_obj.revision_suggestions,
                    "issues": issues_preview,
                }
                if auto_revision.get("applied"):
                    stage_metrics["auto_revision"] = auto_revision
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics=stage_metrics,
                )
                logger.info(f"   ✅ 评审完成: {quality_report_obj.overall_grade} ({quality_report_obj.overall_score:.1f}分)")
                logger.info(f"   发现 {len(quality_report_obj.issues)} 个问题")
                
                # 📡 WebSocket推送：评审阶段完成
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=100,
                        message=f'剧本质量评审完成：{quality_report_obj.overall_grade} ({quality_report_obj.overall_score:.1f}分)',
                        stage_metrics={
                            'overall_score': quality_report_obj.overall_score,
                            'overall_grade': quality_report_obj.overall_grade,
                            'issues_count': len(quality_report_obj.issues),
                        }
                    )

                if quality_report_obj.overall_score < quality_threshold:
                    logger.warning(
                        f"⚠️ 剧本质量评分低于阈值 ({quality_report_obj.overall_score:.1f} < {quality_threshold})"
                    )
                    logger.warning(
                        f"   修订建议: {', '.join(quality_report_obj.revision_suggestions)}"
                    )
            else:
                # 跳过质量评审
                logger.info("⚠️ [6/7] 已跳过剧本质量评审（配置关闭）")
                quality_report = None
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics={"skipped": True},
                )

            # 为脚本片段补全音色参数，便于提示词审阅
            self._assign_voices(script_segments)

            # 音频提示词审阅阶段（输出可编辑的提示词快照）
            self.task_tracker.start_stage(task_id, StageType.AUDIO_PROMPT_REVIEW)
            output_segments = self._build_review_segments(script_segments)
            prompt_metrics = {
                "segments_count": len(script_segments),
                "sound_effects_count": sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments),
                "music_cues_count": sum(
                    1
                    for seg in script_segments
                    if getattr(seg, "music_cue", None) or getattr(seg, "music_cue_simple", "")
                ),
                "instruct_count": sum(
                    1
                    for seg in script_segments
                    if (getattr(seg, "instruct_emotion", "") or getattr(seg, "instruct_scene", "") or getattr(seg, "instruct_role", "") or getattr(seg, "instruct_identity", ""))
                ),
            }
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_PROMPT_REVIEW, metrics=prompt_metrics)

            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='audio_prompt_review',
                    progress=100,
                    message='音频提示词准备完成，可进入审阅',
                    stage_metrics=prompt_metrics,
                )

            # 统计对话和旁白数量
            dialogue_count = 0
            narration_count = 0
            for seg in script_segments:
                seg_type = getattr(seg, "type", "")
                if seg_type == "dialogue":
                    dialogue_count += 1
                elif seg_type == "narration":
                    narration_count += 1

            elapsed_time = time.time() - start_time

            result: Dict[str, Any] = {
                "success": True,
                "task_id": task_id,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "parse_stats": {
                        "total_segments": len(script_segments),
                        "dialogue_count": dialogue_count,
                        "narration_count": narration_count,
                    },
                    "characters": len(character_list or []),
                },
                "script_segments": output_segments,
                "quality_report": quality_report,
            }

            self.task_tracker.complete_task(task_id)
            return result

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"❌ 剧本生成失败: {e}")
            import traceback
            traceback.print_exc()

            if "task_id" in locals():
                task_status = self.task_tracker.get_task_status(task_id)
                if task_status:
                    for stage_name, stage_info in task_status["stages"].items():
                        if stage_info["status"] == "running":
                            self.task_tracker.fail_stage(
                                task_id,
                                StageType(stage_name),
                                str(e),
                            )
                            break

            return {
                "success": False,
                "task_id": task_id,
                "error": str(e),
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                },
            }

    async def generate_chapter_audio_from_script(
        self,
        script_segments_data: List[Dict[str, Any]],
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        output_path: Optional[str] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题",
        enable_quality_review: bool = True,
        audiobook_project_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """使用已经生成/人工编辑后的剧本片段生成章节音频。

        用于两阶段流程的第2阶段：从 ChapterAudio.script_json 直接进入 TTS + 混音。
        """
        start_time = time.time()

        # 创建任务追踪（标记来源为 existing_script）
        task_id = self.task_tracker.create_task(
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            metadata={"character_list": character_list, "source": "script_json"},
        )

        logger.info(f"{'='*70}")
        logger.info(f"🎬 从剧本片段生成章节有声书: Chapter {chapter_id} [TaskID: {task_id[:8]}]")
        logger.info(f"{'='*70}")

        try:
            final_audio_review = None

            # ============ 阶段1：制定改编策略（用于后续设计阶段的风格参考） ============
            self.task_tracker.start_stage(task_id, StageType.STRATEGY)
            strategy = self.audio_director.formulate_strategy(
                novel_genre=novel_genre,
                novel_theme=novel_theme,
                target_audience="通用听众",
            )
            # 应用项目级音效/BGM 配置对策略进行微调
            self._apply_audio_fx_to_strategy(strategy)
            # 虽然不再改编剧本，但仍将策略传入，便于音效/配乐设计阶段参考
            self.script_adapter.strategy = strategy
            self.task_tracker.complete_stage(
                task_id,
                StageType.STRATEGY,
                metrics={
                    "style": strategy.style.value,
                    "sound_density": strategy.sound_effect_density,
                },
            )

            # ============ 阶段2：剧本改编（已完成，这里直接使用传入剧本） ============
            self.task_tracker.start_stage(task_id, StageType.SCRIPT_ADAPTATION)

            # 将dict列表转换为 ScriptSegment 对象列表
            script_segments: List[ScriptSegment] = []
            for seg_dict in script_segments_data:
                seg = ScriptSegment(
                    type=seg_dict.get("type") or "narration",
                    text=seg_dict.get("text") or "",
                    speaker=seg_dict.get("speaker") or "旁白",
                    emotion=seg_dict.get("emotion") or "neutral",
                    performance_notes=seg_dict.get("performance_notes", ""),
                    pause_before=float(seg_dict.get("pause_before") or 0.0),
                    pause_after=float(seg_dict.get("pause_after") or 0.0),
                    voice_params=seg_dict.get("voice_params"),
                    instruct_emotion=seg_dict.get("instruct_emotion", ""),
                    instruct_scene=seg_dict.get("instruct_scene", ""),
                    instruct_role=seg_dict.get("instruct_role", ""),
                    instruct_identity=seg_dict.get("instruct_identity", ""),
                    sound_effects=seg_dict.get("sound_effects") or [],
                    music_cue=seg_dict.get("music_cue"),
                    sound_effects_simple=seg_dict.get("sound_effects_simple", []),
                    music_cue_simple=seg_dict.get("music_cue_simple", ""),
                    original_text=seg_dict.get("original_text", ""),
                    adaptation_reason=seg_dict.get("adaptation_reason", ""),
                )
                script_segments.append(seg)

            segments_count = len(script_segments)
            self.task_tracker.complete_stage(
                task_id,
                StageType.SCRIPT_ADAPTATION,
                metrics={
                    "segments_count": segments_count,
                    "source": "existing_script",
                },
            )

            # ============ 阶段3-5：并行设计（音色+音效+音乐） ============
            logger.info("🎵 [3-5/8] 并行设计：音色+音效+音乐...")

            # 使用剧本文本粗略拼接作为环境描述
            chapter_text_for_design = "".join([seg.text for seg in script_segments])

            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_text_for_design,
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
            )

            # ============ 阶段6：音频提示词审阅 ============
            self._assign_voices(script_segments)
            self.task_tracker.start_stage(task_id, StageType.AUDIO_PROMPT_REVIEW)
            prompt_metrics = {
                "segments_count": len(script_segments),
                "sound_effects_count": sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments),
                "music_cues_count": sum(
                    1
                    for seg in script_segments
                    if getattr(seg, "music_cue", None) or getattr(seg, "music_cue_simple", "")
                ),
                "instruct_count": sum(
                    1
                    for seg in script_segments
                    if (getattr(seg, "instruct_emotion", "") or getattr(seg, "instruct_scene", "") or getattr(seg, "instruct_role", "") or getattr(seg, "instruct_identity", ""))
                ),
            }
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_PROMPT_REVIEW, metrics=prompt_metrics)

            # ============ 阶段7：TTS合成 ============
            self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
            logger.info("🎙️ [7/9] TTS合成中(基于已审稿剧本)...")
            
            # 🔧 调试：从环境变量读取调试开关
            import os
            debug_save_segments = os.getenv("TTS_DEBUG_SAVE_SEGMENTS", "false").lower() == "true"
            
            audio_list = await self._synthesize_segments(
                script_segments,
                debug_save_segments=debug_save_segments,
                debug_output_dir=f"backend/data/tts_debug/chapter_{chapter_id}"
            )

            tts_stats = self.tts_engine.get_cost_stats()

            self.task_tracker.complete_stage(
                task_id,
                StageType.TTS_SYNTHESIS,
                metrics={"tts_stats": tts_stats},
            )

            # 基于真实音频时长对齐音效/配乐时间线
            self._realign_timelines_with_audio(script_segments, audio_list)

            # ============ 阶段8：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [8/9] 音频混合中...")

            final_audio = self.audio_mixer.mix_chapter(audio_list)

            # 应用音效时间线（如有）
            if self._last_effect_timeline and self._last_effect_timeline.get("timeline"):
                logger.info("🎛 应用音效时间线叠加音效...")
                final_audio = self._apply_sound_effects(final_audio, self._last_effect_timeline)

            # 应用配乐时间线（如有）
            if self._last_music_timeline and self._last_music_timeline.get("timeline"):
                logger.info("🎼 应用配乐时间线叠加BGM...")
                final_audio = self._apply_background_music(final_audio, self._last_music_timeline)

            # 允许空音频（用于MVP测试）
            if not final_audio:
                logger.warning("⚠️ 音频为空，生成占位数据")
                final_audio = b""  # 空字节

            audio_info = self.audio_mixer.get_audio_info(final_audio)

            self.task_tracker.complete_stage(
                task_id,
                StageType.AUDIO_MIXING,
                metrics={"audio_info": audio_info},
            )

            # ============ 最终音频评审（可选） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.FINAL_AUDIO_REVIEW)

                final_audio_review = self._final_audio_review(
                    audio_info=audio_info,
                    file_size=len(final_audio),
                    script_quality_report=None,
                )

                self.task_tracker.complete_stage(
                    task_id,
                    StageType.FINAL_AUDIO_REVIEW,
                    metrics=final_audio_review,
                )
            else:
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.FINAL_AUDIO_REVIEW,
                    metrics={"skipped": True},
                )

            # ============ 保存文件（可选） ============
            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(final_audio)

            # ============ 统计结果 ============
            elapsed_time = time.time() - start_time

            # 标记任务完成
            self.task_tracker.complete_task(task_id)

            # 统计对话和旁白数量（兼容parse_stats）
            dialogue_count = 0
            narration_count = 0
            for seg in script_segments:
                seg_type = getattr(seg, "type", "")
                if seg_type == "dialogue":
                    dialogue_count += 1
                elif seg_type == "narration":
                    narration_count += 1

            result: Dict[str, Any] = {
                "success": True,
                "task_id": task_id,
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "mode": "script_only_pipeline",
                    "parse_stats": {
                        "total_segments": len(script_segments),
                        "dialogue_count": dialogue_count,
                        "narration_count": narration_count,
                    },
                    "script_segments": len(script_segments),
                    "sound_effects": sound_effects_count if "sound_effects_count" in locals() else 0,
                    "music_cues": music_cues_count if "music_cues_count" in locals() else 0,
                    "tts_stats": tts_stats,
                    "audio_info": audio_info,
                    "final_audio_review": final_audio_review,
                },
            }

            logger.info(f"{'='*70}")
            if len(final_audio) > 0:
                logger.info("✅ 从剧本生成章节音频成功!")
            else:
                logger.info("⚠️ 章节生成完成（模拟模式，无真实音频）")
                logger.info("   提示: 请配置 DASHSCOPE_API_KEY 环境变量以生成真实音频")
            logger.info(f"   - 时长: {audio_info.get('duration_seconds', 0):.1f}秒")
            logger.info(f"   - 大小: {len(final_audio)/1024:.1f}KB")
            logger.info(f"   - 耗时: {elapsed_time:.1f}秒")
            logger.info(f"   - 成本: {tts_stats.get('estimated_cost', '¥0.00')}")
            logger.info(f"{'='*70}\n")

            return result

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"❌ 从剧本生成章节音频失败: {e}")
            import traceback
            traceback.print_exc()

            # 标记任务失败（如果task_id已创建）
            if "task_id" in locals():
                task_status = self.task_tracker.get_task_status(task_id)
                if task_status:
                    for stage_name, stage_info in task_status["stages"].items():
                        if stage_info["status"] == "running":
                            self.task_tracker.fail_stage(
                                task_id,
                                StageType(stage_name),
                                str(e),
                            )
                            break

            return {
                "success": False,
                "task_id": task_id if "task_id" in locals() else None,
                "error": str(e),
                "audio_data": None,
                "duration": 0,
                "file_size": 0,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                },
            }

    async def generate_project_audio(
        self,
        project_id: int,
        chapter_ids: List[int],
        db_session,
        output_dir: str = "audiobooks"
    ) -> Dict[str, Any]:
        """
        生成整本书的有声书
        
        Args:
            project_id: 项目ID
            chapter_ids: 章节ID列表
            db_session: 数据库会话
            output_dir: 输出目录
        
        Returns:
            生成结果统计
        """
        logger.info(f"📚 开始生成项目 {project_id} 的有声书")
        logger.info(f"   共 {len(chapter_ids)} 章")
        
        # 1. 获取项目角色列表
        character_list = await self._get_project_characters(project_id, db_session)
        logger.info(f"   角色列表: {character_list}")
        
        # 2. 逐章生成
        results = []
        total_duration = 0
        total_size = 0
        
        for i, chapter_id in enumerate(chapter_ids, 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"处理进度: {i}/{len(chapter_ids)}")
            
            # 获取章节内容
            chapter = await self._get_chapter_content(chapter_id, db_session)
            if not chapter:
                logger.warning(f"⚠️ 章节 {chapter_id} 不存在")
                continue
            
            # 生成音频
            output_path = f"{output_dir}/project_{project_id}/chapter_{chapter['number']:03d}.mp3"
            result = await self.generate_chapter_audio(
                chapter_content=chapter["content"],
                chapter_id=chapter_id,
                character_list=character_list,
                output_path=output_path,
                chapter_title=chapter.get("title") or "",
                chapter_summary=chapter.get("summary") or "",
                summary_data=chapter.get("summary_data"),
            )
            
            if result["success"]:
                total_duration += result["duration"]
                total_size += result["file_size"]
                results.append({
                    "chapter_id": chapter_id,
                    "chapter_number": chapter["number"],
                    "success": True,
                    "audio_path": output_path,
                    "duration": result["duration"]
                })
            else:
                results.append({
                    "chapter_id": chapter_id,
                    "chapter_number": chapter["number"],
                    "success": False,
                    "error": result.get("error")
                })
            
            # 短暂延迟，避免API限流
            await asyncio.sleep(0.5)
        
        # 3. 汇总统计
        success_count = sum(1 for r in results if r["success"])
        tts_stats = self.tts_engine.get_cost_stats()
        
        summary = {
            "project_id": project_id,
            "total_chapters": len(chapter_ids),
            "success_count": success_count,
            "failed_count": len(chapter_ids) - success_count,
            "total_duration": total_duration,
            "total_duration_formatted": f"{total_duration/3600:.1f}小时",
            "total_size": total_size,
            "total_size_formatted": f"{total_size/1024/1024:.1f}MB",
            "tts_stats": tts_stats,
            "results": results
        }
        
        logger.info(f"\n{'='*70}")
        logger.info(f"✅ 项目生成完成!")
        logger.info(f"   成功: {success_count}/{len(chapter_ids)}")
        logger.info(f"   总时长: {summary['total_duration_formatted']}")
        logger.info(f"   总大小: {summary['total_size_formatted']}")
        logger.info(f"   总成本: {tts_stats.get('estimated_cost', '¥0.00')}")
        logger.info(f"{'='*70}\n")
        
        return summary
    
    async def _get_project_characters(
        self,
        project_id: int,
        db_session
    ) -> List[str]:
        """获取项目角色列表"""
        try:
            from backend.app.models.character import Character
            characters = db_session.query(Character).filter(
                Character.project_id == project_id
            ).all()
            
            return [c.name for c in characters if c.name]
        except Exception as e:
            logger.warning(f"⚠️ 获取角色列表失败: {e}")
            return []
    
    async def _get_chapter_content(
        self,
        chapter_id: int,
        db_session
    ) -> Optional[Dict[str, Any]]:
        """获取章节内容"""
        try:
            from backend.app.models.project import Chapter
            chapter = db_session.query(Chapter).filter(
                Chapter.id == chapter_id
            ).first()
            
            if chapter:
                return {
                    "id": chapter.id,
                    "number": chapter.chapter_number,
                    "title": chapter.title,
                    "content": chapter.content,
                    "summary": getattr(chapter, "summary", None),
                    "summary_data": getattr(chapter, "summary_data", None),
                }
            return None
        except Exception as e:
            logger.error(f"❌ 获取章节内容失败: {e}")
            return None
    
    # ==================== 章节并行生成功能 ====================
    
    async def generate_chapters_parallel(
        self,
        chapter_list: List[Dict[str, Any]],
        audiobook_project_id: int,
        db_session,
        max_concurrent: int = 3,
        output_dir: str = "audiobooks"
    ) -> Dict[str, Any]:
        """
        并行生成多个章节的有声书（核心功能）
        
        Args:
            chapter_list: 章节列表，每个元素包含:
                - chapter_id: 章节ID
                - content: 章节内容
                - chapter_number: 章节编号
                - character_list: 角色列表
            audiobook_project_id: 有声书项目ID
            db_session: 数据库会话
            max_concurrent: 最大并发数（默认3）
            output_dir: 输出目录
        
        Returns:
            {
                "success": True/False,
                "total_chapters": int,
                "completed_chapters": int,
                "failed_chapters": int,
                "total_duration": float,
                "total_cost": float,
                "results": [...]  # 每个章节的生成结果
            }
        """
        logger.info(f"🎵 开始并行生成 {len(chapter_list)} 个章节，并发数={max_concurrent}")
        
        # 📡 推送整体进度汇总（初始状态）
        if WEBSOCKET_AVAILABLE:
            await ws_manager.send_audiobook_project_summary(
                audiobook_project_id=audiobook_project_id,
                total_chapters=len(chapter_list),
                completed_chapters=0,
                failed_chapters=0,
                total_duration=0.0,
                total_cost=0.0
            )
        
        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # 统计数据
        results = []
        completed_count = 0
        failed_count = 0
        total_duration = 0.0
        total_cost = 0.0
        
        # 并发生成任务
        async def generate_one_chapter(chapter_info: Dict[str, Any]):
            nonlocal completed_count, failed_count, total_duration, total_cost
            
            async with semaphore:
                chapter_id = chapter_info['chapter_id']
                chapter_number = chapter_info['chapter_number']
                content = chapter_info['content']
                character_list = chapter_info.get('character_list', [])
                
                logger.info(f"  🎵 开始生成第{chapter_number}章...")
                
                try:
                    # 生成输出路径
                    output_path = f"{output_dir}/audiobook_{audiobook_project_id}/chapter_{chapter_number:03d}.mp3"
                    
                    # 调用生成方法（传递audiobook_project_id以启用WebSocket推送）
                    result = await self.generate_chapter_audio(
                        chapter_content=content,
                        chapter_id=chapter_id,
                        character_list=character_list,
                        output_path=output_path,
                        audiobook_project_id=audiobook_project_id,
                        chapter_title=chapter_info.get("title") or "",
                        chapter_summary=chapter_info.get("summary") or "",
                        summary_data=chapter_info.get("summary_data"),
                    )
                    
                    if result["success"]:
                        completed_count += 1
                        total_duration += result["duration"]
                        
                        # 提取成本
                        tts_stats = result.get("stats", {}).get("tts_stats", {})
                        cost_str = tts_stats.get("estimated_cost", "￥0.00")
                        # 解析成本字符串（如 "￥0.12"）
                        try:
                            cost = float(cost_str.replace("￥", "").replace("$", ""))
                        except:
                            cost = 0.0
                        total_cost += cost
                        
                        # 📡 推送章节完成通知
                        if WEBSOCKET_AVAILABLE:
                            await ws_manager.send_audiobook_chapter_complete(
                                audiobook_project_id=audiobook_project_id,
                                chapter_id=chapter_id,
                                audio_info={
                                    "chapter_number": chapter_number,
                                    "duration": result["duration"],
                                    "file_size": result["file_size"],
                                    "output_path": output_path
                                },
                                task_id=result.get("task_id")
                            )
                        
                        results.append({
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "success": True,
                            "audio_path": output_path,
                            "duration": result["duration"],
                            "file_size": result["file_size"]
                        })
                        
                        logger.info(f"  ✅ 第{chapter_number}章生成完成: {result['duration']:.1f}秒")
                    else:
                        failed_count += 1
                        error = result.get("error", "未知错误")
                        
                        # 📡 推送章节失败通知
                        if WEBSOCKET_AVAILABLE:
                            await ws_manager.send_audiobook_chapter_error(
                                audiobook_project_id=audiobook_project_id,
                                chapter_id=chapter_id,
                                error=error,
                                task_id=result.get("task_id")
                            )
                        
                        results.append({
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "success": False,
                            "error": error
                        })
                        
                        logger.error(f"  ❌ 第{chapter_number}章生成失败: {error}")
                    
                    # 📡 推送整体进度汇总
                    if WEBSOCKET_AVAILABLE:
                        await ws_manager.send_audiobook_project_summary(
                            audiobook_project_id=audiobook_project_id,
                            total_chapters=len(chapter_list),
                            completed_chapters=completed_count,
                            failed_chapters=failed_count,
                            total_duration=total_duration,
                            total_cost=total_cost
                        )
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"  ❌ 第{chapter_number}章生成异常: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # 📡 推送章节失败通知
                    if WEBSOCKET_AVAILABLE:
                        await ws_manager.send_audiobook_chapter_error(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            error=str(e)
                        )
                    
                    results.append({
                        "chapter_id": chapter_id,
                        "chapter_number": chapter_number,
                        "success": False,
                        "error": str(e)
                    })
                
                # 等待一小段时间，避免API频率限制
                await asyncio.sleep(0.5)
        
        # 并发执行所有章节
        await asyncio.gather(*[generate_one_chapter(chapter_info) for chapter_info in chapter_list])
        
        # 汇总统计
        summary = {
            "success": failed_count == 0,
            "total_chapters": len(chapter_list),
            "completed_chapters": completed_count,
            "failed_chapters": failed_count,
            "total_duration": total_duration,
            "total_duration_formatted": f"{total_duration/3600:.1f}小时" if total_duration >= 3600 else f"{total_duration/60:.1f}分钟",
            "total_cost": total_cost,
            "results": results
        }
        
        logger.info(f"\n{'='*70}")
        logger.info(f"✅ 并行生成完成!")
        logger.info(f"   成功: {completed_count}/{len(chapter_list)}")
        logger.info(f"   失败: {failed_count}")
        logger.info(f"   总时长: {summary['total_duration_formatted']}")
        logger.info(f"   总成本: ￥{total_cost:.2f}")
        logger.info(f"{'='*70}\n")
        
        return summary
