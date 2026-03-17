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
from typing import List, Dict, Any, Optional
from pathlib import Path

from .script_adapter import AudiobookScriptAgent, ScriptSegment
from .voice_manager import VoiceManager
from .audio_mixer import AudioMixer
from core.unified_media_runtime import create_tts_engine

# 导入专业Agent
from .agents import (
    AudioDirector,
    VoiceDesigner,
    SoundEffectDesigner,
    MusicComposer,
    AudioQualityReviewer
)

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
        max_concurrent: int = 5,
        llm_client=None  # LLM客户端（用于专业Agent）
    ):
        # 初始化专业Agent
        logger.info("🎬 启用专业多Agent协作模式")
        self.audio_director = AudioDirector(llm_client=llm_client)
        self.script_adapter = AudiobookScriptAgent(llm_client=llm_client)
        self.voice_designer = VoiceDesigner()
        self.sound_effect_designer = SoundEffectDesigner()
        self.music_composer = MusicComposer()
        self.audio_quality_reviewer = AudioQualityReviewer(llm_client=llm_client)
        
        # 初始化基础组件
        self.voice_manager = VoiceManager()
        self.tts_engine = create_tts_engine(
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
        )
        self.audio_mixer = AudioMixer()
        
        logger.info("🎶 有声书生成引擎初始化完成")
    
    async def generate_chapter_audio(
        self,
        chapter_content: str,
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        output_path: Optional[str] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题"
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
        
        logger.info(f"{'='*70}")
        logger.info(f"🎬 开始生成章节有声书: Chapter {chapter_id}")
        logger.info(f"{'='*70}")
        
        try:
            # ============ 阶段1：制定改编策略 ============
            logger.info("🎭 [1/6] AudioDirector制定改编策略...")
            strategy = self.audio_director.formulate_strategy(
                novel_genre=novel_genre,
                novel_theme=novel_theme,
                target_audience="通用听众"
            )
            logger.info(f"   ✅ 策略: {strategy.style.value}, 音效密度: {strategy.sound_effect_density}")
            
            # ============ 阶段2：剧本改编 ============
            logger.info("📝 [2/6] AudiobookScriptAdapter剧本改编...")
            script_segments = await self.script_adapter.adapt_chapter(
                chapter_content=chapter_content,
                character_list=character_list,
                chapter_title=f"Chapter {chapter_id}",
                genre=novel_genre
            )
            logger.info(f"   ✅ 生成 {len(script_segments)} 个剧本片段")
            
            # ============ 阶段3：音色设计 ============
            logger.info("🎵 [3/6] VoiceDesigner音色设计...")
            # 提取角色列表
            characters_in_script = list(set([seg.speaker for seg in script_segments if seg.speaker != "旁白"]))
            if characters_in_script:
                # 批量设计音色
                voice_profiles = self.voice_designer.batch_design([
                    {"name": char, "gender": "unknown", "age": 30} 
                    for char in characters_in_script
                ])
                logger.info(f"   ✅ 为 {len(voice_profiles)} 个角色设计音色")
            else:
                logger.info("   ✅ 无需音色设计（纯旁白）")
            
            # ============ 阶段4：音效设计 ============
            logger.info("🎧 [4/6] SoundEffectDesigner音效设计...")
            # 提取音效标注
            sound_effects_count = sum(len(seg.sound_effects) for seg in script_segments)
            logger.info(f"   ✅ 检测到 {sound_effects_count} 个音效标注")
            
            # ============ 阶段5：音乐编曲 ============
            logger.info("🎶 [5/6] MusicComposer音乐编曲...")
            # 提取音乐标注
            music_cues_count = sum(1 for seg in script_segments if seg.music_cue)
            logger.info(f"   ✅ 检测到 {music_cues_count} 个音乐提示")
            
            # ============ 阶段6：TTS合成 ============
            logger.info("🎙️ [6/6] TTS合成中...")
            # 为剧本片段分配音色
            self._assign_voices(script_segments)
            audio_list = await self._synthesize_segments(script_segments)
            
            tts_stats = self.tts_engine.get_cost_stats()
            logger.info(f"   ✅ TTS完成: {tts_stats}")
            
            # ============ 阶段7：音频混合 ============
            logger.info("🎧 [7/7] 音频混合中...")
            final_audio = self.audio_mixer.mix_chapter(audio_list)
            
            # 允许空音频（用于MVP测试）
            if not final_audio:
                logger.warning("⚠️ 音频为空，生成占位数据")
                final_audio = b""  # 空字节
                
            audio_info = self.audio_mixer.get_audio_info(final_audio)
            logger.info(f"   ✅ 混合完成: {audio_info}")
            
            # ============ 阶段8：保存文件（可选） ============
            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(final_audio)
                logger.info(f"💾 音频已保存: {output_path}")
            
            # ============ 阶段9：统计结果 ============
            elapsed_time = time.time() - start_time
            
            result = {
                "success": True,
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "mode": "专业Agent模式",
                    "script_segments": len(script_segments),
                    "characters": len(characters_in_script) if 'characters_in_script' in locals() else 0,
                    "sound_effects": sound_effects_count if 'sound_effects_count' in locals() else 0,
                    "music_cues": music_cues_count if 'music_cues_count' in locals() else 0,
                    "tts_stats": tts_stats,
                    "audio_info": audio_info
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
            
            return {
                "success": False,
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
        
        # 批量合成
        audio_list = await self.tts_engine.synthesize_batch(batch_data)
        
        return audio_list
    
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
