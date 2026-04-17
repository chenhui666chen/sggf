from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .voice_consistency_manager import VoiceConsistencyManager
from .cross_batch_audio_manager import CrossBatchAudioManager
from .lipsync_manager import LipsyncManager


class AudioSyncManager:
    """音频同步管理器 - 实现声画同步（通义万相2.6核心能力）"""
    
    def __init__(self, run_dir: Path, batch_id: Optional[str] = None, cache_dir: Optional[Path] = None):
        self.run_dir = run_dir
        self.cache_dir = cache_dir or run_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.cache_dir == run_dir:
            self.audio_dir = run_dir / "audio"
        else:
            self.audio_dir = self.cache_dir / "audio_cache_files"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = run_dir / "audio_metadata.json"
        
        self.batch_id = batch_id
        
        self.voice_consistency_manager = VoiceConsistencyManager(self.cache_dir)
        self.cross_batch_manager = CrossBatchAudioManager(self.cache_dir)
        
        if batch_id:
            self.cross_batch_manager.create_batch(batch_id, f"批次_{batch_id}")
        
        self._load_metadata()
        self._tts_timestamps_by_audio: Dict[str, List[Dict[str, Any]]] = {}
        self._phoneme_timestamps_by_audio: Dict[str, List[Dict[str, Any]]] = {}
    
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

    def get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长（秒）"""
        if not audio_path:
            return 0.0
        return self.voice_consistency_manager._get_audio_duration(audio_path)

    def build_dialogue_tracks(
        self,
        *,
        shot_id: str,
        dialogues: List[Dict[str, Any]],
        character_manager: Any = None,
        target_duration_s: Optional[float] = None,
        speed_floor: float = 0.6,
        speed_ceiling: float = 1.8,
    ) -> List[Dict[str, Any]]:
        """基于对话列表生成TTS音频，返回带时间轴的dialogue tracks。"""
        if not dialogues:
            return []

        base_speed = 4.0
        speed = 1.0
        if target_duration_s and target_duration_s > 0:
            estimated_total = sum(
                self.estimate_dialogue_duration(d.get("text", ""), speed=base_speed) for d in dialogues
            )
            if estimated_total > 0:
                speed = max(speed_floor, min(speed_ceiling, estimated_total / float(target_duration_s)))

        tracks: List[Dict[str, Any]] = []
        cursor = 0.0
        for idx, dialogue in enumerate(dialogues, 1):
            text = str(dialogue.get("text") or "").strip()
            if not text:
                continue
            speaker = str(dialogue.get("speaker") or "").strip()

            character_id = None
            voice_style = "natural"
            voice_id = None
            voice_profile_id = None
            if character_manager and speaker:
                profile = character_manager.get_character_by_name(speaker)
                if profile:
                    character_id = profile.character_id
                    voice_style = profile.voice_style or "natural"
                    voice_id = (profile.voice_id or "").strip() or None
                    voice_profile_id = (profile.voice_profile_id or "").strip() or None

            audio_path = self.generate_audio_for_dialogue(
                shot_id=shot_id,
                dialogue=text,
                character_id=character_id,
                character_name=speaker,
                voice_style=voice_style,
                voice_id=voice_id,
                voice_profile_id=voice_profile_id,
                output_filename=f"{shot_id}_dialogue_{idx}.mp3",
                speed=speed,
            )
            duration_s = 0.0
            if audio_path:
                duration_s = self.get_audio_duration(audio_path)
            if duration_s <= 0.0:
                duration_s = self.estimate_dialogue_duration(text, speed=base_speed * max(speed, 0.1))

            tts_timestamps = None
            phoneme_timestamps = None
            if audio_path:
                tts_timestamps = self._tts_timestamps_by_audio.get(audio_path)
                phoneme_timestamps = self._phoneme_timestamps_by_audio.get(audio_path)
            if not tts_timestamps and not phoneme_timestamps:
                shot_meta = self.metadata.get("shots", {}).get(shot_id)
                if isinstance(shot_meta, dict):
                    tts_timestamps = shot_meta.get("tts_timestamps")
                    phoneme_timestamps = shot_meta.get("phoneme_timestamps")
            start_s = cursor
            end_s = start_s + duration_s
            cursor = end_s

            track = {
                "shot_id": shot_id,
                "speaker": speaker,
                "text": text,
                "audio_path": audio_path,
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": duration_s,
                "voice_style": voice_style,
                "character_id": character_id,
                "voice_id": voice_id,
                "voice_profile_id": voice_profile_id,
                "tts_speed": speed,
            }
            if isinstance(tts_timestamps, list) and tts_timestamps:
                track["tts_timestamps"] = tts_timestamps
            if isinstance(phoneme_timestamps, list) and phoneme_timestamps:
                track["phoneme_timestamps"] = phoneme_timestamps
            tracks.append(track)

        if target_duration_s and target_duration_s > 0 and tracks:
            target = float(target_duration_s)
            total = float(tracks[-1].get("end_s") or 0.0)
            if total > 0:
                if total > target:
                    scale = target / total
                    for track in tracks:
                        start_s = float(track.get("start_s") or 0.0) * scale
                        end_s = float(track.get("end_s") or 0.0) * scale
                        track["start_s"] = start_s
                        track["end_s"] = end_s
                        track["duration_s"] = max(0.01, end_s - start_s)
                elif total < target:
                    gap_count = max(len(tracks) - 1, 0)
                    if gap_count == 0:
                        track = tracks[0]
                        track["start_s"] = 0.0
                        track["end_s"] = target
                        track["duration_s"] = max(float(track.get("duration_s") or 0.0), target)
                    else:
                        gap_s = (target - total) / float(gap_count)
                        cursor = 0.0
                        for idx, track in enumerate(tracks):
                            duration_s = float(track.get("duration_s") or 0.0)
                            start_s = cursor
                            end_s = start_s + duration_s
                            track["start_s"] = start_s
                            track["end_s"] = end_s
                            if idx < len(tracks) - 1:
                                cursor = end_s + gap_s
                            else:
                                cursor = end_s
                        last = tracks[-1]
                        if float(last.get("end_s") or 0.0) < target:
                            last["end_s"] = target
                            last["duration_s"] = max(
                                float(last.get("duration_s") or 0.0),
                                target - float(last.get("start_s") or 0.0),
                            )

        return tracks

    def build_viseme_tracks(
        self,
        tracks: List[Dict[str, Any]],
        *,
        mode: str = "estimate",
    ) -> List[Dict[str, Any]]:
        if not tracks:
            return []
        manager = LipsyncManager(mode=mode)
        return manager.build_tracks(tracks)

    def format_audio_sync_text(
        self,
        tracks: List[Dict[str, Any]],
        *,
        max_lines: int = 6,
        max_chars: int = 360,
    ) -> str:
        """格式化声画同步提示，用于 Wan2.7 上层 prompt。"""
        if not tracks:
            return ""

        lines: List[str] = []
        for track in tracks[: max_lines]:
            text = str(track.get("text") or "").strip()
            if not text:
                continue
            if len(text) > 40:
                text = text[:40].rstrip() + "..."
            speaker = str(track.get("speaker") or "").strip()
            start_s = float(track.get("start_s") or 0.0)
            end_s = float(track.get("end_s") or 0.0)
            prefix = f"[{start_s:.1f}-{end_s:.1f}s]"
            if speaker:
                lines.append(f"{prefix} {speaker}: {text}")
            else:
                lines.append(f"{prefix} {text}")

        if not lines:
            return ""

        text = "声画同步：" + " | ".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars].rstrip(" ,|")
        return text

    def build_audio_markers_from_tracks(self, tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从dialogue tracks生成声画同步标记。"""
        markers: List[Dict[str, Any]] = []
        for track in tracks:
            speaker = str(track.get("speaker") or "").strip()
            text = str(track.get("text") or "").strip()
            start_s = float(track.get("start_s") or 0.0)
            duration_s = float(track.get("duration_s") or 0.0)
            if not text:
                continue
            markers.append(
                {
                    "marker_type": "dialogue",
                    "time_s": start_s,
                    "duration_s": duration_s,
                    "description": f"{speaker}: {text}" if speaker else text,
                    "character_name": speaker,
                    "dialogue_text": text,
                }
            )
        return markers
    
    def generate_audio_for_dialogue(
        self,
        shot_id: str,
        dialogue: str,
        character_id: Optional[str] = None,
        character_name: Optional[str] = None,
        voice_style: str = "natural",
        voice_id: Optional[str] = None,
        voice_profile_id: Optional[str] = None,
        speed: float = 1.0,
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
            character_name: 角色名称（用于声音档案）
            voice_style: 语音风格（natural/emotional/humorous等）
            voice_id: 语音ID（优先使用）
            voice_profile_id: 角色音色档案ID（用于缓存维度）
            output_filename: 输出文件名（可选）
            use_cache: 是否使用缓存（默认True）
            check_cross_batch: 是否检查跨批次缓存（默认True）
        
        Returns:
            生成的音频文件路径，失败返回None
        """
        if not dialogue or not dialogue.strip():
            return None
        
        resolved_voice_style = voice_style or "natural"
        resolved_voice_id = (voice_id or "").strip() or None
        resolved_profile_id = (voice_profile_id or "").strip() or None

        if character_id:
            existing_profile = self.voice_consistency_manager.get_voice_profile(character_id)
            if existing_profile:
                if not resolved_voice_id or not resolved_profile_id:
                    stored_voice_id, stored_profile_id = self.voice_consistency_manager.resolve_voice_ids(character_id)
                    if not resolved_voice_id:
                        resolved_voice_id = stored_voice_id
                    if not resolved_profile_id:
                        resolved_profile_id = stored_profile_id
                if not resolved_profile_id and resolved_voice_id:
                    resolved_profile_id = resolved_voice_id
                if not voice_style:
                    resolved_voice_style = existing_profile.voice_style or resolved_voice_style

        tts_voice_id = resolved_profile_id or resolved_voice_id
        if character_id and tts_voice_id:
            tts_params = {"voice_style": resolved_voice_style}
            if resolved_voice_id:
                tts_params["voice_id"] = resolved_voice_id
            if resolved_profile_id:
                tts_params["voice_profile_id"] = resolved_profile_id
            self.register_character_voice_profile(
                character_id=character_id,
                character_name=character_name or character_id,
                voice_style=resolved_voice_style,
                voice_id=tts_voice_id,
                tts_params=tts_params,
            )

        speed_tag = f"{float(speed):.2f}"
        cache_character_id = character_id or "default"
        voice_key = resolved_profile_id or resolved_voice_id
        profile_key = f"{cache_character_id}_{voice_key}" if voice_key else cache_character_id
        cache_profile_id = f"{profile_key}_{resolved_voice_style}_spd{speed_tag}"
        
        if use_cache:
            cached_entry = self.voice_consistency_manager.get_cached_audio(
                character_id=cache_character_id,
                dialogue_text=dialogue,
                voice_profile_id=cache_profile_id
            )
            if cached_entry and Path(cached_entry.audio_path).exists():
                return cached_entry.audio_path
            
            if check_cross_batch and self.batch_id:
                cross_batch_entry = self.cross_batch_manager.find_audio_across_batches(
                    character_id=cache_character_id,
                    dialogue_text=dialogue,
                    voice_profile_id=cache_profile_id,
                    preferred_batch_id=self.batch_id
                )
                if cross_batch_entry and Path(cross_batch_entry.audio_path).exists():
                    return cross_batch_entry.audio_path
        
        if output_filename is None:
            output_filename = f"{shot_id}_dialogue.mp3"

        output_path = self.audio_dir / output_filename
        if self.cache_dir != self.run_dir:
            cache_id = self.voice_consistency_manager._generate_cache_id(
                character_id=cache_character_id,
                dialogue_text=dialogue,
                voice_profile_id=cache_profile_id,
            )
            output_path = self.audio_dir / f"{cache_id}.mp3"
        
        try:
            from adapters.adapter_helpers import synthesize_speech_sync

            result = synthesize_speech_sync(
                text=dialogue,
                voice_params={
                    "speaker": tts_voice_id or "Ryan",
                    "voice_style": resolved_voice_style,
                    "character_id": character_id,
                    "rate": speed,
                    "speed": speed,
                    "pitch": 1.0,
                    "volume": 50,
                },
                emotion="neutral",
                model_id="qwen3-tts-flash",
            )
            
            if result.success and result.data:
                audio_data = result.data.get("audio_data")
                if audio_data:
                    tts_timestamps = None
                    phoneme_timestamps = None
                    if isinstance(result.data, dict):
                        tts_timestamps = result.data.get("tts_timestamps")
                        if not isinstance(tts_timestamps, list):
                            tts_timestamps = result.data.get("word_timestamps")
                        phoneme_timestamps = result.data.get("phoneme_timestamps")
                    import base64
                    audio_bytes = base64.b64decode(audio_data)
                    with open(output_path, "wb") as f:
                        f.write(audio_bytes)
                        if isinstance(tts_timestamps, list) and tts_timestamps:
                            self._tts_timestamps_by_audio[str(output_path)] = tts_timestamps
                        if isinstance(phoneme_timestamps, list) and phoneme_timestamps:
                            self._phoneme_timestamps_by_audio[str(output_path)] = phoneme_timestamps
                    
                    self._update_audio_metadata(
                        shot_id=shot_id,
                        audio_path=str(output_path),
                        dialogue=dialogue,
                        character_id=character_id,
                        voice_style=resolved_voice_style,
                        tts_timestamps=tts_timestamps,
                        phoneme_timestamps=phoneme_timestamps,
                    )
                    
                    if use_cache:
                        self.voice_consistency_manager.cache_audio(
                            character_id=cache_character_id,
                            dialogue_text=dialogue,
                            audio_path=str(output_path),
                            voice_profile_id=cache_profile_id
                        )
                        
                        if self.batch_id:
                            self.cross_batch_manager.cache_audio(
                                batch_id=self.batch_id,
                                character_id=cache_character_id,
                                dialogue_text=dialogue,
                                audio_path=str(output_path),
                                voice_profile_id=cache_profile_id
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
        voice_style: str = "natural",
        tts_timestamps: Optional[List[Dict[str, Any]]] = None,
        phoneme_timestamps: Optional[List[Dict[str, Any]]] = None,
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
        if isinstance(tts_timestamps, list) and tts_timestamps:
            self.metadata["shots"][shot_id]["tts_timestamps"] = tts_timestamps
        if isinstance(phoneme_timestamps, list) and phoneme_timestamps:
            self.metadata["shots"][shot_id]["phoneme_timestamps"] = phoneme_timestamps
        
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
            voice_id = None
            voice_profile_id = None
            
            if character_manager and speaker:
                profile = character_manager.get_character_by_name(speaker)
                if profile:
                    character_id = profile.character_id
                    voice_style = profile.voice_style
                    voice_id = (profile.voice_id or "").strip() or None
                    voice_profile_id = (profile.voice_profile_id or "").strip() or None
            
            audio_path = self.generate_audio_for_dialogue(
                shot_id=shot_id,
                dialogue=dialogue,
                character_id=character_id,
                character_name=speaker,
                voice_style=voice_style,
                tts_timestamps=tts_timestamps,
                phoneme_timestamps=phoneme_timestamps,
                voice_id=voice_id,
                voice_profile_id=voice_profile_id
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
            existing_profile = self.voice_consistency_manager.get_voice_profile(character_id)
            if existing_profile:
                profile = self.voice_consistency_manager.update_voice_profile(
                    character_id=character_id,
                    voice_style=voice_style,
                    tts_timestamps=tts_timestamps,
                    phoneme_timestamps=phoneme_timestamps,
                    voice_id=voice_id,
                    tts_params=tts_params,
                    audio_samples=audio_samples if audio_samples is not None else None,
                )
            else:
                profile = self.voice_consistency_manager.create_voice_profile(
                    character_id=character_id,
                    character_name=character_name,
                    voice_style=voice_style,
                    tts_timestamps=tts_timestamps,
                    phoneme_timestamps=phoneme_timestamps,
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
                    tts_timestamps=tts_timestamps,
                    phoneme_timestamps=phoneme_timestamps,
                    voice_id=voice_id,
                    tts_params=tts_params,
                    audio_samples=audio_samples
                )
            
            return profile is not None
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
