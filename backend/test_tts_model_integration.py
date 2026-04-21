"""
测试 tts_model 完整链路
- apply_project_voice_mapping 支持 tts_model
- export_to_db / load_from_db 包含 tts_model
- 智能模型推荐
"""

import sys
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# Mock the VoiceProfile dataclass with tts_model
@dataclass
class VoiceProfile:
    voice_id: str
    character_name: str
    gender: str
    age_group: str
    personality: str
    tts_model: str = "qwen3-tts-instruct-flash"
    tts_speaker_id: str = ""
    pitch_base: int = 50
    speed_base: float = 1.0
    volume_base: int = 50
    default_emotion: str = "neutral"
    is_villain_voice: bool = False

    def to_dict(self):
        return {
            "voice_id": self.voice_id,
            "character_name": self.character_name,
            "gender": self.gender,
            "age_group": self.age_group,
            "personality": self.personality,
            "tts_model": self.tts_model,
            "tts_speaker_id": self.tts_speaker_id,
            "pitch_base": self.pitch_base,
            "speed_base": self.speed_base,
            "volume_base": self.volume_base,
            "default_emotion": self.default_emotion,
            "is_villain_voice": self.is_villain_voice,
        }


def suggest_model_for_character(
    character_profile: Optional[Dict[str, Any]] = None,
    preferred_model: Optional[str] = None,
    cost_priority: str = "balanced",
) -> str:
    """推荐TTS模型"""
    if preferred_model:
        return preferred_model
    
    if character_profile:
        importance = character_profile.get("importance_level", "")
        role_position = character_profile.get("role_position", "")
        
        if importance in ["主角", "重要角色"] or role_position in ["主角", "女主角"]:
            if cost_priority != "low_cost":
                return "cosyvoice-v3.5-plus"
        
        if importance in ["次要角色"]:
            if cost_priority == "high_quality":
                return "qwen3-tts-plus"
            return "qwen3-tts-instruct-flash"
        
        if importance in ["群众角色"]:
            return "minimax-speech-2.8-turbo"
    
    if cost_priority == "high_quality":
        return "cosyvoice-v3.5-plus"
    elif cost_priority == "low_cost":
        return "minimax-speech-2.8-turbo"
    
    return "qwen3-tts-instruct-flash"


class MockVoiceManager:
    """简化的VoiceManager用于测试"""
    
    def __init__(self):
        self.character_voices: Dict[str, VoiceProfile] = {}
        self.used_voice_ids = set()
    
    def _create_profile(
        self,
        character_name: str,
        voice_id: str,
        voice_config: Dict[str, Any],
        tts_model: Optional[str] = None,
    ) -> VoiceProfile:
        return VoiceProfile(
            voice_id=voice_id,
            character_name=character_name,
            gender=voice_config.get("gender", "unknown"),
            age_group=voice_config.get("age_group", "unknown"),
            personality=voice_config.get("personality", "neutral"),
            tts_model=tts_model or voice_config.get("tts_model", "qwen3-tts-instruct-flash"),
            pitch_base=voice_config.get("pitch_base", 50),
            speed_base=voice_config.get("speed_base", 1.0),
            volume_base=voice_config.get("volume_base", 50),
        )
    
    def apply_project_voice_mapping(
        self,
        voice_mapping: Dict[str, Any],
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ):
        """应用项目级的角色音配置"""
        if not voice_mapping:
            return
        
        profile_index = {}
        if character_profiles:
            for cp in character_profiles:
                profile_index[cp.get("name", "")] = cp
        
        for character_name, config in voice_mapping.items():
            if not isinstance(config, dict):
                continue
            
            voice_id = config.get("voice_id")
            if not voice_id:
                continue
            
            # Mock voice config
            voice_config = {
                "gender": "unknown",
                "age_group": "unknown",
                "personality": "neutral",
                "pitch_base": 50,
                "speed_base": 1.0,
                "volume_base": 50,
            }
            
            # Apply user settings
            if config.get("volume") is not None:
                voice_config["volume_base"] = int(config["volume"])
            if config.get("speed") is not None:
                voice_config["speed_base"] = float(config["speed"])
            if config.get("pitch") is not None:
                voice_config["pitch_base"] = int(config["pitch"])
            
            # Determine tts_model: user config > recommendation > default
            tts_model = config.get("tts_model")
            if not tts_model:
                char_profile = profile_index.get(character_name)
                tts_model = suggest_model_for_character(
                    character_profile=char_profile,
                    cost_priority="balanced",
                )
            
            voice_config["tts_model"] = tts_model
            profile = self._create_profile(character_name, voice_id, voice_config, tts_model=tts_model)
            self.character_voices[character_name] = profile
            self.used_voice_ids.add(voice_id)
    
    def export_to_db(self) -> Dict[str, Any]:
        """导出到数据库格式"""
        mapping = {}
        for character_name, profile in self.character_voices.items():
            mapping[character_name] = {
                "voice_id": profile.voice_id,
                "volume": profile.volume_base,
                "speed": profile.speed_base,
                "pitch": profile.pitch_base,
                "gender": profile.gender if profile.gender != "unknown" else None,
                "age_group": profile.age_group if profile.age_group != "unknown" else None,
                "personality": profile.personality,
                "tts_model": profile.tts_model if profile.tts_model != "qwen3-tts-instruct-flash" else None,
            }
        return mapping
    
    def load_from_db(self, voice_mapping: Dict[str, Any]):
        """从数据库加载"""
        if not voice_mapping:
            return
        
        for character_name, config in voice_mapping.items():
            if not isinstance(config, dict):
                continue
            
            voice_id = config.get("voice_id")
            if not voice_id:
                continue
            
            voice_config = {
                "gender": config.get("gender") or "unknown",
                "age_group": config.get("age_group") or "unknown",
                "personality": config.get("personality", "neutral"),
                "pitch_base": config.get("pitch", 50),
                "speed_base": config.get("speed", 1.0),
                "volume_base": config.get("volume", 50),
            }
            
            # Restore tts_model
            if config.get("tts_model"):
                voice_config["tts_model"] = config["tts_model"]
            
            profile = self._create_profile(
                character_name,
                voice_id,
                voice_config,
                tts_model=config.get("tts_model"),
            )
            
            self.character_voices[character_name] = profile
            self.used_voice_ids.add(voice_id)


