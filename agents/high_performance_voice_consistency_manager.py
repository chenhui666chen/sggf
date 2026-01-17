"""
高性能音色一致性管理器 - 性能优化版本

优化策略：
1. 使用更快的哈希算法（SHA256替代MD5）
2. 添加内存缓存，减少磁盘IO
3. 优化缓存查找性能
4. 添加缓存预热功能
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from functools import lru_cache


@dataclass
class AudioCacheEntry:
    """音频缓存条目"""
    cache_id: str
    dialogue_text: str
    audio_path: str
    tts_params: Dict[str, Any]
    created_at: str
    expires_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioCacheEntry':
        """从字典创建"""
        return cls(**data)


class HighPerformanceVoiceConsistencyManager:
    """高性能音色一致性管理器"""
    
    def __init__(
        self,
        run_dir: Path,
        cache_expire_days: int = 30,
        memory_cache_size: int = 1000,
        use_sha256: bool = True
    ):
        self.run_dir = run_dir
        self.audio_cache_dir = run_dir / "audio_cache"
        self.audio_cache_file = self.audio_cache_dir / "audio_cache.json"
        self.cache_expire_days = cache_expire_days
        self.memory_cache_size = memory_cache_size
        self.use_sha256 = use_sha256
        
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.audio_cache: Dict[str, AudioCacheEntry] = {}
        self._load_audio_cache()
        self._clean_expired_cache()
        
        self._setup_memory_cache()
    
    def _setup_memory_cache(self):
        """设置内存缓存"""
        self._get_cached_audio_memory = lru_cache(maxsize=self.memory_cache_size)(
            self._get_cached_audio_memory_impl
        )
    
    def _get_cached_audio_memory_impl(
        self,
        cache_id: str
    ) -> Optional[AudioCacheEntry]:
        """
        从内存缓存获取音频（实现）
        
        Args:
            cache_id: 缓存ID
        
        Returns:
            音频缓存条目
        """
        return self.audio_cache.get(cache_id)
    
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
    
    def _save_audio_cache(self):
        """保存音频缓存"""
        try:
            data = [entry.to_dict() for entry in self.audio_cache.values()]
            with open(self.audio_cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存音频缓存失败: {e}")
    
    def _generate_cache_id(self, dialogue_text: str, tts_params: Dict[str, Any]) -> str:
        """
        生成缓存ID（使用SHA256或MD5）
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
        
        Returns:
            缓存ID（SHA256或MD5哈希）
        """
        combined = dialogue_text + json.dumps(tts_params, sort_keys=True)
        
        if self.use_sha256:
            return hashlib.sha256(combined.encode()).hexdigest()
        else:
            return hashlib.md5(combined.encode()).hexdigest()
    
    def cache_audio(
        self,
        dialogue_text: str,
        audio_path: str,
        tts_params: Dict[str, Any],
        expire_days: Optional[int] = None
    ) -> Optional[AudioCacheEntry]:
        """
        缓存音频
        
        Args:
            dialogue_text: 对话文本
            audio_path: 音频文件路径
            tts_params: TTS参数
            expire_days: 过期天数（可选，默认使用类默认值）
        
        Returns:
            音频缓存条目
        """
        cache_id = self._generate_cache_id(dialogue_text, tts_params)
        
        now = datetime.now()
        expires_days = expire_days if expire_days is not None else self.cache_expire_days
        expires_at = (now + timedelta(days=expires_days)).isoformat()
        
        entry = AudioCacheEntry(
            cache_id=cache_id,
            dialogue_text=dialogue_text,
            audio_path=audio_path,
            tts_params=tts_params,
            created_at=now.isoformat(),
            expires_at=expires_at
        )
        
        self.audio_cache[cache_id] = entry
        self._save_audio_cache()
        
        return entry
    
    def get_cached_audio(
        self,
        dialogue_text: str,
        tts_params: Dict[str, Any],
        use_memory_cache: bool = True
    ) -> Optional[AudioCacheEntry]:
        """
        获取缓存的音频
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
            use_memory_cache: 是否使用内存缓存（默认True）
        
        Returns:
            音频缓存条目，如果不存在则返回None
        """
        cache_id = self._generate_cache_id(dialogue_text, tts_params)
        
        if use_memory_cache:
            return self._get_cached_audio_memory(cache_id)
        else:
            return self.audio_cache.get(cache_id)
    
    def get_consistency_report(self) -> Dict[str, Any]:
        """
        获取一致性报告
        
        Returns:
            一致性报告
        """
        now = datetime.now()
        expired_count = 0
        active_count = 0
        
        for entry in self.audio_cache.values():
            if entry.expires_at:
                expires_at = datetime.fromisoformat(entry.expires_at)
                if now > expires_at:
                    expired_count += 1
                else:
                    active_count += 1
            else:
                active_count += 1
        
        return {
            "total_cached_audio": len(self.audio_cache),
            "active_cached_audio": active_count,
            "expired_cached_audio": expired_count,
            "cache_expire_days": self.cache_expire_days,
            "memory_cache_size": self.memory_cache_size,
            "hash_algorithm": "SHA256" if self.use_sha256 else "MD5",
            "cache_dir": str(self.audio_cache_dir)
        }
    
    def _clean_expired_cache(self):
        """清理过期的缓存"""
        now = datetime.now()
        expired_ids = []
        
        for cache_id, entry in self.audio_cache.items():
            if entry.expires_at:
                expires_at = datetime.fromisoformat(entry.expires_at)
                if now > expires_at:
                    expired_ids.append(cache_id)
        
        for cache_id in expired_ids:
            entry = self.audio_cache[cache_id]
            audio_path = Path(entry.audio_path)
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception as e:
                    print(f"删除音频文件失败: {e}")
            del self.audio_cache[cache_id]
        
        if expired_ids:
            self._save_audio_cache()
            print(f"清理了 {len(expired_ids)} 个过期缓存")
    
    def clear_cache(self):
        """清空缓存"""
        for cache_id, entry in self.audio_cache.items():
            audio_path = Path(entry.audio_path)
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception as e:
                    print(f"删除音频文件失败: {e}")
        
        self.audio_cache.clear()
        self._save_audio_cache()
        
        self._setup_memory_cache()
    
    def warmup_cache(
        self,
        dialogues: List[Dict[str, Any]],
        character_manager=None
    ) -> int:
        """
        缓存预热 - 预加载常用对话到内存缓存
        
        Args:
            dialogues: 对话列表
            character_manager: 角色管理器（可选）
        
        Returns:
            预热的缓存数量
        """
        warmup_count = 0
        
        for dialogue_item in dialogues:
            if not isinstance(dialogue_item, dict):
                continue
            
            dialogue_text = str(dialogue_item.get("dialogue", ""))
            voice_style = dialogue_item.get("voice_style", "natural")
            voice_id = dialogue_item.get("voice_id")
            
            if not dialogue_text:
                continue
            
            tts_params = {
                "model": "qwen3-tts",
                "voice": voice_id or "Ryan",
                "voice_style": voice_style
            }
            
            cache_id = self._generate_cache_id(dialogue_text, tts_params)
            
            if cache_id in self.audio_cache:
                self._get_cached_audio_memory(cache_id)
                warmup_count += 1
        
        print(f"缓存预热完成: 预热了 {warmup_count} 个缓存项")
        return warmup_count
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            缓存统计信息
        """
        cache_info = self._get_cached_audio_memory.cache_info()
        
        return {
            "memory_cache_hits": cache_info.hits,
            "memory_cache_misses": cache_info.misses,
            "memory_cache_size": cache_info.currsize,
            "memory_cache_max_size": cache_info.maxsize,
            "disk_cache_size": len(self.audio_cache)
        }
