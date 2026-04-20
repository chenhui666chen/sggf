from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import asyncio
import json
import logging
import os
import re

import httpx
import yaml
from sqlalchemy.orm import Session, selectinload

from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource

try:
    from core.unified_llm_client import get_llm_client
    _LLM_CLIENT_AVAILABLE = True
except ImportError:
    _LLM_CLIENT_AVAILABLE = False
    get_llm_client = None

try:
    from core.model_catalog_runtime import get_model_catalog_runtime_index
    _RUNTIME_SIGNAL_AVAILABLE = True
except ImportError:
    _RUNTIME_SIGNAL_AVAILABLE = False
    get_model_catalog_runtime_index = None

logger = logging.getLogger(__name__)

# 智能触发策略配置
_LLM_VERIFICATION_TRIGGER = {
    "max_verified_age_hours": int(os.getenv("LLM_VERIFICATION_MAX_AGE_HOURS", "72")),  # 已校验结果最大有效期（小时）
    "force_verify_new_models": os.getenv("LLM_VERIFICATION_FORCE_NEW", "true").lower() == "true",  # 新模型首次必须联网
    "force_verify_on_config_change": os.getenv("LLM_VERIFICATION_FORCE_ON_CHANGE", "true").lower() == "true",  # 配置变更时强制联网
    "skip_llm_for_static_validation": os.getenv("LLM_VERIFICATION_SKIP_STATIC", "false").lower() == "true",  # 静态校验是否跳过LLM
}

# 价格验证配置
PRICING_VERIFICATION_CONFIG = {
    "alibaba_cloud_dashscope": {
        "pricing_url": "https://help.aliyun.com/zh/model-studio/pricing",
        "cache_hours": 24,  # 价格缓存时间（小时）
        "timeout_seconds": 30,
    }
}

