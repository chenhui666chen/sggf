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
from typing import List, Dict, Any, Optional
from pathlib import Path

from .script_adapter import AudiobookScriptAgent, ScriptSegment
from .voice_manager import VoiceManager
from .tts_engine import TTSEngine
from .audio_mixer import AudioMixer

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
        llm_client=None  # LLM客户端（用于专业Agent）
    ):
        # 检查LLM客户端
        if llm_client is None:
            raise ValueError("有声书引擎必须提供llm_client参数，用于剧本改编和质量评审")
        
        # 初始化任务追踪和消息总线
        self.task_tracker = TaskTracker()
        self.message_bus = MessageBus()
        
        # 初始化专业Agent
        logger.info("🎬 启用专业LLM驱动的多Agent协作模式")
        self.audio_director = AudioDirector(llm_client=llm_client)
        self.script_adapter = AudiobookScriptAgent(llm_client=llm_client)
        self.voice_designer = VoiceDesigner()
        self.sound_effect_designer = SoundEffectDesigner(llm_client=llm_client)
        self.music_composer = MusicComposer()
        self.audio_quality_reviewer = AudioQualityReviewer(llm_client=llm_client)
        
        # 初始化基础组件
        self.voice_manager = VoiceManager()
        self.tts_engine = TTSEngine(
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
            model="cosyvoice-v3-plus"  # 专业商业版：仅支持v3-plus（顶级音质）
        )
        self.audio_mixer = AudioMixer()
        # 存储最近一次音效时间线（用于混音）
        self._last_effect_timeline: Optional[Dict[str, Any]] = None
        # 存储最近一次配乐时间线（用于混音）
        self._last_music_timeline: Optional[Dict[str, Any]] = None
        
        logger.info("🎶 有声书生成引擎初始化完成")
    
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
        audiobook_project_id: Optional[int] = None  # 新增：用于WebSocket推送
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
            
            script_segments = await self.script_adapter.adapt_chapter(
                chapter_content=chapter_content,
                character_list=character_list,
                chapter_title=f"Chapter {chapter_id}",
                genre=novel_genre
            )
            
            self.task_tracker.complete_stage(task_id, StageType.SCRIPT_ADAPTATION, metrics={
                "segments_count": len(script_segments),
                "text_length": len(chapter_content)
            })
            logger.info(f"   ✅ 生成 {len(script_segments)} 个剧本片段")
            
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
            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id, script_segments, chapter_content
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
            
            # ============ 阶段6：TTS合成 ============
            self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
            logger.info("🎙️ [6/6] TTS合成中...")
            
            # 📡 WebSocket推送：TTS阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='tts_synthesis',
                    progress=0,
                    message=f'正在合成{len(script_segments)}个音频片段...'
                )
            
            # 为剧本片段分配音色
            self._assign_voices(script_segments)
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
            
            # ============ 阶段7：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [7/8] 音频混合中...")
            
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
            
            # ============ 阶段8：质量评审（可选） ============
            quality_report = None
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.QUALITY_REVIEW)
                logger.info("🔍 [8/8] AudioQualityReviewer质量评审...")
                
                # 转换script_segments为评审格式
                review_segments = [
                    {
                        "type": seg.type,
                        "text": seg.text,
                        "speaker": seg.speaker,
                        "emotion": seg.emotion,
                        "performance_notes": seg.performance_notes if hasattr(seg, 'performance_notes') else "",
                        "sound_effects": seg.sound_effects,
                        "music_cue": seg.music_cue if hasattr(seg, 'music_cue') else ""
                    }
                    for seg in script_segments
                ]
                
                quality_report = self.audio_quality_reviewer.review_script(review_segments)
                
                self.task_tracker.complete_stage(task_id, StageType.QUALITY_REVIEW, metrics={
                    "overall_score": quality_report.overall_score,
                    "overall_grade": quality_report.overall_grade,
                    "issues_count": len(quality_report.issues),
                    "script_quality": quality_report.script_quality,
                    "audio_balance": quality_report.audio_balance
                })
                
                logger.info(f"   ✅ 评审完成: {quality_report.overall_grade} ({quality_report.overall_score:.1f}分)")
                logger.info(f"   发现 {len(quality_report.issues)} 个问题")
                
                # 质量预警
                if quality_report.overall_score < quality_threshold:
                    logger.warning(f"⚠️ 质量评分低于阈值 ({quality_report.overall_score:.1f} < {quality_threshold})")
                    logger.warning(f"   修订建议: {', '.join(quality_report.revision_suggestions)}")
                    
                    # 记录质量问题到metrics
                    for issue in quality_report.issues[:5]:  # 只显示前5个
                        logger.warning(f"   - [{issue.severity}] {issue.description}")
            else:
                # 跳过质量评审，标记为已完成
                self.task_tracker.complete_stage(task_id, StageType.QUALITY_REVIEW, metrics={
                    "skipped": True
                })
            
            # ============ 阶段9：保存文件（可选） ============
            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(final_audio)
                logger.info(f"💾 音频已保存: {output_path}")
            
            # ============ 阶段10：统计结果 ============
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
            
            result = {
                "success": True,
                "task_id": task_id,  # 返回任务ID
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
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
                        "revision_suggestions": quality_report.revision_suggestions
                    } if quality_report else None
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
    
    def _assign_voices(self, script_segments):
        """为剧本片段分配音色"""
        for segment in script_segments:
            if segment.speaker == "旁白":
                voice_profile = self.voice_manager.get_narrator_voice()
            else:
                voice_profile = self.voice_manager.get_voice(segment.speaker)
                if not voice_profile:
                    # 未知角色，临时分配
                    voice_profile = self.voice_manager.assign_voice(segment.speaker)
            
            # 为ScriptSegment添加voice_params属性
            if not hasattr(segment, 'voice_params'):
                segment.voice_params = voice_profile.get_tts_params(segment.emotion)
    
    async def _synthesize_segments(self, script_segments) -> List[bytes]:
        """批量合成剧本片段"""
        # 准备批量数据
        batch_data = [
            {
                "text": seg.text,
                "voice_params": seg.voice_params if hasattr(seg, 'voice_params') else {},
                "emotion": seg.emotion
            }
            for seg in script_segments
        ]
        
        # 批量合成（使用分批策略）
        audio_list = await self.tts_engine.synthesize_batch(
            batch_data,
            batch_size=10,  # 每批10个片段
            batch_interval=0  # 批次间0秒（取消节流）
        )
        
        return audio_list

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
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)

            # 根据时间线中的类型和音量，计算对应的音量衰减（dB）
            effect_type_str = item.get("type", "action")
            base_gain_map = {
                "environment": -18.0,
                "action": -8.0,
                "emotion": -10.0,
                "transition": -12.0,
            }
            base_gain = base_gain_map.get(effect_type_str, -10.0)

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
                base_dir = Path(__file__).resolve().parents[3] / "data" / "audio_library"
                effect_path = base_dir / file_ref
            
            if not effect_path.exists():
                logger.warning(f"⚠️ 音效文件不存在: {effect_path}")
                continue
            
            try:
                with effect_path.open("rb") as f:
                    effect_bytes = f.read()
                position_ms = int(timestamp * 1000)
                mixed_audio = self.audio_mixer.add_sound_effect(
                    mixed_audio,
                    effect_bytes,
                    position_ms=position_ms,
                    effect_volume_offset=effect_volume_offset,
                )
            except Exception as e:
                logger.warning(f"⚠️ 叠加音效失败 {effect_path}: {e}")
        
        return mixed_audio
    
    def _apply_background_music(
        self,
        audio_data: bytes,
        music_timeline: Dict[str, Any],
    ) -> bytes:
        """根据配乐时间线，将BGM叠加到音频上
        
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
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)
            volume = item.get("volume", 0.2)
            sync_with_dialogue = item.get("sync_with_dialogue", True)
            
            # 计算音量偏移（dB）
            # 配乐默认音量较低，以-18dB为基准
            base_gain = -18.0
            try:
                volume_val = float(volume)
            except (TypeError, ValueError):
                volume_val = 0.2
            volume_val = max(0.05, min(1.0, volume_val))
            
            # 以 0.2 为基准做相对音量调整
            relative = volume_val / 0.2
            volume_adjust_db = 20 * math.log10(relative)
            bgm_volume_offset = base_gain + volume_adjust_db
            
            if not file_ref:
                continue
            
            music_path = Path(file_ref)
            if not music_path.is_absolute():
                # 相对路径：相对于 audio_library 根目录
                base_dir = Path(__file__).resolve().parents[3] / "data" / "audio_library"
                music_path = base_dir / file_ref
            
            if not music_path.exists():
                logger.warning(f"⚠️ 配乐文件不存在: {music_path}")
                continue
            
            try:
                with music_path.open("rb") as f:
                    bgm_bytes = f.read()
                
                # 使用 AudioMixer.add_background_music 叠加 BGM
                # 注意：add_background_music 会循环 BGM 至与音频相同长度
                mixed_audio = self.audio_mixer.add_background_music(
                    mixed_audio,
                    bgm_bytes,
                    bgm_volume_offset=int(bgm_volume_offset),
                )
                logger.info(f"✅ 已叠加配乐: {music_path.name}, 音量偏移={bgm_volume_offset:.1f}dB")
            except Exception as e:
                logger.warning(f"⚠️ 叠加配乐失败 {music_path}: {e}")
        
        return mixed_audio
    
    async def _parallel_design(
        self,
        task_id: str,
        script_segments: List[Any],
        chapter_content: str = ""
    ) -> tuple:
        """
        并行执行音色、音效、音乐设计
        
        Args:
            task_id: 任务ID
            script_segments: 剧本片段列表
            chapter_content: 章节原文（用于环境音与配乐生成）
        
        Returns:
            (voice_profiles, sound_effects_count, music_cues_count)
        """
        # 定义三个并行任务
        async def voice_design_task():
            """ 音色设计任务"""
            self.task_tracker.start_stage(task_id, StageType.VOICE_DESIGN)
            
            # 提取角色列表
            characters_in_script = list(set([
                seg.speaker for seg in script_segments 
                if seg.speaker != "旁白"
            ]))
            
            if characters_in_script:
                # 批量设计音色
                voice_profiles = self.voice_designer.batch_design([
                    {"name": char, "gender": "unknown", "age": 30} 
                    for char in characters_in_script
                ])
                
                self.task_tracker.complete_stage(task_id, StageType.VOICE_DESIGN, metrics={
                    "characters_count": len(voice_profiles)
                })
                
                return voice_profiles
            else:
                self.task_tracker.complete_stage(task_id, StageType.VOICE_DESIGN, metrics={
                    "characters_count": 0
                })
                return []
        
        async def sound_design_task():
            """音效设计任务（增强 Mureka 环境音）"""
            self.task_tracker.start_stage(task_id, StageType.SOUND_DESIGN)
            
            # 构造用于音效设计的简化片段结构
            script_dicts = [
                {
                    "text": getattr(seg, "text", ""),
                    "sound_effects": getattr(seg, "sound_effects", []) or [],
                }
                for seg in script_segments
            ]
            
            # 调用音效设计器生成音效时间线
            try:
                effect_cues = self.sound_effect_designer.design_effects(script_dicts)
                
                # 为整个章节设计 Mureka 环境音（本地优先 + AI 兜底）
                if chapter_content:
                    # 估算章节时长（粗略，每10字约1秒）
                    estimated_duration = len(chapter_content) / 10.0
                    try:
                        ambient_cue = await self.sound_effect_designer.ensure_mureka_ambient_sound(
                            scene_description=chapter_content[:200],  # 取开头200字推断环境
                            duration=estimated_duration,
                            mood=None  # 自动推断
                        )
                        # 将环境音插入到 effect_cues 开头
                        self.sound_effect_designer.effect_cues.insert(0, ambient_cue)
                        logger.info(f"🌆 已为章节设计 Mureka 环境音: {ambient_cue.audio_file}")
                    except Exception as amb_err:
                        logger.warning(f"⚠️ Mureka 环境音设计失败（不影响主流程）: {amb_err}")
                
                self._last_effect_timeline = self.sound_effect_designer.export_effect_timeline()
                sound_effects_count = len(self.sound_effect_designer.effect_cues)
            except Exception as e:
                logger.warning(f"⚠️ 音效设计阶段异常，将退回到简单计数逻辑: {e}")
                sound_effects_count = sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments)
                self._last_effect_timeline = None
            
            self.task_tracker.complete_stage(task_id, StageType.SOUND_DESIGN, metrics={
                "sound_effects_count": sound_effects_count
            })
            
            return sound_effects_count
        
        async def music_composition_task():
            """音乐编曲任务（增强 AI 配乐）"""
            self.task_tracker.start_stage(task_id, StageType.MUSIC_COMPOSITION)
            
            # 提取音乐标注并设计配乐方案
            try:
                # 构造章节结构用于配乐设计
                chapter_structure = {
                    "total_duration": len(chapter_content) / 10.0 if chapter_content else 600.0,
                    "overall_mood": "mysterious",  # 默认神秘感
                    "scenes": [
                        {
                            "scene_id": f"scene_{i}",
                            "start_time": i * 60.0,
                            "duration": 60.0,
                            "mood": "peaceful",
                            "description": getattr(seg, "text", "")[:50],
                            "is_climax": False,
                            "is_turning_point": False
                        }
                        for i, seg in enumerate(script_segments[:3])  # 只为前3个场景生成配乐
                    ]
                }
                
                music_cues = self.music_composer.design_music(chapter_structure)
                self._last_music_timeline = self.music_composer.export_music_timeline()
                music_cues_count = len(music_cues)
                logger.info(f"🎼 已设计 {music_cues_count} 个配乐提示")
            except Exception as e:
                logger.warning(f"⚠️ 配乐设计异常（不影响主流程）: {e}")
                music_cues_count = sum(1 for seg in script_segments if seg.music_cue)
                self._last_music_timeline = None
            
            self.task_tracker.complete_stage(task_id, StageType.MUSIC_COMPOSITION, metrics={
                "music_cues_count": music_cues_count
            })
            
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
                output_path=output_path
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
                    "content": chapter.content
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
                        audiobook_project_id=audiobook_project_id
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
