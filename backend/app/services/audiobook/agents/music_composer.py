"""
MusicComposer - 音乐设计师Agent（AI增强版）

核心职责：
1. 设计情绪音乐和主题音乐
2. 规划音乐的插入时机
3. 设计音乐与对话的混音关系
4. **AI生成音乐**（昆仑万维Mureka O1集成）
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

# 导入AI音乐生成器
try:
    from ..ai_music import AIMusicGenerator, MusicGenerationRequest, MusicStyle
    AI_MUSIC_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ AI音乐生成模块未安装，将使用静态音乐库")
    AI_MUSIC_AVAILABLE = False

logger = logging.getLogger(__name__)


class MusicType(str, Enum):
    """音乐类型"""
    UNDERSCORE = "underscore"  # 背景音乐（对话下）
    THEME = "theme"  # 主题音乐
    TRANSITION = "transition"  # 转场音乐
    OPENING = "opening"  # 开场音乐
    ENDING = "ending"  # 结尾音乐


class MusicMood(str, Enum):
    """音乐情绪"""
    TENSE = "tense"  # 紧张
    JOYFUL = "joyful"  # 欢快
    SAD = "sad"  # 悲伤
    MYSTERIOUS = "mysterious"  # 神秘
    ROMANTIC = "romantic"  # 浪漫
    EPIC = "epic"  # 史诗
    PEACEFUL = "peaceful"  # 平静


@dataclass
class MusicCue:
    """音乐提示"""
    scene_id: str
    timestamp: float  # 触发时间（秒）
    music_type: MusicType
    mood: MusicMood
    description: str
    audio_file: str = ""  # 音乐文件路径
    volume: float = 0.2  # 音量（0-1）
    fade_in: float = 3.0  # 淡入时长（秒）
    fade_out: float = 5.0  # 淡出时长（秒）
    duration: float = 30.0  # 持续时长（秒）
    sync_with_dialogue: bool = True  # 对话时自动降低音量
    dialogue_volume_reduction: float = 0.5  # 对话时音量降低比例


class MusicComposer:
    """
    音乐设计师Agent（AI增强版）
    
    基于情节节奏和情感基调设计背景音乐
    支持AI动态生成（Mureka O1）+ 静态音乐库降级
    """
    
    def __init__(self, ai_generator: Optional[Any] = None, enable_ai: bool = True):
        """
        Args:
            ai_generator: AI音乐生成器（可选，默认自动创建）
            enable_ai: 是否启用AI生成（默认True）
        """
        self.music_library = self._init_music_library()
        self.music_cues: List[MusicCue] = []
        
        # AI音乐生成器
        self.enable_ai = enable_ai and AI_MUSIC_AVAILABLE
        if self.enable_ai:
            if ai_generator is None and AI_MUSIC_AVAILABLE:
                from ..ai_music import create_music_generator
                self.ai_generator = create_music_generator(enable_cache=True)
                logger.info("✅ AI音乐生成器已启用（Mureka O1）")
            else:
                self.ai_generator = ai_generator
        else:
            self.ai_generator = None
            logger.info("📚 使用静态音乐库模式")
    
    def _init_music_library(self) -> Dict[str, Dict[str, Any]]:
        """初始化音乐库（占位）"""
        return {
            # 紧张悬疑
            "suspense_strings": {"mood": "tense", "description": "悬疑感的低频弦乐", "file": "suspense_1.mp3"},
            "tension_build": {"mood": "tense", "description": "紧张感逐渐升高", "file": "tension_1.mp3"},
            
            # 欢快
            "cheerful_piano": {"mood": "joyful", "description": "欢快的钢琴曲", "file": "joy_1.mp3"},
            "upbeat_melody": {"mood": "joyful", "description": "明快的旋律", "file": "joy_2.mp3"},
            
            # 悲伤
            "sad_violin": {"mood": "sad", "description": "悲伤的小提琴", "file": "sad_1.mp3"},
            "melancholic": {"mood": "sad", "description": "忧郁的氛围音乐", "file": "sad_2.mp3"},
            
            # 神秘
            "mysterious_ambient": {"mood": "mysterious", "description": "神秘的环境音乐", "file": "mystery_1.mp3"},
            
            # 浪漫
            "romantic_strings": {"mood": "romantic", "description": "浪漫的弦乐", "file": "romance_1.mp3"},
            
            # 史诗
            "epic_orchestral": {"mood": "epic", "description": "史诗感的管弦乐", "file": "epic_1.mp3"},
            
            # 平静
            "peaceful_ambient": {"mood": "peaceful", "description": "平静的氛围音乐", "file": "peaceful_1.mp3"},
        }
    
    def design_music(
        self,
        chapter_structure: Dict[str, Any],
        emotion_curve: Optional[List[Dict[str, Any]]] = None
    ) -> List[MusicCue]:
        """
        设计音乐方案
        
        Args:
            chapter_structure: 章节结构
                {
                    "total_duration": 1200.0,  # 总时长（秒）
                    "scenes": [
                        {
                            "scene_id": "scene_1",
                            "start_time": 0.0,
                            "duration": 300.0,
                            "mood": "tense",
                            "description": "开场悬疑场景"
                        }
                    ]
                }
            emotion_curve: 情绪曲线（可选）
        
        Returns:
            音乐提示列表
        """
        logger.info("🎼 设计音乐方案...")
        
        music_cues = []
        
        # 1. 开场音乐
        opening_cue = self._create_opening_music(chapter_structure)
        if opening_cue:
            music_cues.append(opening_cue)
        
        # 2. 场景音乐
        for scene in chapter_structure.get("scenes", []):
            scene_cue = self._design_scene_music(scene)
            if scene_cue:
                music_cues.append(scene_cue)
        
        # 3. 结尾音乐
        total_duration = chapter_structure.get("total_duration", 0)
        ending_cue = self._create_ending_music(total_duration)
        if ending_cue:
            music_cues.append(ending_cue)
        
        self.music_cues = music_cues
        logger.info(f"   ✅ 设计完成: {len(music_cues)} 个音乐提示")
        
        return music_cues
    
    def _create_opening_music(
        self,
        chapter_structure: Dict[str, Any]
    ) -> Optional[MusicCue]:
        """创建开场音乐"""
        # 根据整体基调选择开场音乐
        overall_mood = chapter_structure.get("overall_mood", "mysterious")
        
        music_info = self._match_music(overall_mood)
        
        cue = MusicCue(
            scene_id="opening",
            timestamp=0.0,
            music_type=MusicType.OPENING,
            mood=MusicMood(overall_mood),
            description=f"开场音乐 - {music_info['description']}",
            audio_file=music_info["file"],
            volume=0.3,
            fade_in=2.0,
            fade_out=4.0,
            duration=15.0,
            sync_with_dialogue=True
        )
        
        return cue
    
    def _design_scene_music(
        self,
        scene: Dict[str, Any]
    ) -> Optional[MusicCue]:
        """设计场景音乐（AI增强）"""
        mood = scene.get("mood", "peaceful")
        start_time = scene.get("start_time", 0.0)
        duration = scene.get("duration", 60.0)
        scene_description = scene.get("description", "场景")
            
        # 只为关键场景（高潮、转折）添加音乐
        is_key_scene = scene.get("is_climax", False) or scene.get("is_turning_point", False)
            
        if not is_key_scene and mood == "peaceful":
            return None  # 平静场景不一定需要音乐
            
        # 尝试AI生成（优先）
        if self.enable_ai and self.ai_generator:
            try:
                return self._generate_scene_music_with_ai(
                    scene_description=scene_description,
                    mood=mood,
                    start_time=start_time,
                    duration=min(duration, 120.0)
                )
            except Exception as e:
                logger.warning(f"⚠️ AI生成音乐失败，降级到静态库: {e}")
            
        # 降级到静态音乐库
        music_info = self._match_music(mood)
            
        cue = MusicCue(
            scene_id=scene.get("scene_id", "scene"),
            timestamp=start_time,
            music_type=MusicType.UNDERSCORE,
            mood=MusicMood(mood),
            description=f"场景音乐 - {music_info['description']}",
            audio_file=music_info["file"],
            volume=0.15,  # 背景音乐音量更低
            fade_in=3.0,
            fade_out=3.0,
            duration=min(duration, 120.0),  # 最長2分钟
            sync_with_dialogue=True,
            dialogue_volume_reduction=0.6  # 对话时降低40%
        )
        
        return cue
    
    def _create_ending_music(
        self,
        chapter_duration: float
    ) -> Optional[MusicCue]:
        """创建结尾音乐"""
        cue = MusicCue(
            scene_id="ending",
            timestamp=max(0, chapter_duration - 20.0),  # 最后20秒
            music_type=MusicType.ENDING,
            mood=MusicMood.PEACEFUL,
            description="结尾音乐",
            audio_file="peaceful_ambient.mp3",
            volume=0.25,
            fade_in=3.0,
            fade_out=5.0,
            duration=20.0,
            sync_with_dialogue=False
        )
        
        return cue
    
    def _match_music(self, mood: str) -> Dict[str, Any]:
        """匹配音乐库"""
        # 查找匹配的音乐
        for music_name, music_info in self.music_library.items():
            if music_info["mood"] == mood:
                return music_info
        
        # 默认返回平静音乐
        return {
            "mood": "peaceful",
            "description": "平静的氛围音乐",
            "file": "peaceful_ambient.mp3"
        }
    
    def create_theme_music(
        self,
        character_name: str,
        character_traits: Dict[str, Any]
    ) -> MusicCue:
        """
        为角色创建主题音乐（AI增强）
        
        Args:
            character_name: 角色名
            character_traits: 角色特质
        
        Returns:
            主题音乐提示
        """
        logger.info(f"🎵 为角色 {character_name} 创建主题音乐...")
        
        # 根据角色特质选择音乐情绪
        personality = character_traits.get("personality", "")
        
        if "神秘" in personality:
            mood = MusicMood.MYSTERIOUS
        elif "温柔" in personality or "浪漫" in personality:
            mood = MusicMood.ROMANTIC
        elif "英勇" in personality or "强大" in personality:
            mood = MusicMood.EPIC
        elif "活泼" in personality:
            mood = MusicMood.JOYFUL
        else:
            mood = MusicMood.PEACEFUL
        
        # 尝试AI生成
        if self.enable_ai and self.ai_generator:
            try:
                import asyncio
                result = asyncio.run(self.ai_generator.generate_theme_music(
                    character_name=character_name,
                    personality=personality,
                    duration=30
                ))
                
                if result.success:
                    return MusicCue(
                        scene_id=f"theme_{character_name}",
                        timestamp=0.0,
                        music_type=MusicType.THEME,
                        mood=mood,
                        description=f"{character_name}的主题音乐（AI生成）",
                        audio_file=result.audio_file_path,
                        volume=0.2,
                        fade_in=2.0,
                        fade_out=3.0,
                        duration=30.0,
                        sync_with_dialogue=True
                    )
            except Exception as e:
                logger.warning(f"⚠️ AI生成主题音乐失败: {e}")
        
        # 降级到静态库
        music_info = self._match_music(mood.value)
        
        cue = MusicCue(
            scene_id=f"theme_{character_name}",
            timestamp=0.0,
            music_type=MusicType.THEME,
            mood=mood,
            description=f"{character_name}的主题音乐",
            audio_file=music_info["file"],
            volume=0.2,
            fade_in=2.0,
            fade_out=3.0,
            duration=30.0,
            sync_with_dialogue=True
        )
        
        return cue
    
    def optimize_music_placement(
        self,
        max_music_coverage: float = 0.4
    ) -> List[MusicCue]:
        """
        优化音乐布局（避免音乐过多）
        
        Args:
            max_music_coverage: 最大音乐覆盖率（0-1）
        
        Returns:
            优化后的音乐列表
        """
        logger.info("🔧 优化音乐布局...")
        
        if not self.music_cues:
            return []
        
        # 计算当前音乐覆盖率
        total_duration = sum(cue.duration for cue in self.music_cues)
        
        # 如果覆盖率过高，移除一些非关键音乐
        optimized_cues = []
        
        # 保留开场、结尾和主题音乐
        for cue in self.music_cues:
            if cue.music_type in [MusicType.OPENING, MusicType.ENDING, MusicType.THEME]:
                optimized_cues.append(cue)
        
        # 根据情绪优先级添加场景音乐
        mood_priority = {
            MusicMood.TENSE: 1,
            MusicMood.EPIC: 2,
            MusicMood.SAD: 3,
            MusicMood.MYSTERIOUS: 4,
            MusicMood.JOYFUL: 5,
            MusicMood.ROMANTIC: 5,
            MusicMood.PEACEFUL: 6
        }
        
        scene_cues = [c for c in self.music_cues if c.music_type == MusicType.UNDERSCORE]
        scene_cues.sort(key=lambda x: mood_priority.get(x.mood, 10))
        
        # 逐个添加，直到达到覆盖率上限
        current_coverage = sum(c.duration for c in optimized_cues)
        max_allowed_duration = max_music_coverage * 600  # 假设章节10分钟
        
        for cue in scene_cues:
            if current_coverage + cue.duration <= max_allowed_duration:
                optimized_cues.append(cue)
                current_coverage += cue.duration
        
        logger.info(f"   ✅ 优化完成: {len(self.music_cues)} → {len(optimized_cues)} 个音乐提示")
        
        self.music_cues = optimized_cues
        return optimized_cues
    
    def export_music_timeline(self) -> Dict[str, Any]:
        """导出音乐时间线（用于混音）"""
        timeline = {
            "total_cues": len(self.music_cues),
            "cues_by_type": self._count_by_type(),
            "cues_by_mood": self._count_by_mood(),
            "timeline": [
                {
                    "timestamp": cue.timestamp,
                    "type": cue.music_type.value,
                    "mood": cue.mood.value,
                    "description": cue.description,
                    "file": cue.audio_file,
                    "volume": cue.volume,
                    "duration": cue.duration,
                    "sync_with_dialogue": cue.sync_with_dialogue
                }
                for cue in sorted(self.music_cues, key=lambda x: x.timestamp)
            ]
        }
        
        return timeline
    
    def _count_by_type(self) -> Dict[str, int]:
        """按类型统计"""
        counts = {}
        for cue in self.music_cues:
            t = cue.music_type.value
            counts[t] = counts.get(t, 0) + 1
        return counts
    
    def _count_by_mood(self) -> Dict[str, int]:
        """按情绪统计"""
        counts = {}
        for cue in self.music_cues:
            m = cue.mood.value
            counts[m] = counts.get(m, 0) + 1
        return counts
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息（增强AI统计）"""
        stats = {
            "total_cues": len(self.music_cues),
            "cues_by_type": self._count_by_type(),
            "cues_by_mood": self._count_by_mood(),
            "music_library_size": len(self.music_library)
        }
        
        # AI生成器统计
        if self.enable_ai and self.ai_generator:
            ai_stats = self.ai_generator.get_statistics()
            stats["ai_music_stats"] = ai_stats
        
        return stats
    
    def _generate_scene_music_with_ai(
        self,
        scene_description: str,
        mood: str,
        start_time: float,
        duration: float
    ) -> MusicCue:
        """使用AI生成场景音乐"""
        import asyncio
        
        # 调用AI生成器
        result = asyncio.run(self.ai_generator.generate_for_scene(
            scene_description=scene_description,
            mood=mood,
            duration=int(duration)
        ))
        
        if not result.success:
            raise RuntimeError(result.error_message)
        
        logger.info(f"   ✅ AI生成音乐成功: {result.audio_file_path}")
        
        return MusicCue(
            scene_id=f"scene_{scene_description[:10]}",
            timestamp=start_time,
            music_type=MusicType.UNDERSCORE,
            mood=MusicMood(mood),
            description=f"场景音乐 - {scene_description}（AI生成）",
            audio_file=result.audio_file_path,
            volume=0.15,
            fade_in=3.0,
            fade_out=3.0,
            duration=result.duration,
            sync_with_dialogue=True,
            dialogue_volume_reduction=0.6
        )
