"""
简化的角色管理器 - 只保留音色一致性相关的字段

优化策略：
1. 只保留必要的字段（character_id, name, voice_style, voice_id）
2. 移除不必要的字段（reference_video_path, reference_image_path, voice_reference_path, appearance_description, personality_traits, importance）
3. 简化API调用格式
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SimpleCharacterProfile:
    """简化的角色档案 - 只保留音色一致性相关字段"""
    
    character_id: str
    name: str
    voice_style: str = "natural"
    voice_id: str = "Ryan"
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于保存）"""
        return {
            "character_id": self.character_id,
            "name": self.name,
            "voice_style": self.voice_style,
            "voice_id": self.voice_id,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimpleCharacterProfile":
        """从字典创建角色档案"""
        return cls(
            character_id=str(data.get("character_id", "")),
            name=str(data.get("name", "")),
            voice_style=str(data.get("voice_style", "natural")),
            voice_id=str(data.get("voice_id", "Ryan")),
            created_at=str(data.get("created_at", "")),
        )


class SimpleCharacterManager:
    """简化的角色管理器 - 只管理音色一致性"""
    
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.characters: Dict[str, SimpleCharacterProfile] = {}
        self.profiles_file = run_dir / "simple_character_profiles.json"
        
        self._load_profiles()
    
    def _load_profiles(self) -> None:
        """从文件加载角色档案"""
        if self.profiles_file.exists():
            try:
                with open(self.profiles_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            profile = SimpleCharacterProfile.from_dict(item)
                            self.characters[profile.character_id] = profile
            except Exception as e:
                print(f"加载角色档案失败: {e}")
    
    def _save_profiles(self) -> None:
        """保存角色档案到文件"""
        try:
            profiles = [profile.to_dict() for profile in self.characters.values()]
            with open(self.profiles_file, "w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存角色档案失败: {e}")
    
    def create_character(
        self,
        character_id: str,
        name: str,
        voice_style: str = "natural",
        voice_id: str = "Ryan"
    ) -> SimpleCharacterProfile:
        """
        创建角色
        
        Args:
            character_id: 角色唯一标识
            name: 角色名称
            voice_style: 语音风格（natural/emotional/humorous等）
            voice_id: 语音ID（默认Ryan）
        
        Returns:
            创建的角色档案
        """
        profile = SimpleCharacterProfile(
            character_id=character_id,
            name=name,
            voice_style=voice_style,
            voice_id=voice_id,
            created_at=datetime.now().isoformat()
        )
        
        self.characters[character_id] = profile
        self._save_profiles()
        
        return profile
    
    def get_character(self, character_id: str) -> Optional[SimpleCharacterProfile]:
        """获取角色档案"""
        return self.characters.get(character_id)
    
    def get_character_by_name(self, name: str) -> Optional[SimpleCharacterProfile]:
        """根据名称获取角色档案"""
        name_lower = name.lower().strip()
        for profile in self.characters.values():
            if profile.name.lower().strip() == name_lower:
                return profile
        return None
    
    def get_all_characters(self) -> List[SimpleCharacterProfile]:
        """获取所有角色"""
        return list(self.characters.values())
    
    def update_character_voice(
        self,
        character_id: str,
        voice_style: Optional[str] = None,
        voice_id: Optional[str] = None
    ) -> bool:
        """
        更新角色声音设置
        
        Args:
            character_id: 角色ID
            voice_style: 语音风格（可选）
            voice_id: 语音ID（可选）
        
        Returns:
            是否成功
        """
        profile = self.characters.get(character_id)
        if not profile:
            return False
        
        if voice_style is not None:
            profile.voice_style = voice_style
        if voice_id is not None:
            profile.voice_id = voice_id
        
        profile.created_at = datetime.now().isoformat()
        self._save_profiles()
        
        return True
    
    def delete_character(self, character_id: str) -> bool:
        """
        删除角色
        
        Args:
            character_id: 角色ID
        
        Returns:
            是否成功
        """
        if character_id in self.characters:
            del self.characters[character_id]
            self._save_profiles()
            return True
        return False
    
    def get_character_summary(self) -> str:
        """获取角色摘要（用于LLM提示）"""
        if not self.characters:
            return ""
        
        lines = ["角色信息："]
        for profile in self.characters.values():
            lines.append(f"- {profile.name}（{profile.character_id}）：voice_style={profile.voice_style}, voice_id={profile.voice_id}")
        
        return "\n".join(lines)
    
    def import_from_character_manager(self, character_manager) -> None:
        """
        从完整的CharacterManager导入角色数据
        
        Args:
            character_manager: 完整的CharacterManager实例
        """
        for profile in character_manager.get_all_characters():
            if profile.character_id not in self.characters:
                self.create_character(
                    character_id=profile.character_id,
                    name=profile.name,
                    voice_style=profile.voice_style
                )
