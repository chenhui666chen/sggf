"""TTS engine package."""

from app.services.audiobook.tts_engine_pkg._base import TTSEngineBase
from app.services.audiobook.tts_engine_pkg._api_call_mixin import APICallMixin
from app.services.audiobook.tts_engine_pkg._aliyun_mixin import AliyunMixin
from app.services.audiobook.tts_engine_pkg._minimax_mixin import MinimaxMixin
from app.services.audiobook.tts_engine_pkg._utils_mixin import UtilsMixin


class TTSEngine(
    TTSEngineBase,
    APICallMixin,
    AliyunMixin,
    MinimaxMixin,
    UtilsMixin,
):
    pass


from app.services.audiobook.tts_engine_pkg._constants import (
    TTSProvider,
    RetryConfig,
    TTSCost,
)

__all__ = ["TTSEngine", "TTSProvider", "RetryConfig", "TTSCost"]
