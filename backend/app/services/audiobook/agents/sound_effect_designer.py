"""
SoundEffectDesigner - 音效设计师Agent

核心职责：
1. 设计场景音效和环境音
2. 规划音效的触发时机和时长
3. 确保音效层次合理（避免过载）
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class EffectType(str, Enum):
    """音效类型"""
    ENVIRONMENT = "environment"  # 环境音（持续）
    ACTION = "action"  # 动作音（点缀）
    EMOTION = "emotion"  # 情绪音（氛围）
    TRANSITION = "transition"  # 转场音


@dataclass
class SoundEffectCue:
    """音效提示"""
    scene_id: str
    timestamp: float  # 触发时间（秒）
    effect_type: EffectType
    description: str  # 音效描述，如"雨声渐密"
    audio_file: str = ""  # 音效文件路径
    volume: float = 0.3  # 音量（0-1）
    fade_in: float = 0.0  # 淡入时长（秒）
    fade_out: float = 0.0  # 淡出时长（秒）
    loop: bool = False  # 是否循环
    duration: float = 0.0  # 持续时长（秒，0表示直到结束）
    mix_mode: str = "background"  # background/foreground


class SoundEffectDesigner:
    """
    音效设计师Agent
    
    基于剧本标注设计场景音效
    """
    
    def __init__(self):
        self.sound_library = self._init_sound_library()
        self.effect_cues: List[SoundEffectCue] = []
    
    def _init_sound_library(self) -> Dict[str, Dict[str, Any]]:
        """初始化音效库（占位）"""
        return {
            # 环境音
            "rain_light": {"type": "environment", "file": "rain_light.mp3", "description": "小雨"},
            "rain_heavy": {"type": "environment", "file": "rain_heavy.mp3", "description": "大雨"},
            "wind": {"type": "environment", "file": "wind.mp3", "description": "风声"},
            "city_ambient": {"type": "environment", "file": "city.mp3", "description": "城市环境音"},
            "forest_ambient": {"type": "environment", "file": "forest.mp3", "description": "森林环境音"},
            
            # 动作音
            "footsteps": {"type": "action", "file": "footsteps.mp3", "description": "脚步声"},
            "door_open": {"type": "action", "file": "door_open.mp3", "description": "开门声"},
            "door_close": {"type": "action", "file": "door_close.mp3", "description": "关门声"},
            "paper_rustle": {"type": "action", "file": "paper.mp3", "description": "纸张簌簌声"},
            "keyboard": {"type": "action", "file": "keyboard.mp3", "description": "键盘声"},
            
            # 情绪音
            "heartbeat": {"type": "emotion", "file": "heartbeat.mp3", "description": "心跳声"},
            "breath_heavy": {"type": "emotion", "file": "breath.mp3", "description": "沉重呼吸"},
            "gasp": {"type": "emotion", "file": "gasp.mp3", "description": "倒吸气"},
        }
    
    def design_effects(
        self,
        script_segments: List[Dict[str, Any]],
        scene_info: Optional[Dict[str, Any]] = None
    ) -> List[SoundEffectCue]:
        """
        设计音效方案
        
        Args:
            script_segments: 剧本片段列表
                [
                    {
                        "text": "林墨走在雨中的街道上",
                        "sound_effects": ["rain_heavy", "footsteps"],
                        "timestamp": 0.0
                    }
                ]
            scene_info: 场景信息（可选）
        
        Returns:
            音效提示列表
        """
        logger.info(f"🎵 设计音效方案: {len(script_segments)} 个片段...")
        
        effect_cues = []
        current_time = 0.0
        
        for i, segment in enumerate(script_segments):
            segment_effects = segment.get("sound_effects", [])
            
            for effect_desc in segment_effects:
                # 匹配音效库
                effect_cue = self._match_effect(
                    description=effect_desc,
                    timestamp=current_time,
                    scene_id=f"scene_{i}"
                )
                
                if effect_cue:
                    effect_cues.append(effect_cue)
            
            # 估算片段时长（粗略）
            text_length = len(segment.get("text", ""))
            estimated_duration = text_length / 10  # 假设10字/秒
            current_time += estimated_duration
        
        self.effect_cues = effect_cues
        logger.info(f"   ✅ 设计完成: {len(effect_cues)} 个音效提示")
        
        return effect_cues
    
    def _match_effect(
        self,
        description: str,
        timestamp: float,
        scene_id: str
    ) -> Optional[SoundEffectCue]:
        """匹配音效库"""
        # 简单关键词匹配
        for effect_name, effect_info in self.sound_library.items():
            if effect_info["description"] in description or description in effect_info["description"]:
                
                # 判断音效类型
                effect_type = EffectType(effect_info["type"])
                
                # 设置默认参数
                cue = SoundEffectCue(
                    scene_id=scene_id,
                    timestamp=timestamp,
                    effect_type=effect_type,
                    description=description,
                    audio_file=effect_info["file"],
                    volume=0.3 if effect_type == EffectType.ENVIRONMENT else 0.5,
                    fade_in=2.0 if effect_type == EffectType.ENVIRONMENT else 0.5,
                    fade_out=2.0 if effect_type == EffectType.ENVIRONMENT else 0.5,
                    loop=(effect_type == EffectType.ENVIRONMENT),
                    duration=10.0 if effect_type == EffectType.ENVIRONMENT else 2.0,
                    mix_mode="background" if effect_type == EffectType.ENVIRONMENT else "foreground"
                )
                
                return cue
        
        # 未找到匹配，创建占位
        logger.warning(f"⚠️ 未找到音效: {description}，使用占位")
        return SoundEffectCue(
            scene_id=scene_id,
            timestamp=timestamp,
            effect_type=EffectType.ACTION,
            description=description,
            audio_file="placeholder.mp3",
            volume=0.3
        )
    
    def design_ambient_sound(
        self,
        scene_description: str,
        duration: float
    ) -> SoundEffectCue:
        """
        设计环境音
        
        Args:
            scene_description: 场景描述，如"雨夜的城市街道"
            duration: 持续时长（秒）
        
        Returns:
            环境音效提示
        """
        logger.info(f"🌆 设计环境音: {scene_description}")
        
        # 关键词匹配
        ambient_map = {
            "雨": "rain_light",
            "大雨": "rain_heavy",
            "风": "wind",
            "城市": "city_ambient",
            "森林": "forest_ambient",
        }
        
        effect_name = "city_ambient"  # 默认
        for keyword, name in ambient_map.items():
            if keyword in scene_description:
                effect_name = name
                break
        
        effect_info = self.sound_library.get(effect_name, {})
        
        cue = SoundEffectCue(
            scene_id="ambient",
            timestamp=0.0,
            effect_type=EffectType.ENVIRONMENT,
            description=scene_description,
            audio_file=effect_info.get("file", "ambient.mp3"),
            volume=0.2,  # 环境音音量较低
            fade_in=3.0,
            fade_out=3.0,
            loop=True,
            duration=duration,
            mix_mode="background"
        )
        
        return cue
    
    def optimize_effect_density(
        self,
        max_effects_per_minute: int = 6
    ) -> List[SoundEffectCue]:
        """
        优化音效密度（避免过载）
        
        Args:
            max_effects_per_minute: 每分钟最大音效数
        
        Returns:
            优化后的音效列表
        """
        logger.info("🔧 优化音效密度...")
        
        if not self.effect_cues:
            return []
        
        # 按时间排序
        sorted_cues = sorted(self.effect_cues, key=lambda x: x.timestamp)
        
        # 检查密度
        optimized_cues = []
        last_timestamp = -999
        
        for cue in sorted_cues:
            # 确保音效间隔至少10秒（除了环境音）
            if cue.effect_type == EffectType.ENVIRONMENT:
                optimized_cues.append(cue)
            elif cue.timestamp - last_timestamp >= 10.0:
                optimized_cues.append(cue)
                last_timestamp = cue.timestamp
            else:
                logger.debug(f"   跳过过密音效: {cue.description} at {cue.timestamp}s")
        
        logger.info(f"   ✅ 优化完成: {len(sorted_cues)} → {len(optimized_cues)} 个音效")
        
        self.effect_cues = optimized_cues
        return optimized_cues
    
    def export_effect_timeline(self) -> Dict[str, Any]:
        """导出音效时间线（用于混音）"""
        timeline = {
            "total_effects": len(self.effect_cues),
            "effects_by_type": self._count_by_type(),
            "timeline": [
                {
                    "timestamp": cue.timestamp,
                    "type": cue.effect_type.value,
                    "description": cue.description,
                    "file": cue.audio_file,
                    "volume": cue.volume,
                    "duration": cue.duration
                }
                for cue in sorted(self.effect_cues, key=lambda x: x.timestamp)
            ]
        }
        
        return timeline
    
    def _count_by_type(self) -> Dict[str, int]:
        """按类型统计"""
        counts = {
            "environment": 0,
            "action": 0,
            "emotion": 0,
            "transition": 0
        }
        for cue in self.effect_cues:
            counts[cue.effect_type.value] += 1
        return counts
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_effects": len(self.effect_cues),
            "effects_by_type": self._count_by_type(),
            "sound_library_size": len(self.sound_library)
        }
