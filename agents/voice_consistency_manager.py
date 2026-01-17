"""
音色一致性管理器 - 解决不同批次视频拼接时的音色一致性问题

核心功能：
1. 声音特征提取和保存
2. 跨批次音频复用
3. 声音档案管理
4. 音频指纹匹配
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import subprocess
import shutil


@dataclass
class VoiceProfile:
    """声音档案"""
    character_id: str
    character_name: str
    voice_style: str
    voice_id: str
    audio_fingerprint: str
    tts_params: Dict[str, Any]
    created_at: str
    updated_at: str
    audio_samples: List[str]  # 音频样本路径列表
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VoiceProfile':
        """从字典创建"""
        return cls(**data)


@dataclass
class AudioCacheEntry:
    """音频缓存条目"""
    cache_id: str
    character_id: str
    dialogue_text: str
    audio_path: str
    voice_profile_id: str
    created_at: str
    duration: float
    audio_fingerprint: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioCacheEntry':
        """从字典创建"""
        return cls(**data)


class VoiceConsistencyManager:
    """音色一致性管理器"""
    
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.voice_profiles_dir = run_dir / "voice_profiles"
        self.audio_cache_dir = run_dir / "audio_cache"
        self.voice_profiles_file = self.voice_profiles_dir / "voice_profiles.json"
        self.audio_cache_file = self.audio_cache_dir / "audio_cache.json"
        
        self.voice_profiles_dir.mkdir(parents=True, exist_ok=True)
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.voice_profiles: Dict[str, VoiceProfile] = {}
        self.audio_cache: Dict[str, AudioCacheEntry] = {}
        
        self._load_voice_profiles()
        self._load_audio_cache()
    
    def _load_voice_profiles(self):
        """加载声音档案"""
        if self.voice_profiles_file.exists():
            try:
                with open(self.voice_profiles_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for profile_data in data:
                        profile = VoiceProfile.from_dict(profile_data)
                        self.voice_profiles[profile.character_id] = profile
            except Exception as e:
                print(f"加载声音档案失败: {e}")
    
    def _load_audio_cache(self):
        """加载音频缓存"""
        if self.audio_cache_file.exists():
            try:
                with open(self.audio_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for cache_data in data:
                        entry = AudioCacheEntry.from_dict(cache_data)
                        self.audio_cache[entry.cache_id] = entry
            except Exception as e:
                print(f"加载音频缓存失败: {e}")
    
    def _save_voice_profiles(self):
        """保存声音档案"""
        try:
            data = [profile.to_dict() for profile in self.voice_profiles.values()]
            with open(self.voice_profiles_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存声音档案失败: {e}")
    
    def _save_audio_cache(self):
        """保存音频缓存"""
        try:
            data = [entry.to_dict() for entry in self.audio_cache.values()]
            with open(self.audio_cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存音频缓存失败: {e}")
    
    def _generate_audio_fingerprint(self, audio_path: str) -> str:
        """
        生成音频指纹
        
        Args:
            audio_path: 音频文件路径
        
        Returns:
            音频指纹（MD5哈希）
        """
        try:
            audio_file = Path(audio_path)
            if not audio_file.exists():
                return ""
            
            hash_md5 = hashlib.md5()
            with open(audio_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"生成音频指纹失败: {e}")
            return ""
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """
        获取音频时长
        
        Args:
            audio_path: 音频文件路径
        
        Returns:
            音频时长（秒）
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
            return duration
        except Exception as e:
            print(f"获取音频时长失败: {e}")
            return 0.0
    
    def _generate_cache_id(self, character_id: str, dialogue_text: str, voice_profile_id: str) -> str:
        """
        生成缓存ID
        
        Args:
            character_id: 角色ID
            dialogue_text: 对话文本
            voice_profile_id: 声音档案ID
        
        Returns:
            缓存ID
        """
        content = f"{character_id}_{dialogue_text}_{voice_profile_id}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def create_voice_profile(
        self,
        character_id: str,
        character_name: str,
        voice_style: str,
        voice_id: str,
        tts_params: Dict[str, Any],
        audio_samples: List[str] = None
    ) -> VoiceProfile:
        """
        创建声音档案
        
        Args:
            character_id: 角色ID
            character_name: 角色名称
            voice_style: 声音风格
            voice_id: 语音ID
            tts_params: TTS参数
            audio_samples: 音频样本路径列表
        
        Returns:
            声音档案
        """
        if audio_samples is None:
            audio_samples = []
        
        audio_fingerprint = ""
        if audio_samples:
            combined_fingerprint = ""
            for sample in audio_samples:
                fingerprint = self._generate_audio_fingerprint(sample)
                combined_fingerprint += fingerprint
            audio_fingerprint = hashlib.md5(combined_fingerprint.encode()).hexdigest()
        
        now = datetime.now().isoformat()
        
        profile = VoiceProfile(
            character_id=character_id,
            character_name=character_name,
            voice_style=voice_style,
            voice_id=voice_id,
            audio_fingerprint=audio_fingerprint,
            tts_params=tts_params,
            created_at=now,
            updated_at=now,
            audio_samples=audio_samples
        )
        
        self.voice_profiles[character_id] = profile
        self._save_voice_profiles()
        
        return profile
    
    def get_voice_profile(self, character_id: str) -> Optional[VoiceProfile]:
        """
        获取声音档案
        
        Args:
            character_id: 角色ID
        
        Returns:
            声音档案，如果不存在则返回None
        """
        return self.voice_profiles.get(character_id)
    
    def update_voice_profile(
        self,
        character_id: str,
        voice_style: str = None,
        voice_id: str = None,
        tts_params: Dict[str, Any] = None,
        audio_samples: List[str] = None
    ) -> Optional[VoiceProfile]:
        """
        更新声音档案
        
        Args:
            character_id: 角色ID
            voice_style: 声音风格
            voice_id: 语音ID
            tts_params: TTS参数
            audio_samples: 音频样本路径列表
        
        Returns:
            更新后的声音档案，如果不存在则返回None
        """
        profile = self.voice_profiles.get(character_id)
        if not profile:
            return None
        
        if voice_style is not None:
            profile.voice_style = voice_style
        if voice_id is not None:
            profile.voice_id = voice_id
        if tts_params is not None:
            profile.tts_params.update(tts_params)
        if audio_samples is not None:
            profile.audio_samples = audio_samples
            audio_fingerprint = ""
            for sample in audio_samples:
                fingerprint = self._generate_audio_fingerprint(sample)
                audio_fingerprint += fingerprint
            profile.audio_fingerprint = hashlib.md5(audio_fingerprint.encode()).hexdigest()
        
        profile.updated_at = datetime.now().isoformat()
        self._save_voice_profiles()
        
        return profile
    
    def cache_audio(
        self,
        character_id: str,
        dialogue_text: str,
        audio_path: str,
        voice_profile_id: str
    ) -> Optional[AudioCacheEntry]:
        """
        缓存音频
        
        Args:
            character_id: 角色ID
            dialogue_text: 对话文本
            audio_path: 音频文件路径
            voice_profile_id: 声音档案ID
        
        Returns:
            音频缓存条目
        """
        cache_id = self._generate_cache_id(character_id, dialogue_text, voice_profile_id)
        
        duration = self._get_audio_duration(audio_path)
        audio_fingerprint = self._generate_audio_fingerprint(audio_path)
        
        now = datetime.now().isoformat()
        
        entry = AudioCacheEntry(
            cache_id=cache_id,
            character_id=character_id,
            dialogue_text=dialogue_text,
            audio_path=audio_path,
            voice_profile_id=voice_profile_id,
            created_at=now,
            duration=duration,
            audio_fingerprint=audio_fingerprint
        )
        
        self.audio_cache[cache_id] = entry
        self._save_audio_cache()
        
        return entry
    
    def get_cached_audio(
        self,
        character_id: str,
        dialogue_text: str,
        voice_profile_id: str
    ) -> Optional[AudioCacheEntry]:
        """
        获取缓存的音频
        
        Args:
            character_id: 角色ID
            dialogue_text: 对话文本
            voice_profile_id: 声音档案ID
        
        Returns:
            音频缓存条目，如果不存在则返回None
        """
        cache_id = self._generate_cache_id(character_id, dialogue_text, voice_profile_id)
        return self.audio_cache.get(cache_id)
    
    def find_similar_audio(
        self,
        character_id: str,
        dialogue_text: str,
        voice_profile_id: str,
        similarity_threshold: float = 0.8
    ) -> Optional[AudioCacheEntry]:
        """
        查找相似的音频（基于文本相似度）
        
        Args:
            character_id: 角色ID
            dialogue_text: 对话文本
            voice_profile_id: 声音档案ID
            similarity_threshold: 相似度阈值
        
        Returns:
            最相似的音频缓存条目，如果不存在则返回None
        """
        best_match = None
        best_similarity = 0.0
        
        for entry in self.audio_cache.values():
            if entry.character_id != character_id:
                continue
            if entry.voice_profile_id != voice_profile_id:
                continue
            
            similarity = self._calculate_text_similarity(dialogue_text, entry.dialogue_text)
            if similarity > best_similarity and similarity >= similarity_threshold:
                best_similarity = similarity
                best_match = entry
        
        return best_match
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        计算文本相似度（简单的基于编辑距离）
        
        Args:
            text1: 文本1
            text2: 文本2
        
        Returns:
            相似度（0-1）
        """
        if not text1 or not text2:
            return 0.0
        
        len1, len2 = len(text1), len(text2)
        if len1 == 0 and len2 == 0:
            return 1.0
        
        dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        
        for i in range(len1 + 1):
            dp[i][0] = i
        for j in range(len2 + 1):
            dp[0][j] = j
        
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                if text1[i-1] == text2[j-1]:
                    dp[i][j] = dp[i-1][j-1]
                else:
                    dp[i][j] = min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]) + 1
        
        max_len = max(len1, len2)
        return 1.0 - (dp[len1][len2] / max_len)
    
    def export_voice_profiles(self, export_dir: Path) -> bool:
        """
        导出声音档案（用于跨项目共享）
        
        Args:
            export_dir: 导出目录
        
        Returns:
            是否成功
        """
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            
            profiles_file = export_dir / "voice_profiles.json"
            data = [profile.to_dict() for profile in self.voice_profiles.values()]
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            audio_export_dir = export_dir / "audio_samples"
            audio_export_dir.mkdir(exist_ok=True)
            
            for profile in self.voice_profiles.values():
                for i, sample_path in enumerate(profile.audio_samples):
                    if Path(sample_path).exists():
                        dest_path = audio_export_dir / f"{profile.character_id}_sample_{i}.wav"
                        shutil.copy2(sample_path, dest_path)
            
            return True
        except Exception as e:
            print(f"导出声音档案失败: {e}")
            return False
    
    def import_voice_profiles(self, import_dir: Path) -> bool:
        """
        导入声音档案（用于跨项目共享）
        
        Args:
            import_dir: 导入目录
        
        Returns:
            是否成功
        """
        try:
            profiles_file = import_dir / "voice_profiles.json"
            if not profiles_file.exists():
                return False
            
            with open(profiles_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for profile_data in data:
                    profile = VoiceProfile.from_dict(profile_data)
                    self.voice_profiles[profile.character_id] = profile
            
            self._save_voice_profiles()
            return True
        except Exception as e:
            print(f"导入声音档案失败: {e}")
            return False
    
    def get_consistency_report(self) -> Dict[str, Any]:
        """
        获取音色一致性报告
        
        Returns:
            一致性报告
        """
        report = {
            "total_profiles": len(self.voice_profiles),
            "total_cached_audio": len(self.audio_cache),
            "profiles": [],
            "audio_cache_stats": {
                "total_duration": 0.0,
                "by_character": {}
            }
        }
        
        for profile in self.voice_profiles.values():
            profile_info = {
                "character_id": profile.character_id,
                "character_name": profile.character_name,
                "voice_style": profile.voice_style,
                "voice_id": profile.voice_id,
                "audio_samples_count": len(profile.audio_samples),
                "created_at": profile.created_at,
                "updated_at": profile.updated_at
            }
            report["profiles"].append(profile_info)
        
        for entry in self.audio_cache.values():
            report["audio_cache_stats"]["total_duration"] += entry.duration
            
            if entry.character_id not in report["audio_cache_stats"]["by_character"]:
                report["audio_cache_stats"]["by_character"][entry.character_id] = {
                    "count": 0,
                    "total_duration": 0.0
                }
            
            stats = report["audio_cache_stats"]["by_character"][entry.character_id]
            stats["count"] += 1
            stats["total_duration"] += entry.duration
        
        return report
