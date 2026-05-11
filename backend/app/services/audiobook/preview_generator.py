"""
预览生成服务 - 快速生成试听片段

参考 TextAudio 的 2 句预览功能。

功能：
1. 快速提取文本前 2 句
2. 调用 TTS 生成预览音频
3. 返回预览音频本地路径和时长
"""
import os
import logging
from typing import Optional, Dict, Any
import uuid
import re

logger = logging.getLogger(__name__)


class PreviewGenerator:
    """预览音频生成器"""

    def __init__(
        self,
        max_sentences: int = 2,
        max_duration_seconds: float = 15.0,
        output_dir: str = "previews",
    ):
        self.max_sentences = max_sentences
        self.max_duration_seconds = max_duration_seconds
        self.output_dir = output_dir

    def extract_preview_text(self, full_text: str) -> str:
        """提取预览文本（前 N 句）"""
        # 按句子分割
        sentences = re.split(r'(?<=[。！？.!?])\s*', full_text)

        # 取前 N 句
        preview_sentences = sentences[:self.max_sentences]
        preview_text = ' '.join(preview_sentences).strip()

        # 确保不超过最大时长（估算）
        # 假设每句约 3-5 秒
        estimated_duration = len(preview_sentences) * 4  # 粗略估算
        if estimated_duration > self.max_duration_seconds:
            # 如果估算超时，只取第一句
            preview_text = preview_sentences[0] if preview_sentences else full_text[:100]

        return preview_text

    def generate_preview(
        self,
        text: str,
        voice_id: str,
        tts_engine,
        **tts_params,
    ) -> Dict[str, Any]:
        """
        生成预览音频

        Args:
            text: 完整文本（会自动提取预览部分）
            voice_id: 音色 ID
            tts_engine: TTS 引擎实例
            **tts_params: TTS 参数

        Returns:
            预览信息字典
        """
        # 提取预览文本
        preview_text = self.extract_preview_text(text)

        if not preview_text:
            raise ValueError("无法提取预览文本")

        # 生成唯一文件名
        preview_id = str(uuid.uuid4())[:8]
        filename = f"preview_{preview_id}.mp3"
        output_path = os.path.join(self.output_dir, filename)

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)

        try:
            # 调用 TTS 生成预览
            logger.info(f"🎵 生成预览: voice={voice_id}, text={preview_text[:50]}...")

            # 使用 TTS 引擎生成
            if hasattr(tts_engine, 'synthesize'):
                audio_data = tts_engine.synthesize(
                    text=preview_text,
                    voice_id=voice_id,
                    output_path=output_path,
                    **tts_params,
                )
            else:
                # 兼容不同的 TTS 引擎接口
                audio_data = tts_engine(
                    text=preview_text,
                    voice_id=voice_id,
                    output_path=output_path,
                    **tts_params,
                )

            # 获取音频时长（如果有 pydub）
            duration = self._get_audio_duration(output_path)

            return {
                "preview_id": preview_id,
                "preview_text": preview_text,
                "audio_path": output_path,
                "audio_url": "",
                "duration": duration,
                "voice_id": voice_id,
                "tts_params": tts_params,
            }

        except Exception as e:
            logger.error(f"❌ 预览生成失败: {e}")
            raise

    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长（秒）"""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0
        except Exception:
            # 如果无法获取时长，返回估算值
            return 0.0


# 全局默认实例
default_preview_generator = PreviewGenerator()
