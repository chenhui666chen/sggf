"""
有声书音色持久化与跨章节一致性综合测试（独立版）

此测试不依赖完整的项目环境，直接测试核心逻辑
"""
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


# === Mock VoiceProfile 和 VoiceManager（复制实际实现的核心逻辑）===

@dataclass
class VoiceProfile:
    voice_id: str
    character_name: str
    gender: str = "unknown"
    age_group: str = "unknown"
    personality: str = "calm"
    tts_speaker_id: str = ""
    pitch_base: int = 50
    speed_base: float = 1.0
    volume_base: int = 50
    default_emotion: str = "neutral"
    is_villain_voice: bool = False
    role_type: str = ""


class MockVoiceManager:
    """模拟VoiceManager的核心功能"""
    
    def __init__(self):
        self.character_voices: Dict[str, VoiceProfile] = {}
        self.used_voice_ids = set()
    
    def _resolve_voice_config(self, voice_id: str):
        """模拟解析voice_id"""
        # 简单的映射，实际项目中会更复杂
        return (voice_id, {"volume_base": 50, "speed_base": 1.0, "pitch_base": 50})
    
    def _create_profile(self, character_name: str, voice_id: str, voice_config: Dict) -> VoiceProfile:
        """创建VoiceProfile"""
        return VoiceProfile(
            voice_id=voice_id,
            character_name=character_name,
            volume_base=voice_config.get("volume_base", 50),
            speed_base=voice_config.get("speed_base", 1.0),
            pitch_base=voice_config.get("pitch_base", 50),
        )
    
    def apply_project_voice_mapping(
        self,
        voice_mapping: Dict[str, Any],
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ):
        """应用项目级的角色音色配置（用户配置优先）"""
        if not voice_mapping:
            return
        
        # 🆕 构建角色档案索引
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

            resolved = self._resolve_voice_config(voice_id)
            if not resolved:
                continue
            resolved_voice_id, preset = resolved

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
    
    def load_from_db(self, voice_mapping: Dict[str, Any]):
        """从数据库加载音色映射"""
        if not voice_mapping:
            return
        
        for character_name, config in voice_mapping.items():
            if not isinstance(config, dict):
                continue
            
            voice_id = config.get("voice_id")
            if not voice_id:
                continue
            
            resolved = self._resolve_voice_config(voice_id)
            if not resolved:
                continue
            
            resolved_voice_id, preset = resolved
            voice_config = dict(preset)
            
            if config.get("volume") is not None:
                voice_config["volume_base"] = config["volume"]
            if config.get("speed") is not None:
                voice_config["speed_base"] = config["speed"]
            if config.get("pitch") is not None:
                voice_config["pitch_base"] = config["pitch"]
            
            profile = self._create_profile(character_name, resolved_voice_id, voice_config)
            
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
    
    def export_to_db(self) -> Dict[str, Any]:
        """导出当前音色分配到数据库格式"""
        mapping = {}
        for character_name, profile in self.character_voices.items():
            mapping[character_name] = {
                "voice_id": profile.voice_id,
                "volume": profile.volume_base,
                "speed": profile.speed_base,
                "pitch": profile.pitch_base,
                "gender": profile.gender if profile.gender != "unknown" else None,
                "age_group": profile.age_group if profile.age_group != "unknown" else None,
                "role_type": profile.role_type,
                "personality": profile.personality,
            }
        return mapping


# === 测试函数 ===

def test_1_apply_with_profiles():
    """测试1：apply_project_voice_mapping 接收角色档案"""
    print("\n" + "=" * 60)
    print("测试1：apply_project_voice_mapping 接收角色档案")
    print("=" * 60)
    
    vm = MockVoiceManager()
    voice_mapping = {
        "萧衍": {"voice_id": "Ryan", "volume": 60, "speed": 1.0, "pitch": 50},
        "苏清颜": {"voice_id": "Cherry", "volume": 55, "speed": 1.0, "pitch": 55}
    }
    character_profiles = [
        {"name": "萧衍", "gender": "男", "age": 25, "role": "主角方"},
        {"name": "苏清颜", "gender": "女", "age": 20, "role": "主角方"}
    ]
    
    vm.apply_project_voice_mapping(voice_mapping, character_profiles=character_profiles)
    
    assert "萧衍" in vm.character_voices
    assert vm.character_voices["萧衍"].gender == "男"
    assert vm.character_voices["萧衍"].age_group == "young"
    assert "苏清颜" in vm.character_voices
    assert vm.character_voices["苏清颜"].gender == "女"
    assert vm.character_voices["苏清颜"].age_group == "young"
    
    print(f"✅ 萧衍: {vm.character_voices['萧衍'].voice_id} (性别:{vm.character_voices['萧衍'].gender}, 年龄组:{vm.character_voices['萧衍'].age_group})")
    print(f"✅ 苏清颜: {vm.character_voices['苏清颜'].voice_id} (性别:{vm.character_voices['苏清颜'].gender}, 年龄组:{vm.character_voices['苏清颜'].age_group})")
    print("✅ 测试1通过")
    return True


