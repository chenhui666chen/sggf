"""
音频混合器 - 拼接与后处理（FFmpeg原生版）

核心功能：
1. 音频片段拼接（支持静音间隔）
2. 音效叠加（时间轴定位）
3. 背景音乐混音（自动ducking）
4. 音量归一化
5. 格式转换

技术方案：
- 优先使用 FFmpeg 命令行（原生，无 Python 依赖兼容性问题）
- 降级使用 pydub（仅在 FFmpeg 不可用时）
- 最终降级：简单字节拼接

依赖：
- FFmpeg: https://ffmpeg.org/download.html（必须）
- pydub: pip install pydub（可选，Python 3.13 可能不兼容）

注意：需要先安装FFmpeg到系统PATH
"""
import io
import os
import subprocess
import tempfile
import logging
from typing import List, Optional, Dict, Any
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

# 尝试导入pydub（作为降级方案）
try:
    from pydub import AudioSegment
    from pydub.effects import normalize
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# 输出可用的音频处理引擎
if FFMPEG_AVAILABLE:
    logger.info("✅ 音频混合器：使用 FFmpeg 原生引擎（最佳）")
elif PYDUB_AVAILABLE:
    logger.info("✅ 音频混合器：使用 pydub 引擎（降级）")
else:
    logger.warning("⚠️ 音频混合器：仅支持简单拼接模式（需安装 FFmpeg 以启用完整功能）")
    logger.warning("   下载地址: https://ffmpeg.org/download.html")


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
    音频混合器（FFmpeg原生版）
    
    优先级：
    1. FFmpeg 命令行（最佳）
    2. pydub（降级）
    3. 简单拼接（最终降级）
    """
    
    def __init__(
        self,
        silence_duration: int = 500,  # 静音间隔（毫秒）
        normalize_audio: bool = False,  # 🔧 修复：禁用归一化（避免音频截断）
        enable_fallback: bool = True   # 是否启用降级模式
    ):
        self.silence_duration = silence_duration
        self.normalize_audio = normalize_audio
        self.enable_fallback = enable_fallback
        
        # 检查可用性
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
        混合章节音频（优先使用 FFmpeg 原生）
        
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
        
        # 优先级 1: FFmpeg 命令行
        if self.ffmpeg_available:
            try:
                return self._mix_with_ffmpeg_cli(audio_segments, output_format, bitrate)
            except Exception as e:
                logger.error(f"❌ FFmpeg 原生混音失败: {e}")
                import traceback
                traceback.print_exc()
                
                if not self.enable_fallback:
                    raise
                logger.warning("⚠️ 降级到 pydub 模式")
        
        # 优先级 2: pydub
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
        
        # 优先级 3: 简单字节拼接
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
        bgm_volume_offset: int = -20  # 降低背景音乐音量（dB）
    ) -> bytes:
        """
        添加背景音乐（FFmpeg增强版）
        
        Args:
            voice_audio: 人声音频
            bgm_audio: 背景音乐
            bgm_volume_offset: 背景音乐音量偏移（负数=降低）
        
        Returns:
            混音后的音频
        """
        # 🔥 优先使用 FFmpeg 原生混音
        if self.ffmpeg_available:
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    voice_file = temp_path / "voice.mp3"
                    bgm_file = temp_path / "bgm.mp3"
                    output_file = temp_path / "mixed.mp3"
                    
                    # 写入临时文件
                    voice_file.write_bytes(voice_audio)
                    bgm_file.write_bytes(bgm_audio)
                    
                    # FFmpeg 混音命令：
                    # - aloop=999:size=2e+09 循环 BGM
                    # - volume=X 调整音量（使用线性倍数）
                    # - amix 混音
                    # - shortest=1 截断到最短输入
                    volume_multiplier = 10 ** (bgm_volume_offset / 20)  # dB 转线性
                    
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(voice_file),
                        "-stream_loop", "-1",  # 循环 BGM
                        "-i", str(bgm_file),
                        "-filter_complex",
                        f"[1:a]volume={volume_multiplier}[bgm];[0:a][bgm]amix=inputs=2:duration=first[out]",
                        "-map", "[out]",
                        "-c:a", "libmp3lame",
                        "-b:a", "128k",
                        str(output_file)
                    ]
                    
                    subprocess.run(cmd, check=True, capture_output=True)
                    logger.info(f"✅ FFmpeg 背景音乐混合完成")
                    return output_file.read_bytes()
                    
            except Exception as e:
                logger.warning(f"⚠️ FFmpeg 混音失败，尝试降级方案: {e}")
        
        # 🔻 降级方案：pydub
        if self.pydub_available:
            try:
                # 加载音频
                voice = AudioSegment.from_file(io.BytesIO(voice_audio))
                bgm = AudioSegment.from_file(io.BytesIO(bgm_audio))
                
                # 调整BGM音量
                bgm = bgm + bgm_volume_offset
                
                # 循环BGM到与人声相同长度
                if len(bgm) < len(voice):
                    loops_needed = (len(voice) // len(bgm)) + 1
                    bgm = bgm * loops_needed
                
                # 截取BGM到与人声相同长度
                bgm = bgm[:len(voice)]
                
                # 混音（overlay）
                mixed = voice.overlay(bgm)
                
                # 归一化
                if self.normalize_audio:
                    mixed = normalize(mixed)
                
                # 输出
                output_buffer = io.BytesIO()
                mixed.export(output_buffer, format="mp3", bitrate="128k")
                
                logger.info(f"✅ pydub 背景音乐混合完成")
                return output_buffer.getvalue()
            except Exception as e:
                logger.warning(f"⚠️ pydub 混音失败: {e}")
        
        # 最终降级：返回原始人声
        logger.warning("⚠️ 背景音乐功能不可用，返回原始人声")
        return voice_audio
    
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
    
    def _mix_with_ffmpeg_cli(
        self,
        audio_segments: List[bytes],
        output_format: str = "mp3",
        bitrate: str = "128k"
    ) -> bytes:
        """使用 FFmpeg 命令行混音（filter_complex 无损拼接版）"""
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # 1. 将所有音频片段写入临时文件并解码为 WAV（避免 MP3 帧边界问题）
            input_files = []
            for i, audio_bytes in enumerate(audio_segments):
                if not audio_bytes:
                    continue
                
                # 先保存原始 MP3
                mp3_file = tmpdir_path / f"segment_{i:04d}.mp3"
                mp3_file.write_bytes(audio_bytes)
                
                # 解码为 WAV（无损，避免帧对齐问题）
                wav_file = tmpdir_path / f"segment_{i:04d}.wav"
                subprocess.run([
                    "ffmpeg", "-i", str(mp3_file),
                    "-acodec", "pcm_s16le",
                    "-ar", "44100",
                    "-ac", "2",
                    "-y", str(wav_file)
                ], check=True, capture_output=True)
                
                input_files.append(str(wav_file))
            
            if not input_files:
                logger.warning("⚠️ 没有有效的音频片段")
                return b""
            
            # 2. 生成静音文件（WAV 格式）
            silence_duration_sec = self.silence_duration / 1000.0
            
            # 3. 使用 filter_complex 进行无损拼接（带静音间隔）
            output_file = tmpdir_path / f"output.{output_format}"
            
            # 构建 filter_complex 滤镜链
            # 格式: [0:a][silence][1:a][silence]...[N:a] concat=n=X:v=0:a=1
            filter_parts = []
            concat_inputs = []
            
            for i in range(len(input_files)):
                concat_inputs.append(f"[{i}:a]")
                if i < len(input_files) - 1 and self.silence_duration > 0:
                    # 添加静音（使用 aevalsrc 生成）
                    filter_parts.append(
                        f"aevalsrc=0:d={silence_duration_sec}:s=44100:c=stereo[silence{i}]"
                    )
                    concat_inputs.append(f"[silence{i}]")
            
            # 拼接所有输入
            concat_filter = "".join(concat_inputs) + f"concat=n={len(concat_inputs)}:v=0:a=1[outa]"
            
            # 完整滤镜链
            if filter_parts:
                full_filter = ";".join(filter_parts) + ";" + concat_filter
            else:
                full_filter = concat_filter
            
            # 构建 FFmpeg 命令
            ffmpeg_cmd = ["ffmpeg"]
            
            # 添加所有输入文件
            for input_file in input_files:
                ffmpeg_cmd.extend(["-i", input_file])
            
            # 添加滤镜链
            ffmpeg_cmd.extend([
                "-filter_complex", full_filter,
                "-map", "[outa]",
            ])
            
            # 编码参数
            if output_format == "mp3":
                ffmpeg_cmd.extend([
                    "-c:a", "libmp3lame",
                    "-b:a", bitrate,
                ])
            else:
                ffmpeg_cmd.extend([
                    "-c:a", "pcm_s16le",
                ])
            
            # 添加归一化（如果需要）
            if self.normalize_audio:
                # 注意：loudnorm 要在 filter_complex 之后应用
                ffmpeg_cmd.extend(["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"])
            
            ffmpeg_cmd.extend(["-y", str(output_file)])
            
            # 执行 FFmpeg
            logger.debug(f"🔧 FFmpeg 命令: {' '.join(ffmpeg_cmd)}")
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"❌ FFmpeg 执行失败: {result.stderr}")
                raise RuntimeError(f"FFmpeg failed: {result.stderr}")
            
            # 6. 读取输出文件
            output_bytes = output_file.read_bytes()
            
            logger.info(
                f"✅ FFmpeg filter_complex 无损混音完成: "
                f"片段数 {len(input_files)}, "
                f"大小 {len(output_bytes)/1024:.1f}KB"
            )
            
            return output_bytes
    
    def _mix_with_pydub(
        self,
        audio_segments: List[bytes],
        output_format: str = "mp3",
        bitrate: str = "128k"
    ) -> bytes:
        """使用pydub混音（核心实现）"""
        # 1. 加载所有音频片段
        segments = []
        for audio_bytes in audio_segments:
            if not audio_bytes:
                continue
            try:
                segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
                segments.append(segment)
            except Exception as e:
                logger.warning(f"⚠️ 无法加载音频片段: {e}")
        
        if not segments:
            logger.warning("⚠️ 没有有效的音频片段")
            return b""
        
        # 2. 拼接音频，添加静音间隔
        silence = AudioSegment.silent(duration=self.silence_duration)
        
        combined = AudioSegment.empty()
        for i, segment in enumerate(segments):
            combined += segment
            if i < len(segments) - 1:  # 不在最后一个片段后加静音
                combined += silence
        
        # 3. 归一化音量
        if self.normalize_audio:
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
            f"✅ FFmpeg混音完成: "
            f"时长 {len(combined)/1000:.1f}秒, "
            f"大小 {len(result)/1024:.1f}KB"
        )
        
        return result
    
    def add_sound_effect(
        self,
        voice_audio: bytes,
        effect_audio: bytes,
        position_ms: int,
        effect_volume_offset: int = -10
    ) -> bytes:
        """
        叠加音效（时间轴定位）
        
        Args:
            voice_audio: 人声音频
            effect_audio: 音效
            position_ms: 插入位置（毫秒）
            effect_volume_offset: 音效音量偏移（dB）
        
        Returns:
            叠加音效后的音频
        """
        # 🔥 优先使用 FFmpeg 原生叠加
        if self.ffmpeg_available:
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    voice_file = temp_path / "voice.mp3"
                    effect_file = temp_path / "effect.mp3"
                    output_file = temp_path / "mixed.mp3"
                    
                    # 写入临时文件
                    voice_file.write_bytes(voice_audio)
                    effect_file.write_bytes(effect_audio)
                    
                    # FFmpeg 音效叠加命令
                    volume_multiplier = 10 ** (effect_volume_offset / 20)  # dB 转线性
                    delay_ms = max(0, position_ms)  # 确保非负值
                    
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(voice_file),
                        "-i", str(effect_file),
                        "-filter_complex",
                        f"[1:a]adelay={delay_ms}|{delay_ms},volume={volume_multiplier}[sfx];[0:a][sfx]amix=inputs=2:duration=first[out]",
                        "-map", "[out]",
                        "-c:a", "libmp3lame",
                        "-b:a", "128k",
                        str(output_file)
                    ]
                    
                    subprocess.run(cmd, check=True, capture_output=True)
                    logger.debug(f"✅ FFmpeg 音效叠加完成: position={position_ms}ms")
                    return output_file.read_bytes()
                    
            except Exception as e:
                logger.warning(f"⚠️ FFmpeg 音效叠加失败: {e}")
        
        # 🔻 降级方案：pydub
        if self.pydub_available:
            try:
                voice = AudioSegment.from_file(io.BytesIO(voice_audio))
                effect = AudioSegment.from_file(io.BytesIO(effect_audio))
                
                # 调整音效音量
                effect = effect + effect_volume_offset
                
                # 叠加音效
                mixed = voice.overlay(effect, position=position_ms)
                
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
