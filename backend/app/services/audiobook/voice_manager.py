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
from .llm_client import call_audiobook_llm_sync
from .llm_json import LLMJsonParseError, parse_llm_json_object
from .tts_model_ids import DEFAULT_AUDIOBOOK_TTS_MODEL, normalize_audiobook_tts_model
from .voice_catalog import load_voice_catalog, load_voice_catalog_for_model
from .voice_description_policy import build_quality_voice_description

logger = logging.getLogger(__name__)

STYLE_TRAIT_HINTS = {
    "gentle": ("young", "gentle"),
    "cute": ("young", "energetic"),
    "bright": ("young", "energetic"),
    "lively": ("young", "energetic"),
    "fast": ("young", "energetic"),
    "soft": ("adult", "gentle"),
    "smooth": ("adult", "calm"),
    "calm": ("adult", "calm"),
    "warm": ("adult", "gentle"),
    "elegant": ("adult", "calm"),
    "energetic": ("adult", "energetic"),
    "powerful": ("adult", "serious"),
    "magnetic": ("adult", "calm"),
    "clear": ("adult", "serious"),
    "soothing": ("adult", "gentle"),
    "elder": ("elder", "calm"),
    "dialect": ("adult", "dialect"),
}

VOICE_PROFILE_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "Cherry": {"age_group": "young"},
    "Momo": {"age_group": "young"},
    "Bunny": {"age_group": "young", "personality": "energetic"},
    "Kai": {"personality": "energetic"},
    "Vincent": {"personality": "calm"},
    "Neil": {"personality": "calm"},
    "Mia": {"personality": "energetic"},
    "Eldric Sage": {"age_group": "elder", "personality": "serious"},
    # 方言音色（官方 voice 参数）
}

LEGACY_PRESET_ALIASES = {
    "male_young_energetic": "Ethan",
    "male_young_gentle": "Vincent",
    "male_adult_calm": "Neil",
    "male_adult_energetic": "Ethan",
    "male_elder_wise": "Eldric Sage",
    "male_warm": "Vincent",
    "male_customer_service": "Kai",
    "male_refreshing": "Kai",
    "male_monkey": "Nofish",
    "male_narrator": "Neil",
    "male_villain_sinister": "Vincent",
    "female_villain_cold": "Bellona",
    "female_villain_cunning": "Vivian",
    "female_young_gentle": "Cherry",
    "female_young_energetic": "Bunny",
    "female_young_cute": "Momo",
    "female_adult_elegant": "Bella",
    "female_adult_intellectual": "Vivian",
    "female_capable": "Bellona",
    "female_elder": "Chelsie",
    "female_intimate": "Mochi",
    "female_lively": "Mia",
    "female_child": "Momo",
}

_CATALOG = load_voice_catalog()
_VOICE_ENTRIES = _CATALOG["voices_by_id"]


def _derive_traits(style: str) -> Tuple[str, str]:
    style = (style or "").lower()
    return STYLE_TRAIT_HINTS.get(style, ("adult", "calm"))


def _build_voice_preset(voice_id: str) -> Dict[str, Any]:
    voice_entry = _VOICE_ENTRIES[voice_id]
    overrides = VOICE_PROFILE_OVERRIDES.get(voice_id, {})
    style = voice_entry.get("style", "calm")
    age_group, personality = _derive_traits(style)
    gender = overrides.get("gender", voice_entry.get("gender", "neutral") or "neutral").lower()
    defaults = voice_entry.get("default_params", {})
    return {
        "tts_speaker_id": voice_entry["speaker"],
        "gender": gender,
        "age_group": overrides.get("age_group", age_group),
        "personality": overrides.get("personality", personality),
        "pitch_base": int(overrides.get("pitch_base", defaults.get("pitch", 50))),
        "speed_base": float(overrides.get("speed_base", defaults.get("speed", 1.0))),
        "volume_base": int(overrides.get("volume_base", defaults.get("volume", 50))),
        "description": overrides.get("description", voice_entry.get("description", "")),
        "default_emotion": overrides.get("default_emotion", "neutral"),
    }

_BASE_PRESET_VOICES: Dict[str, Dict[str, Any]] = {
    voice_id: _build_voice_preset(voice_id)
    for voice_id in _VOICE_ENTRIES
}

