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
from typing import Dict, Any, Optional, List, Callable
import io
from dataclasses import dataclass
from enum import Enum

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


# 导入监控模块
try:
    from app.services.monitoring import metrics_collector
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.warning("监控模块未安装，指标收集已禁用")


from app.services.audiobook.tts_engine_pkg._constants import (
    TTSProvider,
    RetryConfig,
    TTSCost,
)

class UtilsMixin:
    def get_cost_stats(self) -> Dict[str, Any]:
        """获取成本统计"""
        return self.cost_tracker.get_stats()
    
    def reset_cost_tracker(self):
        """重置成本统计"""
        self.cost_tracker = TTSCost(price_per_10k=getattr(self, "price_per_10k", 1.0))
