"""
跨批次音频复用管理器 - 解决不同批次视频拼接时的音色一致性问题

核心功能：
1. 管理多个批次的音频
2. 在不同批次之间复用音频
3. 确保音色一致性
4. 支持音频导出和导入
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from datetime import datetime
from .voice_consistency_manager import VoiceConsistencyManager, VoiceProfile, AudioCacheEntry


@dataclass
class BatchInfo:
    """批次信息"""
    batch_id: str
    batch_name: str
    created_at: str
    characters: List[str]  # 角色ID列表
    total_audio_count: int
    total_duration: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BatchInfo':
        """从字典创建"""
        return cls(**data)


class CrossBatchAudioManager:
    """跨批次音频复用管理器"""
    
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.batches_dir = run_dir / "batches"
        self.shared_audio_dir = run_dir / "shared_audio"
        self.batches_index_file = self.batches_dir / "batches_index.json"
        
        self.batches_dir.mkdir(parents=True, exist_ok=True)
        self.shared_audio_dir.mkdir(parents=True, exist_ok=True)
        
        self.batches: Dict[str, BatchInfo] = {}
        self.voice_managers: Dict[str, VoiceConsistencyManager] = {}
        
        self._load_batches_index()
    
    def _load_batches_index(self):
        """加载批次索引"""
        if self.batches_index_file.exists():
            try:
                with open(self.batches_index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for batch_data in data:
                        batch = BatchInfo.from_dict(batch_data)
                        self.batches[batch.batch_id] = batch
            except Exception as e:
                print(f"加载批次索引失败: {e}")
    
    def _save_batches_index(self):
        """保存批次索引"""
        try:
            data = [batch.to_dict() for batch in self.batches.values()]
            with open(self.batches_index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存批次索引失败: {e}")
    
    def _get_batch_dir(self, batch_id: str) -> Path:
        """获取批次目录"""
        return self.batches_dir / batch_id
    
    def _get_voice_manager(self, batch_id: str) -> VoiceConsistencyManager:
        """获取批次的声音一致性管理器"""
        if batch_id not in self.voice_managers:
            batch_dir = self._get_batch_dir(batch_id)
            self.voice_managers[batch_id] = VoiceConsistencyManager(batch_dir)
        return self.voice_managers[batch_id]
    
    def create_batch(
        self,
        batch_id: str,
        batch_name: str = None
    ) -> BatchInfo:
        """
        创建新批次
        
        Args:
            batch_id: 批次ID
            batch_name: 批次名称
        
        Returns:
            批次信息
        """
        if batch_id in self.batches:
            return self.batches[batch_id]
        
        batch_dir = self._get_batch_dir(batch_id)
        batch_dir.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now().isoformat()
        
        batch = BatchInfo(
            batch_id=batch_id,
            batch_name=batch_name or f"批次_{batch_id}",
            created_at=now,
            characters=[],
            total_audio_count=0,
            total_duration=0.0
        )
        
        self.batches[batch_id] = batch
        self._save_batches_index()
        
        return batch
    
    def get_batch(self, batch_id: str) -> Optional[BatchInfo]:
        """
        获取批次信息
        
        Args:
            batch_id: 批次ID
        
        Returns:
            批次信息，如果不存在则返回None
        """
        return self.batches.get(batch_id)
    
    def register_character(
        self,
        batch_id: str,
        character_id: str,
        character_name: str,
        voice_style: str,
        voice_id: str,
        tts_params: Dict[str, Any],
        audio_samples: List[str] = None
    ) -> Optional[VoiceProfile]:
        """
        注册角色到批次
        
        Args:
            batch_id: 批次ID
            character_id: 角色ID
            character_name: 角色名称
            voice_style: 声音风格
            voice_id: 语音ID
            tts_params: TTS参数
            audio_samples: 音频样本路径列表
        
        Returns:
            声音档案
        """
        if batch_id not in self.batches:
            return None
        
        voice_manager = self._get_voice_manager(batch_id)
        profile = voice_manager.create_voice_profile(
            character_id=character_id,
            character_name=character_name,
            voice_style=voice_style,
            voice_id=voice_id,
            tts_params=tts_params,
            audio_samples=audio_samples or []
        )
        
        batch = self.batches[batch_id]
        if character_id not in batch.characters:
            batch.characters.append(character_id)
            self._save_batches_index()
        
        return profile
    
    def get_character_profile(
        self,
        batch_id: str,
        character_id: str
    ) -> Optional[VoiceProfile]:
        """
        获取角色声音档案
        
        Args:
            batch_id: 批次ID
            character_id: 角色ID
        
        Returns:
            声音档案，如果不存在则返回None
        """
        if batch_id not in self.batches:
            return None
        
        voice_manager = self._get_voice_manager(batch_id)
        return voice_manager.get_voice_profile(character_id)
    
    def cache_audio(
        self,
        batch_id: str,
        character_id: str,
        dialogue_text: str,
        audio_path: str,
        voice_profile_id: str
    ) -> Optional[AudioCacheEntry]:
        """
        缓存音频到批次
        
        Args:
            batch_id: 批次ID
            character_id: 角色ID
            dialogue_text: 对话文本
            audio_path: 音频文件路径
            voice_profile_id: 声音档案ID
        
        Returns:
            音频缓存条目
        """
        if batch_id not in self.batches:
            return None
        
        voice_manager = self._get_voice_manager(batch_id)
        entry = voice_manager.cache_audio(
            character_id=character_id,
            dialogue_text=dialogue_text,
            audio_path=audio_path,
            voice_profile_id=voice_profile_id
        )
        
        if entry:
            batch = self.batches[batch_id]
            batch.total_audio_count += 1
            batch.total_duration += entry.duration
            self._save_batches_index()
        
        return entry
    
    def get_cached_audio(
        self,
        batch_id: str,
        character_id: str,
        dialogue_text: str,
        voice_profile_id: str
    ) -> Optional[AudioCacheEntry]:
        """
        获取批次的缓存音频
        
        Args:
            batch_id: 批次ID
            character_id: 角色ID
            dialogue_text: 对话文本
            voice_profile_id: 声音档案ID
        
        Returns:
            音频缓存条目，如果不存在则返回None
        """
        if batch_id not in self.batches:
            return None
        
        voice_manager = self._get_voice_manager(batch_id)
        return voice_manager.get_cached_audio(
            character_id=character_id,
            dialogue_text=dialogue_text,
            voice_profile_id=voice_profile_id
        )
    
    def find_audio_across_batches(
        self,
        character_id: str,
        dialogue_text: str,
        voice_profile_id: str,
        similarity_threshold: float = 0.8,
        preferred_batch_id: str = None
    ) -> Optional[AudioCacheEntry]:
        """
        在所有批次中查找音频
        
        Args:
            character_id: 角色ID
            dialogue_text: 对话文本
            voice_profile_id: 声音档案ID
            similarity_threshold: 相似度阈值
            preferred_batch_id: 优先查找的批次ID
        
        Returns:
            音频缓存条目，如果不存在则返回None
        """
        if preferred_batch_id and preferred_batch_id in self.batches:
            voice_manager = self._get_voice_manager(preferred_batch_id)
            entry = voice_manager.find_similar_audio(
                character_id=character_id,
                dialogue_text=dialogue_text,
                voice_profile_id=voice_profile_id,
                similarity_threshold=similarity_threshold
            )
            if entry:
                return entry
        
        for batch_id in self.batches:
            if batch_id == preferred_batch_id:
                continue
            
            voice_manager = self._get_voice_manager(batch_id)
            entry = voice_manager.find_similar_audio(
                character_id=character_id,
                dialogue_text=dialogue_text,
                voice_profile_id=voice_profile_id,
                similarity_threshold=similarity_threshold
            )
            if entry:
                return entry
        
        return None
    
    def share_audio_across_batches(
        self,
        source_batch_id: str,
        target_batch_id: str,
        character_id: str,
        dialogue_text: str,
        voice_profile_id: str
    ) -> Optional[AudioCacheEntry]:
        """
        在批次之间共享音频
        
        Args:
            source_batch_id: 源批次ID
            target_batch_id: 目标批次ID
            character_id: 角色ID
            dialogue_text: 对话文本
            voice_profile_id: 声音档案ID
        
        Returns:
            音频缓存条目，如果不存在则返回None
        """
        if source_batch_id not in self.batches or target_batch_id not in self.batches:
            return None
        
        source_manager = self._get_voice_manager(source_batch_id)
        target_manager = self._get_voice_manager(target_batch_id)
        
        source_entry = source_manager.get_cached_audio(
            character_id=character_id,
            dialogue_text=dialogue_text,
            voice_profile_id=voice_profile_id
        )
        
        if not source_entry:
            return None
        
        shared_audio_path = self.shared_audio_dir / f"{source_entry.cache_id}.wav"
        if not shared_audio_path.exists():
            shutil.copy2(source_entry.audio_path, shared_audio_path)
        
        target_entry = target_manager.cache_audio(
            character_id=character_id,
            dialogue_text=dialogue_text,
            audio_path=str(shared_audio_path),
            voice_profile_id=voice_profile_id
        )
        
        return target_entry
    
    def sync_character_profiles(
        self,
        source_batch_id: str,
        target_batch_id: str,
        character_id: str
    ) -> bool:
        """
        同步角色声音档案到目标批次
        
        Args:
            source_batch_id: 源批次ID
            target_batch_id: 目标批次ID
            character_id: 角色ID
        
        Returns:
            是否成功
        """
        if source_batch_id not in self.batches or target_batch_id not in self.batches:
            return False
        
        source_manager = self._get_voice_manager(source_batch_id)
        target_manager = self._get_voice_manager(target_batch_id)
        
        profile = source_manager.get_voice_profile(character_id)
        if not profile:
            return False
        
        target_manager.create_voice_profile(
            character_id=profile.character_id,
            character_name=profile.character_name,
            voice_style=profile.voice_style,
            voice_id=profile.voice_id,
            tts_params=profile.tts_params.copy(),
            audio_samples=profile.audio_samples.copy()
        )
        
        batch = self.batches[target_batch_id]
        if character_id not in batch.characters:
            batch.characters.append(character_id)
            self._save_batches_index()
        
        return True
    
    def get_shared_characters(self) -> Dict[str, List[str]]:
        """
        获取跨批次共享的角色
        
        Returns:
            角色ID到批次ID列表的映射
        """
        shared_characters: Dict[str, List[str]] = {}
        
        for batch_id, batch in self.batches.items():
            for character_id in batch.characters:
                if character_id not in shared_characters:
                    shared_characters[character_id] = []
                shared_characters[character_id].append(batch_id)
        
        return {k: v for k, v in shared_characters.items() if len(v) > 1}
    
    def export_batch(
        self,
        batch_id: str,
        export_dir: Path
    ) -> bool:
        """
        导出批次（用于跨项目共享）
        
        Args:
            batch_id: 批次ID
            export_dir: 导出目录
        
        Returns:
            是否成功
        """
        if batch_id not in self.batches:
            return False
        
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            
            voice_manager = self._get_voice_manager(batch_id)
            return voice_manager.export_voice_profiles(export_dir)
        except Exception as e:
            print(f"导出批次失败: {e}")
            return False
    
    def import_batch(
        self,
        batch_id: str,
        batch_name: str,
        import_dir: Path
    ) -> bool:
        """
        导入批次（用于跨项目共享）
        
        Args:
            batch_id: 批次ID
            batch_name: 批次名称
            import_dir: 导入目录
        
        Returns:
            是否成功
        """
        try:
            self.create_batch(batch_id, batch_name)
            
            voice_manager = self._get_voice_manager(batch_id)
            return voice_manager.import_voice_profiles(import_dir)
        except Exception as e:
            print(f"导入批次失败: {e}")
            return False
    
    def get_cross_batch_report(self) -> Dict[str, Any]:
        """
        获取跨批次报告
        
        Returns:
            跨批次报告
        """
        report = {
            "total_batches": len(self.batches),
            "shared_characters": self.get_shared_characters(),
            "batches": [],
            "audio_stats": {
                "total_audio_count": 0,
                "total_duration": 0.0
            }
        }
        
        for batch in self.batches.values():
            batch_info = {
                "batch_id": batch.batch_id,
                "batch_name": batch.batch_name,
                "created_at": batch.created_at,
                "characters_count": len(batch.characters),
                "audio_count": batch.total_audio_count,
                "duration": batch.total_duration
            }
            report["batches"].append(batch_info)
            
            report["audio_stats"]["total_audio_count"] += batch.total_audio_count
            report["audio_stats"]["total_duration"] += batch.total_duration
        
        return report