_PRESET_VOICES: Dict[str, Dict[str, Any]] = dict(_BASE_PRESET_VOICES)
for alias, target in LEGACY_PRESET_ALIASES.items():
    target_cfg = _BASE_PRESET_VOICES.get(target)
    if not target_cfg:
        continue
    alias_cfg = dict(target_cfg)
    alias_cfg["legacy_alias_of"] = target
    _PRESET_VOICES[alias] = alias_cfg

_SPEAKER_TO_PRESET: Dict[str, str] = {}
for preset_id, cfg in _BASE_PRESET_VOICES.items():
    key = cfg["tts_speaker_id"].lower()
    _SPEAKER_TO_PRESET.setdefault(key, preset_id)


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
    tts_model: str = "qwen3-tts-instruct-flash"  # 🆕 适用的TTS模型
    tts_speaker_id: str = ""  # TTS服务的音色ID
    pitch_base: int = 50  # 基础音高 0-100
    speed_base: float = 1.0  # 基础语速 0.5-2.0
    volume_base: int = 50  # 基础音量 0-100
    default_emotion: str = "neutral"  # 默认情感（反派音色专用）
    is_villain_voice: bool = False  # 是否为反派音色（自动加大情绪张力）
    
    # 情感参数映射（扩展版 - 在阿里云API限制内最大化情感表现力）
    # pitch范围: 0-100 (基础50), offset范围: -50~+50 (对应API的0.5-2.0倍率)
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
        """生成传递给TTS接口的参数。"""
        if not emotion or emotion == "neutral":
            emotion = self.default_emotion
        
        adjustment = self.emotion_adjustments.get(emotion, self.emotion_adjustments["neutral"])
        is_instruct_voice = self.tts_speaker_id in INSTRUCT_SPEAKER_IDS
        use_instruct_mode = bool(is_instruct_voice and emotion and emotion != "neutral")
        
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
            "pause_before": self._get_pause_before(emotion),
            "pause_after": self._get_pause_after(emotion),
            "character_base_pitch": max(0, min(100, self.pitch_base)),
            "character_base_speed": max(0.5, min(2.0, self.speed_base)),
            "voice_description": self._build_voice_description(emotion, speed_value),
        }
        
        if use_instruct_mode:
            params["use_instruct_mode"] = True
        
        try:
            logger.debug(
                f"get_tts_params -> speaker={params.get('speaker')}, "
                f"pitch={params.get('pitch')}, speed={params.get('speed'):.2f}, volume={params.get('volume')}"
            )
        except Exception:
            pass
        
        return params

    def _build_voice_description(self, emotion: str, speed_value: float) -> str:
        """生成可被模型风格控制层复用的结构化声音描述。"""
        age_map = {
            "child": "儿童",
            "teen": "青少年",
            "young": "青年",
            "adult": "中年",
            "elder": "老年",
        }
        personality_traits = {
            "calm": ["沉稳", "吐字清晰"],
            "energetic": ["明亮", "有活力"],
            "gentle": ["温柔", "亲切自然"],
            "serious": ["严肃", "有力"],
            "cold": ["冷静", "克制"],
            "warm": ["温暖", "亲切自然"],
            "dialect": ["地域口音", "生活化"],
        }
        pitch_label = "偏高" if self.pitch_base >= 62 else "偏低" if self.pitch_base <= 38 else "中音"
        pace_label = "快速" if speed_value >= 1.15 else "缓慢" if speed_value <= 0.9 else "中速"
        traits = personality_traits.get(str(self.personality or "").strip().lower(), ["吐字清晰"])
        return build_quality_voice_description(
            gender=self.gender,
            age_group=age_map.get(str(self.age_group or "").strip().lower(), "青年"),
            pitch=pitch_label,
            pace=pace_label,
            emotion=emotion or self.default_emotion or "neutral",
            traits=traits,
            use_case="有声书角色对白",
        )

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
    PRESET_VOICES = _PRESET_VOICES
    BASE_PRESET_VOICES = _BASE_PRESET_VOICES
    SPEAKER_TO_PRESET = _SPEAKER_TO_PRESET

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（用于智能推断角色特征）
        """
        self.character_voices: Dict[str, VoiceProfile] = {}
        self.voice_profiles: Dict[str, VoiceProfile] = self.character_voices
        self.used_voice_ids = set()
        self.llm_client = llm_client
        self._fuzzy_threshold = 0.80

    def _fuzzy_match_character(self, character_name: str) -> Optional[str]:
        """模糊匹配角色名，返回已存在的规范角色名

        使用 difflib.SequenceMatcher 计算字符串相似度。
        当相似度超过阈值（默认 0.80）时，视为同一角色。

        处理场景：
        - "张三" vs "张三丰" → 可能匹配
        - "小明" vs "小明子" → 可能匹配
        - "王五" vs "王 五" → 空格差异匹配
        - 全角/半角混用 → 先归一化后匹配

        Args:
            character_name: 传入的角色名

        Returns:
            匹配到的已有角色名，或 None
        """
        import difflib

        name = character_name.strip()
        if not name or not self.character_voices:
            return None

        best_match = None
        best_score = 0.0

        for existing_name in self.character_voices:
            ratio = difflib.SequenceMatcher(None, name, existing_name).ratio()
            if ratio > best_score:
                best_score = ratio
                best_match = existing_name

        if best_score >= self._fuzzy_threshold:
            logger.info(
                "🔗 模糊匹配: '%s' → '%s' (相似度: %.2f, 阈值: %.2f)",
                name, best_match, best_score, self._fuzzy_threshold,
            )
            return best_match

        return None
    
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

    def _resolve_voice_config_for_model(
        self,
        voice_id: Optional[str],
        tts_model: Optional[str] = None,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """按指定模型解析音色配置，支持角色级跨模型 voice_mapping。"""
        if not voice_id:
            return None

        normalized_model = normalize_audiobook_tts_model(tts_model or DEFAULT_AUDIOBOOK_TTS_MODEL)
        if normalized_model == DEFAULT_AUDIOBOOK_TTS_MODEL:
            return self._resolve_voice_config(voice_id)

        try:
            catalog = load_voice_catalog_for_model(normalized_model)
            entry = catalog.get("voices_by_id", {}).get(str(voice_id))
        except Exception as exc:
            logger.warning("⚠️ 加载 %s 音色目录失败: %s", normalized_model, exc)
            entry = None

        if not entry:
            return None

        defaults = entry.get("default_params") or {}
        voice_config = {
            "tts_speaker_id": entry.get("speaker") or entry.get("id") or voice_id,
            "gender": str(entry.get("gender") or "neutral").lower(),
            "age_group": str(entry.get("category") or "adult").lower(),
            "personality": str(entry.get("style") or "calm").lower(),
            "pitch_base": int(defaults.get("pitch", 50) or 50),
            "speed_base": float(defaults.get("speed", 1.0) or 1.0),
            "volume_base": int(defaults.get("volume", 50) or 50),
            "description": entry.get("description", ""),
            "default_emotion": "calm",
            "tts_model": normalized_model,
        }
        return str(entry.get("id") or voice_id), voice_config

    def _apply_voice_type_config(self, voice_config: Dict[str, Any], voice_type: Optional[str]) -> None:
        voice_type = str(voice_type or "").strip()
        if not voice_type:
            return

        try:
            from .voice_types import apply_voice_type_to_tts_params

            enhanced = apply_voice_type_to_tts_params(
                voice_type,
                {
                    "volume": voice_config.get("volume_base"),
                    "speed": voice_config.get("speed_base"),
                    "pitch": voice_config.get("pitch_base"),
                },
            )
            if enhanced.get("volume") is not None:
                voice_config["volume_base"] = int(max(0, min(100, enhanced["volume"])))
            if enhanced.get("speed") is not None:
                voice_config["speed_base"] = float(max(0.5, min(2.0, enhanced["speed"])))
            if enhanced.get("pitch") is not None:
                voice_config["pitch_base"] = int(max(0, min(100, enhanced["pitch"])))
            if enhanced.get("emotion"):
                voice_config["default_emotion"] = enhanced["emotion"]
        except Exception as exc:
            logger.warning("⚠️ 应用声音类型配置失败: %s", exc)
    
    def assign_voice(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
        preferred_voice_id: Optional[str] = None
    ) -> VoiceProfile:
        """
        为角色分配音色（自适应智能推断）
        
        优先级策略：
        0. 🔗 模糊匹配 → 字符名容错匹配（新增）
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
        # 优先级0：模糊匹配（新增）
        fuzzy_match = self._fuzzy_match_character(character_name)
        if fuzzy_match:
            logger.info(f"🔗 模糊命中: '{character_name}' 使用已有角色 '{fuzzy_match}' 的音色")
            return self.character_voices[fuzzy_match]

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
        traits = dict(character_info or {})
        used_llm = False
        missing_values = (None, "", "unknown")
        if not traits:
            if self.llm_client:
                llm_traits = self._llm_infer_traits(character_name)
                if llm_traits:
                    traits = llm_traits
                    used_llm = True
                else:
                    traits = self._rule_based_infer_traits(character_name)
            else:
                traits = self._rule_based_infer_traits(character_name)
        else:
            needs_fill = any(
                traits.get(key) in missing_values
                for key in ("gender", "age_group", "personality")
            )
            if needs_fill and self.llm_client:
                context = traits.get("context") or traits.get("role_type")
                llm_traits = self._llm_infer_traits(character_name, context=context)
                if llm_traits:
                    used_llm = True
                    for key in ("gender", "age_group", "personality"):
                        if traits.get(key) in missing_values and llm_traits.get(key):
                            traits[key] = llm_traits[key]

            if any(traits.get(key) in missing_values for key in ("gender", "age_group", "personality")):
                rule_traits = self._rule_based_infer_traits(character_name)
                for key in ("gender", "age_group", "personality"):
                    if traits.get(key) in missing_values and rule_traits.get(key):
                        traits[key] = rule_traits[key]

        age_group = str(traits.get("age_group") or "").strip().lower()
        if age_group in ("middle", "mid"):
            traits["age_group"] = "adult"
        elif age_group in ("teen", "teenager", "adolescent"):
            traits["age_group"] = "young"

        matched_voice_id = self._match_voice_by_traits(traits)
        voice_config = self.PRESET_VOICES[matched_voice_id]
        profile = self._create_profile(character_name, matched_voice_id, voice_config)
        
        self.character_voices[character_name] = profile
        self.used_voice_ids.add(matched_voice_id)
        
        # 📊 显示分配方式
        if used_llm:
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
        
        # 🎭 反派角色检测：优先分配高张力的 Ethan/Bunny
        villain_keywords = ["反派", "恶人", "反角", "敌人", "boss", "villain", "enemy", "antagonist"]
        villain_personalities = ["cold", "evil", "sinister", "cruel", "ruthless", "domineering", "cunning"]
        
        is_villain = (
            any(keyword in role_type for keyword in villain_keywords) or
            personality in villain_personalities
        )
        
        preferred_villain_voice_id = None
        if is_villain:
            logger.info(f"🎭 检测到反派角色，优先使用高张力音色 (role_type={role_type}, personality={personality})")
            # 根据性别锁定 Ethan/Bunny，并由情感映射增强张力
            # TTS引擎会自动为这些音色添加 angry/disgusted 情感
            if gender == "male":
                preferred_villain_voice_id = "Ethan"  # Ethan，支持angry/disgusted情感
            elif gender == "female":
                preferred_villain_voice_id = "Bunny"  # Sunny，支持angry/disgusted情感

            if preferred_villain_voice_id and preferred_villain_voice_id not in self.used_voice_ids:
                logger.info("🎭 为反派分配专用高张力音色: %s", preferred_villain_voice_id)
                return preferred_villain_voice_id
        
        # 候选音色列表
        candidates = []
            
        for voice_id, voice_config in self.PRESET_VOICES.items():
            if voice_config.get("legacy_alias_of"):
                continue
            # 跳过旁白音色
            if voice_id == "male_narrator":
                continue
                
            # 当已知角色性别时，严格按性别过滤音色池，避免女性角色被分配到男性音色（反之亦然）
            if gender in ("male", "female") and voice_config["gender"] != gender:
                continue
                
            # 计算匹配分数
            score = 0
            if voice_config["gender"] == gender:
                score += 10
            if voice_config["age_group"] == age:
                score += 5
            if voice_config["personality"] == personality:
                score += 3
            if preferred_villain_voice_id and voice_id == preferred_villain_voice_id:
                score += 4
                
            candidates.append((voice_id, score))
            
        # 选择最高分
        if candidates:
            candidate_pool = [
                candidate for candidate in candidates
                if candidate[0] not in self.used_voice_ids
            ] or candidates
            candidate_pool.sort(key=lambda x: x[1], reverse=True)
            return candidate_pool[0][0]
        else:
            # 优先：如果已知性别，则在全量音色中按性别挑一个（不看已使用记录），保证性别一致性
            if gender in ("male", "female"):
                for voice_id, voice_config in self.PRESET_VOICES.items():
                    if voice_config.get("legacy_alias_of"):
                        continue
                    if voice_config.get("legacy_alias_of"):
                        continue
                    if voice_id == "male_narrator":
                        continue
                    if voice_config["gender"] == gender:
                        return voice_id
            # 降级：返回任意未使用的音色
            for voice_id, voice_config in self.PRESET_VOICES.items():
                if voice_config.get("legacy_alias_of"):
                    continue
                if voice_id not in self.used_voice_ids and voice_id != "male_narrator":
                    return voice_id
            # 最后降级：返回默认音色
            return "Ethan"
    
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
   - child: 儿童（小孩/娃娃）
   - young: 青年/少年（小姐/小伙/小姑娘/学生）
   - adult: 成年/中年（大叔/大娘/阿姨）
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
    "age_group": "child|young|adult|elder",
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
            import json
            import asyncio
            
            # 检查当前是否有运行中的事件循环
            try:
                loop = asyncio.get_running_loop()
                # 如果有运行中的事件循环，则使用 run_in_executor 或其他方式
                logger.debug("🔄 当前已有事件循环，使用异步调用")
                
                # 为同步上下文提供异步调用方法
                import concurrent.futures
                def run_llm_call():
                    # 创建新的事件循环用于LLM调用
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return call_audiobook_llm_sync(
                            self.llm_client,
                            messages=[{"role": "user", "content": prompt}],
                            max_tokens=500,
                            response_format={"type": "json_object"},
                            use_cache=True,  # 启用缓存，相同名字不重复调用
                            timeout_seconds=30,
                        )
                    finally:
                        new_loop.close()
                
                # 在线程池中运行异步调用
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_llm_call)
                    response = future.result(timeout=30)  # 30秒超时
                    
            except RuntimeError:
                # 如果没有运行中的事件循环，则可以直接使用 asyncio.run
                logger.debug("🔄 当前无事件循环，直接运行LLM调用")
                response = call_audiobook_llm_sync(
                    self.llm_client,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    response_format={"type": "json_object"},
                    use_cache=True,  # 启用缓存，相同名字不重复调用
                    timeout_seconds=30,
                )
            
            # 解析JSON
            result = parse_llm_json_object(response)
            logger.debug(f"🤖 LLM响应解析结果: {result}")
            
            # 验证结果
            if result.get("gender") and result.get("age_group"):
                # 只返回高置信度的结果
                confidence = float(result.get("confidence", 0.5))
                if confidence >= 0.7:
                    gender = str(result.get("gender") or "").strip().lower()
                    age_group = str(result.get("age_group") or "").strip().lower()
                    personality = str(result.get("personality") or "calm").strip().lower()

                    if age_group in ("middle", "mid"):
                        age_group = "adult"
                    elif age_group in ("teen", "teenager", "adolescent"):
                        age_group = "young"

                    traits = {}
                    if gender in ("male", "female"):
                        traits["gender"] = gender
                    if age_group in ("child", "young", "adult", "elder"):
                        traits["age_group"] = age_group
                    if personality in ("calm", "energetic", "gentle", "serious"):
                        traits["personality"] = personality

                    logger.info(f"🤖 LLM成功推断角色特征: {traits} (置信度: {confidence:.2f})")
                    return traits or None
                else:
                    logger.info(f"📊 LLM置信度较低 ({confidence:.2f})，回退到规则推断")
            
            return None
            
        except (json.JSONDecodeError, LLMJsonParseError) as e:
            logger.warning(f"⚠️ LLM返回非JSON格式: {e}")
            return None
        except Exception as e:
            logger.warning(f"🤖 LLM推断失败: {e}")
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

    def analyze_chapter_characters(
        self,
        script_segments,
        known_characters: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """从章节剧本片段中分析提取角色特征（两阶段分析）

        参考 Audible 项目的 chapter_analysis + character_extraction 流程：
        阶段1：从剧本对话和旁白中提取所有出现的人物及其上下文
        阶段2：使用 LLM 推断每个人的性别、年龄、性格等特征

        Args:
            script_segments: 剧本片段列表（ScriptSegment）
            known_characters: 已知角色信息 {角色名: {gender, age_group, ...}}

        Returns:
            角色特征字典 {角色名: {gender, age_group, personality, context, dialogue_count}}
        """
        if not script_segments:
            return {}

        from collections import defaultdict

        known_characters = known_characters or {}

        # === 阶段1：从片段中提取角色及其上下文 ===
        character_context: Dict[str, List[str]] = defaultdict(list)
        character_dialogue_count: Dict[str, int] = defaultdict(int)

        for seg in script_segments:
            speaker = getattr(seg, "speaker", "")
            if not speaker or speaker == "旁白":
                continue

            character_dialogue_count[speaker] += 1

            # 收集该角色的对话片段（最多 5 条作为上下文）
            text = getattr(seg, "text", "") or ""
            if text and len(character_context[speaker]) < 5:
                # 截取前 200 字
                character_context[speaker].append(text[:200])

        if not character_context:
            return {}

        # === 阶段2：LLM 批量推断角色特征 ===
        if not self.llm_client:
            logger.info("⚠️ 无 LLM 客户端，跳过章节角色分析，使用规则推断")
            result = {}
            for char_name in character_context:
                if char_name in known_characters:
                    result[char_name] = dict(known_characters[char_name])
                else:
                    rule_traits = self._rule_based_infer_traits(char_name)
                    if rule_traits:
                        result[char_name] = rule_traits
            return result

        # 构建 LLM 请求文本
        context_parts = []
        for char_name, snippets in character_context.items():
            if char_name in known_characters:
                continue
            snippets_text = "\n".join(f"  - {s}" for s in snippets[:3])
            context_parts.append(
                f"角色: {char_name}\n"
                f"  对话次数: {character_dialogue_count[char_name]}\n"
                f"  对话片段:\n{snippets_text}\n"
            )

        if not context_parts:
            logger.info("📖 所有角色已有特征信息，跳过 LLM 分析")
            result = {}
            for char_name in character_context:
                if char_name in known_characters:
                    result[char_name] = dict(known_characters[char_name])
            return result

        prompt = (
            "你是一位专业的有声书角色分析专家。请根据以下角色的对话片段，"
            "推断每个角色的性别、年龄段和性格特征。\n\n"
            "请严格按照 JSON 格式输出，不要添加任何解释性文字：\n"
            "{\n"
            '  "角色名": {"gender": "male|female|unknown", "age_group": "child|young|adult|elder", "personality": "calm|energetic|gentle|serious", "confidence": 0.0~1.0},\n'
            "  ...\n"
            "}\n\n"
            "判断依据：\n"
            "- 性别：从称呼（哥/姐/叔/姨等）、语气、用词判断\n"
            "- 年龄段：从自称（老夫/小子等）、语气成熟度、说话内容判断\n"
            "- 性格：从对话风格、语气强弱、情绪表现判断\n"
            "- confidence：置信度，0.0-1.0，基于对话片段的充分程度\n\n"
            "以下是需要分析的角色：\n\n"
        ) + "\n---\n".join(context_parts)

        try:
            response = call_audiobook_llm_sync(
                self.llm_client,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                response_format={"type": "json_object"},
                use_cache=False,
                timeout_seconds=60,
            )

            result = parse_llm_json_object(response)
            logger.info("🤖 章节角色分析完成，提取了 %d 个角色特征", len(result))

            output = {}
            for char_name, traits in result.items():
                if char_name in known_characters:
                    output[char_name] = dict(known_characters[char_name])
                    continue

                gender = str(traits.get("gender") or "").lower()
                age_group = str(traits.get("age_group") or "").lower()
                personality = str(traits.get("personality") or "").lower()
                confidence = float(traits.get("confidence", 0.5))

                if confidence < 0.6:
                    logger.debug("⚠️ '%s' LLM 置信度低 (%.2f)，回退到规则推断", char_name, confidence)
                    rule_traits = self._rule_based_infer_traits(char_name)
                    if rule_traits:
                        output[char_name] = rule_traits
                    continue

                valid_gender = gender if gender in ("male", "female", "unknown") else "unknown"
                valid_age = age_group if age_group in ("child", "young", "adult", "elder") else "young"
                valid_personality = personality if personality in ("calm", "energetic", "gentle", "serious") else "calm"

                if valid_age in ("middle", "mid"):
                    valid_age = "adult"
                elif valid_age in ("teen", "teenager", "adolescent"):
                    valid_age = "young"

                output[char_name] = {
                    "gender": valid_gender,
                    "age_group": valid_age,
                    "personality": valid_personality,
                    "confidence": confidence,
                    "dialogue_count": character_dialogue_count.get(char_name, 0),
                    "source": "chapter_analysis",
                }

            # 补充已有角色
            for char_name in character_context:
                if char_name not in output and char_name in known_characters:
                    output[char_name] = dict(known_characters[char_name])

            return output

        except (json.JSONDecodeError, LLMJsonParseError) as e:
            logger.warning("⚠️ 章节角色分析 LLM 返回非 JSON: %s", e)
            return self._fallback_rule_analysis(character_context, known_characters)
        except Exception as e:
            logger.warning("⚠️ 章节角色分析失败: %s，回退到规则推断", e)
            return self._fallback_rule_analysis(character_context, known_characters)

    def _fallback_rule_analysis(
        self,
        character_context: Dict[str, List[str]],
        known_characters: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """LLM 失败时的规则推断兜底"""
        output = {}
        for char_name in character_context:
            if char_name in known_characters:
                output[char_name] = dict(known_characters[char_name])
            else:
                rule_traits = self._rule_based_infer_traits(char_name)
                if rule_traits:
                    rule_traits["source"] = "rule_fallback"
                    output[char_name] = rule_traits

        return output
    
    def _create_profile(
        self,
        character_name: str,
        voice_id: str,
        voice_config: Dict[str, Any],
        tts_model: Optional[str] = None,
    ) -> VoiceProfile:
        """创建音色档案
        
        Args:
            tts_model: 🆕 适用的TTS模型（可选，默认从voice_config获取或使用默认值）
        """
        return VoiceProfile(
            voice_id=voice_id,
            character_name=character_name,
            gender=voice_config["gender"],
            age_group=voice_config["age_group"],
            personality=voice_config["personality"],
            tts_model=tts_model or voice_config.get("tts_model", "qwen3-tts-instruct-flash"),
            tts_speaker_id=voice_config["tts_speaker_id"],
            pitch_base=voice_config["pitch_base"],
            speed_base=voice_config["speed_base"],
            volume_base=voice_config["volume_base"],
            default_emotion=voice_config.get("default_emotion", "neutral")
        )
    
    def get_narrator_voice(self) -> VoiceProfile:
        """获取旁白音色"""
        if "旁白" not in self.character_voices:
            voice_config = self.PRESET_VOICES["male_narrator"]  # 修复：使用正确的key
            self.character_voices["旁白"] = self._create_profile(
                "旁白",
                "male_narrator",
                voice_config
            )
        return self.character_voices["旁白"]
    
    def get_voice(self, character_name: str) -> Optional[VoiceProfile]:
        """获取角色音色"""
        return self.character_voices.get(character_name)
    
    def apply_project_voice_mapping(
        self,
        voice_mapping: Dict[str, Any],
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ):
        """应用项目级的角色音配置（用户配置优先）

        voice_mapping 结构示例:
        {
            "角色名": {
                "voice_id": "male_young_energetic",
                "volume": 60,
                "tts_model": "cosyvoice-v3.5-plus"  # 🆕 可选，指定TTS模型
            }
        }
        
        Args:
            voice_mapping: 用户配置的音色映射
            character_profiles: 🆕 完整角色档案（用于增强音色profile信息和模型推荐）
        """
        if not voice_mapping:
            return
        
        # 🆕 构建角色档案索引，方便快速查找
        profile_index = {}
        if character_profiles:
            for cp in character_profiles:
                profile_index[cp.get("name", "")] = cp

        # 🆕 导入模型推荐函数
        try:
            from .voice_manager_factory import suggest_model_for_character
        except ImportError:
            suggest_model_for_character = None

        for character_name, config in voice_mapping.items():
            if not isinstance(config, dict):
                continue

            voice_id = config.get("voice_id")
            if not voice_id:
                # 未显式配置音色，保留为自动分配
                continue

            # 🆕 确定TTS模型：用户配置 > 智能推荐 > 默认值
            tts_model = config.get("tts_model")
            if not tts_model and suggest_model_for_character:
                char_profile = profile_index.get(character_name)
                tts_model = suggest_model_for_character(
                    character_profile=char_profile,
                    cost_priority="balanced",
                )
            if not tts_model:
                tts_model = DEFAULT_AUDIOBOOK_TTS_MODEL
            tts_model = normalize_audiobook_tts_model(tts_model)

            resolved = self._resolve_voice_config_for_model(voice_id, tts_model)
            if not resolved:
                logger.warning(f"⚠️ 未知的voice_id/model组合: {voice_id} ({tts_model})，跳过角色 {character_name}")
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

            self._apply_voice_type_config(voice_config, config.get("voice_type"))
            
            voice_config["tts_model"] = tts_model

            profile = self._create_profile(character_name, voice_id, voice_config, tts_model=tts_model)
            if config.get("personality"):
                profile.personality = str(config["personality"])
            
            # 🆕 如果有角色档案，增强profile信息
            char_profile = profile_index.get(character_name)
            if char_profile:
                if char_profile.get('gender'):
                    profile.gender = char_profile['gender'].lower()
                if char_profile.get('age'):
                    age = char_profile['age']
                    if age < 12:
                        profile.age_group = "child"
                    elif age < 18:
                        profile.age_group = "teen"
                    elif age < 35:
                        profile.age_group = "young"
                    elif age < 60:
                        profile.age_group = "adult"
                    else:
                        profile.age_group = "elder"
            
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
    
    def load_from_db(self, voice_mapping: Dict[str, Any]):
        """从数据库加载音色映射
        
        Args:
            voice_mapping: 从数据库读取的voice_mapping字段（JSON格式）
        """
        if not voice_mapping:
            return
        
        for character_name, config in voice_mapping.items():
            if not isinstance(config, dict):
                continue
            
            voice_id = config.get("voice_id")
            if not voice_id:
                continue
            
            tts_model = normalize_audiobook_tts_model(config.get("tts_model") or DEFAULT_AUDIOBOOK_TTS_MODEL)
            resolved = self._resolve_voice_config_for_model(voice_id, tts_model)
            if not resolved:
                continue
            
            resolved_voice_id, preset = resolved
            voice_config = dict(preset)
            
            # 🆕 恢复TTS模型（如果数据库中有记录）
            voice_config["tts_model"] = tts_model
            
            # 恢复音量、语速、音高
            if config.get("volume") is not None:
                voice_config["volume_base"] = config["volume"]
            if config.get("speed") is not None:
                voice_config["speed_base"] = config["speed"]
            if config.get("pitch") is not None:
                voice_config["pitch_base"] = config["pitch"]

            self._apply_voice_type_config(voice_config, config.get("voice_type"))
            
            profile = self._create_profile(
                character_name, 
                resolved_voice_id, 
                voice_config, 
                tts_model=tts_model,
            )
            
            # 恢复角色档案信息
            if config.get("gender"):
                profile.gender = config["gender"]
            if config.get("age_group"):
                profile.age_group = config["age_group"]
            if config.get("role_type"):
                profile.role_type = config["role_type"]
            if config.get("personality"):
                profile.personality = config["personality"]
            
            self.character_voices[character_name] = profile
            self.used_voice_ids.add(resolved_voice_id)
        
        logger.info(f"📂 从数据库加载音色映射: {len(self.character_voices)} 个角色")
    
    def export_to_db(self) -> Dict[str, Any]:
        """导出当前音色分配到数据库格式
        
        Returns:
            可用于保存到数据库的voice_mapping字典
        """
        mapping = {}
        for character_name, profile in self.character_voices.items():
            mapping[character_name] = {
                "voice_id": profile.voice_id,
                "volume": profile.volume_base,
                "speed": profile.speed_base,
                "pitch": profile.pitch_base,
                "gender": profile.gender if profile.gender != "unknown" else None,
                "age_group": profile.age_group if profile.age_group != "unknown" else None,
                "role_type": getattr(profile, 'role_type', None),
                "personality": profile.personality,
                "tts_model": profile.tts_model if profile.tts_model != "qwen3-tts-instruct-flash" else None,  # 🆕 TTS模型
            }
        return mapping
    
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


