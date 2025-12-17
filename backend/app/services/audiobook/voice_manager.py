"""
音色管理器 - 智能分配与管理角色音色

核心功能：
1. 预设音色库管理（5-10种基础音色）
2. 角色音色自动分配（确保差异化）
3. 音色一致性保证
4. 情感参数映射
"""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import json

logger = logging.getLogger(__name__)


@dataclass
class VoiceProfile:
    """音色档案"""
    voice_id: str  # 音色唯一标识
    character_name: str  # 角色名
    
    # 基础属性
    gender: str  # "male" | "female" | "neutral"
    age_group: str  # "child" | "teen" | "young" | "adult" | "elder"
    personality: str  # "calm" | "energetic" | "gentle" | "cold" | "warm"
    
    # TTS参数
    tts_speaker_id: str  # TTS服务的音色ID
    pitch_base: int = 50  # 基础音高 0-100
    speed_base: float = 1.0  # 基础语速 0.5-2.0
    volume_base: int = 50  # 基础音量 0-100
    
    # 情感参数映射
    emotion_adjustments: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "neutral": {"pitch_offset": 0, "speed_multiplier": 1.0},
        "happy": {"pitch_offset": 10, "speed_multiplier": 1.1},
        "sad": {"pitch_offset": -10, "speed_multiplier": 0.9},
        "angry": {"pitch_offset": 15, "speed_multiplier": 1.2},
        "excited": {"pitch_offset": 20, "speed_multiplier": 1.3},
        "calm": {"pitch_offset": -5, "speed_multiplier": 0.95},
    })
    
    def get_tts_params(self, emotion: str = "neutral") -> Dict[str, Any]:
        """获取TTS参数"""
        adjustment = self.emotion_adjustments.get(emotion, self.emotion_adjustments["neutral"])
        
        return {
            "speaker": self.tts_speaker_id,
            "pitch": max(0, min(100, self.pitch_base + adjustment["pitch_offset"])),
            "speed": max(0.5, min(2.0, self.speed_base * adjustment["speed_multiplier"])),
            "volume": self.volume_base
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceProfile":
        """从字典创建"""
        return cls(**data)


class VoiceManager:
    """
    音色库管理器
    
    职责：
    1. 管理预设音色库
    2. 为角色智能分配音色
    3. 保证音色一致性
    """
    
    # 预设音色库（基于阿里云TTS音色）
    # 注意：
    # - Qwen3-TTS：49种官方音色，原生支持情感标签
    # - CosyVoice3：零样本克隆，9语种+18方言
    # - 优先使用Qwen3-TTS（免费100万字符/月）
    # 预设音色库（针对 CosyVoice-v3-flash 优化）
    # 注意：cosyvoice-v3-flash 支持多种音色，通过参数调节实现角色差异化
    PRESET_VOICES = {
        "male_young_energetic": {
            "tts_speaker_id": "longanyang",  # CosyVoice v3: 男性音色
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 55,
            "speed_base": 1.1,
            "volume_base": 55,
            "description": "年轻男性，活力充沛，适合热血主角"
        },
        "male_adult_calm": {
            "tts_speaker_id": "longanyang",  # 同一音色，通过参数调节
            "gender": "male",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 45,
            "speed_base": 0.95,
            "volume_base": 50,
            "description": "成熟男性，沉稳冷静，适合智者角色"
        },
        "female_young_gentle": {
            "tts_speaker_id": "longanyang",  # 提高音高模拟女性
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 70,  # 高音高模拟女性
            "speed_base": 1.05,
            "volume_base": 50,
            "description": "年轻女性，温柔体贴，适合女主角"
        },
        "female_adult_cold": {
            "tts_speaker_id": "longanyang",
            "gender": "female",
            "age_group": "adult",
            "personality": "cold",
            "pitch_base": 65,  # 略高音高模拟成熟女性
            "speed_base": 0.9,
            "volume_base": 48,
            "description": "成熟女性，高冷理智，适合女强人"
        },
        "elder_wise": {
            "tts_speaker_id": "longanyang",
            "gender": "male",
            "age_group": "elder",
            "personality": "calm",
            "pitch_base": 40,  # 低音高模拟长者
            "speed_base": 0.85,
            "volume_base": 52,
            "description": "长者，睿智稳重，适合导师角色"
        },
        "narrator_neutral": {
            "tts_speaker_id": "longanyang",
            "gender": "neutral",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "旁白专用，中性平稳"
        }
    }
    
    def __init__(self):
        self.character_voices: Dict[str, VoiceProfile] = {}  # 角色名 -> 音色档案
        self.used_voice_ids = set()  # 已使用的音色ID
    
    def assign_voice(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
        preferred_voice_id: Optional[str] = None
    ) -> VoiceProfile:
        """
        为角色分配音色
        
        Args:
            character_name: 角色名
            character_info: 角色信息（可选），包含 gender, age_group, personality
            preferred_voice_id: 指定音色ID（可选）
        
        Returns:
            音色档案
        """
        # 1. 检查是否已分配
        if character_name in self.character_voices:
            logger.info(f"✅ 角色 '{character_name}' 已有音色档案")
            return self.character_voices[character_name]
        
        # 2. 使用指定音色
        if preferred_voice_id and preferred_voice_id in self.PRESET_VOICES:
            voice_config = self.PRESET_VOICES[preferred_voice_id]
            profile = self._create_profile(character_name, preferred_voice_id, voice_config)
            self.character_voices[character_name] = profile
            self.used_voice_ids.add(preferred_voice_id)
            logger.info(f"✅ 为 '{character_name}' 分配指定音色: {preferred_voice_id}")
            return profile
        
        # 3. 智能匹配音色
        matched_voice_id = self._match_voice_by_traits(character_info or {})
        voice_config = self.PRESET_VOICES[matched_voice_id]
        profile = self._create_profile(character_name, matched_voice_id, voice_config)
        
        self.character_voices[character_name] = profile
        self.used_voice_ids.add(matched_voice_id)
        
        logger.info(f"✅ 为 '{character_name}' 自动分配音色: {matched_voice_id}")
        return profile
    
    def _match_voice_by_traits(self, character_info: Dict[str, Any]) -> str:
        """
        基于角色特征匹配最佳音色
        
        优先级：gender > age_group > personality
        同时避免使用已分配的音色（确保差异化）
        """
        gender = character_info.get("gender", "male").lower()
        age = character_info.get("age_group", "young").lower()
        personality = character_info.get("personality", "calm").lower()
        
        # 候选音色列表
        candidates = []
        
        for voice_id, voice_config in self.PRESET_VOICES.items():
            # 跳过旁白音色
            if voice_id == "narrator_neutral":
                continue
            
            # 跳过已使用的音色（除非没有可用选项）
            if voice_id in self.used_voice_ids and len(self.used_voice_ids) < len(self.PRESET_VOICES) - 2:
                continue
            
            # 计算匹配分数
            score = 0
            if voice_config["gender"] == gender:
                score += 10
            if voice_config["age_group"] == age:
                score += 5
            if voice_config["personality"] == personality:
                score += 3
            
            candidates.append((voice_id, score))
        
        # 选择最高分
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        else:
            # 降级：返回任意未使用的音色
            for voice_id in self.PRESET_VOICES:
                if voice_id not in self.used_voice_ids and voice_id != "narrator_neutral":
                    return voice_id
            # 最后降级：返回默认音色
            return "male_young_energetic"
    
    def _create_profile(
        self,
        character_name: str,
        voice_id: str,
        voice_config: Dict[str, Any]
    ) -> VoiceProfile:
        """创建音色档案"""
        return VoiceProfile(
            voice_id=voice_id,
            character_name=character_name,
            gender=voice_config["gender"],
            age_group=voice_config["age_group"],
            personality=voice_config["personality"],
            tts_speaker_id=voice_config["tts_speaker_id"],
            pitch_base=voice_config["pitch_base"],
            speed_base=voice_config["speed_base"],
            volume_base=voice_config["volume_base"]
        )
    
    def get_narrator_voice(self) -> VoiceProfile:
        """获取旁白音色"""
        if "旁白" not in self.character_voices:
            voice_config = self.PRESET_VOICES["narrator_neutral"]
            self.character_voices["旁白"] = self._create_profile(
                "旁白",
                "narrator_neutral",
                voice_config
            )
        return self.character_voices["旁白"]
    
    def get_voice(self, character_name: str) -> Optional[VoiceProfile]:
        """获取角色音色"""
        return self.character_voices.get(character_name)
    
    def apply_project_voice_mapping(self, voice_mapping: Dict[str, Any]):
        """应用项目级的角色音配置（用户配置优先）

        voice_mapping 结构示例:
        {
            "角色名": {
                "voice_id": "male_young_energetic",
                "volume": 60
            }
        }
        """
        if not voice_mapping:
            return

        for character_name, config in voice_mapping.items():
            if not isinstance(config, dict):
                continue

            voice_id = config.get("voice_id")
            if not voice_id:
                # 未显式配置音色，保留为自动分配
                continue

            preset = self.PRESET_VOICES.get(voice_id)
            if not preset:
                logger.warning(f"⚠️ 未知的voice_id: {voice_id}，跳过角色 {character_name}")
                continue

            # 基于预设音色创建一份副本，并允许覆盖音量
            voice_config = dict(preset)
            volume = config.get("volume")
            if volume is not None:
                try:
                    volume_int = int(volume)
                except (TypeError, ValueError):
                    volume_int = preset.get("volume_base", 50)
                voice_config["volume_base"] = max(0, min(100, volume_int))

            # 可选：覆盖语速和音高
            speed = config.get("speed")
            if speed is not None:
                try:
                    speed_float = float(speed)
                except (TypeError, ValueError):
                    speed_float = preset.get("speed_base", 1.0)
                voice_config["speed_base"] = max(0.5, min(2.0, speed_float))

            pitch = config.get("pitch")
            if pitch is not None:
                try:
                    pitch_int = int(pitch)
                except (TypeError, ValueError):
                    pitch_int = preset.get("pitch_base", 50)
                voice_config["pitch_base"] = max(0, min(100, pitch_int))

            profile = self._create_profile(character_name, voice_id, voice_config)
            self.character_voices[character_name] = profile
            self.used_voice_ids.add(voice_id)
            logger.info(
                f"🎛 应用用户音频配置: {character_name} -> {voice_id} "
                f"(volume={voice_config.get('volume_base')})"
            )
    
    def save_mapping(self, filepath: str):
        """保存音色映射到文件"""
        mapping = {
            name: profile.to_dict()
            for name, profile in self.character_voices.items()
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 音色映射已保存: {filepath}")
    
    def load_mapping(self, filepath: str):
        """从文件加载音色映射"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            
            self.character_voices = {
                name: VoiceProfile.from_dict(data)
                for name, data in mapping.items()
            }
            self.used_voice_ids = {p.voice_id for p in self.character_voices.values()}
            logger.info(f"📂 音色映射已加载: {filepath}, 共 {len(self.character_voices)} 个角色")
        except FileNotFoundError:
            logger.warning(f"⚠️ 音色映射文件不存在: {filepath}")
        except Exception as e:
            logger.error(f"❌ 加载音色映射失败: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        gender_dist = {}
        age_dist = {}
        
        for profile in self.character_voices.values():
            gender_dist[profile.gender] = gender_dist.get(profile.gender, 0) + 1
            age_dist[profile.age_group] = age_dist.get(profile.age_group, 0) + 1
        
        return {
            "total_characters": len(self.character_voices),
            "used_voices": len(self.used_voice_ids),
            "available_voices": len(self.PRESET_VOICES) - len(self.used_voice_ids),
            "gender_distribution": gender_dist,
            "age_distribution": age_dist,
            "characters": list(self.character_voices.keys())
        }
