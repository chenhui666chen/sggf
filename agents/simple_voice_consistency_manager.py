"""
简化的音色一致性管理器 - 只保留最佳策略

最佳策略：
1. 使用相同的TTS参数生成音频
2. 缓存已生成的音频，避免重复生成
3. 跨批次复用相同的音频文件
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta


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


class SimpleVoiceConsistencyManager:
    """简化的音色一致性管理器"""
    
    def __init__(self, run_dir: Path, cache_expire_days: int = 30):
        self.run_dir = run_dir
        self.audio_cache_dir = run_dir / "audio_cache"
        self.audio_cache_file = self.audio_cache_dir / "audio_cache.json"
        self.cache_expire_days = cache_expire_days
        
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.audio_cache: Dict[str, AudioCacheEntry] = {}
        self._load_audio_cache()
        self._clean_expired_cache()
    
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
        生成缓存ID
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
        
        Returns:
            缓存ID（MD5哈希）
        """
        combined = dialogue_text + json.dumps(tts_params, sort_keys=True)
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
        tts_params: Dict[str, Any]
    ) -> Optional[AudioCacheEntry]:
        """
        获取缓存的音频
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
        
        Returns:
            音频缓存条目，如果不存在则返回None
        """
        cache_id = self._generate_cache_id(dialogue_text, tts_params)
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
