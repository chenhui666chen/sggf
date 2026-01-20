from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CharacterProfile:
    """角色档案 - 用于通义万相2.6角色一致性"""
    
    character_id: str
    name: str
    reference_video_path: Optional[str] = None
    reference_image_path: Optional[str] = None
    voice_reference_path: Optional[str] = None
    appearance_description: str = ""
    personality_traits: List[str] = field(default_factory=list)
    voice_style: str = "natural"
    voice_id: str = ""
    voice_profile_id: str = ""
    importance: str = "secondary"
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_api_format(self) -> Dict[str, Any]:
        """转换为 API 调用格式（用于通义万相2.6）"""
        result: Dict[str, Any] = {
            "character_id": self.character_id,
            "name": self.name,
        }
        
        if self.reference_video_path and Path(self.reference_video_path).exists():
            try:
                with open(self.reference_video_path, "rb") as f:
                    result["reference_video"] = base64.b64encode(f.read()).decode()
            except Exception:
                pass
        
        if self.reference_image_path and Path(self.reference_image_path).exists():
            try:
                with open(self.reference_image_path, "rb") as f:
                    result["reference_image"] = base64.b64encode(f.read()).decode()
            except Exception:
                pass
        
        if self.appearance_description:
            result["appearance"] = self.appearance_description
        
        if self.voice_style:
            result["voice_style"] = self.voice_style
        
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于保存）"""
        return {
            "character_id": self.character_id,
            "name": self.name,
            "reference_video_path": self.reference_video_path,
            "reference_image_path": self.reference_image_path,
            "voice_reference_path": self.voice_reference_path,
            "appearance_description": self.appearance_description,
            "personality_traits": self.personality_traits,
            "voice_style": self.voice_style,
            "voice_id": self.voice_id,
            "voice_profile_id": self.voice_profile_id,
            "importance": self.importance,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterProfile":
        """从字典创建角色档案"""
        return cls(
            character_id=str(data.get("character_id", "")),
            name=str(data.get("name", "")),
            reference_video_path=data.get("reference_video_path"),
            reference_image_path=data.get("reference_image_path"),
            voice_reference_path=data.get("voice_reference_path"),
            appearance_description=str(data.get("appearance_description", "")),
            personality_traits=data.get("personality_traits") or [],
            voice_style=str(data.get("voice_style", "natural")),
            voice_id=str(data.get("voice_id", "")),
            voice_profile_id=str(data.get("voice_profile_id", "")),
            importance=str(data.get("importance", "secondary")),
            created_at=str(data.get("created_at", "")),
        )


class CharacterManager:
    """角色管理器 - 管理跨镜头角色一致性"""
    
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.characters: Dict[str, CharacterProfile] = {}
        self.max_characters = 3
        self.assignments_file = run_dir / "character_assignments.json"
        self.profiles_file = run_dir / "character_profiles.json"
        self._voice_manager: Any = None
        
        self._load_profiles()

    def _get_voice_manager(self) -> Optional[Any]:
        if self._voice_manager is False:
            return None
        if self._voice_manager is not None:
            return self._voice_manager
        try:
            backend_root = Path(__file__).resolve().parents[1] / "backend"
            if backend_root.exists() and str(backend_root) not in sys.path:
                sys.path.insert(0, str(backend_root))
            from app.services.audiobook.voice_manager import VoiceManager  # type: ignore
        except Exception:
            self._voice_manager = False
            return None
        self._voice_manager = VoiceManager()
        return self._voice_manager

    def _ensure_voice_profile(self, profile: CharacterProfile) -> bool:
        changed = False
        preferred_voice_id = str(profile.voice_id or "").strip() or None
        manager = self._get_voice_manager()
        if manager and profile.name:
            try:
                assigned = manager.assign_voice(
                    profile.name,
                    preferred_voice_id=preferred_voice_id
                )
                if assigned:
                    resolved_voice_id = getattr(assigned, "voice_id", "") or profile.voice_id
                    resolved_profile_id = getattr(assigned, "tts_speaker_id", "") or resolved_voice_id
                    if profile.voice_id != resolved_voice_id:
                        profile.voice_id = resolved_voice_id
                        changed = True
                    if profile.voice_profile_id != resolved_profile_id:
                        profile.voice_profile_id = resolved_profile_id
                        changed = True
            except Exception:
                pass

        if not profile.voice_id:
            profile.voice_id = preferred_voice_id or "Ryan"
            changed = True
        if not profile.voice_profile_id:
            profile.voice_profile_id = profile.voice_id
            changed = True
        return changed

    def _load_profiles(self) -> None:
        """从文件加载角色档案"""
        if self.profiles_file.exists():
            try:
                with open(self.profiles_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        changed = False
                        for item in data:
                            profile = CharacterProfile.from_dict(item)
                            if self._ensure_voice_profile(profile):
                                changed = True
                            self.characters[profile.character_id] = profile
                        if changed:
                            self._save_profiles()
            except Exception:
                pass
    
    def _save_profiles(self) -> None:
        """保存角色档案到文件"""
        try:
            profiles = [profile.to_dict() for profile in self.characters.values()]
            with open(self.profiles_file, "w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def create_character_from_script(
        self,
        character_id: str,
        name: str,
        description: str,
        importance: str = "secondary",
        personality_traits: List[str] = None,
        voice_style: str = "natural",
        reference_media_path: Optional[str] = None,
        voice_id: Optional[str] = None,
        voice_profile_id: Optional[str] = None
    ) -> CharacterProfile:
        """
        从脚本创建角色
        
        Args:
            character_id: 角色唯一标识（如 character1, character2）
            name: 角色名称
            description: 外貌描述
            importance: 重要程度（main/secondary/minor）
            personality_traits: 性格特征列表
            voice_style: 语音风格（natural/emotional/humorous等）
            reference_media_path: 参考媒体路径（图片或视频）
        
        Returns:
            创建的角色档案
        """
        if len(self.characters) >= self.max_characters:
            raise ValueError(f"最多支持 {self.max_characters} 个角色")
        
        profile = CharacterProfile(
            character_id=character_id,
            name=name,
            appearance_description=description,
            personality_traits=personality_traits or [],
            voice_style=voice_style,
            voice_id=voice_id or "",
            voice_profile_id=voice_profile_id or "",
            importance=importance,
            created_at=datetime.now().isoformat()
        )

        self._ensure_voice_profile(profile)
        
        if reference_media_path:
            ext = Path(reference_media_path).suffix.lower()
            if ext in {".mp4", ".mov", ".avi", ".mkv"}:
                profile.reference_video_path = reference_media_path
            else:
                profile.reference_image_path = reference_media_path
        
        self.characters[character_id] = profile
        self._save_profiles()
        
        return profile
    
    def create_character_from_entity(
        self,
        entity: Dict[str, Any],
        character_id: Optional[str] = None
    ) -> CharacterProfile:
        """
        从实体抽取创建角色
        
        Args:
            entity: 实体字典（包含 name, descriptor, importance）
            character_id: 角色ID（可选，自动生成）
        
        Returns:
            创建的角色档案
        """
        if character_id is None and isinstance(entity, dict):
            raw_id = entity.get("character_id")
            if raw_id is None:
                raw_id = entity.get("entity_id") or entity.get("id")
            if raw_id is not None:
                candidate = str(raw_id).strip()
                if candidate:
                    character_id = candidate

        if character_id is None:
            existing_ids = set(self.characters.keys())
            for i in range(1, self.max_characters + 1):
                cid = f"character{i}"
                if cid not in existing_ids:
                    character_id = cid
                    break
        
        if character_id is None:
            raise ValueError("无法生成角色ID")
        
        name = str(entity.get("name", "")).strip()
        descriptor = str(entity.get("descriptor", "")).strip()
        importance = str(entity.get("importance", "secondary")).strip()
        
        if not name:
            raise ValueError("角色名称不能为空")
        
        return self.create_character_from_script(
            character_id=character_id,
            name=name,
            description=descriptor,
            importance=importance
        )
    
    def get_character(self, character_id: str) -> Optional[CharacterProfile]:
        """获取角色档案"""
        return self.characters.get(character_id)
    
    def get_character_by_name(self, name: str) -> Optional[CharacterProfile]:
        """根据名称获取角色档案"""
        name_lower = name.lower().strip()
        for profile in self.characters.values():
            if profile.name.lower().strip() == name_lower:
                return profile
        return None
    
    def get_all_characters(self) -> List[CharacterProfile]:
        """获取所有角色"""
        return list(self.characters.values())
    
    def get_main_characters(self) -> List[CharacterProfile]:
        """获取主要角色"""
        return [p for p in self.characters.values() if p.importance == "main"]
    
    def get_characters_for_shot(self, shot_id: str) -> List[CharacterProfile]:
        """获取镜头中的角色列表"""
        if not self.assignments_file.exists():
            return []
        
        try:
            with open(self.assignments_file, "r", encoding="utf-8") as f:
                assignments = json.load(f)
        except Exception:
            return []
        
        shot_assignments = assignments.get(shot_id, [])
        characters = []
        for assignment in shot_assignments:
            character = self.get_character(assignment.get("character_id"))
            if character:
                characters.append(character)
        
        return characters
    
    def assign_character_to_shot(
        self,
        shot_id: str,
        character_id: str,
        role: str = "main",
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> None:
        """
        将角色分配到镜头
        
        Args:
            shot_id: 镜头ID
            character_id: 角色ID
            role: 角色（main/secondary/background）
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
        """
        assignments: Dict[str, List[Dict[str, Any]]] = {}
        
        if self.assignments_file.exists():
            try:
                with open(self.assignments_file, "r", encoding="utf-8") as f:
                    assignments = json.load(f)
            except Exception:
                pass
        
        if shot_id not in assignments:
            assignments[shot_id] = []
        
        assignment = {
            "character_id": character_id,
            "role": role,
        }
        
        if start_time is not None:
            assignment["start_time"] = start_time
        if end_time is not None:
            assignment["end_time"] = end_time
        
        assignments[shot_id].append(assignment)
        
        try:
            with open(self.assignments_file, "w", encoding="utf-8") as f:
                json.dump(assignments, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def get_characters_for_api(self, shot_id: str, max_characters: int = 3) -> List[Dict[str, Any]]:
        """
        获取镜头角色的API格式（用于通义万相2.6）
        
        Args:
            shot_id: 镜头ID
            max_characters: 最大角色数量
        
        Returns:
            角色API格式列表
        """
        characters = self.get_characters_for_shot(shot_id)
        
        api_characters = []
        for profile in characters[:max_characters]:
            api_characters.append(profile.to_api_format())
        
        return api_characters
    
    def auto_assign_characters_from_storyboard(
        self,
        storyboard: List[Dict[str, Any]],
        entities: Dict[str, Any]
    ) -> None:
        """
        从分镜自动分配角色
        
        Args:
            storyboard: 分镜列表
            entities: 实体字典
        """
        if not isinstance(entities, dict):
            return
        
        entity_characters = entities.get("characters", [])
        if not isinstance(entity_characters, list):
            return
        
        for entity in entity_characters:
            try:
                raw_id = None
                if isinstance(entity, dict):
                    raw_id = entity.get("character_id") or entity.get("entity_id") or entity.get("id")
                character_id = str(raw_id).strip() if raw_id is not None else None
                if character_id == "":
                    character_id = None
                profile = self.create_character_from_entity(entity, character_id=character_id)
            except Exception:
                continue
        
        for shot in storyboard:
            if not isinstance(shot, dict):
                continue
            
            shot_id = str(shot.get("shot_id", ""))
            if not shot_id:
                continue
            
            ff_chars = shot.get("ff_vis_char_ids", [])
            lf_chars = shot.get("lf_vis_char_ids", [])
            
            all_chars = set()
            if isinstance(ff_chars, list):
                all_chars.update(ff_chars)
            if isinstance(lf_chars, list):
                all_chars.update(lf_chars)
            
            for char_name in all_chars:
                profile = self.get_character_by_name(str(char_name))
                if profile:
                    self.assign_character_to_shot(
                        shot_id=shot_id,
                        character_id=profile.character_id,
                        role="main"
                    )
    
    def get_character_summary(self) -> str:
        """获取角色摘要（用于LLM提示）"""
        if not self.characters:
            return ""
        
        lines = ["角色信息："]
        for profile in self.characters.values():
            importance_tag = "【主角】" if profile.importance == "main" else ""
            lines.append(f"- {profile.name}（{profile.character_id}）{importance_tag}：{profile.appearance_description}")
        
        return "\n".join(lines)
