"""MiniMax Speech 2.8 声音管理器

继承 VoiceManager 基类，处理 MiniMax 语音模型的音色选择和管理。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .tts_model_ids import MINIMAX_SPEECH_28_HD_MODEL, normalize_audiobook_tts_model
from .minimax_voice_clone_client import is_minimax_custom_voice_id
from .voice_manager import VoiceManager, VoiceProfile
from .voice_catalog import load_voice_catalog_for_model

logger = logging.getLogger(__name__)


class MiniMaxVoiceManager(VoiceManager):
    """MiniMax Speech 2.8 声音管理器
    
    处理 MiniMax Speech 2.8 系列模型的音色选择和管理：
    - speech-2.8-hd: 最高音质（600积分/万字符）
    - speech-2.8-turbo: 优秀音质（300积分/万字符）
    
    特性：
    1. 20种预设音色
    2. 7种情感控制（happy/sad/angry/fearful/disgusted/surprised/calm）
    3. 19种语气词标签（(laughs)/(sighs)/(gasps)等）
    4. 混合音色（最多4种按比例混合）
    """
    DEFAULT_NARRATOR_VOICE_ID = "male-qn-qingse"
    DEFAULT_FEMALE_VOICE_ID = "female-shaonv"

    def __init__(self, model: str = MINIMAX_SPEECH_28_HD_MODEL):
        super().__init__()
        self.model = normalize_audiobook_tts_model(model)
        self.voice_catalog = None
        self._load_catalog()
        logger.info("MiniMax VoiceManager initialized with %s voices", len(self.voice_catalog.get("voices", [])))

    def _load_catalog(self):
        """加载 MiniMax 音色目录"""
        try:
            self.voice_catalog = load_voice_catalog_for_model(self.model)
        except Exception as e:
            logger.warning("Failed to load MiniMax voice catalog: %s", e)
            self.voice_catalog = {"voices": [], "voices_by_id": {}}

    def get_voices(self) -> List[Dict[str, Any]]:
        """获取 MiniMax 支持的音色列表"""
        return self.voice_catalog.get("voices", [])

    def get_voice_entry(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """获取指定音色信息"""
        return self.voice_catalog.get("voices_by_id", {}).get(voice_id)

    def _build_profile(
        self,
        character_name: str,
        voice_id: str,
        voice_config: Optional[Dict[str, Any]] = None,
    ) -> VoiceProfile:
        entry = self.get_voice_entry(voice_id)
        if entry is None and is_minimax_custom_voice_id(voice_id):
            entry = {
                "id": voice_id,
                "speaker": voice_id,
                "gender": "neutral",
                "category": "custom",
                "style": "cloned",
                "default_params": {"pitch": 0, "speed": 1.0, "volume": 50},
            }
        entry = entry or self.get_voice_entry(self.DEFAULT_NARRATOR_VOICE_ID)
        if not entry:
            raise ValueError("MiniMax voice catalog is empty")

        defaults = entry.get("default_params") or {}
        config = voice_config or {}
        profile_config = {
            "pitch_base": int(config.get("pitch", defaults.get("pitch", 50)) or 50),
            "speed_base": float(config.get("speed", defaults.get("speed", 1.0)) or 1.0),
            "volume_base": int(config.get("volume", defaults.get("volume", 50)) or 50),
            "default_emotion": "calm",
        }
        self._apply_voice_type_config(profile_config, config.get("voice_type"))
        return VoiceProfile(
            voice_id=str(entry.get("id") or voice_id),
            character_name=character_name,
            gender=str(entry.get("gender") or "neutral").lower(),
            age_group=str(entry.get("category") or "adult"),
            personality=str(config.get("personality") or entry.get("style") or "calm"),
            tts_model=self.model,
            tts_speaker_id=str(entry.get("speaker") or entry.get("id") or voice_id),
            pitch_base=profile_config["pitch_base"],
            speed_base=profile_config["speed_base"],
            volume_base=profile_config["volume_base"],
            default_emotion=profile_config["default_emotion"],
        )

    def get_narrator_voice(self) -> VoiceProfile:
        """鑾峰彇 MiniMax 鏃佺櫧闊宠壊"""
        if "旁白" not in self.character_voices:
            self.character_voices["旁白"] = self._build_profile("旁白", self.DEFAULT_NARRATOR_VOICE_ID)
        return self.character_voices["旁白"]

    def get_voice(self, character_name: str) -> Optional[VoiceProfile]:
        """鑾峰彇瑙掕壊闊宠壊妗ｆ"""
        return self.character_voices.get(character_name)

    def assign_voice(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
    ) -> VoiceProfile:
        """涓鸿鑹插垎閰?MiniMax 闊宠壊妗ｆ"""
        voice_id = self.select_voice_for_character(character_name, character_info)
        profile = self._build_profile(character_name, voice_id)
        self.character_voices[character_name] = profile
        self.used_voice_ids.add(profile.voice_id)
        return profile

    def apply_project_voice_mapping(
        self,
        voice_mapping: Dict[str, Any],
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ):
        """搴旂敤椤圭洰绾?MiniMax 闊宠壊鏄犲皠"""
        del character_profiles
        for character_name, raw_config in (voice_mapping or {}).items():
            if not character_name:
                continue
            config = raw_config if isinstance(raw_config, dict) else {"voice_id": raw_config}
            voice_id = str(config.get("voice_id") or config.get("speaker") or "").strip()
            if not voice_id or not self.validate_voice(voice_id):
                voice_id = self.select_voice_for_character(str(character_name))
            profile = self._build_profile(str(character_name), voice_id, config)
            self.character_voices[str(character_name)] = profile
            self.used_voice_ids.add(profile.voice_id)

    def select_voice_for_character(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """为角色选择合适的音色
        
        基于角色名称和特征信息选择最匹配的 MiniMax 音色
        
        Args:
            character_name: 角色名称
            character_info: 角色特征信息（如性别、年龄等）
        
        Returns:
            音色ID
        """
        character_info = character_info or {}
        gender = (character_info.get("gender") or "").lower()
        age_group = (character_info.get("age_group") or "").lower()
        
        voices = self.get_voices()
        candidates = []
        
        # 筛选匹配音色的候选人
        for voice in voices:
            voice_gender = (voice.get("gender") or "").lower()
            voice_style = (voice.get("style") or "").lower()
            
            # 性别匹配优先
            if gender and voice_gender and gender != voice_gender:
                continue
            
            # 年龄组匹配
            if age_group:
                voice_category = (voice.get("category") or "").lower()
                if age_group in ["young", "youth"] and voice_style in ["young", "youthful", "energetic"]:
                    candidates.append((voice, 2))
                elif age_group in ["adult", "mature"] and voice_style in ["mature", "elegant", "standard"]:
                    candidates.append((voice, 2))
                elif age_group in ["old", "elderly"] and voice_style in ["elderly"]:
                    candidates.append((voice, 2))
                else:
                    candidates.append((voice, 1))
            else:
                candidates.append((voice, 1))
        
        # 按匹配分数排序，返回最佳匹配
        if candidates:
            candidate_pool = [
                candidate for candidate in candidates
                if candidate[0].get("id") not in self.used_voice_ids
            ] or candidates
            candidate_pool.sort(key=lambda x: x[1], reverse=True)
            best_voice = candidate_pool[0][0]
            logger.info(
                f"Selected MiniMax voice '{best_voice['id']}' for character '{character_name}' "
                f"(gender={gender}, age_group={age_group})"
            )
            return best_voice["id"]
        
        # 默认返回标准音色
        default_voice = self.DEFAULT_NARRATOR_VOICE_ID if gender != "female" else self.DEFAULT_FEMALE_VOICE_ID
        logger.warning(
            f"No matching MiniMax voice for character '{character_name}', using default: {default_voice}"
        )
        return default_voice

    def validate_voice(self, voice_id: str) -> bool:
        """验证音色ID是否有效"""
        return voice_id in self.voice_catalog.get("voices_by_id", {}) or is_minimax_custom_voice_id(voice_id)

    def get_supported_emotions(self) -> List[str]:
        """获取 MiniMax 支持的情感列表"""
        return ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm"]

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "model": self.model,
            "voices": self.get_voices(),
            "emotions": self.get_supported_emotions(),
            "supports_ssml": True,
            "supports_interjections": True,
            "supports_voice_mixing": True,
            "max_mix_voices": 4,
        }
