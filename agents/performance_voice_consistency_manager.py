"""
性能优化的音色一致性管理器

优化策略：
1. 使用更快的哈希算法（xxhash）替换MD5
2. 实现内存缓存机制减少磁盘I/O
3. 批量保存缓存减少写入次数
4. 优化文本相似度匹配算法
"""

import json
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from collections import OrderedDict
import time


@dataclass
class AudioCacheEntry:
    """音频缓存条目"""
    cache_id: str
    dialogue_text: str
    audio_path: str
    tts_params: Dict[str, Any]
    created_at: str
    expires_at: str = ""
    access_count: int = 0
    last_accessed: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioCacheEntry':
        """从字典创建"""
        return cls(**data)
    
    def mark_accessed(self):
        """标记访问"""
        self.access_count += 1
        self.last_accessed = datetime.now().isoformat()


class PerformanceVoiceConsistencyManager:
    """性能优化的音色一致性管理器"""
    
    def __init__(
        self,
        run_dir: Path,
        cache_expire_days: int = 30,
        use_xxhash: bool = True,
        max_memory_cache_size: int = 1000,
        auto_save_interval: int = 10
    ):
        self.run_dir = run_dir
        self.audio_cache_dir = run_dir / "audio_cache"
        self.audio_cache_file = self.audio_cache_dir / "audio_cache.json"
        self.cache_expire_days = cache_expire_days
        self.use_xxhash = use_xxhash
        self.max_memory_cache_size = max_memory_cache_size
        self.auto_save_interval = auto_save_interval
        
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.audio_cache: Dict[str, AudioCacheEntry] = {}
        self._memory_cache: OrderedDict[str, AudioCacheEntry] = OrderedDict()
        self._pending_writes: List[str] = []
        self._write_count = 0
        
        self._load_audio_cache()
        self._clean_expired_cache()
        self._initialize_memory_cache()
    
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
            self._pending_writes.clear()
        except Exception as e:
            print(f"保存音频缓存失败: {e}")
    
    def _initialize_memory_cache(self):
        """初始化内存缓存"""
        for cache_id, entry in self.audio_cache.items():
            if len(self._memory_cache) < self.max_memory_cache_size:
                self._memory_cache[cache_id] = entry
    
    def _update_memory_cache(self, cache_id: str, entry: AudioCacheEntry):
        """更新内存缓存（LRU策略）"""
        if cache_id in self._memory_cache:
            del self._memory_cache[cache_id]
        
        self._memory_cache[cache_id] = entry
        
        if len(self._memory_cache) > self.max_memory_cache_size:
            self._memory_cache.popitem(last=False)
    
    def _generate_cache_id(self, dialogue_text: str, tts_params: Dict[str, Any]) -> str:
        """
        生成缓存ID（使用更快的哈希算法）
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
        
        Returns:
            缓存ID
        """
        combined = dialogue_text + json.dumps(tts_params, sort_keys=True)
        
        if self.use_xxhash:
            try:
                import xxhash
                return xxhash.xxh64(combined.encode()).hexdigest()
            except ImportError:
                print("xxhash不可用，使用blake2b")
                import hashlib
                return hashlib.blake2b(combined.encode(), digest_size=16).hexdigest()
        else:
            import hashlib
            return hashlib.blake2b(combined.encode(), digest_size=16).hexdigest()
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        计算文本相似度（优化版）
        
        Args:
            text1: 文本1
            text2: 文本2
        
        Returns:
            相似度（0-1）
        """
        if text1 == text2:
            return 1.0
        
        if not text1 or not text2:
            return 0.0
        
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        jaccard_similarity = len(intersection) / len(union) if union else 0.0
        
        return jaccard_similarity
    
    def cache_audio(
        self,
        dialogue_text: str,
        audio_path: str,
        tts_params: Dict[str, Any],
        expire_days: Optional[int] = None
    ) -> Optional[AudioCacheEntry]:
        """
        缓存音频（优化版）
        
        Args:
            dialogue_text: 对话文本
            audio_path: 音频文件路径
            tts_params: TTS参数
            expire_days: 过期天数（可选）
        
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
            expires_at=expires_at,
            access_count=0,
            last_accessed=now.isoformat()
        )
        
        self.audio_cache[cache_id] = entry
        self._update_memory_cache(cache_id, entry)
        
        self._pending_writes.append(cache_id)
        self._write_count += 1
        
        if self._write_count >= self.auto_save_interval:
            self._save_audio_cache()
            self._write_count = 0
        
        return entry
    
    def get_cached_audio(
        self,
        dialogue_text: str,
        tts_params: Dict[str, Any]
    ) -> Optional[AudioCacheEntry]:
        """
        获取缓存的音频（优化版，优先从内存缓存读取）
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
        
        Returns:
            音频缓存条目
        """
        cache_id = self._generate_cache_id(dialogue_text, tts_params)
        
        if cache_id in self._memory_cache:
            entry = self._memory_cache[cache_id]
            entry.mark_accessed()
            self._update_memory_cache(cache_id, entry)
            return entry
        
        if cache_id in self.audio_cache:
            entry = self.audio_cache[cache_id]
            entry.mark_accessed()
            self._update_memory_cache(cache_id, entry)
            return entry
        
        return None
    
    def find_similar_audio(
        self,
        dialogue_text: str,
        tts_params: Dict[str, Any],
        min_similarity: float = 0.7
    ) -> Optional[AudioCacheEntry]:
        """
        查找相似的音频（优化版）
        
        Args:
            dialogue_text: 对话文本
            tts_params: TTS参数
            min_similarity: 最小相似度阈值
        
        Returns:
            最相似的音频缓存条目
        """
        best_match = None
        best_similarity = 0.0
        
        for entry in self.audio_cache.values():
            if entry.tts_params != tts_params:
                continue
            
            similarity = self._calculate_text_similarity(dialogue_text, entry.dialogue_text)
            
            if similarity > best_similarity and similarity >= min_similarity:
                best_similarity = similarity
                best_match = entry
        
        if best_match:
            best_match.mark_accessed()
            self._update_memory_cache(best_match.cache_id, best_match)
        
        return best_match
    
    def get_consistency_report(self) -> Dict[str, Any]:
        """
        获取一致性报告（优化版）
        
        Returns:
            一致性报告
        """
        now = datetime.now()
        expired_count = 0
        active_count = 0
        total_access_count = 0
        most_accessed = None
        max_access_count = 0
        
        for entry in self.audio_cache.values():
            total_access_count += entry.access_count
            
            if entry.access_count > max_access_count:
                max_access_count = entry.access_count
                most_accessed = entry.cache_id
            
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
            "memory_cached_audio": len(self._memory_cache),
            "active_cached_audio": active_count,
            "expired_cached_audio": expired_count,
            "total_access_count": total_access_count,
            "most_accessed_cache_id": most_accessed,
            "max_access_count": max_access_count,
            "cache_expire_days": self.cache_expire_days,
            "cache_dir": str(self.audio_cache_dir),
            "use_xxhash": self.use_xxhash,
            "max_memory_cache_size": self.max_memory_cache_size,
            "pending_writes": len(self._pending_writes)
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
            
            if cache_id in self._memory_cache:
                del self._memory_cache[cache_id]
            
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
        self._memory_cache.clear()
        self._pending_writes.clear()
        self._write_count = 0
        self._save_audio_cache()
    
    def flush_cache(self):
        """强制刷新缓存到磁盘"""
        if self._pending_writes:
            self._save_audio_cache()
            self._write_count = 0
    
    def benchmark_cache_operations(self, iterations: int = 1000) -> Dict[str, float]:
        """
        性能基准测试
        
        Args:
            iterations: 迭代次数
        
        Returns:
            性能指标
        """
        test_dialogue = "这是一个测试对话文本"
        test_params = {"model": "qwen3-tts", "voice": "Ryan", "voice_style": "natural"}
        
        start_time = time.time()
        for _ in range(iterations):
            self._generate_cache_id(test_dialogue, test_params)
        hash_time = time.time() - start_time
        
        start_time = time.time()
        for _ in range(iterations):
            self.get_cached_audio(test_dialogue, test_params)
        cache_lookup_time = time.time() - start_time
        
        return {
            "hash_time_per_operation": hash_time / iterations,
            "cache_lookup_time_per_operation": cache_lookup_time / iterations,
            "total_hash_time": hash_time,
            "total_cache_lookup_time": cache_lookup_time,
            "iterations": iterations
        }