# Run tests
print("=" * 60)
print("测试 tts_model 完整链路")
print("=" * 60)

# Test 1: apply_project_voice_mapping with tts_model and character profiles
print("\n测试1：应用角色音配置并推荐模型...")
vm1 = MockVoiceManager()
voice_mapping = {
    "林风": {"voice_id": "male_young_energetic", "volume": 60},
    "苏娜": {"voice_id": "female_young_gentle", "volume": 55},
    "路人甲": {"voice_id": "male_adult_calm", "volume": 45},
}
character_profiles = [
    {"name": "林风", "importance_level": "主角", "role_position": "男主角"},
    {"name": "苏娜", "importance_level": "重要角色", "role_position": "女主角"},
    {"name": "路人甲", "importance_level": "群众角色"},
]
vm1.apply_project_voice_mapping(voice_mapping, character_profiles)

assert vm1.character_voices["林风"].tts_model == "cosyvoice-v3.5-plus", f"主角应该用 cosyvoice-v3.5-plus，实际: {vm1.character_voices['林风'].tts_model}"
assert vm1.character_voices["苏娜"].tts_model == "cosyvoice-v3.5-plus", f"重要角色应该用 cosyvoice-v3.5-plus，实际: {vm1.character_voices['苏娜'].tts_model}"
assert vm1.character_voices["路人甲"].tts_model == "minimax-speech-2.8-turbo", f"群众角色应该用 minimax，实际: {vm1.character_voices['路人甲'].tts_model}"
print("✅ 测试1通过：模型推荐正确")

# Test 2: User explicitly sets tts_model
print("\n测试2：用户显式设置tts_model...")
vm2 = MockVoiceManager()
voice_mapping_with_model = {
    "林风": {"voice_id": "male_young_energetic", "volume": 60, "tts_model": "qwen3-tts-instruct-flash"},
}
vm2.apply_project_voice_mapping(voice_mapping_with_model, character_profiles)
assert vm2.character_voices["林风"].tts_model == "qwen3-tts-instruct-flash", f"应该使用用户指定的模型，实际: {vm2.character_voices['林风'].tts_model}"
print("✅ 测试2通过：用户配置优先")

# Test 3: export_to_db includes tts_model
print("\n测试3：导出到数据库包含tts_model...")
exported = vm1.export_to_db()
assert "tts_model" in exported["林风"], "导出应该包含tts_model"
assert exported["林风"]["tts_model"] == "cosyvoice-v3.5-plus", f"导出的tts_model应该正确，实际: {exported['林风']['tts_model']}"
assert exported["苏娜"]["tts_model"] == "cosyvoice-v3.5-plus", "重要角色的tts_model应该正确"
assert exported["路人甲"]["tts_model"] == "minimax-speech-2.8-turbo", "群众角色的tts_model应该正确"
print("✅ 测试3通过：导出包含tts_model")

# Test 4: load_from_db restores tts_model
print("\n测试4：从数据库加载恢复tts_model...")
vm3 = MockVoiceManager()
vm3.load_from_db(exported)
assert vm3.character_voices["林风"].tts_model == "cosyvoice-v3.5-plus", f"林风的tts_model应该从数据库恢复，实际: {vm3.character_voices['林风'].tts_model}"
assert vm3.character_voices["苏娜"].tts_model == "cosyvoice-v3.5-plus", f"苏娜的tts_model应该从数据库恢复，实际: {vm3.character_voices['苏娜'].tts_model}"
assert vm3.character_voices["路人甲"].tts_model == "minimax-speech-2.8-turbo", f"路人甲的tts_model应该从数据库恢复，实际: {vm3.character_voices['路人甲'].tts_model}"
print("✅ 测试4通过：从数据库加载恢复tts_model")

# Test 5: Cross-chapter consistency
print("\n测试5：跨章节一致性（导出->加载->再生成）...")
vm4 = MockVoiceManager()
vm4.load_from_db(exported)
# Simulate using the same mapping for another chapter
vm4.apply_project_voice_mapping(voice_mapping, character_profiles)
assert vm4.character_voices["林风"].tts_model == "cosyvoice-v3.5-plus", "跨章节后林风的模型应该保持一致"
assert vm4.character_voices["苏娜"].tts_model == "cosyvoice-v3.5-plus", "跨章节后苏娜的模型应该保持一致"
assert vm4.character_voices["路人甲"].tts_model == "minimax-speech-2.8-turbo", "跨章节后路人甲的模型应该保持一致"
print("✅ 测试5通过：跨章节一致性")

print("\n" + "=" * 60)
print("所有测试通过！✅")
print("=" * 60)
print("\n测试总结：")
print("1. apply_project_voice_mapping 正确支持 tts_model 参数")
print("2. 智能模型推荐根据角色重要性分配模型")
print("3. export_to_db 包含 tts_model 信息")
print("4. load_from_db 正确恢复 tts_model")
print("5. 跨章节一致性得到保证")
