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
    
    # 情感参数映射（扩展版 - 在阿里云API限制内最大化情感表现力）
    # pitch范围: 0-100 (基础50), offset范围: -50到+50 (对应API的0.5-2.0倍率)
    # speed范围: 0.5-2.0倍率, volume范围: 0-100
    emotion_adjustments: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        # === 基础情感（6种） ===
        "neutral": {"pitch_offset": 0, "speed_multiplier": 1.0, "volume_offset": 0},
        "happy": {"pitch_offset": 15, "speed_multiplier": 1.15, "volume_offset": 5},      # 开心：音高↑15%，语速↑15%，音量↑
        "sad": {"pitch_offset": -15, "speed_multiplier": 0.85, "volume_offset": -8},       # 悲伤：音高↓15%，语速↓15%，音量↓
        "angry": {"pitch_offset": 20, "speed_multiplier": 1.25, "volume_offset": 10},      # 愤怒：音高↑20%，语速↑25%，音量↑↑
        "excited": {"pitch_offset": 25, "speed_multiplier": 1.35, "volume_offset": 8},     # 兴奋：音高↑25%，语速↑35%，音量↑
        "calm": {"pitch_offset": -8, "speed_multiplier": 0.92, "volume_offset": -3},       # 平静：音高↓8%，语速↓8%，音量略↓
        
        # === 扩展情感（10种） ===
        "fearful": {"pitch_offset": 18, "speed_multiplier": 1.28, "volume_offset": -5},    # 恐惧：音高↑18%，语速↑28%，音量↓
        "tense": {"pitch_offset": 12, "speed_multiplier": 1.18, "volume_offset": -2},      # 紧张：音高↑12%，语速↑18%，音量略↓
        "surprised": {"pitch_offset": 22, "speed_multiplier": 1.32, "volume_offset": 7},   # 惊讶：音高↑22%，语速↑32%，音量↑
        "disgusted": {"pitch_offset": -12, "speed_multiplier": 0.88, "volume_offset": 3},  # 厌恶：音高↓12%，语速↓12%，音量略↑
        "tender": {"pitch_offset": -5, "speed_multiplier": 0.90, "volume_offset": -5},     # 温柔：音高↓5%，语速↓10%，音量↓
        "serious": {"pitch_offset": -10, "speed_multiplier": 0.95, "volume_offset": 0},    # 严肃：音高↓10%，语速↓5%，音量不变
        "gentle": {"pitch_offset": -6, "speed_multiplier": 0.93, "volume_offset": -4},     # 轻柔：音高↓6%，语速↓7%，音量↓
        "nervous": {"pitch_offset": 14, "speed_multiplier": 1.22, "volume_offset": -3},    # 紧张不安：音高↑14%，语速↑22%，音量略↓
        "whisper": {"pitch_offset": -18, "speed_multiplier": 0.75, "volume_offset": -20},  # 低语：音高↓18%，语速↓25%，音量↓↓
        "shout": {"pitch_offset": 28, "speed_multiplier": 1.20, "volume_offset": 15},      # 呼喊：音高↑28%，语速↑20%，音量↑↑↑
    })
    
    def get_tts_params(self, emotion: str = "neutral") -> Dict[str, Any]:
        """获取TTS参数（支持情感动态调节）"""
        adjustment = self.emotion_adjustments.get(emotion, self.emotion_adjustments["neutral"])
        
        # 动态计算音量（基础音量 + 情感偏移）
        volume_offset = adjustment.get("volume_offset", 0)
        final_volume = max(0, min(100, self.volume_base + volume_offset))
        
        return {
            "speaker": self.tts_speaker_id,
            "pitch": max(0, min(100, self.pitch_base + adjustment["pitch_offset"])),
            "speed": max(0.5, min(2.0, self.speed_base * adjustment["speed_multiplier"])),
            "volume": final_volume  # 动态音量调节
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
    # 预设音色库（基于阿里云 CosyVoice-v3-flash 官方音色列表）
    # 参考文档：https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list
    # 使用官方支持的20种不同音色ID，确保完全兼容
    PRESET_VOICES = {
        # === 男性音色（10种） ===
        "male_young_energetic": {
            "tts_speaker_id": "longanyang",  # 阳光大男孩
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻男主（阳光）"
        },
        "male_young_gentle": {
            "tts_speaker_id": "longanyun_v3",  # 居家暖男
            "gender": "male",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻男主（温柔）"
        },
        "male_adult_calm": {
            "tts_speaker_id": "longanzhi_v3",  # 睿智轻熟男
            "gender": "male",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟男性（沉稳）"
        },
        "male_adult_energetic": {
            "tts_speaker_id": "longyichen_v3",  # 洒脱活力男
            "gender": "male",
            "age_group": "adult",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟男性（豪迈）"
        },
        "male_elder_wise": {
            "tts_speaker_id": "longlaobo_v3",  # 沧桑岁月爷
            "gender": "male",
            "age_group": "elder",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "长者（睿智）"
        },
        "male_warm": {
            "tts_speaker_id": "longhan_v3",  # 温暖痴情男
            "gender": "male",
            "age_group": "adult",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "暖男（痴情）"
        },
        "male_customer_service": {
            "tts_speaker_id": "longyingxun_v3",  # 年轻青涩男
            "gender": "male",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "书生（青涩）"
        },
        "male_refreshing": {
            "tts_speaker_id": "longanlang_v3",  # 清爽利落男
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "武将（利落）"
        },
        "male_monkey": {
            "tts_speaker_id": "longhouge_v3",  # 经典猴哥
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "特色（猴哥）"
        },
        "male_narrator": {
            "tts_speaker_id": "longshange_v3",  # 原味陕北男
            "gender": "male",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "旁白（方言）"
        },
        
        # === 女性音色（10种） ===
        "female_young_gentle": {
            "tts_speaker_id": "longwanjun_v3",  # 细腻柔声女
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻女主（温柔）"
        },
        "female_young_energetic": {
            "tts_speaker_id": "longanhuan",  # 欢脱元气女
            "gender": "female",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻女主（活泼）"
        },
        "female_young_cute": {
            "tts_speaker_id": "longanmin_v3",  # 清纯萝莉女
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "少女（可爱）"
        },
        "female_adult_elegant": {
            "tts_speaker_id": "longanya_v3",  # 高雅气质女
            "gender": "female",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟女性（优雅）"
        },
        "female_adult_intellectual": {
            "tts_speaker_id": "longanwen_v3",  # 优雅知性女
            "gender": "female",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟女性（知性）"
        },
        "female_capable": {
            "tts_speaker_id": "longanli_v3",  # 利落从容女
            "gender": "female",
            "age_group": "adult",
            "personality": "cold",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "女强人（干练）"
        },
        "female_elder": {
            "tts_speaker_id": "longlaoyi_v3",  # 烟火从容阿姨
            "gender": "female",
            "age_group": "elder",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "长者（慈祥）"
        },
        "female_intimate": {
            "tts_speaker_id": "longanrou_v3",  # 温柔闺蜜女
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "闺蜜（亲切）"
        },
        "female_lively": {
            "tts_speaker_id": "longanqin_v3",  # 亲和活泼女
            "gender": "female",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "才女（活泼）"
        },
        "female_child": {
            "tts_speaker_id": "longhuhu_v3",  # 天真烂漫女童
            "gender": "female",
            "age_group": "child",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "童声（天真）"
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
        traits = character_info or {}
        if not traits:
            traits = self._infer_traits_from_name(character_name)
        matched_voice_id = self._match_voice_by_traits(traits)
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
        gender = str(character_info.get("gender", "male")).lower()
        age = str(character_info.get("age_group", "young")).lower()
        personality = str(character_info.get("personality", "calm")).lower()
        
        # 候选音色列表
        candidates = []
        
        for voice_id, voice_config in self.PRESET_VOICES.items():
            # 跳过旁白音色
            if voice_id == "male_narrator":  # 修复：使用正确的key
                continue
            
            # 当已知角色性别时，严格按性别过滤音色池，避免女性角色被分配到男性音色（反之亦然）
            if gender in ("male", "female") and voice_config["gender"] != gender:
                continue
            
            # 对性别未知的情况，才使用“避免重复”的策略
            if gender not in ("male", "female"):
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
            # 优先：如果已知性别，则在全量音色中按性别挑一个（不看已使用记录），保证性别一致性
            if gender in ("male", "female"):
                for voice_id, voice_config in self.PRESET_VOICES.items():
                    if voice_id == "male_narrator":
                        continue
                    if voice_config["gender"] == gender:
                        return voice_id
            # 降级：返回任意未使用的音色
            for voice_id in self.PRESET_VOICES:
                if voice_id not in self.used_voice_ids and voice_id != "male_narrator":  # 修复：使用正确的key
                    return voice_id
            # 最后降级：返回默认音色
            return "male_young_energetic"
    
    def _infer_traits_from_name(self, character_name: str) -> Dict[str, Any]:
        """根据中文称呼简单推断性别/年龄段，用于缺少结构化信息时的兜底逻辑。"""
        name = (character_name or "").strip()
        # 老年女性称呼
        elder_female_keywords = ["奶奶", "婆婆", "大妈", "阿姨"]
        if any(k in name for k in elder_female_keywords):
            return {"gender": "female", "age_group": "elder"}
        # 老年男性称呼
        elder_male_keywords = ["爷爷", "大爷", "老头", "老伯", "伯伯"]
        if any(k in name for k in elder_male_keywords):
            return {"gender": "male", "age_group": "elder"}
        # 典型女性名字特征（优先覆盖“苏娜”等场景）
        female_name_keywords = ["妹", "丫头", "姑娘", "小姐姐"]
        if name and (
            name.endswith("娜")
            or any(k in name for k in female_name_keywords)
        ):
            # 默认按年轻女性处理
            return {"gender": "female", "age_group": "young"}
        # 默认返回空，由 _match_voice_by_traits 使用默认规则处理
        return {}
    
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
            logger.info("🔍 [调试] 旁白未配置，使用默认音色: male_narrator")
            voice_config = self.PRESET_VOICES["male_narrator"]  # 修复：使用正确的key
            self.character_voices["旁白"] = self._create_profile(
                "旁白",
                "male_narrator",
                voice_config
            )
        else:
            profile = self.character_voices["旁白"]
            logger.info(f"✅ [调试] 旁白已配置: {profile.voice_id} ({profile.tts_speaker_id})")
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
        
        logger.info(f"🎵 [调试] 应用音色配置: {list(voice_mapping.keys())}")

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
            logger.info(f"✅ [调试] 已配置 {character_name}: {voice_id} ({preset.get('description', '')})")
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
