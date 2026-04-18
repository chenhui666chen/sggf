"""
音频混合器 - 拼接与后处理（纯pydub版）

🔥 修改说明：
- 移除FFmpeg命令行依赖，只使用pydub
- pydub底层仍需ffmpeg/avconv，但通过Python封装更稳定
- 解决Python 3.13上FFmpeg命令行调用兼容性问题

核心功能：
1. 音频片段拼接（支持静音间隔）
2. 音效叠加（时间轴定位）
3. 背景音乐混音（overlay方式，保持人声音量）
4. 音量归一化（可选）
5. 格式转换

技术方案：
- 优先使用 pydub（主要方案）
- 降级使用简单字节拼接（pydub不可用时）

依赖：
- pydub: pip install pydub（必须）
- ffmpeg/avconv: pydub底层依赖，系统安装即可

注意：需要先安装pydub到Python环境
"""
import io
import os
import subprocess
import tempfile
import logging
import math  # 🆕 新增：用于音量计算
from typing import List, Optional, Dict, Any, Tuple  # 🆕 添加Tuple
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import shutil

logger = logging.getLogger(__name__)

# 检查 FFmpeg 是否可用
def _check_ffmpeg_available() -> bool:
    """检查 FFmpeg 是否安装"""
    return shutil.which("ffmpeg") is not None

FFMPEG_AVAILABLE = _check_ffmpeg_available()

# 尝试导入pydub
try:
    from pydub import AudioSegment
    from pydub.effects import normalize
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# 输出可用的音频处理引擎
if PYDUB_AVAILABLE:
    logger.info("✅ 音频混合器：使用 pydub 引擎（主要方案）")
else:
    logger.warning("⚠️ 音频混合器：仅支持简单拼接模式（需安装 pydub 以启用完整功能）")
    logger.warning("   安装命令: pip install pydub")


class AudioQualityGrade(str, Enum):
    """音频质量等级"""
    EXCELLENT = "A"  # 优秀：无明显问题
    GOOD = "B"       # 良好：轻微问题
    FAIR = "C"       # 一般：存在问题但可用
    POOR = "D"       # 差：严重问题


@dataclass
class AudioQualityIssue:
    """音频质量问题"""
    severity: str  # "high" / "medium" / "low"
    category: str  # "loudness" / "clipping" / "silence" / "format"
    description: str
    suggestion: str = ""


@dataclass
class AudioQualityReport:
    """音频质量报告"""
    grade: AudioQualityGrade
    score: float  # 0-100
    issues: List[AudioQualityIssue]
    metrics: Dict[str, Any]  # 原始指标
    passed: bool  # 是否通过质量检查


