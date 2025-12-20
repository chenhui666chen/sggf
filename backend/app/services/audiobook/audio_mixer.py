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
        force_pydub: bool = True        # 🔥 新增：强制使用pydub（忽略FFmpeg）
    ):
        self.silence_duration = silence_duration
        self.normalize_audio = normalize_audio
        self.enable_fallback = enable_fallback
        self.force_pydub = force_pydub
        
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
        bgm_volume_offset: int = -20  # 降低背景音乐音量（dB）
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
                
                # 循环BGM到与人声相同长度
                if len(bgm) < len(voice):
                    loops_needed = (len(voice) // len(bgm)) + 1
                    bgm = bgm * loops_needed
                
                # 截取BGM到与人声相同长度
                bgm = bgm[:len(voice)]
                
                # 🔥 关键：使用 overlay 叠加混音（不会削弱人声）
                # overlay 会将 BGM 叠加在人声上，不会降低人声音量
                mixed = voice.overlay(bgm)
                
                # 归一化（如果启用）
                if self.normalize_audio:
                    mixed = normalize(mixed)
                
                # 输出
                output_buffer = io.BytesIO()
                mixed.export(output_buffer, format="mp3", bitrate="128k")
                
                logger.info(f"✅ pydub 背景音乐混合完成：BGM音量偏移={bgm_volume_offset}dB, 混音方式=overlay（保持人声原始音量）")
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
    
    def _mix_with_pydub(
        self,
        audio_segments: List[bytes],
        output_format: str = "mp3",
        bitrate: str = "128k"
    ) -> bytes:
        """使用pydub混音（主要方案）"""
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
            f"✅ pydub混音完成: "
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
        叠加音效（时间轴定位，纯pydub版）
        
        Args:
            voice_audio: 人声音频
            effect_audio: 音效
            position_ms: 插入位置（毫秒）
            effect_volume_offset: 音效音量偏移（dB）
        
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
