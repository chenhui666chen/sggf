"""TTS语音合成引擎 - 专业版（支持多提供商 + 智能重试）

核心功能：
1. 阿里云CosyVoice v3-plus集成（顶级音质）
2. 备用提供商支持（故障转移）
3. 智能重试机制（指数退避 + 熟熄断路）
4. 智能缓存（降低成本60%）
5. 批量并行处理
6. 成本监控与限额
7. 高级参数控制：语速/音调/停顿/重音
8. 指标埋点（性能监控 + 业务监控）
"""
import asyncio
import hashlib
import logging
import random
import os
from typing import Dict, Any, Optional, List, Callable
import io
from dataclasses import dataclass
from enum import Enum

from ..constants import INSTRUCT_SPEAKER_IDS, normalize_speaker_id
from ..voice_catalog import get_voice_entry

logger = logging.getLogger(__name__)

# cosyvoice-v3-plus Instruct 约束（按官方文档枚举）
COSYVOICE_V3_PLUS_INSTRUCT_EMOTIONS = {
    "neutral",
    "fearful",
    "angry",
    "sad",
    "surprised",
    "happy",
    "disgusted",
}
COSYVOICE_V3_PLUS_EMOTION_ALIASES = {
    "excited": "happy",
    "tense": "fearful",
    "calm": "neutral",
    "tender": "neutral",
    "solemn": "sad",
    "nervous": "fearful",
    "focused": "neutral",
    "gentle": "neutral",
    "serious": "neutral",
    "whisper": "neutral",
    "shout": "angry",
}
COSYVOICE_V3_PLUS_INSTRUCT_CHOICES = {
    "longanyang": {
        "scenes": ["闲聊互动", "新闻播报", "广告促销", "比赛解说", "一些儿童内容解说", "语音导航", "脱口秀表演"],
        "roles": ["一个旁白"],
        "identities": ["故事机"],
    },
    "longanhuan": {
        "scenes": ["闲聊对话", "比赛解说", "深夜电台广播", "诗歌朗诵", "科普知识推广", "产品推广", "脱口秀表演"],
        "roles": ["温和客服"],
        "identities": [],
    },
}

# Windows/Linux 常见网络瞬断 errno（用于判定可重试）。
_RETRYABLE_NETWORK_ERRNOS = {10053, 10054, 104, 110, 111}

# Qwen3-TTS Instruct Flash：优先读取新的 deployment 配置，并兼容历史环境变量。
QWEN3_TTS_INSTRUCT_FLASH_MODEL_ID = (
    os.getenv("QWEN3_TTS_INSTRUCT_FLASH_MODEL_ID")
    or os.getenv("QWEN3_TTS_FLASH_MODEL_ID")
    or "qwen3-tts-instruct-flash"
)

# 导入监控模块
try:
    from app.services.monitoring import metrics_collector
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.warning("监控模块未安装，指标收集已禁用")


class TTSProvider(str, Enum):
    """
    TTS 提供商枚举
    """
    ALIYUN = "aliyun"      # 阿里云 CosyVoice
    MINIMAX = "minimax"    # MiniMax Speech 2.8
    # 未来可扩展：
    # AZURE = "azure"      # 微软 Azure TTS
    # GOOGLE = "google"    # Google Cloud TTS
    # OPENAI = "openai"    # OpenAI TTS

# 前端显示用模型名 -> DashScope 实际模型 ID
ALIYUN_MODEL_ALIASES: Dict[str, str] = {
    # 应用侧统一切到 qwen3-tts-instruct-flash，并兼容历史 qwen3-tts-flash 配置。
    "qwen3-tts-instruct-flash": QWEN3_TTS_INSTRUCT_FLASH_MODEL_ID,
    "qwen3-tts-flash": QWEN3_TTS_INSTRUCT_FLASH_MODEL_ID,
    # 预留高阶版本；若未来官方启用真正的 qwen3-tts-plus，可在此更新
    "qwen3-tts-plus": "qwen3-tts-plus",
}

# MiniMax Speech 2.8 模型映射
MINIMAX_MODEL_ALIASES: Dict[str, str] = {
    "minimax-speech-2.8-hd": "speech-2.8-hd",
    "minimax-speech-2.8-turbo": "speech-2.8-turbo",
    "minimax-speech-2.8": "speech-2.8-hd",  # 默认使用 HD
}

# MiniMax 支持的情感
MINIMAX_EMOTIONS = {
    "happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm"
}

# MiniMax 语气词标签
MINIMAX_INTERJECTIONS = {
    "(laughs)", "(chuckles)", "(giggles)", "(sighs)", "(gasps)",
    "(coughs)", "(clear-throat)", "(breath)", "(sniffs)", "(sneezes)",
    "(exhales)", "(inhales)", "(smacks)", "(hmm)", "(uh)", "(ah)",
    "(oh)", "(wow)", "(oops)"
}


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3               # 最大重试次数
    base_delay: float = 1.0            # 基础延迟（秒）
    max_delay: float = 60.0            # 最大延迟（秒）
    exponential_base: float = 2.0      # 指数退避基数
    jitter: bool = True                # 是否添加随机抖动
    
    def calculate_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避 + 抖动）"""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            # 添加 ±25% 随机抖动
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)


@dataclass
class TTSCost:
    """TTS成本记录"""
    total_characters: int = 0
    total_segments: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    estimated_cost: float = 0.0  # 单位：元
    price_per_10k: float = 1.0   # 每万字符价格，默认按 v3-flash 计算
    
    def add_segment(self, char_count: int, is_cached: bool = False):
        """添加片段统计"""
        self.total_characters += char_count
        self.total_segments += 1
        
        if is_cached:
            self.cache_hits += 1
        else:
            self.api_calls += 1
            # 根据当前模型的单价计算成本
            self.estimated_cost += (char_count / 10000) * self.price_per_10k
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        cache_rate = (self.cache_hits / self.total_segments * 100) if self.total_segments > 0 else 0
        
        return {
            "total_characters": self.total_characters,
            "total_segments": self.total_segments,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": f"{cache_rate:.1f}%",
            "api_calls": self.api_calls,
            "estimated_cost": f"¥{self.estimated_cost:.2f}"
        }