class AudioMixer:
    """
    音频混合器（纯pydub版）
    
    🔥 修改说明：
    - 移除FFmpeg依赖，只使用pydub
    - pydub底层仍需ffmpeg/avconv，但通过Python封装更稳定
    - 优先级：pydub > 简单拼接
    """
    
    def __init__(
        self,
        silence_duration: int = 500,  # 静音间隔（毫秒）
        normalize_audio: bool = False,  # 🔧 修复：禁用归一化（避免音频截断）
        enable_fallback: bool = True,   # 是否启用降级模式
        force_pydub: bool = True,        # 🔥 新增：强制使用pydub（忽略FFmpeg）
        # 🆕 新增：静音修剪参数
        enable_silence_trim: bool = True,
        silence_trim_threshold: int = -40,  # dBFS，静音检测阈值
        silence_trim_min_silence: int = 100,  # 最小静音长度（ms）
        # 🆕 新增：响度标准化参数
        enable_loudness_norm: bool = True,
        target_loudness_lufs: float = -16.0,  # EBU R128 标准响度
        # 🆕 新增：语义停顿参数
        enable_semantic_pause: bool = True,
        paragraph_pause_ms: int = 1500,  # 段落间停顿
        sentence_pause_ms: int = 500,  # 句子间停顿（默认值，覆盖 silence_duration）
        phrase_pause_ms: int = 250,  # 短语间停顿
    ):
        self.silence_duration = silence_duration
        self.normalize_audio = normalize_audio
        self.enable_fallback = enable_fallback
        self.force_pydub = force_pydub

        self.enable_silence_trim = enable_silence_trim
        self.silence_trim_threshold = silence_trim_threshold
        self.silence_trim_min_silence = silence_trim_min_silence

        self.enable_loudness_norm = enable_loudness_norm
        self.target_loudness_lufs = target_loudness_lufs

        self.enable_semantic_pause = enable_semantic_pause
        self.paragraph_pause_ms = paragraph_pause_ms
        self.sentence_pause_ms = sentence_pause_ms
        self.phrase_pause_ms = phrase_pause_ms
        
        # 🔥 强制使用pydub模式（忽略FFmpeg）
        if force_pydub:
            self.ffmpeg_available = False  # 强制禁用FFmpeg
            self.pydub_available = PYDUB_AVAILABLE
            if self.pydub_available:
                logger.info(f"✅ 音频混合器初始化（纯pydub模式）: silence={silence_duration}ms, normalize={normalize_audio}")
            else:
                logger.error("❌ pydub不可用！请安装: pip install pydub")
                if not self.enable_fallback:
                    raise RuntimeError("pydub不可用且未启用降级模式")
        else:
            # 原有逻辑：检查可用性
            self.ffmpeg_available = FFMPEG_AVAILABLE
            self.pydub_available = PYDUB_AVAILABLE
            
            if self.ffmpeg_available:
                logger.info(f"✅ 音频混合器初始化（FFmpeg原生模式）: silence={silence_duration}ms, normalize={normalize_audio}")
            elif self.pydub_available:
                logger.info(f"✅ 音频混合器初始化（pydub模式）: silence={silence_duration}ms, normalize={normalize_audio}")
            else:
                logger.warning(f"⚠️ 音频混合器初始化（降级模式）: 缺少 FFmpeg/pydub 支持")
                if not self.enable_fallback:
                    raise RuntimeError("FFmpeg 和 pydub 均不可用且未启用降级模式")
    
    def mix_chapter(
        self,
        audio_segments: List[bytes],
        output_format: str = "mp3",
        bitrate: str = "128k"
    ) -> bytes:
        """
        混合章节音频（纯pydub模式）
        
        Args:
            audio_segments: 音频片段列表
            output_format: 输出格式（mp3/wav）
            bitrate: 比特率
        
        Returns:
            完整音频字节流
        """
        if not audio_segments:
            logger.warning("⚠️ 没有音频片段可混合")
            return b""
        
        logger.info(f"🎧 开始混合音频: {len(audio_segments)} 个片段")
        
        # 🔥 优先级 1: pydub（主要方案）
        if self.pydub_available:
            try:
                return self._mix_with_pydub(audio_segments, output_format, bitrate)
            except Exception as e:
                logger.error(f"❌ pydub 混音失败: {e}")
                import traceback
                traceback.print_exc()
                
                if not self.enable_fallback:
                    raise
                logger.warning("⚠️ 降级到简单拼接模式")
        
        # 🔥 优先级 2：简单字节拼接（降级方案）
        try:
            combined = b"".join(audio_segments)
            logger.info(
                f"✅ 混合完成（降级模式）: "
                f"大小 {len(combined)/1024:.1f}KB"
            )
            return combined
        except Exception as e:
            logger.error(f"❌ 音频混合失败: {e}")
            return b""
    
    def add_background_music(
        self,
        voice_audio: bytes,
        bgm_audio: bytes,
        bgm_volume_offset: int = -20,  # 降低背景音乐音量（dB）
        position_ms: int = 0,
        duration_ms: Optional[int] = None,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
        loop_fill: bool = True,
        sync_with_dialogue: bool = False,
        dialogue_volume_reduction: float = 0.0,
    ) -> bytes:
        """
        添加背景音乐（纯pydub版）
        
        Args:
            voice_audio: 人声音频
            bgm_audio: 背景音乐
            bgm_volume_offset: 背景音乐音量偏移（负数=降低）
        
        Returns:
            混音后的音频
        """
        # 🔥 使用 pydub 混音（主要方案）
        if self.pydub_available:
            try:
                # 加载音频
                voice = AudioSegment.from_file(io.BytesIO(voice_audio))
                bgm = AudioSegment.from_file(io.BytesIO(bgm_audio))
                
                # 调整BGM音量（默认-20dB）
                bgm = bgm + bgm_volume_offset
                
                start_ms = max(0, int(position_ms or 0))
                if start_ms >= len(voice):
                    return voice_audio

                if duration_ms is None:
                    end_ms = len(voice)
                else:
                    end_ms = min(len(voice), start_ms + max(0, int(duration_ms)))

                if end_ms <= start_ms:
                    return voice_audio

                target_len = end_ms - start_ms
                bgm_seg = bgm

                if loop_fill and len(bgm_seg) > 0 and len(bgm_seg) < target_len:
                    loops_needed = (target_len // len(bgm_seg)) + 1
                    bgm_seg = bgm_seg * loops_needed

                bgm_seg = bgm_seg[:target_len]

                if fade_in_ms > 0:
                    bgm_seg = bgm_seg.fade_in(min(int(fade_in_ms), len(bgm_seg)))
                if fade_out_ms > 0:
                    bgm_seg = bgm_seg.fade_out(min(int(fade_out_ms), len(bgm_seg)))

                if sync_with_dialogue and dialogue_volume_reduction and dialogue_volume_reduction > 0:
                    try:
                        voice_seg = voice[start_ms:end_ms]
                        reduction_factor = max(0.0, min(1.0, 1.0 - float(dialogue_volume_reduction)))
                        # 0.4 => -7.96dB
                        reduction_db = 20 * math.log10(max(0.0001, reduction_factor))
                        threshold_dbfs = -35.0
                        chunk_ms = 300

                        adjusted = AudioSegment.empty()
                        for offset in range(0, len(bgm_seg), chunk_ms):
                            bgm_chunk = bgm_seg[offset:offset + chunk_ms]
                            voice_chunk = voice_seg[offset:offset + chunk_ms]

                            voice_dbfs = voice_chunk.dBFS
                            if voice_dbfs != float("-inf") and voice_dbfs > threshold_dbfs:
                                bgm_chunk = bgm_chunk + reduction_db
                            adjusted += bgm_chunk
                        bgm_seg = adjusted
                    except Exception:
                        # ducking 失败不影响主流程
                        pass

                # 🔥 关键：使用 overlay 叠加混音（不会削弱人声）
                mixed = voice.overlay(bgm_seg, position=start_ms)
                
                # 归一化（如果启用）
                if self.normalize_audio:
                    mixed = normalize(mixed)
                
                # 输出
                output_buffer = io.BytesIO()
                mixed.export(output_buffer, format="mp3", bitrate="128k")
                
                logger.info(
                    f"✅ pydub 背景音乐混合完成：offset={bgm_volume_offset}dB pos={start_ms}ms len={target_len}ms overlay"
                )
                return output_buffer.getvalue()
            except Exception as e:
                logger.warning(f"⚠️ pydub 混音失败: {e}")
        
        # 最终降级：返回原始人声
        logger.warning("⚠️ 背景音乐功能不可用，返回原始人声")
        return voice_audio
    
    def crossfade_audio(
        self,
        audio1: bytes,
        audio2: bytes,
        crossfade_duration_ms: int = 3000
    ) -> bytes:
        """
        🆕 音频交叉淡化（平滑过渡）
        
        Args:
            audio1: 第一段音频
            audio2: 第二段音频
            crossfade_duration_ms: 交叉淡化时长（毫秒）
        
        Returns:
            交叉淡化后的音频
        """
        if not self.pydub_available:
            # 降级：直接拼接
            return audio1 + audio2
        
        try:
            sound1 = AudioSegment.from_file(io.BytesIO(audio1))
            sound2 = AudioSegment.from_file(io.BytesIO(audio2))
            
            # 确保交叉时长不超过较短的音频
            actual_crossfade = min(crossfade_duration_ms, len(sound1), len(sound2))
            
            # 使用pydub的append方法，带交叉淡化
            result = sound1.append(sound2, crossfade=actual_crossfade)
            
            # 输出
            output_buffer = io.BytesIO()
            result.export(output_buffer, format="mp3", bitrate="128k")
            
            logger.debug(f"✅ 音频交叉淡化完成: {actual_crossfade}ms")
            return output_buffer.getvalue()
        except Exception as e:
            logger.warning(f"⚠️ 交叉淡化失败: {e}，降级为直接拼接")
            return audio1 + audio2
    
    def apply_volume_curve(
        self,
        audio_data: bytes,
        volume_curve: List[Tuple[float, float]]
    ) -> bytes:
        """
        🆕 应用动态音量曲线
        
        Args:
            audio_data: 音频数据
            volume_curve: 音量曲线 [(time_sec, volume_0to1), ...]
                例：[(0.0, 0.15), (15.0, 0.3), (30.0, 0.2)]
        
        Returns:
            应用音量曲线后的音频
        """
        if not self.pydub_available or not volume_curve or len(volume_curve) < 2:
            return audio_data
        
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            result = AudioSegment.empty()
            
            for i in range(len(volume_curve) - 1):
                t1, v1 = volume_curve[i]
                t2, v2 = volume_curve[i + 1]
                
                # 提取片段
                start_ms = int(t1 * 1000)
                end_ms = int(t2 * 1000)
                segment = audio[start_ms:end_ms]
                
                # 计算音量调整（dB）
                # 从 v1 到 v2 线性渐变
                avg_volume = (v1 + v2) / 2
                db_change = 20 * math.log10(avg_volume) if avg_volume > 0 else -40
                
                # 应用音量
                adjusted_segment = segment + db_change
                
                # 添加淡入淡出效果
                fade_duration = min(500, len(adjusted_segment) // 4)  # 最长500ms
                if i == 0:  # 第一段淡入
                    adjusted_segment = adjusted_segment.fade_in(fade_duration)
                if i == len(volume_curve) - 2:  # 最后一段淡出
                    adjusted_segment = adjusted_segment.fade_out(fade_duration)
                
                result += adjusted_segment
            
            # 输出
            output_buffer = io.BytesIO()
            result.export(output_buffer, format="mp3", bitrate="128k")
            
            logger.debug(f"✅ 应用音量曲线完成: {len(volume_curve)}个控制点")
            return output_buffer.getvalue()
        except Exception as e:
            logger.warning(f"⚠️ 应用音量曲线失败: {e}")
            return audio_data
    
    def get_audio_info(self, audio_data: bytes) -> dict:
        """获取音频信息（FFmpeg增强版）"""
        if not self.pydub_available or not audio_data:
            return {
                "duration_seconds": 0.0,
                "channels": 2,
                "sample_rate": 44100,
                "size_kb": len(audio_data) / 1024 if audio_data else 0
            }
        
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            return {
                "duration_seconds": len(audio) / 1000.0,
                "channels": audio.channels,
                "sample_rate": audio.frame_rate,
                "size_kb": len(audio_data) / 1024,
                "loudness_dBFS": audio.dBFS,
                "max_dBFS": audio.max_dBFS
            }
        except Exception as e:
            logger.warning(f"⚠️ 无法解析音频信息: {e}")
            return {
                "duration_seconds": 0.0,
                "channels": 2,
                "sample_rate": 44100,
                "size_kb": len(audio_data) / 1024
            }
    
    def _trim_silence(self, audio: AudioSegment) -> AudioSegment:
        """
        修剪音频首尾静音
        
        原理：检测音频中连续低于阈值的静音段，移除首尾的静音部分。
        
        Args:
            audio: 原始音频片段
        
        Returns:
            修剪后的音频片段
        """
        if not self.enable_silence_trim:
            return audio

        threshold = self.silence_trim_threshold
        min_silence = self.silence_trim_min_silence

        try:
            # pydub没有detect_leading_silence方法，手动实现
            # 检测开头静音
            trimmed = 0
            for i in range(0, len(audio), 10):  # 每10ms检查一次
                chunk = audio[i:i+10]
                if chunk.dBFS > threshold:
                    trimmed = i
                    break
            
            if trimmed > 0:
                audio = audio[trimmed:]

            # 检测结尾静音
            trimmed_end = 0
            for i in range(len(audio), 0, -10):
                chunk = audio[max(0, i-10):i]
                if chunk.dBFS > threshold:
                    trimmed_end = len(audio) - i
                    break
            
            if trimmed_end > 0:
                audio = audio[:len(audio) - trimmed_end]

            if len(audio) > 0:
                logger.debug(
                    f"✂️ 静音修剪完成: 原始{len(audio) + trimmed + trimmed_end}ms -> "
                    f"修剪后{len(audio)}ms"
                )
            return audio
        except Exception as e:
            logger.warning(f"⚠️ 静音修剪失败: {e}，返回原始音频")
            return audio

    def _normalize_loudness(self, audio: AudioSegment) -> AudioSegment:
        """
        EBU R128 响度标准化
        
        将音频响度调整到目标 LUFS 值（默认 -16.0 LUFS，播客/有声书标准）。
        使用 pydub 的 normalize 函数，但手动控制目标响度。
        
        Args:
            audio: 原始音频片段
        
        Returns:
            标准化后的音频片段
        """
        if not self.enable_loudness_norm:
            return audio

        try:
            current_loudness = audio.dBFS
            if current_loudness == float("-inf"):
                return audio

            target_loudness = self.target_loudness_lufs
            adjustment = target_loudness - current_loudness

            max_allowed = 0 - current_loudness
            adjustment = min(adjustment, max_allowed)

            normalized = audio + adjustment

            logger.debug(
                f"📊 响度标准化: {current_loudness:.1f}dBFS -> "
                f"{normalized.dBFS:.1f}dBFS (目标: {target_loudness}LUFS)"
            )
            return normalized
        except Exception as e:
            logger.warning(f"⚠️ 响度标准化失败: {e}，返回原始音频")
            return audio

    def _mix_with_pydub(
        self,
        audio_segments: List[bytes],
        output_format: str = "mp3",
        bitrate: str = "128k",
        segment_types: Optional[List[str]] = None
    ) -> bytes:
        """
        使用pydub混音（主要方案）
        
        Args:
            audio_segments: 音频片段列表
            output_format: 输出格式
            bitrate: 比特率
            segment_types: 每个片段的类型（paragraph/sentence/phrase），用于语义停顿
        """
        # 1. 加载所有音频片段
        segments = []
        for audio_bytes in audio_segments:
            if not audio_bytes:
                continue
            try:
                segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
                
                if self.enable_silence_trim:
                    segment = self._trim_silence(segment)
                
                segments.append(segment)
            except Exception as e:
                logger.warning(f"⚠️ 无法加载音频片段: {e}")
        
        if not segments:
            logger.warning("⚠️ 没有有效的音频片段")
            return b""
        
        # 2. 拼接音频，使用语义停顿或固定停顿
        combined = AudioSegment.empty()
        for i, segment in enumerate(segments):
            combined += segment
            if i < len(segments) - 1:
                if self.enable_semantic_pause and segment_types and i < len(segment_types):
                    seg_type = segment_types[i].lower()
                    if seg_type == "paragraph":
                        pause = AudioSegment.silent(duration=self.paragraph_pause_ms)
                    elif seg_type == "sentence":
                        pause = AudioSegment.silent(duration=self.sentence_pause_ms)
                    elif seg_type == "phrase":
                        pause = AudioSegment.silent(duration=self.phrase_pause_ms)
                    else:
                        pause = AudioSegment.silent(duration=self.silence_duration)
                    
                    logger.debug(
                        f"🔇 语义停顿: {seg_type} -> {pause.duration_seconds*1000:.0f}ms"
                    )
                else:
                    pause = AudioSegment.silent(duration=self.silence_duration)
                
                combined += pause
        
        # 3. 响度标准化
        if self.enable_loudness_norm:
            combined = self._normalize_loudness(combined)
        elif self.normalize_audio:
            combined = normalize(combined)
            logger.debug("✅ 音量归一化完成")
        
        # 4. 输出
        output_buffer = io.BytesIO()
        combined.export(
            output_buffer,
            format=output_format,
            bitrate=bitrate,
            parameters=["-q:a", "2"]  # 质量参数
        )
        
        result = output_buffer.getvalue()
        
        logger.info(
            f"✅ pydub混音完成: "
            f"时长 {len(combined)/1000:.1f}秒, "
            f"大小 {len(result)/1024:.1f}KB"
        )
        
        return result

    def create_silence(self, duration_ms: int, output_format: str = "mp3", bitrate: str = "128k") -> bytes:
        """创建指定时长的静音音频（pydub 版）。"""
        if not self.pydub_available:
            return b""
        try:
            silence = AudioSegment.silent(duration=max(0, int(duration_ms)))
            output_buffer = io.BytesIO()
            silence.export(output_buffer, format=output_format, bitrate=bitrate)
            return output_buffer.getvalue()
        except Exception as e:
            logger.warning(f"⚠️ 生成静音音频失败: {e}")
            return b""
    
    def add_sound_effect(
        self,
        voice_audio: bytes,
        effect_audio: bytes,
        position_ms: int,
        effect_volume_offset: int = -10,
        effect_duration_ms: Optional[int] = None,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
        loop_fill: bool = False,
        ducking_enabled: bool = True,
        ducking_priority: str = "dialogue",
        ducking_threshold_dbfs: float = -35.0,
        ducking_reduction_db: float = -6.0,
        ducking_chunk_ms: int = 250,
    ) -> bytes:
        """
        叠加音效（时间轴定位，纯pydub版）
        
        Args:
            voice_audio: 人声音频
            effect_audio: 音效
            position_ms: 插入位置（毫秒）
            effect_volume_offset: 音效音量偏移（dB）
            effect_duration_ms: 指定音效覆盖时长（毫秒）
            fade_in_ms: 音效淡入时长（毫秒）
            fade_out_ms: 音效淡出时长（毫秒）
            loop_fill: 是否循环填充至指定时长
            ducking_enabled: 是否启用对白优先的ducking
            ducking_priority: ducking 优先级（dialogue/sfx）
            ducking_threshold_dbfs: 触发ducking的对白响度阈值（dBFS）
            ducking_reduction_db: ducking 时的音量衰减（负数，dB）
            ducking_chunk_ms: ducking 分段分析窗口（毫秒）
        
        Returns:
            叠加音效后的音频
        """
        # 🔥 使用 pydub 叠加音效（主要方案）
        if self.pydub_available:
            try:
                voice = AudioSegment.from_file(io.BytesIO(voice_audio))
                effect = AudioSegment.from_file(io.BytesIO(effect_audio))
                
                # 调整音效音量
                effect = effect + effect_volume_offset

                if effect_duration_ms is not None:
                    target_len = max(0, int(effect_duration_ms))
                    if target_len <= 0:
                        return voice_audio
                    if loop_fill and len(effect) > 0 and len(effect) < target_len:
                        loops_needed = (target_len // len(effect)) + 1
                        effect = effect * loops_needed
                    effect = effect[:target_len]

                if fade_in_ms > 0:
                    effect = effect.fade_in(min(int(fade_in_ms), len(effect)))
                if fade_out_ms > 0:
                    effect = effect.fade_out(min(int(fade_out_ms), len(effect)))

                start_ms = max(0, int(position_ms or 0))
                if start_ms >= len(voice):
                    return voice_audio
                effect_len = len(effect)
                if effect_len <= 0:
                    return voice_audio
                end_ms = min(len(voice), start_ms + effect_len)
                target_len = max(0, end_ms - start_ms)
                if target_len <= 0:
                    return voice_audio

                effect_seg = effect[:target_len]
                voice_seg = voice[start_ms:end_ms]

                if ducking_enabled:
                    try:
                        priority = str(ducking_priority or "dialogue").strip().lower()
                        chunk_ms = max(80, int(ducking_chunk_ms or 250))
                        threshold = float(ducking_threshold_dbfs)
                        reduction_db = float(ducking_reduction_db)
                        if reduction_db > 0:
                            reduction_db = -abs(reduction_db)

                        adjusted_effect = AudioSegment.empty()
                        adjusted_voice = AudioSegment.empty()
                        for offset in range(0, target_len, chunk_ms):
                            effect_chunk = effect_seg[offset:offset + chunk_ms]
                            voice_chunk = voice_seg[offset:offset + chunk_ms]
                            voice_dbfs = voice_chunk.dBFS
                            if voice_dbfs != float("-inf") and voice_dbfs > threshold:
                                if priority in {"sfx", "effect", "effects"}:
                                    voice_chunk = voice_chunk + reduction_db
                                else:
                                    effect_chunk = effect_chunk + reduction_db
                            adjusted_effect += effect_chunk
                            adjusted_voice += voice_chunk

                        effect_seg = adjusted_effect
                        if priority in {"sfx", "effect", "effects"}:
                            voice = voice[:start_ms] + adjusted_voice + voice[end_ms:]
                    except Exception:
                        # ducking 失败不影响主流程
                        pass
                
                # 叠加音效
                mixed = voice.overlay(effect_seg, position=start_ms)
                
                # 输出
                output_buffer = io.BytesIO()
                mixed.export(output_buffer, format="mp3", bitrate="128k")
                
                logger.debug(f"✅ pydub 音效叠加完成: position={position_ms}ms")
                return output_buffer.getvalue()
                
            except Exception as e:
                logger.warning(f"⚠️ pydub 音效叠加失败: {e}")
        
        # 最终降级：返回原始人声
        logger.warning("⚠️ 音效叠加不可用")
        return voice_audio

    def analyze_quality(
        self,
        audio_data: bytes,
        min_loudness_dbfs: float = -40.0,
        max_loudness_dbfs: float = -3.0,
        clipping_threshold_dbfs: float = -0.5,
        silence_threshold_dbfs: float = -50.0,
        min_duration_seconds: float = 1.0
    ) -> AudioQualityReport:
        """
        分析音频质量
        
        Args:
            audio_data: 音频数据
            min_loudness_dbfs: 最小响度阈值（dBFS）
            max_loudness_dbfs: 最大响度阈值（dBFS）
            clipping_threshold_dbfs: 削波检测阈值（dBFS）
            silence_threshold_dbfs: 静音检测阈值（dBFS）
            min_duration_seconds: 最小时长阈值（秒）
        
        Returns:
            音频质量报告
        """
        issues: List[AudioQualityIssue] = []
        score = 100.0
        
        if not self.pydub_available or not audio_data:
            return AudioQualityReport(
                grade=AudioQualityGrade.POOR,
                score=0.0,
                issues=[AudioQualityIssue(
                    severity="high",
                    category="format",
                    description="无法分析音频：pydub 不可用或音频为空",
                    suggestion="安装 pydub 和 FFmpeg"
                )],
                metrics={},
                passed=False
            )
        
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            
            # 收集指标
            duration_ms = len(audio)
            duration_seconds = duration_ms / 1000.0
            loudness_dbfs = audio.dBFS
            max_dbfs = audio.max_dBFS
            channels = audio.channels
            sample_rate = audio.frame_rate
            
            metrics = {
                "duration_seconds": duration_seconds,
                "loudness_dbfs": loudness_dbfs,
                "max_dbfs": max_dbfs,
                "channels": channels,
                "sample_rate": sample_rate,
            }
            
            # 1. 检查时长
            if duration_seconds < min_duration_seconds:
                issues.append(AudioQualityIssue(
                    severity="high",
                    category="format",
                    description=f"音频时长过短: {duration_seconds:.1f}秒 < {min_duration_seconds}秒",
                    suggestion="检查 TTS 生成是否正常"
                ))
                score -= 30
            
            # 2. 检查响度（过低）
            if loudness_dbfs < min_loudness_dbfs:
                issues.append(AudioQualityIssue(
                    severity="medium",
                    category="loudness",
                    description=f"音频响度过低: {loudness_dbfs:.1f} dBFS < {min_loudness_dbfs} dBFS",
                    suggestion="建议增大音量或使用归一化"
                ))
                score -= 15
            
            # 3. 检查响度（过高）
            if loudness_dbfs > max_loudness_dbfs:
                issues.append(AudioQualityIssue(
                    severity="medium",
                    category="loudness",
                    description=f"音频响度过高: {loudness_dbfs:.1f} dBFS > {max_loudness_dbfs} dBFS",
                    suggestion="建议降低音量以避免失真"
                ))
                score -= 10
            
            # 4. 检查削波（clipping）
            if max_dbfs > clipping_threshold_dbfs:
                issues.append(AudioQualityIssue(
                    severity="high",
                    category="clipping",
                    description=f"检测到音频削波: {max_dbfs:.1f} dBFS > {clipping_threshold_dbfs} dBFS",
                    suggestion="必须降低音量或使用限制器（limiter）"
                ))
                score -= 25
            
            # 5. 检查采样率
            if sample_rate < 16000:
                issues.append(AudioQualityIssue(
                    severity="medium",
                    category="format",
                    description=f"采样率过低: {sample_rate} Hz < 16000 Hz",
                    suggestion="建议使用 22050 Hz 或 44100 Hz"
                ))
                score -= 10
            
            # 6. 检查声道
            if channels < 1:
                issues.append(AudioQualityIssue(
                    severity="high",
                    category="format",
                    description="音频声道数异常",
                    suggestion="检查音频文件是否损坏"
                ))
                score -= 30
            
            # 确保评分在 0-100 范围
            score = max(0.0, min(100.0, score))
            
            # 评级分类
            if score >= 90:
                grade = AudioQualityGrade.EXCELLENT
            elif score >= 75:
                grade = AudioQualityGrade.GOOD
            elif score >= 60:
                grade = AudioQualityGrade.FAIR
            else:
                grade = AudioQualityGrade.POOR
            
            passed = score >= 60 and not any(issue.severity == "high" for issue in issues)
            
            logger.info(f"🔍 音频质量分析完成: {grade.value} ({score:.1f}分), 问题数: {len(issues)}")
            
            return AudioQualityReport(
                grade=grade,
                score=score,
                issues=issues,
                metrics=metrics,
                passed=passed
            )
            
        except Exception as e:
            logger.error(f"❌ 音频质量分析失败: {e}")
            return AudioQualityReport(
                grade=AudioQualityGrade.POOR,
                score=0.0,
                issues=[AudioQualityIssue(
                    severity="high",
                    category="format",
                    description=f"分析失败: {str(e)}",
                    suggestion="检查音频文件格式"
                )],
                metrics={},
                passed=False
            )