# 已验证的价格数据（来自多渠道交叉验证：阿里百炼、火山引擎、可灵官网等）
VERIFIED_PRICING_DATA = {
    # 视频生成模型（阿里百炼）
    "wan2.7-t2v": {
        "720p": {"price": 0.6, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
        "1080p": {"price": 1.0, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.7-i2v": {
        "720p": {"price": 0.6, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
        "1080p": {"price": 1.0, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.7-r2v": {
        "720p": {"price": 0.6, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
        "1080p": {"price": 1.0, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.7-videoedit": {
        "720p": {"price": 0.6, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
        "1080p": {"price": 1.0, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.6-t2v-fast": {
        "720p": {"price": 0.4, "unit": "元/秒", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    # 图像生成模型（阿里百炼）
    "qwen-image-2.0-pro": {
        "default": {"price": 0.5, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "qwen-image-2.0": {
        "default": {"price": 0.2, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.6-t2i": {
        "default": {"price": 0.20, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.7-image": {
        "default": {"price": 0.20, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "wan2.7-image-pro": {
        "default": {"price": 0.50, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    # 图像编辑模型（阿里百炼）
    "qwen-image-edit-plus": {
        "default": {"price": 0.2, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    "qwen-image-edit-max": {
        "default": {"price": 0.5, "unit": "元/张", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    # 视觉理解模型（阿里百炼）
    "qwen3.5-omni-plus": {
        "default": {"price": 0.02, "unit": "元/千tokens", "source": "https://help.aliyun.com/zh/model-studio/pricing"},
    },
    # Doubao Seedance 系列（火山引擎）
    "doubao-seedance-2-0": {
        "480p": {"price": 0.44, "unit": "元/秒", "source": "https://www.volcengine.com/docs/82379/1399263"},
        "720p": {"price": 0.99, "unit": "元/秒", "source": "https://www.volcengine.com/docs/82379/1399263"},
    },
    "doubao-seedance-2-0-fast": {
        "720p": {"price": 0.60, "unit": "元/秒", "source": "https://www.volcengine.com/docs/82379/1399263"},
    },
    "doubao-seedance-1-5-pro": {
        "720p": {"price": 0.8, "unit": "元/秒", "source": "https://www.volcengine.com/docs/82379/1399263"},
    },
    # Doubao Seedream 系列（火山引擎）
    "doubao-seedream-4-5": {
        "default": {"price": 0.3, "unit": "元/张", "source": "https://www.volcengine.com/docs/82379/1399263"},
    },
    "doubao-seedream-5-0": {
        "default": {"price": 0.5, "unit": "元/张", "source": "https://www.volcengine.com/docs/82379/1399263"},
    },
    # Kling 可灵系列（快手）
    "kling-v3-video-generation": {
        "720p": {"price": 1.13, "unit": "元/次", "source": "https://kling3.io/zh/pricing"},
        "1080p": {"price": 1.39, "unit": "元/次", "source": "https://kling3.io/zh/pricing"},
    },
    "kling-v3-omni-video-generation": {
        "720p": {"price": 1.5, "unit": "元/次", "source": "https://kling3.io/zh/pricing"},
        "1080p": {"price": 2.0, "unit": "元/次", "source": "https://kling3.io/zh/pricing"},
    },
    "kling-v3-image-generation": {
        "default": {"price": 0.15, "unit": "元/张", "source": "https://kling3.io/zh/pricing"},
    },
    "kling-v3-omni-image-generation": {
        "default": {"price": 0.2, "unit": "元/张", "source": "https://kling3.io/zh/pricing"},
    },
    # PixVerse 系列
    "pixverse-c1-r2v": {
        "720p": {"price": 0.28, "unit": "元/次", "source": "https://pixverse.ai/pricing"},
    },
    "pixverse-v6-t2v": {
        "720p": {"price": 0.45, "unit": "元/次", "source": "https://pixverse.ai/pricing"},
    },
    # Vidu 系列（生数科技）
    "vidu-q3-pro-img2video": {
        "720p": {"price": 0.5, "unit": "元/次", "source": "https://www.vidu.cn/pricing"},
    },
    "vidu-q3-pro-text2video": {
        "720p": {"price": 0.6, "unit": "元/次", "source": "https://www.vidu.cn/pricing"},
    },
    "vidu-q3-pro-start-end2video": {
        "720p": {"price": 0.8, "unit": "元/次", "source": "https://www.vidu.cn/pricing"},
    },
}

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

_DURATION_RANGE_RE = re.compile(
    r"(?:时长|duration|视频时长)[：:\s]*"
    r"(\d+)\s*[-~至到]\s*(\d+)\s*(秒|seconds?|s)",
    re.IGNORECASE,
)
_RESOLUTION_RE = re.compile(r"\b(480[pP]|720[pP]|1080[pP]|4[kK])\b")
_FRAME_RATE_RE = re.compile(r"(\d+)\s*fps", re.IGNORECASE)
_FORMAT_RE = re.compile(r"\b(MP4|MOV|AVI|H\.264|H\.265|HEVC|AAC)\b", re.IGNORECASE)
_MULTI_SHOT_RE = re.compile(r"多镜头|multi[-\s]?shot|多镜头叙事", re.IGNORECASE)
_AUDIO_SYNC_RE = re.compile(r"声画同步|audio[-\s]?sync|配音|自动配音", re.IGNORECASE)
_PROMPT_REWRITE_RE = re.compile(r"智能改写|prompt[-\s]?rewrite|提示词优化", re.IGNORECASE)
_INPUT_MODALITY_RE = re.compile(
    r"支持[的]?(文本|图像|图片|音频|声音|视频)[输入/模态]|"
    r"(text|image|audio|video)\s*(input|modality)",
    re.IGNORECASE,
)
_MAX_REFERENCE_RE = re.compile(r"最多\s*(\d+)\s*(张|个|幅)", re.IGNORECASE)
_WEIGHT_CONTROL_RE = re.compile(r"权重|weight[-\s]?control", re.IGNORECASE)
_FIRST_FRAME_RE = re.compile(r"首帧|first[-\s]?frame", re.IGNORECASE)
_LAST_FRAME_RE = re.compile(r"尾帧|last[-\s]?frame|结束帧", re.IGNORECASE)

_CATEGORY_LABELS: dict[str, str] = {
    "llm": "文本模型",
    "image": "图像模型",
    "video": "视频模型",
    "audio": "音频模型",
    "multimodal": "多模态模型",
    "embedding": "向量模型",
}

_PROVIDER_LABELS: dict[str, str] = {
    "alibaba": "阿里云 / 通义",
    "deepseek": "DeepSeek",
    "kunlun": "昆仑万维 / Mureka",
    "stability": "Stability AI",
    "kuaishou": "快手 / 可灵",
}

_MODALITY_LABELS: dict[str, str] = {
    "text_generation": "文本生成",
    "text_to_image": "文生图",
    "image_to_image": "图生图",
    "image_edit": "图像编辑",
    "image_to_image_edit": "多图编辑",
    "text_to_video": "文生视频",
    "image_to_video": "图生视频",
    "reference_to_video": "参考生视频",
    "video_to_video": "视频参考生成",
    "multimodal_chat": "多模态对话",
    "image_understanding": "图像理解",
    "video_understanding": "视频理解",
    "text_to_audio": "文生音频",
    "video_to_audio": "视频转音频",
    "text_to_speech": "文本转语音",
    "voice_clone": "语音克隆",
    "embedding": "向量嵌入",
}

_CAPABILITY_LABELS: dict[str, str] = {
    "creative": "创意写作",
    "dialogue": "角色对话",
    "reasoning": "复杂推理",
    "writing": "正文写作",
    "chinese": "中文表达",
    "long_context": "长上下文",
    "summarization": "长文摘要",
    "analysis": "综合分析",
    "fast": "高速响应",
    "simple": "轻量处理",
    "extraction": "信息提取",
    "logic": "逻辑审校",
    "planning": "结构规划",
    "chat": "通用对话",
    "reference_images": "参考图约束",
    "reference_videos": "参考视频约束",
    "camera_control": "镜头控制",
    "motion_control": "运动控制",
    "dialogue_audio": "对白音频",
    "sfx_audio": "音效生成",
    "music_generation": "音乐生成",
    "background_music": "背景音乐",
    "character_consistency": "角色一致性",
    "image_understanding": "图像理解",
    "video_understanding": "视频理解",
    "json_output": "结构化输出",
    "image_edit": "图像编辑",
    "multi_image": "多图参考",
    "prompt_extend": "提示增强",
    "speech_synthesis": "语音合成",
    "word_timestamps": "词级时间戳",
    "phoneme_timestamps": "音素时间戳",
    "preset_voices": "预设音色",
    "instruct_control": "表现力控制",
    "voice_clone": "音色克隆",
    "style_control": "风格控制",
    "negative_prompt": "负向提示词",
    "seed_control": "随机种子",
    "batch_generation": "批量生成",
}

_TASK_TYPE_LABELS: dict[str, str] = {
    "concept": "题材概念生成",
    "chapter": "章节正文生成",
    "dialogue": "对话润色",
    "creative": "创意扩写",
    "writing": "正文写作",
    "outline_expand": "长篇大纲扩展",
    "book_synthesis": "整书汇总",
    "long_context": "超长上下文分析",
    "summarize_long": "长文摘要",
    "entity_extract": "实体提取",
    "summarize": "摘要提炼",
    "simple": "简单改写",
    "fast": "高速处理",
    "worldview": "世界观设计",
    "character": "人物设定",
    "character_expand": "人物扩展",
    "structure_plot": "情节结构审校",
    "structure_events": "事件链审校",
    "review": "综合审校",
    "quality_review": "质量复审",
    "final_review": "最终复审",
    "reasoning": "复杂推理",
    "audiobook_director": "有声导演脚本",
    "audiobook_voice": "有声角色分配",
    "audiobook_sound": "有声音效规划",
    "audiobook_music": "有声配乐规划",
    "audiobook_review": "有声审校",
    "audiobook_script": "有声剧本改编",
    "asset_music": "资产配乐生成",
    "asset_sfx": "资产音效生成",
    "asset_audio": "资产音频预研",
    "volume_detail_expand": "卷级细纲扩写",
}

_PROJECT_MODULE_LABELS: dict[str, str] = {
    "novel": "灵感方舟 / 小说创作",
    "audiobook": "耳畔星河 / 有声创作",
    "drama": "织梦映心 / 多模态短剧",
    "asset_studio": "资产生成工作台",
    "catalog": "模型档案中心",
}

_REFERENCE_HUBS: dict[str, list[dict[str, str]]] = {
    "selection_hubs": [
        {
            "label": "Arena AI",
            "url": "https://arena.ai",
            "note": "适合查看对话、多模态与排行榜趋势。",
        },
        {
            "label": "Artificial Analysis",
            "url": "https://artificialanalysis.ai",
            "note": "适合比较智能、速度、成本与延迟。",
        },
    ],
    "model_hubs": [
        {
            "label": "Hugging Face Hub",
            "url": "https://huggingface.co",
            "note": "适合查模型卡、版本与开源推理入口。",
        },
        {
            "label": "ModelScope 魔搭社区",
            "url": "https://www.modelscope.cn",
            "note": "适合查国产模型、部署与微调资料。",
        },
    ],
    "provider_portals": [
        {
            "label": "通义实验室",
            "url": "https://tongyi.aliyun.com",
            "note": "适合了解阿里系模型与产品入口。",
        },
        {
            "label": "DeepSeek 官网",
            "url": "https://www.deepseek.com",
            "note": "适合查看 DeepSeek 产品与入口。",
        },
        {
            "label": "Mureka 开发文档",
            "url": "https://platform.mureka.cn/docs/",
            "note": "适合查看 Mureka 音乐生成与 API 文档。",
        },
        {
            "label": "智谱清言",
            "url": "https://chatglm.cn",
            "note": "适合关注智谱系模型与入口。",
        },
        {
            "label": "文心一言",
            "url": "https://yiyan.baidu.com",
            "note": "适合关注百度系模型入口。",
        },
        {
            "label": "豆包",
            "url": "https://www.doubao.com/chat/",
            "note": "适合关注字节系模型入口。",
        },
    ],
}

_PROVIDER_KEYWORDS: dict[str, list[str]] = {
    "alibaba": ["alibaba", "aliyun", "通义", "百炼", "dashscope", "wanx", "万相"],
    "deepseek": ["deepseek"],
    "volcengine": ["volcengine", "火山方舟", "火山引擎", "doubao", "豆包", "seedance", "seedream"],
    "kunlun": ["mureka", "昆仑万维", "kunlun"],
    "kuaishou": ["kling", "可灵", "kuaishou", "快手"],
    "pixverse": ["pixverse", "pixverseai"],
    "vidu": ["vidu", "生数科技"],
    "minimax": ["minimax", "MiniMax"],
}

_PROVIDER_DOMAINS: dict[str, list[str]] = {
    "alibaba": ["aliyun.com", "aliyuncs.com"],
    "deepseek": ["deepseek.com"],
    "volcengine": ["volcengine.com", "volces.com"],
    "kunlun": ["mureka.cn"],
    "kuaishou": ["klingai.com", "kuaishou.com"],
    "pixverse": ["pixverseai.com", "pixverse.ai"],
    "vidu": ["vidu.cn"],
    "minimax": ["minimaxi.com"],
}

_GLOBAL_FALLBACK_SOURCES: dict[str, list[str]] = {
    "alibaba": [
        "https://help.aliyun.com/zh/model-studio/models",
        "https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api",
    ],
    "deepseek": [
        "https://help.aliyun.com/zh/model-studio/deepseek-api",
        "https://help.aliyun.com/zh/model-studio/models",
    ],
    "volcengine": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "kunlun": [
        "https://platform.mureka.cn/docs/",
    ],
    "kuaishou": [
        "https://help.aliyun.com/zh/model-studio/kling-video-generation-api-reference",
    ],
    "pixverse": [
        "https://help.aliyun.com/zh/model-studio/pixverse-video-generation-api-reference",
    ],
    "vidu": [
        "https://help.aliyun.com/zh/model-studio/vidu-img2video-api-reference",
    ],
    "minimax": [
        "https://help.aliyun.com/zh/model-studio/minimax-tts-api-reference",
    ],
}

# 全局通用搜索源（所有模型都会使用）
_UNIVERSAL_FALLBACK_SOURCES: list[str] = [
    "https://www.modelscope.cn/home",  # ModelScope 魔搭社区 - 国内最大模型开放平台
    "https://artificialanalysis.ai/",  # Artificial Analysis - AI模型性能分析和基准测试
    "https://waytoagi.feishu.cn/wiki/QPe5w5g7UisbEkkow8XcDmOpn8e",  # WayToAGI 飞书知识库 - AGI学习资源和模型信息汇总
]

_MODEL_FALLBACK_SOURCES: dict[str, list[str]] = {
    "qwen3.5-omni-plus": [
        "https://help.aliyun.com/zh/model-studio/qwen3-omni-plus-api-reference",
        "https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api",
    ],
    "qwen3.6-plus": [
        "https://help.aliyun.com/zh/model-studio/qwen3-api-reference",
        "https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api",
    ],
    "qwen3-vl-plus": [
        "https://help.aliyun.com/zh/model-studio/qwen-vl-plus-api-reference",
        "https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api",
    ],
    "doubao-seed-2-0-pro": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "doubao-seed-2-0-lite": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "qwen-image-2.0": [
        "https://help.aliyun.com/zh/model-studio/qwen-image-generation-api-reference",
        "https://help.aliyun.com/zh/model-studio/wanx-image-generation-quick-start",
    ],
    "qwen-image-2.0-pro": [
        "https://help.aliyun.com/zh/model-studio/qwen-image-generation-api-reference",
    ],
    "wan2.7-image": [
        "https://help.aliyun.com/zh/model-studio/wan2-image-generation-api-reference",
    ],
    "wan2.6-t2i": [
        "https://help.aliyun.com/zh/model-studio/wan2-image-generation-api-reference",
    ],
    "kling/kling-v3-image-generation": [
        "https://help.aliyun.com/zh/model-studio/kling-image-generation-api-reference",
    ],
    "kling/kling-v3-omni-image-generation": [
        "https://help.aliyun.com/zh/model-studio/kling-image-generation-api-reference",
    ],
    "doubao-seedream-4-5": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "doubao-seedream-5-0": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "qwen-image-edit-plus": [
        "https://help.aliyun.com/zh/model-studio/qwen-image-edit-api-reference",
    ],
    "qwen-image-edit-max": [
        "https://help.aliyun.com/zh/model-studio/qwen-image-edit-api-reference",
    ],
    "MiniMax/speech-2.8-turbo": [
        "https://help.aliyun.com/zh/model-studio/minimax-tts-api-reference",
    ],
    "MiniMax/speech-2.8-hd": [
        "https://help.aliyun.com/zh/model-studio/minimax-tts-api-reference",
    ],
    "qwen3-tts-flash": [
        "https://help.aliyun.com/zh/model-studio/qwen-tts-api-reference",
    ],
    "cosyvoice-v3-plus": [
        "https://help.aliyun.com/zh/model-studio/cosyvoice-api-reference",
    ],
    "wan2.7-t2v": [
        "https://help.aliyun.com/zh/model-studio/wan-video-generation-api-reference",
    ],
    "wan2.6-t2v-fast": [
        "https://help.aliyun.com/zh/model-studio/wan-video-generation-api-reference",
    ],
    "wan2.7-i2v": [
        "https://help.aliyun.com/zh/model-studio/wan-video-generation-api-reference",
    ],
    "wan2.7-r2v": [
        "https://help.aliyun.com/zh/model-studio/wan-video-generation-api-reference",
    ],
    "wan2.7-videoedit": [
        "https://help.aliyun.com/zh/model-studio/wan-video-generation-api-reference",
    ],
    "pixverse-c1-r2v": [
        "https://help.aliyun.com/zh/model-studio/pixverse-video-generation-api-reference",
    ],
    "pixverse-v6-t2v": [
        "https://help.aliyun.com/zh/model-studio/pixverse-video-generation-api-reference",
    ],
    "vidu-q3-pro-text2video": [
        "https://help.aliyun.com/zh/model-studio/vidu-text2video-api-reference",
    ],
    "vidu-q3-pro-img2video": [
        "https://help.aliyun.com/zh/model-studio/vidu-img2video-api-reference",
    ],
    "vidu-q3-pro-start-end2video": [
        "https://help.aliyun.com/zh/model-studio/vidu-keyframe-to-video-api-reference",
    ],
    "kling/kling-v3-video-generation": [
        "https://help.aliyun.com/zh/model-studio/kling-video-generation-api-reference",
    ],
    "kling/kling-v3-omni-video-generation": [
        "https://help.aliyun.com/zh/model-studio/kling-video-generation-api-reference",
    ],
    "doubao-seedance-2-0": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "doubao-seedance-2-0-fast": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "doubao-seedance-1-5-pro": [
        "https://www.volcengine.com/docs/82379/1520757",
        "https://www.volcengine.com/docs/82379/1399132",
    ],
    "vidu-timing2audio": [
        "https://platform.vidu.cn/docs/timing-to-audio",
        "https://docs.platform.vidu.cn/",
    ],
    "mureka-o1-instrumental": [
        "https://platform.mureka.cn/docs/",
        "https://platform.mureka.cn/docs/api/operations/post-v1-instrumental-generate.html",
    ],
}

_MODEL_ALIAS_KEYWORDS: dict[str, list[str]] = {
    "qwen3-max": ["qwen-max", "qwen max", "千问max", "千问 max"],
    "qwen3-vl-plus": ["qwen-vl-plus", "qwen vl plus"],
    "deepseek-reasoner": ["deepseek-r1", "deepseek r1"],
    "wan2.6-t2i": [
        "wan 2.6 text-to-image",
        "wan2.6 text-to-image",
    ],
    "wan2.7-t2v": [
        "wan 2.7 text-to-video",
        "wan2.7 text-to-video",
    ],
    "wan2.7-i2v": [
        "wan 2.7 image-to-video",
        "wan2.7 image-to-video",
    ],
    "wan2.7-r2v": [
        "wan 2.7 reference-to-video",
        "wan2.7 reference-to-video",
    ],
    "wan2.7-videoedit": [
        "wan 2.7 video edit",
        "wan2.7 video edit",
        "wan 2.7 video-edit",
    ],
}

_ERROR_PAGE_KEYWORDS = [
    "404错误页",
    "404 error",
    "page not found",
    "not found",
    "页面不存在",
]


@dataclass(slots=True)
class CatalogSeed:
    """归一化后的模型种子信息。"""

    model_key: str
    name: str
    provider: str
    category: str
    subcategory: str
    model_family: str
    config_source: str
    status: str
    summary: str
    recommended_scenarios: list[str]
    limitations: list[str]
    integration_notes: list[str]
    documentation_url: str
    source_urls: list[str]
    tags: list[str]
    modalities: list[str]
    capabilities: list[dict[str, Any]]
    constraints: dict[str, Any]
    performance: dict[str, Any]
    routing: dict[str, Any]
    default_params: dict[str, Any]
    raw_config: dict[str, Any]


@dataclass(slots=True)
class SourceVerification:
    """单个来源的联网校验结果。"""

    url: str
    source_type: str
    source_domain: str
    http_status: Optional[int]
    reachable: bool
    verified: bool
    page_title: str
    page_excerpt: str
    matched_keywords: list[str]
    verification_note: str
    raw_metadata: dict[str, Any]
    fetched_at: Optional[datetime]
    score: float
    extracted_specs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DetailedSpecExtraction:
    """从网页中提取的详细规格信息。"""

    duration_range: Optional[dict[str, Any]] = None
    resolution_options: list[str] = field(default_factory=list)
    frame_rate: Optional[int] = None
    output_format: Optional[str] = None
    input_modalities: list[str] = field(default_factory=list)
    advanced_features: list[str] = field(default_factory=list)
    max_reference_images: Optional[int] = None
    weight_control: bool = False
    first_frame_support: bool = False
    last_frame_support: bool = False
    prompt_examples: list[dict[str, str]] = field(default_factory=list)
    best_practices: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    extraction_confidence: float = 0.0
    extraction_source: str = ""

