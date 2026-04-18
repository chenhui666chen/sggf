"""MiniMax Speech 2.8 声音管理器

继承 VoiceManager 基类，处理 MiniMax 语音模型的音色选择和管理。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .voice_manager import VoiceManager
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
    
    def __init__(self):
        super().__init__()
        self.model = "minimax-speech-2.8"
        self.voice_catalog = None
        self._load_catalog()
        logger.info("MiniMax VoiceManager initialized with %s voices", len(self.voice_catalog.get("voices", [])))

    def _load_catalog(self):
        """加载 MiniMax 音色目录"""
        try:
            self.voice_catalog = load_voice_catalog_for_model("minimax-speech-2.8-hd")
        except Exception as e:
            logger.warning("Failed to load MiniMax voice catalog: %s", e)
            self.voice_catalog = {"voices": [], "voices_by_id": {}}

    def get_voices(self) -> List[Dict[str, Any]]:
        """获取 MiniMax 支持的音色列表"""
        return self.voice_catalog.get("voices", [])

    def get_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """获取指定音色信息"""
        return self.voice_catalog.get("voices_by_id", {}).get(voice_id)

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
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_voice = candidates[0][0]
            logger.info(
                f"Selected MiniMax voice '{best_voice['id']}' for character '{character_name}' "
                f"(gender={gender}, age_group={age_group})"
            )
            return best_voice["id"]
        
        # 默认返回标准音色
        default_voice = "male-qingnian" if gender == "male" else "female-qingnian"
        logger.warning(
            f"No matching MiniMax voice for character '{character_name}', using default: {default_voice}"
        )
        return default_voice

    def validate_voice(self, voice_id: str) -> bool:
        """验证音色ID是否有效"""
        return voice_id in self.voice_catalog.get("voices_by_id", {})

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