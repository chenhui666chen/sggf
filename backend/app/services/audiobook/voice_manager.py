"""
音色管理器 - 智能分配与管理角色音色

核心功能：
1. 预设音色库管理（5-10种基础音色）
2. 角色音色自动分配（确保差异化）
3. 音色一致性保证
4. 情感参数映射
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
import json

from .constants import INSTRUCT_SPEAKER_IDS, normalize_speaker_id

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
    default_emotion: str = "neutral"  # 🆕 默认情感（反派音色专用）
    is_villain_voice: bool = False  # 🆕 是否为反派音色（自动加大情绪张力）
    
    # 情感参数映射（扩展版 - 在阿里云API限制内最大化情感表现力）
    # pitch范围: 0-100 (基础50), offset范围: -50到+50 (对应API的0.5-2.0倍率)
    # speed范围: 0.5-2.0倍率, volume范围: 0-100
    emotion_adjustments: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        # === 基础情感（6种） ===
        "neutral": {"pitch_offset": 0, "speed_multiplier": 1.0, "volume_offset": 0},
        "happy": {"pitch_offset": 10, "speed_multiplier": 1.12, "volume_offset": 5},      # 开心：音高↑10%，语速↑12%，音量↑
        "sad": {"pitch_offset": -15, "speed_multiplier": 0.85, "volume_offset": -8},       # 悲伤：音高↓15%，语速↓15%，音量↓
        "angry": {"pitch_offset": 12, "speed_multiplier": 1.15, "volume_offset": 8},      # 愤怒：音高↑12%，语速↑15%，音量↑↑（降低幅度避免API 428错误）
        "excited": {"pitch_offset": 8, "speed_multiplier": 1.10, "volume_offset": 5},     # 兴奋：音高↑8%，语速↑10%，音量↑（降低幅度避免API 428错误）
        "calm": {"pitch_offset": -8, "speed_multiplier": 0.92, "volume_offset": -3},       # 平静：音高↓8%，语速↓8%，音量略↓
        
        # === 扩展情感（10种） ===
        "fearful": {"pitch_offset": 10, "speed_multiplier": 1.15, "volume_offset": -5},    # 恐惧：音高↑10%，语速↑15%，音量↓（降低幅度避免API 428错误）
        "tense": {"pitch_offset": 8, "speed_multiplier": 1.12, "volume_offset": -2},      # 紧张：音高↑8%，语速↑12%，音量略↓
        "surprised": {"pitch_offset": 12, "speed_multiplier": 1.18, "volume_offset": 5},   # 惊讶：音高↑12%，语速↑18%，音量↑（降低幅度避免API 428错误）
        "disgusted": {"pitch_offset": -12, "speed_multiplier": 0.88, "volume_offset": 3},  # 厌恶：音高↓12%，语速↓12%，音量略↑
        "tender": {"pitch_offset": -5, "speed_multiplier": 0.90, "volume_offset": -5},     # 温柔：音高↓5%，语速↓10%，音量↓
        "serious": {"pitch_offset": -10, "speed_multiplier": 0.95, "volume_offset": 0},    # 严肃：音高↓10%，语速↓5%，音量不变
        "gentle": {"pitch_offset": -6, "speed_multiplier": 0.93, "volume_offset": -4},     # 轻柔：音高↓6%，语速↓7%，音量↓
        "nervous": {"pitch_offset": 8, "speed_multiplier": 1.12, "volume_offset": -3},    # 紧张不安：音高↑8%，语速↑12%，音量略↓（降低幅度避免API 428错误）
        "whisper": {"pitch_offset": -18, "speed_multiplier": 0.75, "volume_offset": -20},  # 低语：音高↓18%，语速↓25%，音量↓↓
        "shout": {"pitch_offset": 28, "speed_multiplier": 1.20, "volume_offset": 15},      # 呼喊：音高↑28%，语速↑20%，音量↑↑↑
    })
    
    def get_tts_params(self, emotion: str = "") -> Dict[str, Any]:
        """??????TTS????????????????????????????????????
        
        ???? ?????????????????????????????????default_emotion????????????????????????????????????????????????
        """
        # ???? ??????????????????????????????????????????
        if not emotion or emotion == "neutral":
            emotion = self.default_emotion
        
        adjustment = self.emotion_adjustments.get(emotion, self.emotion_adjustments["neutral"])
        is_instruct_voice = self.tts_speaker_id in INSTRUCT_SPEAKER_IDS
        use_instruct_mode = bool(is_instruct_voice and emotion and emotion != "neutral")
        
        # ????????????????????????????????? + ???????????????
        volume_offset = adjustment.get("volume_offset", 0)
        final_volume = max(0, min(100, self.volume_base + volume_offset))
        
        if use_instruct_mode:
            pitch_value = max(0, min(100, self.pitch_base))
            speed_value = max(0.5, min(2.0, self.speed_base))
        else:
            pitch_value = max(0, min(100, self.pitch_base + adjustment["pitch_offset"]))
            speed_value = max(0.5, min(2.0, self.speed_base * adjustment["speed_multiplier"]))
        
        speaker_id = normalize_speaker_id(self.tts_speaker_id)

        params = {
            "speaker": speaker_id,
            "pitch": pitch_value,
            "speed": speed_value,
            "volume": final_volume,
            # ???? ???????????????????????????????????????
            "pause_before": self._get_pause_before(emotion),
            "pause_after": self._get_pause_after(emotion),
            "character_base_pitch": max(0, min(100, self.pitch_base)),
            "character_base_speed": max(0.5, min(2.0, self.speed_base))
        }
        
        if use_instruct_mode:
            params["use_instruct_mode"] = True
        
        # ???? ???????????????TTS??????
        try:
            logger.debug(
                f"   ???? get_tts_params??????: speaker={params.get('speaker')}, "
                f"pitch={params.get('pitch')}, speed={params.get('speed'):.2f}, volume={params.get('volume')}"
            )
        except Exception:
            pass  # ??????????????????
        
        return params

    def _get_pause_before(self, emotion: str) -> float:
        """根据情感计算前停顿时长（秒）"""
        pause_map = {
            "neutral": 0.2,
            "calm": 0.3,
            "sad": 0.4,
            "tense": 0.15,
            "angry": 0.1,
            "excited": 0.1,
            "happy": 0.15,
        }
        return pause_map.get(emotion, 0.2)
    
    def _get_pause_after(self, emotion: str) -> float:
        """根据情感计算后停顿时长（秒）"""
        pause_map = {
            "neutral": 0.3,
            "calm": 0.4,
            "sad": 0.5,
            "tense": 0.25,
            "angry": 0.2,
            "excited": 0.25,
            "happy": 0.3,
        }
        return pause_map.get(emotion, 0.3)
    
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
    # - Qwen3-TTS：官方音色 >20 种，原生支持情感参数
    # - CosyVoice3：零样本克隆（保留为精品模式，可选）
    # - 优先使用 Qwen3-TTS（免费 100 万字符/月）
    # 预设音色库（基于阿里云 Qwen3 官方音色列表 + 旧 CosyVoice ID 映射）
    # 参考文档：https://bailian.console.aliyun.com/?tab=doc#/doc/?type=model&url=2879134
    # 使用官方支持的音色 ID，确保完全兼容
    PRESET_VOICES = {
        # === 男性音色（10种） ===
        "male_young_energetic": {
            "tts_speaker_id": "Ethan",  # 阳光大男孩
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻男主（阳光）"
        },
        "male_young_gentle": {
            "tts_speaker_id": "Elias",  # 居家暖男
            "gender": "male",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻男主（温柔）"
        },
        "male_adult_calm": {
            "tts_speaker_id": "Ryan",  # 睿智轻熟男
            "gender": "male",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟男性（沉稳）"
        },
        "male_adult_energetic": {
            "tts_speaker_id": "Dylan",  # 洒脱活力男
            "gender": "male",
            "age_group": "adult",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟男性（豪迈）"
        },
        "male_elder_wise": {
            "tts_speaker_id": "Marcus",  # 沧桑岁月爷
            "gender": "male",
            "age_group": "elder",
            "personality": "calm",
            "pitch_base": 43,  # 降低音高到0.86倍（43/50=0.86），让老年音色更明显
            "speed_base": 0.92,  # 降低语速到0.92倍，更符合老年人说话节奏
            "volume_base": 52,  # 稍微提高音量，避免声音过小
            "description": "长者（睿智）"
        },
        "male_warm": {
            "tts_speaker_id": "Roy",  # 温暖痴情男
            "gender": "male",
            "age_group": "adult",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "暖男（痴情）"
        },
        "male_customer_service": {
            "tts_speaker_id": "Peter",  # 年轻青涩男
            "gender": "male",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "书生（青涩）"
        },
        "male_refreshing": {
            "tts_speaker_id": "Li",  # 清爽利落男
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "武将（利落）"
        },
        "male_monkey": {
            "tts_speaker_id": "Nofish",  # 经典猴哥
            "gender": "male",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "特色（猴哥）"
        },
        "male_narrator": {
            "tts_speaker_id": "Eric",  # 原味陕北男
            "gender": "male",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "旁白（方言）"
        },
        
        # === 特色音色（3种） ===
        "male_villain_sinister": {
            "tts_speaker_id": "Roy",  # 基于温暖痴情男
            "gender": "male",
            "age_group": "adult",
            "personality": "calm",  # 沉稳
            "pitch_base": 45,  # 降低音高10%
            "speed_base": 0.92,  # 减慢语速8%
            "volume_base": 48,  # 降低音量，更沉稳
            "description": "成熟谋士（沉稳）",
            "default_emotion": "neutral"  # 默认中性情感
        },
        "female_villain_cold": {
            "tts_speaker_id": "Jennifer",  # 基于利落从容女
            "gender": "female",
            "age_group": "adult",
            "personality": "calm",  # 冷静
            "pitch_base": 45,  # 降低音高10%，更沉稳
            "speed_base": 0.90,  # 减慢语速10%
            "volume_base": 50,
            "description": "冷静御姐（高雅）",
            "default_emotion": "neutral"  # 默认中性情感
        },
        "female_villain_cunning": {
            "tts_speaker_id": "Katerina",  # 基于高雅气质女
            "gender": "female",
            "age_group": "adult",
            "personality": "elegant",  # 优雅
            "pitch_base": 48,  # 略降低音高4%
            "speed_base": 0.95,  # 略减慢语速5%
            "volume_base": 48,
            "description": "优雅名媛（睿智）",
            "default_emotion": "neutral"  # 默认中性情感
        },
        
        # === 女性音色（10种） ===
        "female_young_gentle": {
            "tts_speaker_id": "Cherry",  # 细腻柔声女
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻女主（温柔）"
        },
        "female_young_energetic": {
            "tts_speaker_id": "Sunny",  # 欢脱元气女
            "gender": "female",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "年轻女主（活泼）"
        },
        "female_young_cute": {
            "tts_speaker_id": "Momo",  # 清纯萝莉女
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "少女（可爱）"
        },
        "female_adult_elegant": {
            "tts_speaker_id": "Katerina",  # 高雅气质女
            "gender": "female",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟女性（优雅）"
        },
        "female_adult_intellectual": {
            "tts_speaker_id": "Serena",  # 优雅知性女
            "gender": "female",
            "age_group": "adult",
            "personality": "calm",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "成熟女性（知性）"
        },
        "female_capable": {
            "tts_speaker_id": "Jennifer",  # 利落从容女
            "gender": "female",
            "age_group": "adult",
            "personality": "cold",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "女强人（干练）"
        },
        "female_elder": {
            "tts_speaker_id": "Chelsie",  # 烟火从容阿姨
            "gender": "female",
            "age_group": "elder",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "长者（慈祥）"
        },
        "female_intimate": {
            "tts_speaker_id": "Jada",  # 温柔闺蜜女
            "gender": "female",
            "age_group": "young",
            "personality": "gentle",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "闺蜜（亲切）"
        },
        "female_lively": {
            "tts_speaker_id": "Kiki",  # 亲和活泼女
            "gender": "female",
            "age_group": "young",
            "personality": "energetic",
            "pitch_base": 50,
            "speed_base": 1.0,
            "volume_base": 50,
            "description": "才女（活泼）"
        },
        "female_child": {
            "tts_speaker_id": "Momo",  # 天真烂漫女童
            "gender": "female",
            "age_group": "child",
            "personality": "energetic",
            "pitch_base": 65,  # 提高音高到1.3倍（65/50=1.3），让童声更明显
            "speed_base": 1.05,  # 略加快语速，符合儿童活泼特质
            "volume_base": 52,  # 略提高音量，让声音更清晰
            "description": "童声（天真）"
        }
    }

    SPEAKER_TO_PRESET = {
        cfg["tts_speaker_id"].lower(): preset_id
        for preset_id, cfg in PRESET_VOICES.items()
    }
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（用于智能推断角色特征）
        """
        # 统一管理角色音色档案
        self.character_voices: Dict[str, VoiceProfile] = {}  # 角色名 -> 音色档案
        # 向后兼容旧字段 voice_profiles（部分模块仍然引用）
        self.voice_profiles: Dict[str, VoiceProfile] = self.character_voices
        self.used_voice_ids = set()  # 已使用的音色ID
        self.llm_client = llm_client  # 🆕 存储LLM客户端用于智能推断
    
    def _resolve_voice_config(self, voice_id: Optional[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """将 legacy voice_id（含 CosyVoice speaker）映射到 Qwen3 预设。"""
        if not voice_id:
            return None
        if voice_id in self.PRESET_VOICES:
            return voice_id, self.PRESET_VOICES[voice_id]
        
        normalized = normalize_speaker_id(voice_id)
        preset_id = self.SPEAKER_TO_PRESET.get(normalized.lower())
        if preset_id:
            logger.info(f"🔁 映射旧音色 '{voice_id}' → Qwen3 speaker '{normalized}' (preset {preset_id})")
            return preset_id, self.PRESET_VOICES[preset_id]
        return None
    
    def assign_voice(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
        preferred_voice_id: Optional[str] = None
    ) -> VoiceProfile:
        """
        为角色分配音色（自适应智能推断）
        
        优先级策略：
        1. ✅ 已配置角色 → 直接返回（用户配置优先）
        2. 🔒 指定音色 → 使用指定ID（手动覆盖）
        3. 🤖 LLM推断 → 智能匹配（自动启用）
        4. 📖 规则推断 → 基于名字特征（兜底）
        
        Args:
            character_name: 角色名
            character_info: 角色信息（可选），包含 gender, age_group, personality
            preferred_voice_id: 指定音色ID（可选）
        
        Returns:
            音色档案
        """
        # 优先级1：检查是否已分配（用户配置优先）
        if character_name in self.character_voices:
            logger.info(f"✅ 角色 '{character_name}' 已有音色档案（用户配置）")
            return self.character_voices[character_name]
        
        # 优先级2：使用指定音色（手动覆盖）
        if preferred_voice_id and preferred_voice_id in self.PRESET_VOICES:
            voice_config = self.PRESET_VOICES[preferred_voice_id]
            profile = self._create_profile(character_name, preferred_voice_id, voice_config)
            self.character_voices[character_name] = profile
            self.used_voice_ids.add(preferred_voice_id)
            logger.info(f"🔒 为 '{character_name}' 分配指定音色: {preferred_voice_id}")
            return profile
        
        # 优先级3 & 4：智能匹配（LLM推断 → 规则推断）
        traits = character_info or {}
        if not traits:
            # 🆕 自动尝试LLM推断（如果有LLM客户端）
            traits = self._infer_traits_from_name(character_name)
        
        matched_voice_id = self._match_voice_by_traits(traits)
        voice_config = self.PRESET_VOICES[matched_voice_id]
        profile = self._create_profile(character_name, matched_voice_id, voice_config)
        
        self.character_voices[character_name] = profile
        self.used_voice_ids.add(matched_voice_id)
        
        # 📊 显示分配方式
        if self.llm_client and traits:
            logger.info(f"🤖 为 '{character_name}' 智能分配音色: {matched_voice_id}")
        else:
            logger.info(f"📖 为 '{character_name}' 规则分配音色: {matched_voice_id}")
        
        return profile
    
    def _match_voice_by_traits(self, character_info: Dict[str, Any]) -> str:
        """
        基于角色特征匹配最佳音色
            
        优先级：gender > age_group > personality > role_type
        同时避免使用已分配的音色（确保差异化）
        🆕 支持反派角色识别与专属音色匹配
        """
        gender = str(character_info.get("gender", "male")).lower()
        age = str(character_info.get("age_group", "young")).lower()
        personality = str(character_info.get("personality", "calm")).lower()
        role_type = str(character_info.get("role_type", "")).lower()
        
        # 🎭 反派角色检测：优先分配高张力的 Ethan/Sunny
        villain_keywords = ["反派", "恶人", "反角", "敌人", "boss", "villain", "enemy", "antagonist"]
        villain_personalities = ["cold", "evil", "sinister", "cruel", "ruthless", "domineering", "cunning"]
        
        is_villain = (
            any(keyword in role_type for keyword in villain_keywords) or
            personality in villain_personalities
        )
        
        if is_villain:
            logger.info(f"🎭 检测到反派角色，优先使用高张力音色 (role_type={role_type}, personality={personality})")
            # 根据性别锁定 Ethan/Sunny，并由情感映射增强张力
            # TTS引擎会自动为这些音色添加 angry/disgusted 情感
            if gender == "male":
                logger.info("🎭 为男性反派分配: male_young_energetic (Ethan)")
                return "male_young_energetic"  # Ethan，支持angry/disgusted情感
            elif gender == "female":
                logger.info("🎭 为女性反派分配: female_young_energetic (Sunny)")
                return "female_young_energetic"  # Sunny，支持angry/disgusted情感
        
        # 候选音色列表
        candidates = []
            
        for voice_id, voice_config in self.PRESET_VOICES.items():
            # 跳过旁白音色
            if voice_id == "male_narrator":
                continue
                
            # 当已知角色性别时，严格按性别过滤音色池，避免女性角色被分配到男性音色（反之亦然）
            if gender in ("male", "female") and voice_config["gender"] != gender:
                continue
                
            # 对性别未知的情况，才使用"避免重复"的策略
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
                if voice_id not in self.used_voice_ids and voice_id != "male_narrator":
                    return voice_id
            # 最后降级：返回默认音色
            return "male_young_energetic"
    
    def _infer_traits_from_name(self, character_name: str) -> Dict[str, Any]:
        """
        🤖 智能推断角色特征（基于名字）
        
        优先使用LLM进行语义理解，失败时回退到规则推断
        
        Args:
            character_name: 角色名
        
        Returns:
            角色特征 {gender, age_group, personality}
        """
        name = (character_name or "").strip()
        if not name:
            return {}
        
        # 🆕 优先尝试LLM智能推断
        if self.llm_client:
            try:
                llm_traits = self._llm_infer_traits(name)
                if llm_traits:
                    logger.info(f"🤖 [智能推断] '{name}' -> {llm_traits}")
                    return llm_traits
            except Exception as e:
                logger.warning(f"⚠️ LLM推断失败，回退到规则推断: {e}")
        
        # 📖 回退到规则推断
        return self._rule_based_infer_traits(name)
    
    def _llm_infer_traits(
        self,
        character_name: str,
        context: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        🤖 使用LLM智能推断角色特征
        
        Args:
            character_name: 角色名
            context: 上下文信息（可选，如角色描述）
        
        Returns:
            角色特征字典，失败返回None
        """
        prompt = f"""你是专业的角色分析助手，请根据角色名推断其基本特征。

**角色名**：{character_name}
{f'**上下文**：{context}' if context else ''}

**推断规则**：
1. **性别** (gender)：根据中文名字特征判断
   - female: 常见女性名字（娜/婷/芝/霞/雪/梅/芳/琳/雯/瑜/娥等）、称呼（娘/姐/妹/娃/奶奶/婆婆/姑娘/阿姨）
   - male: 常见男性名字（昊/浩/强/伟/军/明/建/凌/龙等）、称呼（爷爷/大爷/老头/伯伯）
   - unknown: 无法判断（如英文名/中性称呼）

2. **年龄段** (age_group)：根据称呼/职业推断
   - child: 儿童（小孩/娃娃/小屏风）
   - young: 青年（小姐/小伙/小姑娘/默认）
   - middle: 中年（大叔/大娘/阿姨）
   - elder: 老年（爷爷/奶奶/老人）

3. **性格** (personality)：根据名字气质猜测
   - calm: 沉稳冷静（默认）
   - energetic: 活泼开朗
   - gentle: 温柔亲切
   - serious: 严肃正经

**输出格式**：纯JSON，不要包含注释
```json
{{
    "gender": "female|male|unknown",
    "age_group": "child|young|middle|elder",
    "personality": "calm|energetic|gentle|serious",
    "confidence": 0.8
}}
```

**示例**：
- "苏娜" -> {{"gender": "female", "age_group": "young", "personality": "gentle", "confidence": 0.9}}
- "陈浩" -> {{"gender": "male", "age_group": "young", "personality": "calm", "confidence": 0.85}}
- "李奶奶" -> {{"gender": "female", "age_group": "elder", "personality": "gentle", "confidence": 0.95}}
- "Alice" -> {{"gender": "unknown", "age_group": "young", "personality": "calm", "confidence": 0.5}}
"""
        
        try:
            from app.services.model_optimizer import TaskType
            import asyncio
            import json
            
            response = asyncio.run(self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                max_tokens=500,
                response_format={"type": "json_object"},
                use_cache=True,  # 启用缓存，相同名字不重复调用
            ))
            
            # 解析JSON
            result = json.loads(response.strip())
            
            # 验证结果
            if result.get("gender") and result.get("age_group"):
                # 只返回高置信度的结果
                confidence = result.get("confidence", 0.5)
                if confidence >= 0.7:
                    return {
                        "gender": result["gender"],
                        "age_group": result["age_group"],
                        "personality": result.get("personality", "calm")
                    }
                else:
                    logger.info(f"📊 LLM置信度较低 ({confidence:.2f})，回退到规则推断")
            
            return None
            
        except Exception as e:
            logger.debug(f"🤖 LLM推断失败: {e}")
            return None
    
    def _rule_based_infer_traits(self, character_name: str) -> Dict[str, Any]:
        """📖 基于规则的特征推断（增强版）"""
        name = character_name.strip()
        
        # === 年龄段判断 ===
        # 老年女性
        elder_female_keywords = ["奶奶", "婆婆", "大妈", "阿姨", "老太太"]
        if any(k in name for k in elder_female_keywords):
            return {"gender": "female", "age_group": "elder", "personality": "gentle"}
        
        # 老年男性
        elder_male_keywords = ["爷爷", "大爷", "老头", "老伯", "伯伯", "老爷子"]
        if any(k in name for k in elder_male_keywords):
            return {"gender": "male", "age_group": "elder", "personality": "serious"}
        
        # 儿童
        child_keywords = ["小孩", "娃娃", "小屏风", "孩子"]
        if any(k in name for k in child_keywords):
            return {"gender": "unknown", "age_group": "child", "personality": "energetic"}
        
        # === 性别判断（增强版） ===
        # 女性特征字（扩充）
        female_chars = [
            "娜", "婷", "芝", "霞", "雪", "梅", "芳", "琳", "雯", "瑜", "娥",
            "芭", "妮", "蕾", "萝", "莉", "慧", "敏", "静", "涵", "琼",
            "娟", "娅", "珊", "嘉", "莲", "蓉", "珊", "洁", "雅", "怡"
        ]
        if any(name.endswith(c) for c in female_chars):
            return {"gender": "female", "age_group": "young", "personality": "gentle"}
        
        # 女性称呼/关键词
        female_keywords = ["姐", "姑娘", "小姐", "妹", "丫头", "娘", "女士"]
        if any(k in name for k in female_keywords):
            return {"gender": "female", "age_group": "young", "personality": "energetic"}
        
        # 男性特征字（扩充）
        male_chars = [
            "昊", "浩", "强", "伟", "军", "明", "建", "凌", "龙", "杰",
            "博", "宇", "峰", "岭", "浩", "辉", "宏", "俊", "强", "瑞"
        ]
        if any(name.endswith(c) for c in male_chars):
            return {"gender": "male", "age_group": "young", "personality": "calm"}
        
        # 男性称呼/关键词
        male_keywords = ["大叔", "小伙", "公子", "少侠", "少爷"]
        if any(k in name for k in male_keywords):
            return {"gender": "male", "age_group": "young", "personality": "energetic"}
        
        # 默认返回空（由 _match_voice_by_traits 使用默认规则处理）
        logger.info(f"📊 [规则推断] '{name}' 无法判断，使用默认配置")
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
            volume_base=voice_config["volume_base"],
            default_emotion=voice_config.get("default_emotion", "neutral")  # 🆕 支持反派音色默认情感
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
            # 🔍 详细调试：输出旁白的实际参数
            logger.info(f"✅ [调试] 旁白已配置: {profile.voice_id} ({profile.tts_speaker_id})")
            logger.info(f"   📦 旁白参数: pitch_base={profile.pitch_base}, speed_base={profile.speed_base}, volume_base={profile.volume_base}")
        return self.character_voices["旁白"]
    
    def get_voice(self, character_name: str) -> Optional[VoiceProfile]:
        """获取角色音色"""
        profile = self.character_voices.get(character_name)
        if profile:
            # 🔍 调试：输出角色的实际参数
            logger.debug(f"   📦 {character_name}参数: pitch_base={profile.pitch_base}, speed_base={profile.speed_base}, volume_base={profile.volume_base}")
        return profile
    
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

            resolved = self._resolve_voice_config(voice_id)
            if not resolved:
                logger.warning(f"⚠️ 未知的voice_id: {voice_id}，跳过角色 {character_name}")
                continue
            resolved_voice_id, preset = resolved

            # 基于预设音色创建一份副本，并允许覆盖音量
            voice_config = dict(preset)
            if resolved_voice_id != voice_id:
                voice_id = resolved_voice_id
                config["voice_id"] = resolved_voice_id
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
            for profile in self.character_voices.values():
                profile.tts_speaker_id = normalize_speaker_id(profile.tts_speaker_id)
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