def test_2_export_and_load():
    """测试2：音色配置导出和加载"""
    print("\n" + "=" * 60)
    print("测试2：音色配置导出和加载")
    print("=" * 60)
    
    vm1 = MockVoiceManager()
    voice_mapping = {
        "萧衍": {"voice_id": "Ryan", "volume": 60},
        "苏清颜": {"voice_id": "Cherry", "volume": 55}
    }
    character_profiles = [
        {"name": "萧衍", "gender": "男", "age": 25},
        {"name": "苏清颜", "gender": "女", "age": 20}
    ]
    vm1.apply_project_voice_mapping(voice_mapping, character_profiles=character_profiles)
    
    exported = vm1.export_to_db()
    print(f"📤 导出: {json.dumps(exported, indent=2, ensure_ascii=False)}")
    
    assert "萧衍" in exported
    assert exported["萧衍"]["voice_id"] == "Ryan"
    assert exported["萧衍"]["gender"] == "男"
    assert exported["萧衍"]["age_group"] == "young"
    
    vm2 = MockVoiceManager()
    vm2.load_from_db(exported)
    
    assert "萧衍" in vm2.character_voices
    assert vm2.character_voices["萧衍"].voice_id == "Ryan"
    assert vm2.character_voices["萧衍"].gender == "男"
    assert vm2.character_voices["萧衍"].age_group == "young"
    
    print(f"📥 加载: 萧衍={vm2.character_voices['萧衍'].voice_id}, 苏清颜={vm2.character_voices['苏清颜'].voice_id}")
    print("✅ 测试2通过")
    return True


def test_3_cross_chapter():
    """测试3：跨章节音色一致性"""
    print("\n" + "=" * 60)
    print("测试3：跨章节音色一致性")
    print("=" * 60)
    
    print("📅 第一天：生成第1-5章")
    vm1 = MockVoiceManager()
    vm1.apply_project_voice_mapping(
        {"萧衍": {"voice_id": "Ryan"}, "苏清颜": {"voice_id": "Cherry"}},
        character_profiles=[
            {"name": "萧衍", "gender": "男", "age": 25},
            {"name": "苏清颜", "gender": "女", "age": 20}
        ]
    )
    day1_export = vm1.export_to_db()
    print(f"   萧衍: {vm1.character_voices['萧衍'].voice_id}")
    print(f"   苏清颜: {vm1.character_voices['苏清颜'].voice_id}")
    
    print("📅 第二天：生成第6-10章（模拟服务重启）")
    vm2 = MockVoiceManager()
    vm2.load_from_db(day1_export)
    
    assert vm2.character_voices["萧衍"].voice_id == "Ryan"
    assert vm2.character_voices["苏清颜"].voice_id == "Cherry"
    
    print(f"   萧衍: {vm2.character_voices['萧衍'].voice_id} (与第一天一致)")
    print(f"   苏清颜: {vm2.character_voices['苏清颜'].voice_id} (与第一天一致)")
    print("✅ 测试3通过：跨章节音色一致性得到保证")
    return True


def test_4_user_override():
    """测试4：用户配置优先于数据库配置"""
    print("\n" + "=" * 60)
    print("测试4：用户配置优先于数据库配置")
    print("=" * 60)
    
    db_mapping = {
        "萧衍": {"voice_id": "Ryan", "volume": 60, "gender": "男", "age_group": "young"},
        "苏清颜": {"voice_id": "Cherry", "volume": 55, "gender": "女", "age_group": "young"}
    }
    vm = MockVoiceManager()
    vm.load_from_db(db_mapping)
    print(f"📂 从数据库加载: 萧衍={vm.character_voices['萧衍'].voice_id}, 苏清颜={vm.character_voices['苏清颜'].voice_id}")
    
    user_mapping = {
        "萧衍": {"voice_id": "Aiden", "volume": 65},
        "李将军": {"voice_id": "Marcus", "volume": 60}
    }
    user_profiles = [
        {"name": "萧衍", "gender": "男", "age": 25},
        {"name": "李将军", "gender": "男", "age": 45}
    ]
    vm.apply_project_voice_mapping(user_mapping, character_profiles=user_profiles)
    
    assert vm.character_voices["萧衍"].voice_id == "Aiden"
    assert vm.character_voices["李将军"].voice_id == "Marcus"
    assert vm.character_voices["苏清颜"].voice_id == "Cherry"
    
    print(f"🎛 应用用户配置后:")
    print(f"   萧衍: {vm.character_voices['萧衍'].voice_id} (已覆盖为 Aiden)")
    print(f"   苏清颜: {vm.character_voices['苏清颜'].voice_id} (保持不变)")
    print(f"   李将军: {vm.character_voices['李将军'].voice_id} (新增)")
    print("✅ 测试4通过：用户配置优先于数据库配置")
    return True


def main():
    print("\n" + "=" * 60)
    print("🧪 有声书音色持久化与跨章节一致性综合测试")
    print("=" * 60)
    
    tests = [
        ("apply_project_voice_mapping接收角色档案", test_1_apply_with_profiles),
        ("音色配置导出和加载", test_2_export_and_load),
        ("跨章节音色一致性", test_3_cross_chapter),
        ("用户配置优先于数据库配置", test_4_user_override),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            results.append((name, test_fn()))
        except Exception as e:
            print(f"\n❌ {name} 失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {status} - {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！音色持久化与跨章节一致性正常。")
    else:
        print(f"\n⚠️ 有 {total - passed} 个测试失败，请检查相关代码。")


if __name__ == "__main__":
    main()
