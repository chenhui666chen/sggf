"""豆包 Seed Audio 音效生成器

分轨合成（legacy_stems）模式下，把单段音效描述适配为豆包
seed-audio-1.0 的文本生成音频请求，供 SoundEffectDesigner
生成环境音与短音效素材。
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

DOUBAO_SFX_MODEL = "seed-audio-1.0"
# 与 DoubaoSeedAudio10Adapter._call_api 的鉴权链保持一致
DOUBAO_SFX_API_KEY_ENVS = (
    "VOLCENGINE_OPEN_SPEECH_API_KEY",
    "VOLCENGINE_TTS_API_KEY",
    "DOUBAO_TTS_API_KEY",
    "SEED_TTS_API_KEY",
    "DOUBAO_API_KEY",
)
# 音效素材无需字幕，固定 mp3 便于入库
DOUBAO_SFX_AUDIO_CONFIG = {"format": "mp3", "enable_subtitle": False}


def has_doubao_sfx_api_key() -> bool:
    """检查豆包音频生成密钥链是否已配置"""
    return any(os.getenv(name, "").strip() for name in DOUBAO_SFX_API_KEY_ENVS)


@dataclass
class DoubaoSfxResult:
    """豆包音效生成结果"""
    success: bool
    audio_url: str = ""  # HTTP(S) 地址或 data:audio/...;base64 数据地址
    error: str = ""
    task_id: str = ""


class DoubaoSfxGenerator:
    """豆包 Seed Audio 音效生成器

    复用统一注册表中的 DoubaoSeedAudio10Adapter，把纯文本音效
    描述转成一次性音频生成请求；适配器为同步实现，调用时放入
    线程避免阻塞事件循环。
    """

    def __init__(self, adapter: Optional[Any] = None):
        self._adapter = adapter

    def _get_adapter(self) -> Any:
        if self._adapter is None:
            from adapters.registry import registry

            self._adapter = registry.get_adapter(DOUBAO_SFX_MODEL)
        if self._adapter is None:
            raise RuntimeError("Doubao Seed Audio adapter is unavailable")
        return self._adapter

    @staticmethod
    def build_text_prompt(prompt: str, duration: Optional[float]) -> str:
        """把音效描述与目标时长编译为纯音效生成提示词

        duration 为 None 表示描述本身已包含明确时长（如“2秒左右”），
        不再追加时长提示，避免两个矛盾时长同时出现在提示词里。
        """
        description = str(prompt or "").strip().rstrip("。")
        if duration is None:
            return f"{description}。"
        duration_sec = max(1, round(float(duration or 0) or 5))
        return f"{description}。时长约{duration_sec}秒。"

    async def generate_audio_async(
        self,
        *,
        prompt: str,
        duration: Optional[float],
    ) -> DoubaoSfxResult:
        """调用豆包 seed-audio-1.0 生成音效素材"""
        try:
            adapter = self._get_adapter()
        except Exception as exc:
            return DoubaoSfxResult(success=False, error=str(exc))

        text_prompt = self.build_text_prompt(prompt, duration)
        logger.info(f"🎧 [豆包] 创建音效生成请求: {text_prompt}")
        try:
            result = await asyncio.to_thread(
                adapter.generate,
                prompt=text_prompt,
                model=DOUBAO_SFX_MODEL,
                audio_config=dict(DOUBAO_SFX_AUDIO_CONFIG),
            )
        except Exception as exc:
            return DoubaoSfxResult(success=False, error=str(exc))

        task_id = str(getattr(result, "task_id", "") or "")
        if not getattr(result, "success", False):
            return DoubaoSfxResult(
                success=False,
                error=str(getattr(result, "error", "") or "doubao_sfx_generation_failed"),
                task_id=task_id,
            )
        outputs = getattr(result, "outputs", None) or []
        audio_url = next((str(value) for value in outputs if value), "")
        if not audio_url:
            return DoubaoSfxResult(
                success=False,
                error="豆包响应中缺少音频输出",
                task_id=task_id,
            )
        return DoubaoSfxResult(success=True, audio_url=audio_url, task_id=task_id)


def create_doubao_sfx_generator(adapter: Optional[Any] = None) -> DoubaoSfxGenerator:
    """创建豆包音效生成器工厂函数"""
    return DoubaoSfxGenerator(adapter=adapter)
