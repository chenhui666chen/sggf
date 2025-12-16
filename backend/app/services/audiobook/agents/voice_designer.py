"""
VoiceDesigner - 角色音色设计师Agent

核心职责：
1. 为每个角色设计差异化的声音特征
2. 确保角色间音色可区分性
3. 提供TTS参数配置
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VoiceCharacteristics:
    """声音特征"""
    age_range: str = "25-35岁"
    gender: str = "neutral"
    tone: str = "中性"  # 低沉/清亮/沙哑/甜美等
    speaking_pace: str = "中速"  # 慢速/中速/快速
    accent: str = "标准普通话"
    emotional_range: List[str] = field(default_factory=lambda: ["neutral"])
    voice_quality: str = "清晰"  # 清晰/沙哑/磁性/活泼


@dataclass
class TTSParams:
    """TTS参数"""
    speaker: str = "zhixiaobao"  # 音色ID
    pitch: int = 50  # 音调 (0-100)
    speed: float = 1.0  # 语速 (0.5-2.0)
    volume: int = 50  # 音量 (0-100)
    emotion: str = "neutral"  # 情感标签


@dataclass
class VoiceProfile:
    """完整的角色音色档案"""
    character_name: str
    voice_characteristics: VoiceCharacteristics
    tts_params: TTSParams
    voice_description: str = ""
    sample_texts: List[str] = field(default_factory=list)
    differentiation_notes: str = ""  # 与其他角色的区分点


class VoiceDesigner:
    """
    角色音色设计师Agent
    
    基于角色性格、年龄、背景设计差异化的声音特征
    """
    
    def __init__(self):
        self.voice_profiles: Dict[str, VoiceProfile] = {}
        
        # 预设音色库（阿里云TTS可用音色）
        self.available_voices = {
            "zhixiaobao": {"gender": "female", "age": "child", "tone": "活泼"},
            "zhiyan": {"gender": "female", "age": "young_adult", "tone": "甜美"},
            "zhimiao": {"gender": "female", "age": "adult", "tone": "温柔"},
            "zhixiaomei": {"gender": "female", "age": "adult", "tone": "清亮"},
            "aixia": {"gender": "female", "age": "adult", "tone": "知性"},
            "aitong": {"gender": "female", "age": "child", "tone": "可爱"},
            
            "zhichu": {"gender": "male", "age": "young_adult", "tone": "阳光"},
            "zhitian": {"gender": "male", "age": "adult", "tone": "稳重"},
            "zhixiaoxue": {"gender": "male", "age": "adult", "tone": "磁性"},
            "aixiang": {"gender": "male", "age": "adult", "tone": "成熟"},
        }
    
    def design_voice(
        self,
        character_info: Dict[str, Any]
    ) -> VoiceProfile:
        """
        为角色设计音色
        
        Args:
            character_info: 角色信息
                {
                    "name": "角色名",
                    "gender": "male/female",
                    "age": 25,
                    "personality": "冷静、理性",
                    "background": "科研人员",
                    "role": "主角/配角"
                }
        
        Returns:
            音色档案
        """
        character_name = character_info.get("name", "未知角色")
        logger.info(f"🎙️ 为角色 {character_name} 设计音色...")
        
        # 1. 确定声音特征
        characteristics = self._determine_characteristics(character_info)
        
        # 2. 匹配TTS参数
        tts_params = self._match_tts_params(characteristics, character_info)
        
        # 3. 生成描述
        description = self._generate_description(characteristics, character_info)
        
        # 4. 生成示例文本
        sample_texts = self._generate_sample_texts(character_info)
        
        # 5. 确保差异化
        differentiation_notes = self._ensure_differentiation(character_name, characteristics)
        
        profile = VoiceProfile(
            character_name=character_name,
            voice_characteristics=characteristics,
            tts_params=tts_params,
            voice_description=description,
            sample_texts=sample_texts,
            differentiation_notes=differentiation_notes
        )
        
        self.voice_profiles[character_name] = profile
        logger.info(f"   ✅ 音色设计完成: {tts_params.speaker}")
        
        return profile
    
    def _determine_characteristics(
        self,
        character_info: Dict[str, Any]
    ) -> VoiceCharacteristics:
        """确定声音特征"""
        gender = character_info.get("gender", "neutral")
        age = character_info.get("age", 30)
        personality = character_info.get("personality", "")
        
        # 年龄段映射
        if age < 12:
            age_range = "儿童"
        elif age < 20:
            age_range = "青少年"
        elif age < 35:
            age_range = "青年"
        elif age < 50:
            age_range = "中年"
        else:
            age_range = "老年"
        
        # 音色推断
        tone = "中性"
        if "冷静" in personality or "理性" in personality:
            tone = "低沉稳重"
        elif "活泼" in personality or "开朗" in personality:
            tone = "清亮明快"
        elif "温柔" in personality:
            tone = "温柔甜美"
        elif "强势" in personality or "霸道" in personality:
            tone = "磁性有力"
        
        # 语速推断
        pace = "中速"
        if "急躁" in personality:
            pace = "快速"
        elif "沉稳" in personality or "老成" in personality:
            pace = "慢速"
        
        return VoiceCharacteristics(
            age_range=age_range,
            gender=gender,
            tone=tone,
            speaking_pace=pace,
            accent="标准普通话",
            emotional_range=["neutral", "calm", "tense"],
            voice_quality="清晰"
        )
    
    def _match_tts_params(
        self,
        characteristics: VoiceCharacteristics,
        character_info: Dict[str, Any]
    ) -> TTSParams:
        """匹配TTS参数"""
        gender = characteristics.gender
        age_range = characteristics.age_range
        
        # 选择音色
        speaker = "zhitian"  # 默认
        if gender == "female":
            if "儿童" in age_range:
                speaker = "zhixiaobao"
            elif "青年" in age_range:
                speaker = "zhiyan"
            else:
                speaker = "zhimiao"
        else:  # male
            if "青年" in age_range:
                speaker = "zhichu"
            else:
                speaker = "zhitian"
        
        # 音调
        pitch = 50
        if "低沉" in characteristics.tone:
            pitch = 40
        elif "清亮" in characteristics.tone:
            pitch = 60
        
        # 语速
        speed = 1.0
        if "快速" in characteristics.speaking_pace:
            speed = 1.2
        elif "慢速" in characteristics.speaking_pace:
            speed = 0.8
        
        return TTSParams(
            speaker=speaker,
            pitch=pitch,
            speed=speed,
            volume=50,
            emotion="neutral"
        )
    
    def _generate_description(
        self,
        characteristics: VoiceCharacteristics,
        character_info: Dict[str, Any]
    ) -> str:
        """生成音色描述"""
        name = character_info.get("name", "角色")
        gender_desc = "男性" if characteristics.gender == "male" else "女性"
        
        description = (
            f"{name}的声音：{gender_desc}，{characteristics.age_range}，"
            f"音色{characteristics.tone}，语速{characteristics.speaking_pace}。"
            f"适合表现{character_info.get('personality', '普通')}的性格特质。"
        )
        
        return description
    
    def _generate_sample_texts(
        self,
        character_info: Dict[str, Any]
    ) -> List[str]:
        """生成示例文本（用于试音）"""
        name = character_info.get("name", "我")
        
        samples = [
            f"你好，我是{name}。",
            f"这件事我需要仔细考虑一下。",
            f"不，这不可能！",
        ]
        
        return samples
    
    def _ensure_differentiation(
        self,
        character_name: str,
        new_characteristics: VoiceCharacteristics
    ) -> str:
        """确保与其他角色的差异化"""
        notes = []
        
        for existing_name, existing_profile in self.voice_profiles.items():
            existing_char = existing_profile.voice_characteristics
            
            # 检查是否过于相似
            if (new_characteristics.gender == existing_char.gender and
                new_characteristics.age_range == existing_char.age_range and
                new_characteristics.tone == existing_char.tone):
                
                notes.append(
                    f"与 {existing_name} 音色相似，建议调整语速或音调以区分"
                )
        
        if notes:
            return "; ".join(notes)
        else:
            return "音色差异明显，易于区分"
    
    def batch_design(
        self,
        characters: List[Dict[str, Any]]
    ) -> Dict[str, VoiceProfile]:
        """批量设计角色音色"""
        logger.info(f"🎙️ 批量设计 {len(characters)} 个角色的音色...")
        
        profiles = {}
        for char_info in characters:
            profile = self.design_voice(char_info)
            profiles[char_info["name"]] = profile
        
        logger.info(f"   ✅ 完成 {len(profiles)} 个角色的音色设计")
        
        return profiles
    
    def get_voice_profile(self, character_name: str) -> Optional[VoiceProfile]:
        """获取角色音色档案"""
        return self.voice_profiles.get(character_name)
    
    def get_tts_params(
        self,
        character_name: str,
        emotion: str = "neutral"
    ) -> Optional[TTSParams]:
        """获取TTS参数（带情感调整）"""
        profile = self.voice_profiles.get(character_name)
        if not profile:
            return None
        
        params = profile.tts_params
        # 根据情感调整参数
        adjusted_params = TTSParams(
            speaker=params.speaker,
            pitch=params.pitch,
            speed=params.speed,
            volume=params.volume,
            emotion=emotion
        )
        
        # 情感调整
        if emotion == "angry":
            adjusted_params.pitch += 10
            adjusted_params.volume += 10
        elif emotion == "sad":
            adjusted_params.pitch -= 10
            adjusted_params.speed *= 0.9
        elif emotion == "excited":
            adjusted_params.speed *= 1.2
            adjusted_params.pitch += 5
        
        return adjusted_params
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_voices": len(self.voice_profiles),
            "gender_distribution": self._count_by_gender(),
            "age_distribution": self._count_by_age(),
            "voice_list": list(self.voice_profiles.keys())
        }
    
    def _count_by_gender(self) -> Dict[str, int]:
        """按性别统计"""
        counts = {"male": 0, "female": 0, "neutral": 0}
        for profile in self.voice_profiles.values():
            gender = profile.voice_characteristics.gender
            counts[gender] = counts.get(gender, 0) + 1
        return counts
    
    def _count_by_age(self) -> Dict[str, int]:
        """按年龄段统计"""
        counts = {}
        for profile in self.voice_profiles.values():
            age_range = profile.voice_characteristics.age_range
            counts[age_range] = counts.get(age_range, 0) + 1
        return counts
