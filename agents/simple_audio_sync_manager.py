"""
简化的音频同步管理器 - 只保留最佳策略

最佳策略：
1. 使用相同的TTS参数生成音频
2. 缓存已生成的音频，避免重复生成
3. 跨批次复用相同的音频文件（通过共享缓存目录）
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from .simple_voice_consistency_manager import SimpleVoiceConsistencyManager


class SimpleAudioSyncManager:
    """简化的音频同步管理器"""
    
    def __init__(self, run_dir: Path, batch_id: Optional[str] = None):
        self.run_dir = run_dir
        self.audio_dir = run_dir / "audio"
        self.audio_dir.mkdir(exist_ok=True)
        self.metadata_file = run_dir / "audio_metadata.json"
        
        self.batch_id = batch_id
        
        self.voice_consistency_manager = SimpleVoiceConsistencyManager(run_dir)
        
        self._load_metadata()
    
    def _load_metadata(self):
        """加载元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print(f"加载音频元数据失败: {e}")
                self.metadata = {}
        else:
            self.metadata = {}
    
    def _save_metadata(self):
        """保存元数据"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存音频元数据失败: {e}")
    
    def _estimate_audio_duration(self, dialogue_text: str, speed: float = 4.0) -> float:
        """
        估算音频时长
        
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
        voice_id: Optional[str] = None,
        output_filename: Optional[str] = None,
        use_cache: bool = True
    ) -> Optional[str]:
        """
        为对话生成音频（使用Qwen3-TTS）
        
        Args:
            shot_id: 镜头ID
            dialogue: 对话文本
            character_id: 角色ID（用于音色匹配）
            voice_style: 语音风格（natural/emotional/humorous等）
            voice_id: 语音ID（如果为None，则使用默认）
            output_filename: 输出文件名（可选）
            use_cache: 是否使用缓存（默认True）
        
        Returns:
            生成的音频文件路径，失败返回None
        """
        if not dialogue or not dialogue.strip():
            return None
        
        tts_params = {
            "model": "qwen3-tts",
            "voice": voice_id or "Ryan",
            "voice_style": voice_style
        }
        
        if use_cache:
            cached_entry = self.voice_consistency_manager.get_cached_audio(
                dialogue_text=dialogue,
                tts_params=tts_params
            )
            if cached_entry and Path(cached_entry.audio_path).exists():
                return cached_entry.audio_path
        
        if output_filename is None:
            output_filename = f"{shot_id}_dialogue.mp3"
        
        output_path = self.audio_dir / output_filename
        
        try:
            from adapters.adapter_helpers import synthesize_speech_sync

            result = synthesize_speech_sync(
                text=dialogue,
                voice_params={
                    "speaker": voice_id or "Ryan",
                    "voice_style": voice_style,
                    "character_id": character_id,
                    "rate": 1.0,
                    "speed": 1.0,
                    "pitch": 1.0,
                    "volume": 50,
                },
                emotion="neutral",
                model_id="qwen3-tts-instruct-flash",
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
                            dialogue_text=dialogue,
                            audio_path=str(output_path),
                            tts_params=tts_params
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
            import subprocess
            
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
        music_path: str,
        output_path: str,
        volume: float = 0.3
    ) -> bool:
        """
        添加背景音乐
        
        Args:
            video_path: 视频文件路径
            music_path: 音乐文件路径
            output_path: 输出文件路径
            volume: 音乐音量（0-1）
        
        Returns:
            是否成功
        """
        try:
            import subprocess
            
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-i", music_path,
                "-filter_complex",
                f"[1:a]volume={volume}[music];[0:a][music]amix=inputs=2:duration=first",
                "-c:v", "copy",
                "-c:a", "aac",
                output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"添加背景音乐失败: {e}")
            return False
    
    def extract_dialogue_from_text(self, text: str) -> List[Dict[str, Any]]:
        """
        从文本中提取对话
        
        Args:
            text: 文本内容
        
        Returns:
            对话列表
        """
        dialogues = []
        
        dialogue_pattern = r'[""]([^""\n]+)[""]|[""]([^""\n]+)[""]'
        matches = re.findall(dialogue_pattern, text)
        
        for match in matches:
            dialogue = match[0] if match[0] else match[1]
            dialogues.append({
                "text": dialogue,
                "speaker": None
            })
        
        return dialogues
    
    def generate_audio_for_dialogue_batch(
        self,
        dialogues: List[Dict[str, Any]],
        character_manager=None,
        use_cache: bool = True,
        show_progress: bool = True
    ) -> Dict[str, str]:
        """
        批量生成音频
        
        Args:
            dialogues: 对话列表，每个元素包含 shot_id, dialogue, character_id, voice_style, voice_id
            character_manager: 角色管理器（可选）
            use_cache: 是否使用缓存（默认True）
            show_progress: 是否显示进度（默认True）
        
        Returns:
            镜头ID到音频路径的映射
        """
        audio_map: Dict[str, str] = {}
        
        for idx, dialogue_item in enumerate(dialogues):
            if not isinstance(dialogue_item, dict):
                continue
            
            shot_id = str(dialogue_item.get("shot_id", ""))
            dialogue_text = str(dialogue_item.get("dialogue", ""))
            character_id = dialogue_item.get("character_id")
            voice_style = dialogue_item.get("voice_style", "natural")
            voice_id = dialogue_item.get("voice_id")
            
            if not shot_id or not dialogue_text:
                continue
            
            if show_progress:
                print(f"正在生成音频 {idx + 1}/{len(dialogues)}: {shot_id}")
            
            audio_path = self.generate_audio_for_dialogue(
                shot_id=shot_id,
                dialogue=dialogue_text,
                character_id=character_id,
                voice_style=voice_style,
                voice_id=voice_id,
                use_cache=use_cache
            )
            
            if audio_path:
                audio_map[shot_id] = audio_path
        
        return audio_map
    
    def generate_audio_for_storyboard(
        self,
        storyboard: List[Dict[str, Any]],
        character_manager=None
    ) -> Dict[str, str]:
        """
        为故事板生成音频
        
        Args:
            storyboard: 故事板数据
            character_manager: 角色管理器（可选）
        
        Returns:
            镜头ID到音频路径的映射
        """
        dialogues = []
        
        for shot in storyboard:
            if not isinstance(shot, dict):
                continue
            
            shot_id = str(shot.get("shot_id", ""))
            desc = str(shot.get("desc", ""))
            
            if not shot_id:
                continue
            
            dialogues_list = self.extract_dialogue_from_text(desc)
            
            if not dialogues_list:
                continue
            
            dialogue = dialogues_list[0]["text"]
            speaker = dialogues_list[0].get("speaker")
            
            character_id = None
            voice_style = "natural"
            voice_id = None
            
            if character_manager and speaker:
                profile = character_manager.get_character_by_name(speaker)
                if profile:
                    character_id = profile.character_id
                    voice_style = profile.voice_style
                    voice_id = profile.voice_id
            
            dialogues.append({
                "shot_id": shot_id,
                "dialogue": dialogue,
                "character_id": character_id,
                "voice_style": voice_style,
                "voice_id": voice_id
            })
        
        return self.generate_audio_for_dialogue_batch(
            dialogues=dialogues,
            character_manager=character_manager,
            use_cache=True,
            show_progress=True
        )
    
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
    
    def get_voice_consistency_report(self) -> Dict[str, Any]:
        """
        获取音色一致性报告
        
        Returns:
            音色一致性报告
        """
        return self.voice_consistency_manager.get_consistency_report()
    
    def clear_cache(self):
        """清空缓存"""
        self.voice_consistency_manager.clear_cache()
