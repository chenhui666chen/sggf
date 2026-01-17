from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .voice_consistency_manager import VoiceConsistencyManager
from .cross_batch_audio_manager import CrossBatchAudioManager


class AudioSyncManager:
    """音频同步管理器 - 实现声画同步（通义万相2.6核心能力）"""
    
    def __init__(self, run_dir: Path, batch_id: Optional[str] = None):
        self.run_dir = run_dir
        self.audio_dir = run_dir / "audio"
        self.audio_dir.mkdir(exist_ok=True)
        self.metadata_file = run_dir / "audio_metadata.json"
        
        self.batch_id = batch_id
        
        self.voice_consistency_manager = VoiceConsistencyManager(run_dir)
        self.cross_batch_manager = CrossBatchAudioManager(run_dir)
        
        if batch_id:
            self.cross_batch_manager.create_batch(batch_id, f"批次_{batch_id}")
        
        self._load_metadata()
    
    def _load_metadata(self) -> None:
        """加载音频元数据"""
        self.metadata: Dict[str, Any] = {}
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception:
                pass
    
    def _save_metadata(self) -> None:
        """保存音频元数据"""
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def extract_dialogue_from_text(self, text: str) -> List[Dict[str, Any]]:
        """
        从文本中提取对话
        
        Args:
            text: 文本内容
        
        Returns:
            对话列表，每个包含 text, speaker, start_time, end_time
        """
        dialogues: List[Dict[str, Any]] = []
        
        lines = str(text or "").split("\n")
        current_speaker = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            speaker_match = re.match(r"^([A-Za-z\u4e00-\u9fa5]+)[：:]\s*(.+)$", line)
            if speaker_match:
                current_speaker = speaker_match.group(1)
                dialogue_text = speaker_match.group(2).strip()
                
                if dialogue_text:
                    dialogues.append({
                        "text": dialogue_text,
                        "speaker": current_speaker,
                        "start_time": None,
                        "end_time": None
                    })
            elif current_speaker and line.startswith("-"):
                dialogue_text = line[1:].strip()
                if dialogue_text:
                    dialogues.append({
                        "text": dialogue_text,
                        "speaker": current_speaker,
                        "start_time": None,
                        "end_time": None
                    })
        
        return dialogues
    
    def estimate_dialogue_duration(self, dialogue_text: str, speed: float = 4.0) -> float:
        """
        估算对话时长（秒）
        
        Args:
            dialogue_text: 对话文本
            speed: 语速（字/秒）
        
        Returns:
            估算时长（秒）
        """
        text = re.sub(r"[^\w\u4e00-\u9fa5]", "", dialogue_text)
        char_count = len(text)
        return max(1.0, float(char_count) / speed)
    
    def generate_audio_for_dialogue(
        self,
        shot_id: str,
        dialogue: str,
        character_id: Optional[str] = None,
        voice_style: str = "natural",
        output_filename: Optional[str] = None,
        use_cache: bool = True,
        check_cross_batch: bool = True
    ) -> Optional[str]:
        """
        为对话生成音频（使用Qwen3-TTS）
        
        Args:
            shot_id: 镜头ID
            dialogue: 对话文本
            character_id: 角色ID（用于音色匹配）
            voice_style: 语音风格（natural/emotional/humorous等）
            output_filename: 输出文件名（可选）
            use_cache: 是否使用缓存（默认True）
            check_cross_batch: 是否检查跨批次缓存（默认True）
        
        Returns:
            生成的音频文件路径，失败返回None
        """
        if not dialogue or not dialogue.strip():
            return None
        
        voice_profile_id = f"{character_id}_{voice_style}" if character_id else f"default_{voice_style}"
        
        if use_cache:
            cached_entry = self.voice_consistency_manager.get_cached_audio(
                character_id=character_id or "default",
                dialogue_text=dialogue,
                voice_profile_id=voice_profile_id
            )
            if cached_entry and Path(cached_entry.audio_path).exists():
                return cached_entry.audio_path
            
            if check_cross_batch and self.batch_id:
                cross_batch_entry = self.cross_batch_manager.find_audio_across_batches(
                    character_id=character_id or "default",
                    dialogue_text=dialogue,
                    voice_profile_id=voice_profile_id,
                    preferred_batch_id=self.batch_id
                )
                if cross_batch_entry and Path(cross_batch_entry.audio_path).exists():
                    return cross_batch_entry.audio_path
        
        if output_filename is None:
            output_filename = f"{shot_id}_dialogue.mp3"
        
        output_path = self.audio_dir / output_filename
        
        try:
            from adapters.model_adapters import ModelAdapterFactory
            
            factory = ModelAdapterFactory()
            adapter = factory.get_adapter("qwen3_tts")
            
            result = adapter.generate(
                text=dialogue,
                voice_style=voice_style,
                character_id=character_id
            )
            
            if result.success and result.data:
                audio_data = result.data.get("audio_data")
                if audio_data:
                    import base64
                    audio_bytes = base64.b64decode(audio_data)
                    with open(output_path, "wb") as f:
                        f.write(audio_bytes)
                    
                    self._update_audio_metadata(
                        shot_id=shot_id,
                        audio_path=str(output_path),
                        dialogue=dialogue,
                        character_id=character_id,
                        voice_style=voice_style
                    )
                    
                    if use_cache:
                        self.voice_consistency_manager.cache_audio(
                            character_id=character_id or "default",
                            dialogue_text=dialogue,
                            audio_path=str(output_path),
                            voice_profile_id=voice_profile_id
                        )
                        
                        if self.batch_id:
                            self.cross_batch_manager.cache_audio(
                                batch_id=self.batch_id,
                                character_id=character_id or "default",
                                dialogue_text=dialogue,
                                audio_path=str(output_path),
                                voice_profile_id=voice_profile_id
                            )
                    
                    return str(output_path)
        except Exception as e:
            print(f"生成音频失败: {e}")
        
        return None
    
    def _update_audio_metadata(
        self,
        shot_id: str,
        audio_path: str,
        dialogue: str,
        character_id: Optional[str] = None,
        voice_style: str = "natural"
    ) -> None:
        """更新音频元数据"""
        if "shots" not in self.metadata:
            self.metadata["shots"] = {}
        
        if shot_id not in self.metadata["shots"]:
            self.metadata["shots"][shot_id] = {}
        
        self.metadata["shots"][shot_id]["audio_path"] = audio_path
        self.metadata["shots"][shot_id]["dialogue"] = dialogue
        self.metadata["shots"][shot_id]["character_id"] = character_id
        self.metadata["shots"][shot_id]["voice_style"] = voice_style
        
        self._save_metadata()
    
    def sync_audio_to_video(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        start_time: float = 0.0,
        volume: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0
    ) -> bool:
        """
        将音频同步到视频（实现声画同步）
        
        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            output_path: 输出文件路径
            start_time: 音频开始时间（秒）
            volume: 音频音量（0-1）
            fade_in: 淡入时长（秒）
            fade_out: 淡出时长（秒）
        
        Returns:
            是否成功
        """
        try:
            filters = []
            
            if start_time > 0:
                filters.append(f"adelay={int(start_time * 1000)}|{int(start_time * 1000)}")
            
            if volume != 1.0:
                filters.append(f"volume={volume}")
            
            if fade_in > 0 or fade_out > 0:
                fade_filter = f"afade=t=in:st={start_time}:d={fade_in}"
                if fade_out > 0:
                    fade_filter += f",afade=t=out:st=-{fade_out}:d={fade_out}"
                filters.append(fade_filter)
            
            filter_str = ",".join(filters) if filters else "anull"
            
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                "-af", filter_str,
                output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"音频同步失败: {e}")
            return False
    
    def add_background_music(
        self,
        video_path: str,
        bgm_path: str,
        output_path: str,
        volume: float = 0.3,
        fade_in: float = 1.0,
        fade_out: float = 1.0
    ) -> bool:
        """
        添加背景音乐
        
        Args:
            video_path: 视频文件路径
            bgm_path: 背景音乐路径
            output_path: 输出文件路径
            volume: 背景音乐音量（0-1）
            fade_in: 淡入时长（秒）
            fade_out: 淡出时长（秒）
        
        Returns:
            是否成功
        """
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-i", bgm_path,
                "-filter_complex",
                f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100[aud];[1:a]aformat=sample_fmts=fltp:sample_rates=44100,volume={volume},afade=t=in:st=0:d={fade_in},afade=t=out:st=-{fade_out}:d={fade_out}[bgm];[aud][bgm]amix=inputs=2:duration=first:dropout_transition=2[outa]",
                "-map", "0:v:0",
                "-map", "[outa]",
                "-c:v", "copy",
                "-c:a", "aac",
                output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"添加背景音乐失败: {e}")
            return False
    
    def mix_dialogue_and_bgm(
        self,
        video_path: str,
        dialogue_audio_path: str,
        bgm_path: str,
        output_path: str,
        dialogue_volume: float = 1.0,
        bgm_volume: float = 0.2,
        dialogue_start: float = 0.0
    ) -> bool:
        """
        混合对话音频和背景音乐
        
        Args:
            video_path: 视频文件路径
            dialogue_audio_path: 对话音频路径
            bgm_path: 背景音乐路径
            output_path: 输出文件路径
            dialogue_volume: 对话音量（0-1）
            bgm_volume: 背景音乐音量（0-1）
            dialogue_start: 对话开始时间（秒）
        
        Returns:
            是否成功
        """
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-i", dialogue_audio_path,
                "-i", bgm_path,
                "-filter_complex",
                f"[1:a]adelay={int(dialogue_start * 1000)}|{int(dialogue_start * 1000)},volume={dialogue_volume}[dial];[2:a]volume={bgm_volume}[bgm];[dial][bgm]amix=inputs=2:duration=first:dropout_transition=2[outa]",
                "-map", "0:v:0",
                "-map", "[outa]",
                "-c:v", "copy",
                "-c:a", "aac",
                output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"混合音频失败: {e}")
            return False
    
    def generate_audio_for_storyboard(
        self,
        storyboard: List[Dict[str, Any]],
        character_manager: Any = None
    ) -> Dict[str, str]:
        """
        为分镜批量生成音频
        
        Args:
            storyboard: 分镜列表
            character_manager: 角色管理器（用于获取角色信息）
        
        Returns:
            镜头ID到音频路径的映射
        """
        audio_map: Dict[str, str] = {}
        
        for shot in storyboard:
            if not isinstance(shot, dict):
                continue
            
            shot_id = str(shot.get("shot_id", ""))
            desc = str(shot.get("desc", ""))
            
            if not shot_id:
                continue
            
            dialogues = self.extract_dialogue_from_text(desc)
            
            if not dialogues:
                continue
            
            dialogue = dialogues[0]["text"]
            speaker = dialogues[0].get("speaker")
            
            character_id = None
            voice_style = "natural"
            
            if character_manager and speaker:
                profile = character_manager.get_character_by_name(speaker)
                if profile:
                    character_id = profile.character_id
                    voice_style = profile.voice_style
            
            audio_path = self.generate_audio_for_dialogue(
                shot_id=shot_id,
                dialogue=dialogue,
                character_id=character_id,
                voice_style=voice_style
            )
            
            if audio_path:
                audio_map[shot_id] = audio_path
        
        return audio_map
    
    def get_audio_for_shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        获取镜头的音频信息
        
        Args:
            shot_id: 镜头ID
        
        Returns:
            音频信息字典
        """
        if "shots" not in self.metadata:
            return None
        
        return self.metadata["shots"].get(shot_id)
    
    def get_all_audio_paths(self) -> Dict[str, str]:
        """
        获取所有音频路径
        
        Returns:
            镜头ID到音频路径的映射
        """
        audio_map: Dict[str, str] = {}
        
        if "shots" not in self.metadata:
            return audio_map
        
        for shot_id, shot_data in self.metadata["shots"].items():
            audio_path = shot_data.get("audio_path")
            if audio_path and Path(audio_path).exists():
                audio_map[shot_id] = audio_path
        
        return audio_map
    
    def register_character_voice_profile(
        self,
        character_id: str,
        character_name: str,
        voice_style: str,
        voice_id: str,
        tts_params: Dict[str, Any],
        audio_samples: List[str] = None
    ) -> bool:
        """
        注册角色声音档案（用于跨批次音色一致性）
        
        Args:
            character_id: 角色ID
            character_name: 角色名称
            voice_style: 声音风格
            voice_id: 语音ID
            tts_params: TTS参数
            audio_samples: 音频样本路径列表
        
        Returns:
            是否成功
        """
        try:
            profile = self.voice_consistency_manager.create_voice_profile(
                character_id=character_id,
                character_name=character_name,
                voice_style=voice_style,
                voice_id=voice_id,
                tts_params=tts_params,
                audio_samples=audio_samples or []
            )
            
            if self.batch_id:
                self.cross_batch_manager.register_character(
                    batch_id=self.batch_id,
                    character_id=character_id,
                    character_name=character_name,
                    voice_style=voice_style,
                    voice_id=voice_id,
                    tts_params=tts_params,
                    audio_samples=audio_samples or []
                )
            
            return True
        except Exception as e:
            print(f"注册角色声音档案失败: {e}")
            return False
    
    def get_character_voice_profile(self, character_id: str) -> Optional[Any]:
        """
        获取角色声音档案
        
        Args:
            character_id: 角色ID
        
        Returns:
            声音档案，如果不存在则返回None
        """
        return self.voice_consistency_manager.get_voice_profile(character_id)
    
    def sync_voice_profile_from_batch(
        self,
        source_batch_id: str,
        character_id: str
    ) -> bool:
        """
        从其他批次同步角色声音档案
        
        Args:
            source_batch_id: 源批次ID
            character_id: 角色ID
        
        Returns:
            是否成功
        """
        if not self.batch_id:
            return False
        
        try:
            return self.cross_batch_manager.sync_character_profiles(
                source_batch_id=source_batch_id,
                target_batch_id=self.batch_id,
                character_id=character_id
            )
        except Exception as e:
            print(f"同步角色声音档案失败: {e}")
            return False
    
    def get_voice_consistency_report(self) -> Dict[str, Any]:
        """
        获取音色一致性报告
        
        Returns:
            音色一致性报告
        """
        report = {
            "voice_profiles": self.voice_consistency_manager.get_consistency_report(),
            "cross_batch": self.cross_batch_manager.get_cross_batch_report() if self.batch_id else None
        }
        return report
    
    def export_voice_profiles(self, export_dir: Path) -> bool:
        """
        导出声音档案（用于跨项目共享）
        
        Args:
            export_dir: 导出目录
        
        Returns:
            是否成功
        """
        return self.voice_consistency_manager.export_voice_profiles(export_dir)
    
    def import_voice_profiles(self, import_dir: Path) -> bool:
        """
        导入声音档案（用于跨项目共享）
        
        Args:
            import_dir: 导入目录
        
        Returns:
            是否成功
        """
        return self.voice_consistency_manager.import_voice_profiles(import_dir)
