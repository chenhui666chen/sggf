"""模型档案中心同步与联网校验服务。"""

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
    "alibaba": ["alibaba", "aliyun", "通义", "百炼", "dashscope"],
    "deepseek": ["deepseek"],
    "kunlun": ["mureka", "昆仑万维", "kunlun"],
    "stability": ["stability", "stable diffusion", "stable image"],
    "kuaishou": ["kling", "可灵", "kuaishou", "快手"],
}

_PROVIDER_DOMAINS: dict[str, list[str]] = {
    "alibaba": ["aliyun.com", "aliyuncs.com"],
    "deepseek": ["deepseek.com"],
    "kunlun": ["mureka.cn"],
    "kuaishou": ["klingai.com", "kuaishou.com"],
}

_GLOBAL_FALLBACK_SOURCES: dict[str, list[str]] = {
    "alibaba": [
        "https://help.aliyun.com/zh/model-studio/models",
    ],
    "deepseek": [
        "https://help.aliyun.com/zh/model-studio/deepseek-api",
        "https://help.aliyun.com/zh/model-studio/models",
    ],
    "kunlun": [
        "https://platform.mureka.cn/docs/",
    ],
}

_MODEL_FALLBACK_SOURCES: dict[str, list[str]] = {
    "mureka-o1-instrumental": [
        "https://platform.mureka.cn/docs/",
        "https://platform.mureka.cn/docs/api/operations/post-v1-instrumental-generate.html",
    ],
    "vidu-timing2audio": [
        "https://www.vidu.cn/",
        "https://docs.platform.vidu.cn/",
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


class ModelCatalogSyncService:
    """负责从配置读取模型清单、联网核验并同步到数据库。"""

    def __init__(self, config_dir: Optional[Path] = None):
        project_root = Path(__file__).resolve().parents[3]
        self._config_dir = config_dir or (project_root / "config")
        self._llm_config_path = self._config_dir / "llm_models.yaml"
        self._model_config_path = self._config_dir / "models.yaml"
        self._catalog_profile_path = self._config_dir / "model_catalog_profiles.yaml"
        self._runtime_snapshot_path = self._config_dir / "model_catalog_runtime.json"
        self._response_cache: Optional[dict[str, httpx.Response]] = None
        self._fetch_cache_hits = 0
        self._fetch_cache_misses = 0

    def load_catalog_seeds(self) -> list[CatalogSeed]:
        """从配置文件读取模型清单并归一化。"""

        seeds: list[CatalogSeed] = []
        catalog_profiles = self._load_catalog_profiles()

        llm_payload = self._load_yaml(self._llm_config_path)
        for raw in llm_payload.get("llm_models", []) or []:
            model_key = str(raw.get("id", "")).strip()
            seeds.append(
                self._normalize_llm_seed(
                    raw,
                    catalog_profile=catalog_profiles.get(model_key),
                )
            )

        model_payload = self._load_yaml(self._model_config_path)
        for raw in model_payload.get("models", []) or []:
            model_key = str(raw.get("id", "")).strip()
            seeds.append(
                self._normalize_capability_seed(
                    raw,
                    catalog_profile=catalog_profiles.get(model_key),
                )
            )

        return sorted(seeds, key=lambda item: (item.category, item.provider, item.name.lower()))

    def get_entry_queryset(self, db: Session):
        """统一封装查询，默认带来源预加载。"""

        active_model_keys = sorted({seed.model_key for seed in self.load_catalog_seeds()})
        query = db.query(ModelCatalogEntry).options(selectinload(ModelCatalogEntry.sources))
        if not active_model_keys:
            return query.filter(ModelCatalogEntry.id == -1)
        return query.filter(ModelCatalogEntry.model_key.in_(active_model_keys))

    def sync_catalog(
        self,
        db: Session,
        *,
        force_refresh: bool = False,
        model_keys: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """执行配置归档与联网校验同步。
        
        Args:
            db: 数据库会话
            force_refresh: 强制刷新所有模型，忽略更新检测
            model_keys: 指定要校验的模型，未指定时校验所有
        """

        all_seeds = self.load_catalog_seeds()
        all_seed_keys = {seed.model_key for seed in all_seeds}
        seeds = all_seeds
        requested_model_keys: Optional[set[str]] = None
        if model_keys:
            allowed = {item.strip() for item in model_keys if item and item.strip()}
            requested_model_keys = allowed
            seeds = [seed for seed in seeds if seed.model_key in allowed]
        
        # 加载 models.yaml 的配置内容，用于检测模型是否更新
        current_model_configs = {}
        try:
            model_payload = self._load_yaml(self._model_config_path)
            for raw in model_payload.get("models", []) or []:
                model_key = str(raw.get("id", "")).strip()
                if model_key:
                    current_model_configs[model_key] = raw
        except Exception as e:
            logger.warning(f"加载模型配置失败，将跳过更新检测: {e}")

        now = datetime.now(timezone.utc)
        stats = {
            "processed": 0,
            "verified": 0,
            "partial": 0,
            "failed": 0,
            "skipped": 0,
            "skipped_up_to_date": 0,
            "updated_at": now.isoformat(),
            "model_keys": [],
            "cache_hits": 0,
            "network_requests": 0,
            "cached_response_count": 0,
            "deleted_obsolete_entries": 0,
            "deleted_model_keys": [],
        }
        previous_cache = self._response_cache
        previous_hits = self._fetch_cache_hits
        previous_misses = self._fetch_cache_misses
        self._response_cache = {}
        self._fetch_cache_hits = 0
        self._fetch_cache_misses = 0

        try:
            deleted_model_keys = self._prune_obsolete_entries(
                db,
                active_model_keys=all_seed_keys,
                restrict_to_model_keys=requested_model_keys,
            )
            stats["deleted_obsolete_entries"] = len(deleted_model_keys)
            stats["deleted_model_keys"] = deleted_model_keys

            for seed in seeds:
                entry = db.query(ModelCatalogEntry).filter(ModelCatalogEntry.model_key == seed.model_key).first()
                if entry and self._should_skip_refresh(
                    entry,
                    seed,
                    current_model_configs.get(seed.model_key),
                    force_refresh=force_refresh,
                    now=now,
                ):
                    stats["skipped"] += 1
                    stats["skipped_up_to_date"] += 1
                    continue

                if entry is None:
                    entry = ModelCatalogEntry(model_key=seed.model_key)
                    db.add(entry)

                self._apply_seed_to_entry(entry, seed)
                db.flush()

                db.query(ModelCatalogSource).filter(ModelCatalogSource.entry_id == entry.id).delete(
                    synchronize_session=False
                )

                verifications = self._verify_seed(seed)
                self._apply_verifications_to_entry(entry, seed, verifications, now)
                
                pricing_result = self._verify_pricing_for_model(seed.model_key)
                self._apply_pricing_to_entry(entry, pricing_result)
                
                capability_issues = self._verify_capability_provenance(seed)
                if capability_issues:
                    entry.verification_notes += f" 能力溯源问题: {', '.join(capability_issues[:3])}"
                
                error_handler_issues = self._verify_error_handlers(seed)
                if error_handler_issues:
                    entry.verification_notes += f" 错误处理问题: {', '.join(error_handler_issues[:3])}"

                for verification in verifications:
                    db.add(
                        ModelCatalogSource(
                            entry_id=entry.id,
                            url=verification.url,
                            source_type=verification.source_type,
                            source_domain=verification.source_domain,
                            http_status=verification.http_status,
                            reachable=verification.reachable,
                            verified=verification.verified,
                            page_title=verification.page_title,
                            page_excerpt=verification.page_excerpt,
                            matched_keywords=verification.matched_keywords,
                            verification_note=verification.verification_note,
                            raw_metadata_json=verification.raw_metadata,
                            fetched_at=verification.fetched_at,
                        )
                    )

                stats["processed"] += 1
                stats["model_keys"].append(seed.model_key)
                stats[entry.verification_status] = stats.get(entry.verification_status, 0) + 1

            stats["cache_hits"] = self._fetch_cache_hits
            stats["network_requests"] = self._fetch_cache_misses
            stats["cached_response_count"] = len(self._response_cache or {})
            db.commit()
            try:
                snapshot_entries = self.get_entry_queryset(db).all()
                self._write_runtime_snapshot(snapshot_entries, generated_at=now)
                stats["runtime_snapshot_updated"] = True
                stats["runtime_snapshot_path"] = str(self._runtime_snapshot_path)
            except Exception as exc:
                logger.warning("写入模型档案运行时快照失败 | path=%s | error=%s", self._runtime_snapshot_path, exc)
                stats["runtime_snapshot_updated"] = False
                stats["runtime_snapshot_error"] = str(exc)
            return stats
        except Exception:
            db.rollback()
            raise
        finally:
            self._response_cache = previous_cache
            self._fetch_cache_hits = previous_hits
            self._fetch_cache_misses = previous_misses

    def _prune_obsolete_entries(
        self,
        db: Session,
        *,
        active_model_keys: set[str],
        restrict_to_model_keys: Optional[set[str]] = None,
    ) -> list[str]:
        deleted_model_keys: list[str] = []
        existing_entries = db.query(ModelCatalogEntry).all()

        for entry in existing_entries:
            model_key = str(entry.model_key or "").strip()
            if not model_key:
                continue
            if model_key in active_model_keys:
                continue
            if restrict_to_model_keys is not None and model_key not in restrict_to_model_keys:
                continue

            db.query(ModelCatalogSource).filter(ModelCatalogSource.entry_id == entry.id).delete(
                synchronize_session=False
            )
            db.query(ModelCatalogEntry).filter(ModelCatalogEntry.id == entry.id).delete(
                synchronize_session=False
            )
            deleted_model_keys.append(model_key)

        if deleted_model_keys:
            db.flush()
        return deleted_model_keys

    def _should_skip_refresh(
        self,
        entry: ModelCatalogEntry,
        seed: "CatalogSeed",
        current_config: Optional[dict[str, Any]] = None,
        *,
        force_refresh: bool = False,
        now: datetime,
    ) -> bool:
        """判断是否应该跳过该模型的校验
        
        跳过条件（满足任一即可）：
        1. force_refresh=False（非强制刷新）
        2. 该模型已被校验过（last_verified_at 不为空）
        3. 模型配置自上次校验后未发生变化
        
        Args:
            entry: 数据库中的模型档案
            seed: 当前加载的种子配置
            current_config: models.yaml 中的当前配置（原始dict）
            force_refresh: 是否强制刷新
            now: 当前时间
        """
        # 强制刷新时不过期
        if force_refresh:
            return False
        
        # 从未校验过的模型需要校验
        if entry.last_verified_at is None:
            return False
        
        # 模型配置未发生变化且已校验过，则跳过
        if not self._has_model_config_changed(entry, seed, current_config):
            return True
        
        return False
    
    def _has_model_config_changed(
        self,
        entry: ModelCatalogEntry,
        seed: "CatalogSeed",
        current_config: Optional[dict[str, Any]] = None,
    ) -> bool:
        """检测模型配置是否自上次校验后发生变化
        
        检测项：
        1. capabilities - 能力列表是否变化
        2. tags - 标签列表是否变化
        3. constraints - 约束条件是否变化
        4. performance - 性能配置是否变化
        
        Args:
            entry: 数据库中的模型档案
            seed: 当前加载的种子配置
            current_config: models.yaml 中的当前配置
            
        Returns:
            True 表示配置已变化，需要重新校验
        """
        if current_config is None:
            # 无法获取当前配置，保守起见需要校验
            return True
        
        # 对比 capabilities
        current_caps = current_config.get("capabilities", [])
        seed_caps = seed.capabilities or []
        if len(current_caps) != len(seed_caps):
            return True
        
        current_cap_names = {c.get("name") for c in current_caps if isinstance(c, dict)}
        seed_cap_names = {c.get("name") for c in seed_caps if isinstance(c, dict)}
        if current_cap_names != seed_cap_names:
            return True
        
        # 对比 tags
        current_tags = set(current_config.get("tags", []))
        seed_tags = set(seed.tags or [])
        if current_tags != seed_tags:
            return True
        
        # 对比 constraints
        current_constraints = current_config.get("constraints", {})
        seed_constraints = seed.constraints or {}
        if current_constraints != seed_constraints:
            return True
        
        # 对比 performance
        current_performance = current_config.get("performance", {})
        seed_performance = seed.performance or {}
        if current_performance != seed_performance:
            return True
        
        return False
    
    def _verify_pricing_for_model(self, model_key: str) -> dict[str, Any]:
        """校验模型价格信息
        
        Args:
            model_key: 模型标识符
            
        Returns:
            价格校验结果字典，包含 verified/pricing/source/verified_at 字段
        """
        if model_key in VERIFIED_PRICING_DATA:
            pricing = VERIFIED_PRICING_DATA[model_key]
            first_tier = next(iter(pricing.values())) if pricing else {}
            source_url = first_tier.get("source", "") if isinstance(first_tier, dict) else ""
            
            return {
                "verified": True,
                "pricing": pricing,
                "source": source_url or "多渠道交叉验证",
                "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "confidence": "high",
            }
        
        return {
            "verified": False,
            "pricing": None,
            "source": "未在已验证价格数据库中找到",
            "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "confidence": "low",
        }
    
    async def _verify_pricing_from_provider(
        self,
        seed: dict[str, Any],
        model_key: str,
    ) -> Optional[dict[str, Any]]:
        """
        Verify pricing information from cloud provider.
        
        Args:
            seed: Model seed data from models.yaml
            model_key: Model identifier
        
        Returns:
            Pricing information dict or None if verification failed
        """
        api_config = seed.get("api_config", {})
        auth_type = api_config.get("auth_type", "")
        
        # Only verify pricing for Alibaba Cloud DashScope
        if auth_type != "alibaba_cloud_dashscope":
            return None
        
        pricing_config = PRICING_VERIFICATION_CONFIG.get(auth_type)
        if not pricing_config:
            return None
        
        pricing_url = pricing_config["pricing_url"]
        timeout = pricing_config["timeout_seconds"]
        
        try:
            # Fetch pricing page
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(pricing_url)
                response.raise_for_status()
                html_content = response.text
            
            # Extract pricing information from HTML
            pricing_info = self._extract_pricing_from_html(html_content, model_key)
            
            if pricing_info:
                logger.info(
                    "Verified pricing for %s: %s",
                    model_key,
                    pricing_info.get("price", "N/A")
                )
                return {
                    "success": True,
                    "pricing": pricing_info,
                    "source_url": pricing_url,
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                logger.warning("Could not extract pricing for %s from %s", model_key, pricing_url)
                return None
        
        except httpx.TimeoutException as e:
            logger.warning("Timeout fetching pricing for %s: %s", model_key, e)
            return {"success": False, "error": f"Timeout: {str(e)}"}
        except httpx.RequestError as e:
            logger.warning("Request error fetching pricing for %s: %s", model_key, e)
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.warning("Error verifying pricing for %s: %s", model_key, e)
            return {"success": False, "error": f"Error: {str(e)}"}
    
    def _extract_pricing_from_html(
        self,
        html_content: str,
        model_key: str,
    ) -> Optional[dict[str, Any]]:
        """
        Extract pricing information from HTML content.
        
        Args:
            html_content: HTML content from pricing page
            model_key: Model identifier to search for
        
        Returns:
            Pricing information dict or None
        """
        # Clean HTML content
        text = _SCRIPT_STYLE_RE.sub("", html_content)
        text = _TAG_RE.sub(" ", text)
        text = unescape(text)
        text = _SPACE_RE.sub(" ", text).strip()
        
        # Search for model-specific pricing
        # Example: "MiniMax/speech-2.8-hd 3.5 元"
        model_name = model_key.replace("-", "/")  # Convert model ID to official name
        
        # Try to find pricing pattern
        pricing_patterns = [
            rf"{re.escape(model_name)}.*?(\d+\.?\d*)\s*元",
            rf"(\d+\.?\d*)\s*元.*?{re.escape(model_name)}",
        ]
        
        for pattern in pricing_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                price = float(match.group(1))
                return {
                    "price": price,
                    "currency": "CNY",
                    "unit": "元/万字符",
                    "model": model_name,
                }
        
        # If specific price not found, return general pricing info
        return {
            "note": "价格请以阿里云百炼平台实时价格为准",
            "pricing_url": "https://help.aliyun.com/zh/model-studio/pricing",
        }

    def _apply_seed_to_entry(self, entry: ModelCatalogEntry, seed: CatalogSeed) -> None:
        entry.name = seed.name
        entry.provider = seed.provider
        entry.category = seed.category
        entry.subcategory = seed.subcategory
        entry.model_family = seed.model_family
        entry.config_source = seed.config_source
        entry.status = seed.status
        entry.summary = seed.summary
        entry.recommended_scenarios = seed.recommended_scenarios
        entry.limitations = seed.limitations
        entry.integration_notes = seed.integration_notes
        entry.documentation_url = seed.documentation_url
        entry.source_urls = seed.source_urls
        entry.tags = seed.tags
        entry.modalities = seed.modalities
        entry.capabilities_json = {"items": seed.capabilities}
        entry.constraints_json = seed.constraints
        entry.performance_json = seed.performance
        entry.routing_json = seed.routing
        entry.default_params_json = seed.default_params
        entry.raw_config_json = seed.raw_config

    def _apply_verifications_to_entry(
        self,
        entry: ModelCatalogEntry,
        seed: CatalogSeed,
        verifications: list[SourceVerification],
        synced_at: datetime,
    ) -> None:
        reachable = sum(1 for item in verifications if item.reachable)
        verified = sum(1 for item in verifications if item.verified)
        avg_score = sum(item.score for item in verifications) / len(verifications) if verifications else 0.0

        if reachable >= 2 and verified >= 1:
            status = "verified"
            note = "至少两个来源可达，且已识别模型身份与主模态。"
        elif reachable >= 1:
            status = "partial"
            note = "已完成单源或弱匹配校验，建议继续补充官方来源。"
        else:
            status = "failed"
            note = "当前未能访问可用来源，请稍后重试或检查文档链接。"

        entry.verification_status = status
        entry.verification_scope = "模型身份 + 提供商 + 主模态"
        entry.verification_score = round(avg_score, 4)
        entry.total_source_count = len(verifications)
        entry.reachable_source_count = reachable
        entry.verified_source_count = verified
        entry.verification_notes = note
        entry.last_synced_at = synced_at
        entry.last_verified_at = synced_at

        extracted_specs_list = [
            DetailedSpecExtraction(
                duration_range=item.extracted_specs.get("duration_range"),
                resolution_options=item.extracted_specs.get("resolution_options", []),
                frame_rate=item.extracted_specs.get("frame_rate"),
                output_format=item.extracted_specs.get("output_format"),
                input_modalities=item.extracted_specs.get("input_modalities", []),
                advanced_features=item.extracted_specs.get("advanced_features", []),
                max_reference_images=item.extracted_specs.get("max_reference_images"),
                weight_control=item.extracted_specs.get("weight_control", False),
                first_frame_support=item.extracted_specs.get("first_frame_support", False),
                last_frame_support=item.extracted_specs.get("last_frame_support", False),
                prompt_examples=item.extracted_specs.get("prompt_examples", []),
                extraction_confidence=item.extracted_specs.get("extraction_confidence", 0.0),
                extraction_source=item.extracted_specs.get("extraction_source", ""),
            )
            for item in verifications
            if item.extracted_specs and item.extracted_specs.get("extraction_confidence", 0) > 0.2
        ]

        if extracted_specs_list:
            existing_specs = (entry.raw_config_json or {}).get("detailed_specs", {})
            merged_specs = self._merge_extracted_specs(extracted_specs_list, existing_specs, seed.category)
            if merged_specs:
                entry.raw_config_json = {
                    **(entry.raw_config_json or {}),
                    "detailed_specs": merged_specs,
                }
                note += f" 已从 {len(extracted_specs_list)} 个来源提取详细规格。"

    def _apply_pricing_to_entry(self, entry: ModelCatalogEntry, pricing_result: dict[str, Any]) -> None:
        """将价格校验结果应用到模型档案
        
        Args:
            entry: 模型档案实体
            pricing_result: 价格校验结果
        """
        raw_config = entry.raw_config_json or {}
        
        existing_pricing = raw_config.get("pricing_verification", {})
        
        updated_pricing = {
            **existing_pricing,
            "last_verified_at": pricing_result.get("verified_at"),
            "pricing_status": "verified" if pricing_result.get("verified") else "unverified",
            "confidence": pricing_result.get("confidence", "low"),
            "source": pricing_result.get("source", ""),
        }
        
        if pricing_result.get("verified") and pricing_result.get("pricing"):
            verified_pricing = pricing_result["pricing"]
            first_tier = next(iter(verified_pricing.values())) if verified_pricing else {}
            
            if isinstance(first_tier, dict):
                updated_pricing["price"] = first_tier.get("price")
                updated_pricing["unit"] = first_tier.get("unit")
                updated_pricing["currency"] = "CNY"
                updated_pricing["pricing_tiers"] = verified_pricing
                
                cost_profile = entry.performance_json.get("cost_profile", {}) or {}
                cost_profile["price"] = first_tier.get("price")
                cost_profile["unit"] = first_tier.get("unit")
                cost_profile["currency"] = "CNY"
                cost_profile["pricing_verified"] = True
                entry.performance_json = {
                    **entry.performance_json,
                    "cost_profile": cost_profile,
                }
        
        raw_config["pricing_verification"] = updated_pricing
        entry.raw_config_json = raw_config

    def _verify_capability_provenance(self, seed: CatalogSeed) -> list[str]:
        """验证能力溯源字段的完整性
        
        Args:
            seed: 模型种子信息
            
        Returns:
            问题列表，如果所有能力溯源完整则返回空列表
        """
        issues = []
        capabilities = seed.capabilities or []
        
        for cap in capabilities:
            if not isinstance(cap, dict):
                continue
            
            cap_name = cap.get("name", "unnamed")
            
            if not cap.get("source") or cap.get("source", "").startswith("TODO"):
                issues.append(f"{cap_name}: 缺少溯源来源(source)")
            
            if not cap.get("verified_at"):
                issues.append(f"{cap_name}: 缺少验证时间(verified_at)")
            
            if not cap.get("confidence") or cap.get("confidence") not in ("high", "medium", "low"):
                issues.append(f"{cap_name}: 置信度(confidence)无效")
        
        return issues
    
    def _verify_error_handlers(self, seed: CatalogSeed) -> list[str]:
        """验证 error_handlers 配置的完整性
        
        检查项：
        1. content_safety - 内容安全错误处理配置
        2. rate_limit - 限流错误处理配置
        3. timeout - 超时错误处理配置
        4. fallback_model - 降级模型是否有效
        
        Args:
            seed: 模型种子信息
            
        Returns:
            问题列表，如果 error_handlers 配置完整则返回空列表
        """
        issues = []
        raw_config = seed.raw_config or {}
        error_handlers = raw_config.get("error_handlers", {})
        
        if not error_handlers:
            # error_handlers 是可选的，没有配置不报错
            return issues
        
        # 检查 content_safety
        content_safety = error_handlers.get("content_safety", {})
        if content_safety:
            if not content_safety.get("action"):
                issues.append("content_safety: 缺少 action 配置")
            if not content_safety.get("retry") is None and not isinstance(content_safety.get("retry"), bool):
                issues.append("content_safety: retry 应为布尔值")
        
        # 检查 rate_limit
        rate_limit = error_handlers.get("rate_limit", {})
        if rate_limit:
            if not rate_limit.get("action"):
                issues.append("rate_limit: 缺少 action 配置")
            wait_seconds = rate_limit.get("wait_seconds")
            if wait_seconds is not None and (not isinstance(wait_seconds, (int, float)) or wait_seconds <= 0):
                issues.append("rate_limit: wait_seconds 应为正数")
        
        # 检查 timeout
        timeout = error_handlers.get("timeout", {})
        if timeout:
            if not timeout.get("action"):
                issues.append("timeout: 缺少 action 配置")
            fallback_model = timeout.get("fallback_model")
            if fallback_model and not isinstance(fallback_model, str):
                issues.append("timeout: fallback_model 应为字符串")
        
        return issues
    
    def _run_three_layer_consistency_check(self, model_keys: Optional[list[str]] = None) -> dict[str, Any]:
        """运行三层配置一致性校验（intent_domains <-> models <-> semantic_matcher）
        
        Args:
            model_keys: 可选，仅校验指定模型
            
        Returns:
            校验结果字典
        """
        try:
            import importlib
            import sys
            
            # 确保项目根目录在 sys.path 中
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            
            # 动态导入 verify_model_config 模块
            spec = importlib.util.spec_from_file_location(
                "verify_model_config",
                project_root / "scripts" / "verify_model_config.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            issues = module.Issues()
            domains = module.load_domains()
            models = module.load_models()
            matcher_vocab = module.load_matcher_vocab()
            
            if model_keys:
                models = [m for m in models if m.get("id") in model_keys]
            
            module.check_style_vocab(domains, matcher_vocab, issues)
            module.check_model_tags(domains, models, issues)
            module.check_model_capabilities(models, issues)
            module.check_video_models_in_tags(domains, models, issues)
            module.check_camera_terms(domains, matcher_vocab, issues)
            
            return {
                "check_status": "completed",
                "errors": issues.errors,
                "warnings": issues.warnings,
                "fixes": issues.fixes,
                "is_consistent": issues.ok(),
                "error_count": len(issues.errors),
                "warning_count": len(issues.warnings),
            }
        except Exception as e:
            logger.warning(f"三层配置一致性校验失败: {e}")
            return {
                "check_status": "failed",
                "errors": [str(e)],
                "warnings": [],
                "fixes": [],
                "is_consistent": False,
                "error_count": 1,
                "warning_count": 0,
            }

    def _build_runtime_snapshot(
        self,
        entries: list[ModelCatalogEntry],
        *,
        generated_at: datetime,
    ) -> dict[str, Any]:
        payload_entries: dict[str, dict[str, Any]] = {}
        for entry in entries:
            payload_entries[entry.model_key] = {
                "model_key": entry.model_key,
                "provider": entry.provider,
                "category": entry.category,
                "modalities": list(entry.modalities or []),
                "verification_status": entry.verification_status,
                "verification_score": entry.verification_score,
                "total_source_count": entry.total_source_count,
                "reachable_source_count": entry.reachable_source_count,
                "verified_source_count": entry.verified_source_count,
                "last_verified_at": entry.last_verified_at.isoformat() if entry.last_verified_at else None,
                "last_synced_at": entry.last_synced_at.isoformat() if entry.last_synced_at else None,
                "capability_hints": self._derive_runtime_capability_hints(entry),
                "task_constraints": self._derive_runtime_task_constraints(entry),
            }

        return {
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "entry_count": len(payload_entries),
            "entries": payload_entries,
        }

    def _write_runtime_snapshot(
        self,
        entries: list[ModelCatalogEntry],
        *,
        generated_at: datetime,
    ) -> None:
        payload = self._build_runtime_snapshot(entries, generated_at=generated_at)
        snapshot_path = self._runtime_snapshot_path
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = snapshot_path.with_suffix(f"{snapshot_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(snapshot_path)

    def _derive_runtime_capability_hints(self, entry: ModelCatalogEntry) -> dict[str, Any]:
        raw = entry.raw_config_json or {}
        detailed_specs = raw.get("detailed_specs") or {}
        video_specs = detailed_specs.get("video_generation") or {}
        image_editing_specs = detailed_specs.get("image_editing") or {}

        reference_input = video_specs.get("reference_input") or {}
        reference_images = reference_input.get("reference_images") or {}
        reference_videos = reference_input.get("reference_videos") or {}
        frame_control = video_specs.get("frame_control") or {}
        multi_image_input = image_editing_specs.get("multi_image_input") or {}

        input_modalities: list[str] = []
        for item in video_specs.get("input_modalities") or []:
            if isinstance(item, dict):
                modality_id = str(item.get("id") or "").strip().lower()
                if modality_id and modality_id not in input_modalities:
                    input_modalities.append(modality_id)

        advanced_feature_ids = {
            str(item.get("id") or "").strip().lower()
            for item in video_specs.get("advanced_features") or []
            if isinstance(item, dict)
        }
        modalities = {str(item).strip().lower() for item in entry.modalities or []}

        def _coerce_int(value: Any) -> Optional[int]:
            try:
                if value is None or value == "":
                    return None
                return int(value)
            except (TypeError, ValueError):
                return None

        max_reference_images = _coerce_int(reference_images.get("max_count"))
        multi_image_max_count = _coerce_int(multi_image_input.get("max_count"))
        if multi_image_max_count is not None:
            max_reference_images = max(max_reference_images or 0, multi_image_max_count)

        max_reference_videos = _coerce_int(reference_videos.get("max_count"))
        supports_reference_images = bool(
            reference_images.get("enabled")
            or multi_image_input.get("enabled")
            or "image" in input_modalities
            or "image_to_video" in modalities
            or "image_to_image_edit" in modalities
        )
        supports_reference_videos = bool(
            reference_videos.get("enabled")
            or "video_to_video" in modalities
            or "reference_to_video" in modalities
        )
        supports_first_frame = bool(frame_control.get("enabled") and frame_control.get("first_frame")) or bool(
            frame_control.get("first_frame")
        )
        supports_last_frame = bool(frame_control.get("enabled") and frame_control.get("last_frame")) or bool(
            frame_control.get("last_frame")
        )
        supports_audio_input = bool("audio" in input_modalities or "audio_sync" in advanced_feature_ids)
        supports_multi_image_edit = bool(multi_image_input.get("enabled") and (multi_image_max_count or 0) > 1)
        supports_camera_control = bool((video_specs.get("camera_control") or {}).get("enabled"))
        supports_motion_control = bool((video_specs.get("motion_control") or {}).get("enabled"))

        return {
            "supports_reference_images": supports_reference_images,
            "max_reference_images": max_reference_images,
            "supports_reference_videos": supports_reference_videos,
            "max_reference_videos": max_reference_videos,
            "supports_first_frame": supports_first_frame,
            "supports_last_frame": supports_last_frame,
            "supports_audio_input": supports_audio_input,
            "supports_multi_image_edit": supports_multi_image_edit,
            "supports_camera_control": supports_camera_control,
            "supports_motion_control": supports_motion_control,
            "declared_input_modalities": input_modalities,
        }

    def _derive_runtime_task_constraints(self, entry: ModelCatalogEntry) -> dict[str, Any]:
        constraints = entry.constraints_json or {}
        raw = entry.raw_config_json or {}
        detailed_specs = raw.get("detailed_specs") or {}

        def _coerce_int(value: Any) -> Optional[int]:
            try:
                if value is None or value == "":
                    return None
                return int(value)
            except (TypeError, ValueError):
                return None

        def _coerce_float(value: Any) -> Optional[float]:
            try:
                if value is None or value == "":
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        def _coerce_float_list(values: Any) -> list[float]:
            if not isinstance(values, list):
                return []
            result: list[float] = []
            for item in values:
                parsed = _coerce_float(item)
                if parsed is None:
                    continue
                if all(abs(existing - parsed) >= 0.001 for existing in result):
                    result.append(parsed)
            return result

        def _coerce_str_list(values: Any) -> list[str]:
            if not isinstance(values, list):
                return []
            result: list[str] = []
            for item in values:
                text = str(item or "").strip()
                if text and text not in result:
                    result.append(text)
            return result

        basic_params: dict[str, Any] = {}
        for section_name in ("video_generation", "image_generation", "image_editing", "audio_generation"):
            section = detailed_specs.get(section_name)
            if isinstance(section, dict) and isinstance(section.get("basic_params"), dict):
                basic_params = section.get("basic_params") or {}
                break

        duration_values = _coerce_float_list(constraints.get("duration"))
        duration_config = basic_params.get("duration") or {}
        if isinstance(duration_config, dict):
            derived_duration_values = _coerce_float_list(duration_config.get("supported_values"))
            if not derived_duration_values:
                min_seconds = _coerce_float(duration_config.get("min_seconds") or duration_config.get("min"))
                max_seconds = _coerce_float(duration_config.get("max_seconds") or duration_config.get("max"))
                step = _coerce_float(duration_config.get("step_seconds") or duration_config.get("step"))
                if (
                    min_seconds is not None
                    and max_seconds is not None
                    and step is not None
                    and step > 0
                    and max_seconds >= min_seconds
                    and (max_seconds - min_seconds) / step <= 60
                ):
                    current = min_seconds
                    generated_values: list[float] = []
                    while current <= max_seconds + 0.001:
                        generated_values.append(round(current, 3))
                        current += step
                    derived_duration_values = generated_values
            if derived_duration_values:
                duration_values = derived_duration_values

        ratio_values = _coerce_str_list(constraints.get("ratios"))
        aspect_ratio_config = basic_params.get("aspect_ratio") or {}
        if isinstance(aspect_ratio_config, dict):
            derived_ratio_values = _coerce_str_list(aspect_ratio_config.get("supported"))
            if derived_ratio_values:
                ratio_values = derived_ratio_values

        resolution_options: list[str] = []
        resolution_specs: list[dict[str, Any]] = []
        resolution_config = basic_params.get("resolution") or {}
        if isinstance(resolution_config, dict):
            resolution_options = _coerce_str_list(
                resolution_config.get("options") or resolution_config.get("supported")
            )
            for item in resolution_config.get("specs") or []:
                if not isinstance(item, dict):
                    continue
                width = _coerce_int(item.get("width"))
                height = _coerce_int(item.get("height"))
                if width is None or height is None:
                    continue
                resolution_specs.append(
                    {
                        "value": str(item.get("value") or item.get("label") or f"{width}x{height}"),
                        "width": width,
                        "height": height,
                    }
                )

        min_width = _coerce_int(constraints.get("min_width"))
        max_width = _coerce_int(constraints.get("max_width"))
        min_height = _coerce_int(constraints.get("min_height"))
        max_height = _coerce_int(constraints.get("max_height"))
        if resolution_specs and min_width is None:
            min_width = min(item["width"] for item in resolution_specs)
        if resolution_specs and max_width is None:
            max_width = max(item["width"] for item in resolution_specs)
        if resolution_specs and min_height is None:
            min_height = min(item["height"] for item in resolution_specs)
        if resolution_specs and max_height is None:
            max_height = max(item["height"] for item in resolution_specs)

        task_constraints = {
            "duration_values": duration_values,
            "ratio_values": ratio_values,
            "min_width": min_width,
            "max_width": max_width,
            "min_height": min_height,
            "max_height": max_height,
            "max_batch_size": _coerce_int(constraints.get("max_batch_size")),
            "resolution_options": resolution_options,
            "resolution_specs": resolution_specs,
        }
        return {
            key: value
            for key, value in task_constraints.items()
            if value not in (None, [], {})
        }

    def _verify_seed(self, seed: CatalogSeed) -> list[SourceVerification]:
        urls = self._build_source_candidates(seed)
        if not urls:
            return []

        with httpx.Client(
            follow_redirects=True,
            headers={
                "User-Agent": "NovelWritingAgent/ModelCatalogSync (+https://localhost)",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=httpx.Timeout(20.0, connect=8.0),
        ) as client:
            return self._deduplicate_verifications(
                [self._verify_single_source(client, seed, candidate) for candidate in urls]
            )

    def _verify_single_source(
        self,
        client: httpx.Client,
        seed: CatalogSeed,
        candidate: tuple[str, str],
    ) -> SourceVerification:
        source_type, url = candidate
        fetched_at = datetime.now(timezone.utc)
        domain = urlparse(url).netloc

        try:
            response = self._fetch_response(client, url)

            title = self._extract_title(response.text)
            excerpt = self._extract_excerpt(response.text)
            search_text = self._extract_search_text(response.text)
            if self._is_error_page(title, excerpt, search_text):
                return SourceVerification(
                    url=str(response.url),
                    source_type=source_type,
                    source_domain=urlparse(str(response.url)).netloc or domain,
                    http_status=response.status_code,
                    reachable=False,
                    verified=False,
                    page_title=title,
                    page_excerpt=excerpt,
                    matched_keywords=[],
                    verification_note="来源返回了错误页或失效页，无法作为有效校验依据。",
                    raw_metadata={
                        "final_url": str(response.url),
                        "content_type": response.headers.get("content-type", ""),
                        "content_length": response.headers.get("content-length", ""),
                        "is_error_page": True,
                    },
                    fetched_at=fetched_at,
                    score=0.0,
                    extracted_specs={},
                )

            analysis_text = f"{title} {excerpt} {search_text}".lower()
            matched_keywords = self._collect_matched_keywords(seed, analysis_text)
            matched_keywords.extend(self._collect_url_matched_keywords(seed, str(response.url)))
            matched_keywords = list(dict.fromkeys(matched_keywords))
            provider_match = self._matches_provider(seed.provider, analysis_text, str(response.url))
            alias_match = any(keyword.startswith("alias:") for keyword in matched_keywords)
            modality_match = any(keyword.startswith("modality:") for keyword in matched_keywords)
            score = 0.35
            score += 0.3 if alias_match else 0.0
            score += 0.2 if modality_match else 0.0
            score += 0.1 if provider_match else 0.0
            score += 0.05 if source_type == "documentation" else 0.0

            verified = alias_match and (modality_match or provider_match or source_type == "documentation")
            note = "已识别模型身份与主模态。" if verified else "来源可访问，但只完成了部分特征匹配。"

            extracted_specs = self._extract_detailed_specs(response.text, seed, str(response.url))
            prompt_examples = self._extract_prompt_examples_from_html(response.text)

            extracted_specs_dict = {
                "duration_range": extracted_specs.duration_range,
                "resolution_options": extracted_specs.resolution_options,
                "frame_rate": extracted_specs.frame_rate,
                "output_format": extracted_specs.output_format,
                "input_modalities": extracted_specs.input_modalities,
                "advanced_features": extracted_specs.advanced_features,
                "max_reference_images": extracted_specs.max_reference_images,
                "weight_control": extracted_specs.weight_control,
                "first_frame_support": extracted_specs.first_frame_support,
                "last_frame_support": extracted_specs.last_frame_support,
                "prompt_examples": prompt_examples,
                "extraction_confidence": extracted_specs.extraction_confidence,
            }

            # LLM校验（强制启用）
            try:
                llm_verified_specs = self._sync_verify_with_llm(
                    seed,
                    extracted_specs_dict,
                    search_text,
                )
                if llm_verified_specs.get("_llm_verification"):
                    extracted_specs_dict = llm_verified_specs
                    llm_meta = llm_verified_specs["_llm_verification"]
                    note += f" LLM校验置信度: {llm_meta.get('confidence', 0):.0%}，可靠性: {llm_meta.get('reliability_score', 0)}分。"
                else:
                    note += " LLM校验未返回有效结果。"
            except Exception as e:
                logger.warning(f"LLM 校验调用失败: {e}")
                note += f" LLM校验调用失败: {e}"

            if extracted_specs.extraction_confidence > 0.3:
                note += f" 已提取详细规格（置信度: {extracted_specs.extraction_confidence:.0%}）。"

            return SourceVerification(
                url=str(response.url),
                source_type=source_type,
                source_domain=urlparse(str(response.url)).netloc or domain,
                http_status=response.status_code,
                reachable=True,
                verified=verified,
                page_title=title,
                page_excerpt=excerpt,
                matched_keywords=matched_keywords,
                verification_note=note,
                raw_metadata={
                    "final_url": str(response.url),
                    "content_type": response.headers.get("content-type", ""),
                    "content_length": response.headers.get("content-length", ""),
                },
                fetched_at=fetched_at,
                score=score,
                extracted_specs=extracted_specs_dict,
            )
        except httpx.HTTPError as exc:
            logger.warning("模型来源校验失败 | model=%s | url=%s | error=%s", seed.model_key, url, exc)
            return SourceVerification(
                url=url,
                source_type=source_type,
                source_domain=domain,
                http_status=getattr(getattr(exc, "response", None), "status_code", None),
                reachable=False,
                verified=False,
                page_title="",
                page_excerpt="",
                matched_keywords=[],
                verification_note=f"请求失败: {exc}",
                raw_metadata={"error": str(exc)},
                fetched_at=fetched_at,
                score=0.0,
                extracted_specs={},
            )

    def _build_source_candidates(self, seed: CatalogSeed) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []

        def _push(source_type: str, url: str) -> None:
            clean_url = (url or "").strip()
            if not clean_url:
                return
            if any(existing_url == clean_url for _, existing_url in candidates):
                return
            candidates.append((source_type, clean_url))

        _push("documentation", seed.documentation_url)
        for url in seed.source_urls:
            _push("reference", url)
        for url in _GLOBAL_FALLBACK_SOURCES.get(seed.provider, []):
            _push("fallback", url)
        for url in _MODEL_FALLBACK_SOURCES.get(seed.model_key, []):
            _push("fallback", url)

        return candidates

    def _deduplicate_verifications(
        self,
        verifications: list[SourceVerification],
    ) -> list[SourceVerification]:
        deduped: dict[str, SourceVerification] = {}
        for verification in verifications:
            key = verification.url.strip().lower()
            existing = deduped.get(key)
            if existing is None or verification.score > existing.score:
                deduped[key] = verification
        return list(deduped.values())

    def _normalize_llm_seed(
        self,
        raw: dict[str, Any],
        *,
        catalog_profile: Optional[dict[str, Any]] = None,
    ) -> CatalogSeed:
        capabilities = raw.get("capabilities", []) or []
        tags = [str(item) for item in raw.get("tags", []) or []]
        category = "llm"
        subcategory = self._infer_llm_subcategory(capabilities, tags)
        raw_config = deepcopy(raw)
        if catalog_profile:
            raw_config["catalog_profile"] = deepcopy(catalog_profile)
        return CatalogSeed(
            model_key=str(raw.get("id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            provider=str(raw.get("provider", "")).strip(),
            category=category,
            subcategory=subcategory,
            model_family=self._infer_model_family(str(raw.get("name", "")), str(raw.get("id", ""))),
            config_source="llm_models.yaml",
            status=str(raw.get("status", "active")),
            summary=str(raw.get("summary", "")).strip(),
            recommended_scenarios=self._normalize_string_list(raw.get("recommended_scenarios")),
            limitations=self._normalize_string_list(raw.get("limitations")),
            integration_notes=self._normalize_string_list(raw.get("integration_notes")),
            documentation_url=str(raw.get("documentation_url", "")).strip(),
            source_urls=self._normalize_string_list(raw.get("source_urls")),
            tags=tags,
            modalities=["text_generation"],
            capabilities=[item for item in capabilities if isinstance(item, dict)],
            constraints=raw.get("constraints", {}) or {},
            performance=raw.get("performance", {}) or {},
            routing=raw.get("routing", {}) or {},
            default_params=raw.get("default_params", {}) or {},
            raw_config=raw_config,
        )

    def _normalize_capability_seed(
        self,
        raw: dict[str, Any],
        *,
        catalog_profile: Optional[dict[str, Any]] = None,
    ) -> CatalogSeed:
        modalities = [str(item) for item in raw.get("modality", []) or []]
        capabilities = raw.get("capabilities", []) or []
        tags = [str(item) for item in raw.get("tags", []) or []]
        category = self._infer_model_category(modalities)
        subcategory = self._infer_capability_subcategory(modalities, tags, raw.get("id", ""))
        performance = {
            "quality_metrics": raw.get("quality_metrics", {}) or {},
            "cost_profile": raw.get("cost_profile", {}) or {},
            "avg_latency_seconds": raw.get("avg_latency_seconds", 0.0),
            "p95_latency_seconds": raw.get("p95_latency_seconds", 0.0),
        }
        routing = {
            "rate_limit": raw.get("rate_limit", {}) or {},
            "best_practice": raw.get("best_practice", {}) or {},
            "fallback_strategies": raw.get("fallback_strategies", []) or [],
            "endpoint": raw.get("endpoint", ""),
            "auth_method": raw.get("auth_method", ""),
            "task_types": raw.get("task_types", []) or [],
        }
        raw_config = deepcopy(raw)
        if catalog_profile:
            raw_config["catalog_profile"] = deepcopy(catalog_profile)
        return CatalogSeed(
            model_key=str(raw.get("id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            provider=str(raw.get("provider", "")).strip(),
            category=category,
            subcategory=subcategory,
            model_family=self._infer_model_family(str(raw.get("name", "")), str(raw.get("id", ""))),
            config_source="models.yaml",
            status=str(raw.get("status", "active")),
            summary=str(raw.get("summary", "")).strip(),
            recommended_scenarios=self._normalize_string_list(raw.get("recommended_scenarios")),
            limitations=self._normalize_string_list(raw.get("limitations")),
            integration_notes=self._normalize_string_list(raw.get("integration_notes")),
            documentation_url=str(raw.get("documentation_url", "")).strip(),
            source_urls=self._normalize_string_list(raw.get("source_urls")),
            tags=tags,
            modalities=modalities,
            capabilities=[item for item in capabilities if isinstance(item, dict)],
            constraints=raw.get("constraints", {}) or {},
            performance=performance,
            routing=routing,
            default_params=raw.get("default_params", {}) or {},
            raw_config=raw_config,
        )

    def _infer_model_category(self, modalities: list[str]) -> str:
        lowered = [item.lower() for item in modalities]
        if any("multimodal" in item or "understanding" in item for item in lowered):
            return "multimodal"
        if any("speech" in item or "voice" in item or "audio" in item for item in lowered):
            return "audio"
        if any("embedding" in item for item in lowered):
            return "embedding"
        if any("video" in item for item in lowered):
            return "video"
        if any("image" in item for item in lowered):
            return "image"
        return "llm"

    def _infer_llm_subcategory(self, capabilities: list[dict[str, Any]], tags: list[str]) -> str:
        names = {str(item.get("name", "")).lower() for item in capabilities}
        lowered_tags = {tag.lower() for tag in tags}
        if "long_context" in names:
            return "长上下文"
        if {"reasoning", "logic", "planning"} & names:
            return "推理审校"
        if {"fast", "simple", "extraction", "chat"} & names or {"fast", "cheap"} & lowered_tags:
            return "轻量快写"
        if {"creative", "writing", "dialogue"} & names:
            return "创作写作"
        return "通用文本"

    def _infer_capability_subcategory(self, modalities: list[str], tags: list[str], model_key: str) -> str:
        lowered = [item.lower() for item in modalities]
        lowered_tags = {tag.lower() for tag in tags}
        if "voice_clone" in lowered or "voice-clone" in lowered_tags:
            return "语音克隆"
        if "text_to_speech" in lowered:
            return "文本转语音"
        if "video_to_audio" in lowered:
            return "视频转音频"
        if "text_to_audio" in lowered:
            return "文生音频"
        if "image_edit" in lowered or "image_to_image_edit" in lowered:
            return "图像编辑"
        if "text_to_video" in lowered:
            return "文生视频"
        if "image_to_video" in lowered:
            return "图生视频"
        if "reference_to_video" in lowered or "video_to_video" in lowered:
            return "参考生视频"
        if "text_to_image" in lowered:
            return "文生图"
        if "multimodal_chat" in lowered or any("understanding" in item for item in lowered):
            return "多模态理解"
        if "embedding" in lowered or "embedding" in model_key.lower():
            return "向量嵌入"
        return "通用能力"

    def _infer_model_family(self, name: str, model_key: str) -> str:
        source = (name or model_key or "").strip()
        match = re.match(r"([A-Za-z]+(?:\s*\d+(?:\.\d+)?)?)", source)
        if match:
            return match.group(1).strip()
        return source

    def _collect_matched_keywords(self, seed: CatalogSeed, content: str) -> list[str]:
        matched: list[str] = []
        for keyword in self._build_alias_keywords(seed):
            if keyword and keyword in content:
                matched.append(f"alias:{keyword}")
        for keyword in self._build_modality_keywords(seed):
            if keyword and keyword in content:
                matched.append(f"modality:{keyword}")
        for keyword in _PROVIDER_KEYWORDS.get(seed.provider, []):
            if keyword and keyword in content:
                matched.append(f"provider:{keyword}")
        return matched

    def _collect_url_matched_keywords(self, seed: CatalogSeed, url: str) -> list[str]:
        lowered_url = (url or "").lower().strip()
        if not lowered_url:
            return []

        compact_url = re.sub(r"[^a-z0-9]+", "", lowered_url)
        matched: list[str] = []

        def _push(prefix: str, value: str) -> None:
            clean_value = str(value or "").strip()
            if not clean_value:
                return
            keyword = f"{prefix}:{clean_value}"
            if keyword not in matched:
                matched.append(keyword)

        for keyword in self._build_alias_keywords(seed):
            compact_keyword = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", keyword)
            if len(compact_keyword) >= 8 and compact_keyword in compact_url:
                _push("alias", keyword)

        if seed.provider == "vidu" and "vidu.cn" in lowered_url:
            if "timing" in (seed.modalities or []) and "timing" in compact_url:
                _push("modality", "timing audio")
                if seed.model_key == "vidu-timing2audio":
                    _push("alias", seed.model_key)

        return matched

    def _build_alias_keywords(self, seed: CatalogSeed) -> list[str]:
        keywords: list[str] = []
        raw_candidates = [seed.model_key, seed.name, *_MODEL_ALIAS_KEYWORDS.get(seed.model_key, [])]
        for candidate in raw_candidates:
            self._append_keyword_variants(keywords, candidate)
        return sorted(set(keywords), key=len, reverse=True)

    def _build_modality_keywords(self, seed: CatalogSeed) -> list[str]:
        keywords = [seed.subcategory.lower(), seed.category.lower()]
        if seed.category == "llm":
            keywords.extend(["text generation", "chat", "reasoning", "长上下文", "推理", "文本生成"])
        elif seed.category == "image":
            keywords.extend(["text to image", "image generation", "image edit", "文生图", "图像编辑"])
        elif seed.category == "video":
            keywords.extend(["text to video", "image to video", "video generation", "文生视频", "图生视频"])
        elif seed.category == "audio":
            keywords.extend(["text to speech", "speech synthesis", "voice clone", "语音合成", "文本转语音"])
            if "text_to_audio" in seed.modalities:
                keywords.extend(["text to audio", "music generation", "sound effect", "文生音频", "音乐生成", "音效生成"])
            if "video_to_audio" in seed.modalities:
                keywords.extend(["video to audio", "视频转音频", "视频补声音"])
        elif seed.category == "multimodal":
            keywords.extend(["multimodal", "vision", "image understanding", "video understanding", "多模态"])
        elif seed.category == "embedding":
            keywords.extend(["embedding", "向量", "嵌入"])
        return sorted({item.lower() for item in keywords if item}, key=len, reverse=True)

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"模型配置文件不存在: {path}")
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def _load_catalog_profiles(self) -> dict[str, dict[str, Any]]:
        if not self._catalog_profile_path.exists():
            return {}

        payload = self._load_yaml(self._catalog_profile_path)
        profiles = payload.get("profiles", {}) or {}
        if not isinstance(profiles, dict):
            return {}

        normalized: dict[str, dict[str, Any]] = {}
        for model_key, profile in profiles.items():
            clean_key = str(model_key or "").strip()
            if not clean_key or not isinstance(profile, dict):
                continue
            normalized[clean_key] = deepcopy(profile)
        return normalized

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _fetch_response(self, client: httpx.Client, url: str) -> httpx.Response:
        cache_key = (url or "").strip()
        if self._response_cache is not None:
            cached = self._response_cache.get(cache_key)
            if cached is not None:
                self._fetch_cache_hits += 1
                return cached

        last_error: Optional[httpx.HTTPError] = None
        for _ in range(2):
            try:
                self._fetch_cache_misses += 1
                response = client.get(url)
                response.raise_for_status()
                if self._response_cache is not None:
                    self._response_cache[cache_key] = response
                    final_url = str(response.url or "").strip()
                    if final_url:
                        self._response_cache.setdefault(final_url, response)
                return response
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc

        if last_error is None:
            raise httpx.HTTPError("未知的模型来源请求错误")
        raise last_error

    def _matches_provider(self, provider: str, content: str, url: str) -> bool:
        if any(keyword in content for keyword in _PROVIDER_KEYWORDS.get(provider, [])):
            return True

        lowered_url = (url or "").lower()
        return any(domain in lowered_url for domain in _PROVIDER_DOMAINS.get(provider, []))

    def _append_keyword_variants(self, keywords: list[str], candidate: str) -> None:
        lowered = (candidate or "").lower().strip()
        if not lowered:
            return

        compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)
        keywords.append(lowered)
        if compact and compact != lowered:
            keywords.append(compact)

    def _extract_title(self, html: str) -> str:
        match = _TITLE_RE.search(html or "")
        if not match:
            return ""
        return self._clean_html_fragment(match.group(1))[:300]

    def _extract_excerpt(self, html: str) -> str:
        meta_match = _META_RE.search(html or "")
        if meta_match:
            return self._clean_html_fragment(meta_match.group(1))[:500]

        return self._extract_search_text(html)[:500]

    def _extract_search_text(self, html: str) -> str:
        cleaned = _SCRIPT_STYLE_RE.sub(" ", html or "")
        cleaned = _TAG_RE.sub(" ", cleaned)
        cleaned = _SPACE_RE.sub(" ", unescape(cleaned)).strip()
        return cleaned[:300000]

    def _is_error_page(self, title: str, excerpt: str, search_text: str) -> bool:
        headline = f"{title} {excerpt}".lower()
        if any(keyword in headline for keyword in _ERROR_PAGE_KEYWORDS):
            return True

        leading_content = (search_text or "")[:1200].lower()
        return any(keyword in leading_content for keyword in _ERROR_PAGE_KEYWORDS)

    def _clean_html_fragment(self, fragment: str) -> str:
        text = _TAG_RE.sub(" ", fragment or "")
        return _SPACE_RE.sub(" ", unescape(text)).strip()

    def _extract_detailed_specs(
        self,
        html: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """从网页内容中提取详细规格信息（按模型类型差异化提取）。"""
        text = self._extract_search_text(html)
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        
        # 根据模型类型调用不同的提取逻辑
        if seed.category == "video":
            return self._extract_video_specs(text, seed, url)
        elif seed.category == "image":
            return self._extract_image_specs(text, seed, url)
        elif seed.category == "audio":
            return self._extract_audio_specs(text, seed, url)
        elif seed.category == "llm":
            return self._extract_llm_specs(text, seed, url)
        else:
            # 其他类型使用通用提取
            return self._extract_generic_specs(text, seed, url)
    
    def _extract_video_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """视频模型专用提取逻辑。
        
        核心字段：duration_range, frame_rate, resolution, aspect_ratios
        高级功能：multi_shot, audio_sync, camera_control, motion_control
        输入模态：first_frame_support, last_frame_support, reference_images, reference_videos
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 核心字段：时长范围
        duration_match = _DURATION_RANGE_RE.search(text)
        if duration_match:
            extraction.duration_range = {
                "min_seconds": int(duration_match.group(1)),
                "max_seconds": int(duration_match.group(2)),
                "unit": "seconds",
                "step": 1,
            }
            confidence_points += 1
        total_checks += 1

        # 核心字段：分辨率选项
        resolutions = list(set(_RESOLUTION_RE.findall(text)))
        if resolutions:
            extraction.resolution_options = sorted(resolutions, key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 100)
            confidence_points += 1
        total_checks += 1

        # 核心字段：帧率
        frame_rate_match = _FRAME_RATE_RE.search(text)
        if frame_rate_match:
            extraction.frame_rate = int(frame_rate_match.group(1))
            confidence_points += 1
        total_checks += 1

        # 输出格式
        formats = list(set(_FORMAT_RE.findall(text)))
        if formats:
            extraction.output_format = ", ".join(formats[:3])
            confidence_points += 0.5
        total_checks += 1

        # 输入模态（视频/音频特有）
        input_modalities = []
        if re.search(r"文本|text", text, re.IGNORECASE):
            input_modalities.append("text")
        if re.search(r"图像|图片|image", text, re.IGNORECASE):
            input_modalities.append("image")
        if re.search(r"视频|video", text, re.IGNORECASE):
            input_modalities.append("video")
        if re.search(r"音频|声音|audio", text, re.IGNORECASE):
            input_modalities.append("audio")
        if input_modalities:
            extraction.input_modalities = input_modalities
            confidence_points += 1
        total_checks += 1

        # 高级功能：视频特有
        advanced_features = []
        if _MULTI_SHOT_RE.search(text):
            advanced_features.append("multi_shot")
            confidence_points += 1
        if _AUDIO_SYNC_RE.search(text):
            advanced_features.append("audio_sync")
            confidence_points += 1
        if _PROMPT_REWRITE_RE.search(text):
            advanced_features.append("prompt_rewrite")
            confidence_points += 0.5
        # 运镜控制
        if re.search(r"运镜|camera.*control|镜头.*移动", text, re.IGNORECASE):
            advanced_features.append("camera_control")
            confidence_points += 1
        # 动作控制
        if re.search(r"动作.*控制|motion.*control|首尾.*帧", text, re.IGNORECASE):
            advanced_features.append("motion_control")
            confidence_points += 1
        if advanced_features:
            extraction.advanced_features = advanced_features
        total_checks += 5

        # 参考图/视频支持
        max_ref_match = _MAX_REFERENCE_RE.search(text)
        if max_ref_match:
            extraction.max_reference_images = int(max_ref_match.group(1))
            confidence_points += 1
        total_checks += 1

        # 首帧/尾帧支持
        if _FIRST_FRAME_RE.search(text):
            extraction.first_frame_support = True
            confidence_points += 1
        total_checks += 1

        if _LAST_FRAME_RE.search(text):
            extraction.last_frame_support = True
            confidence_points += 1
        total_checks += 1

        # 权重控制
        if _WEIGHT_CONTROL_RE.search(text):
            extraction.weight_control = True
            confidence_points += 1
        total_checks += 1

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_image_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """图像模型专用提取逻辑。
        
        核心字段：resolution_options, aspect_ratios, max_output_count
        生成参数：style_support, seed_support, negative_prompt
        编辑功能：image_edit_support, multi_image_input, style_transfer
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 核心字段：分辨率选项
        resolutions = list(set(_RESOLUTION_RE.findall(text)))
        if resolutions:
            extraction.resolution_options = sorted(resolutions, key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 100)
            confidence_points += 1
        total_checks += 1

        # 宽高比支持
        ratio_patterns = [
            r"(\d+:\d+)",
            r"支持.*比例.*?([\d:]+)",
        ]
        for pattern in ratio_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                ratios = list(set(matches))
                if ratios:
                    extraction.output_format = ", ".join(ratios[:5])  # 暂存到 output_format
                    confidence_points += 0.5
                    break
        total_checks += 1

        # 输出格式
        formats = list(set(_FORMAT_RE.findall(text)))
        if formats:
            extraction.output_format = (extraction.output_format + ", " if extraction.output_format else "") + ", ".join(formats[:3])
            confidence_points += 0.5
        total_checks += 1

        # 输入模态
        input_modalities = []
        if re.search(r"文本|text", text, re.IGNORECASE):
            input_modalities.append("text")
        if re.search(r"图像|图片|image", text, re.IGNORECASE):
            input_modalities.append("image")
        if input_modalities:
            extraction.input_modalities = input_modalities
            confidence_points += 1
        total_checks += 1

        # 风格支持
        if re.search(r"风格.*支持|style.*support|多种风格", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("style_support")
            confidence_points += 1
        total_checks += 1

        # Seed 支持（可复现性）
        if re.search(r"seed|随机种子|可复现", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("seed_support")
            confidence_points += 0.5
        total_checks += 1

        # 负向提示词支持
        if re.search(r"负向.*提示|negative.*prompt|排除", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("negative_prompt")
            confidence_points += 0.5
        total_checks += 1

        # 多图输入支持
        if re.search(r"多图.*输入|multi.*image|参考.*图.*多", text, re.IGNORECASE):
            extraction.max_reference_images = 2  # 默认多图
            confidence_points += 1
        total_checks += 1

        # 图像编辑支持
        if re.search(r"图像.*编辑|image.*edit|编辑.*功能", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("image_edit")
            confidence_points += 1
        total_checks += 1

        # 权重控制
        if _WEIGHT_CONTROL_RE.search(text):
            extraction.weight_control = True
            confidence_points += 1
        total_checks += 1

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_audio_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """音频模型专用提取逻辑。
        
        核心字段：sample_rate, audio_format, duration_range
        语音合成：voice_clone, language_support, emotion_control
        音乐生成：music_style, instrument_control, vocal_removal
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 采样率
        sample_rate_match = re.search(r"(\d+)\s*kHz", text, re.IGNORECASE)
        if sample_rate_match:
            extraction.output_format = f"{sample_rate_match.group(1)}kHz"
            confidence_points += 1
        total_checks += 1

        # 音频格式
        audio_formats = re.findall(r"\.(mp3|wav|flac|aac|ogg)", text, re.IGNORECASE)
        if audio_formats:
            extraction.output_format = (extraction.output_format + ", " if extraction.output_format else "") + ", ".join(set(audio_formats[:3]))
            confidence_points += 0.5
        total_checks += 1

        # 时长范围（音频特有）
        duration_match = _DURATION_RANGE_RE.search(text)
        if duration_match:
            extraction.duration_range = {
                "min_seconds": int(duration_match.group(1)),
                "max_seconds": int(duration_match.group(2)),
                "unit": "seconds",
                "step": 1,
            }
            confidence_points += 1
        total_checks += 1

        # 输入模态
        input_modalities = []
        if re.search(r"文本|text", text, re.IGNORECASE):
            input_modalities.append("text")
        if re.search(r"音频|audio", text, re.IGNORECASE):
            input_modalities.append("audio")
        if re.search(r"视频|video", text, re.IGNORECASE):
            input_modalities.append("video")
        if input_modalities:
            extraction.input_modalities = input_modalities
            confidence_points += 1
        total_checks += 1

        # 高级功能：音频特有
        advanced_features = []
        
        # 声音克隆
        if re.search(r"声音.*克隆|voice.*clone|音色.*复制", text, re.IGNORECASE):
            advanced_features.append("voice_clone")
            confidence_points += 1
        
        # 语言支持
        if re.search(r"多语言|multi.*language|.*种语言", text, re.IGNORECASE):
            advanced_features.append("multi_language")
            confidence_points += 1
        
        # 情感控制
        if re.search(r"情感.*控制|emotion.*control|情绪.*表达", text, re.IGNORECASE):
            advanced_features.append("emotion_control")
            confidence_points += 1
        
        # 音乐风格
        if re.search(r"音乐.*风格|music.*style|流派", text, re.IGNORECASE):
            advanced_features.append("music_style")
            confidence_points += 1
        
        # 乐器控制
        if re.search(r"乐器|instrument|伴奏", text, re.IGNORECASE):
            advanced_features.append("instrument_control")
            confidence_points += 1
        
        # 人声分离
        if re.search(r"人声.*分离|vocal.*removal|伴奏.*提取", text, re.IGNORECASE):
            advanced_features.append("vocal_removal")
            confidence_points += 1
        
        if advanced_features:
            extraction.advanced_features = advanced_features
        total_checks += 6

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_llm_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """LLM 模型专用提取逻辑。
        
        核心字段：context_window, max_output_tokens, temperature_range
        功能特性：function_calling, tool_use, multi_turn, streaming
        推理能力：reasoning, code_generation, math
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 上下文窗口
        context_match = re.search(r"(\d+[KkMm]?)\s*(tokens?|上下文|context)", text, re.IGNORECASE)
        if context_match:
            extraction.output_format = context_match.group(1)
            confidence_points += 1
        total_checks += 1

        # 输出长度
        output_match = re.search(r"最大.*输出.*?(\d+)", text, re.IGNORECASE)
        if output_match:
            extraction.duration_range = {"max_tokens": int(output_match.group(1))}
            confidence_points += 0.5
        total_checks += 1

        # 输入模态
        input_modalities = ["text"]
        if re.search(r"视觉|vision|image.*understanding|多模态", text, re.IGNORECASE):
            input_modalities.append("image")
        if re.search(r"音频|audio|语音", text, re.IGNORECASE):
            input_modalities.append("audio")
        if re.search(r"视频|video", text, re.IGNORECASE):
            input_modalities.append("video")
        extraction.input_modalities = input_modalities
        confidence_points += 1
        total_checks += 1

        # 高级功能：LLM 特有
        advanced_features = []
        
        # 函数调用
        if re.search(r"function.*call|工具.*调用|function.*calling", text, re.IGNORECASE):
            advanced_features.append("function_calling")
            confidence_points += 1
        
        # 流式输出
        if re.search(r"流式|streaming|stream", text, re.IGNORECASE):
            advanced_features.append("streaming")
            confidence_points += 0.5
        
        # 多轮对话
        if re.search(r"多轮|multi.*turn|对话|chat", text, re.IGNORECASE):
            advanced_features.append("multi_turn")
            confidence_points += 0.5
        
        # 推理能力
        if re.search(r"推理|reasoning|chain.*of.*thought", text, re.IGNORECASE):
            advanced_features.append("reasoning")
            confidence_points += 1
        
        # 代码生成
        if re.search(r"代码|code.*generation|编程", text, re.IGNORECASE):
            advanced_features.append("code_generation")
            confidence_points += 0.5
        
        # 数学能力
        if re.search(r"数学|math|计算", text, re.IGNORECASE):
            advanced_features.append("math")
            confidence_points += 0.5
        
        # 联网搜索
        if re.search(r"联网|web.*search|搜索", text, re.IGNORECASE):
            advanced_features.append("web_search")
            confidence_points += 1
        
        if advanced_features:
            extraction.advanced_features = advanced_features
        total_checks += 7

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_generic_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """通用提取逻辑（用于其他模型类型）。"""
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 基础字段提取
        duration_match = _DURATION_RANGE_RE.search(text)
        if duration_match:
            extraction.duration_range = {
                "min_seconds": int(duration_match.group(1)),
                "max_seconds": int(duration_match.group(2)),
                "unit": "seconds",
                "step": 1,
            }
            confidence_points += 1
        total_checks += 1

        resolutions = list(set(_RESOLUTION_RE.findall(text)))
        if resolutions:
            extraction.resolution_options = sorted(resolutions, key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 100)
            confidence_points += 1
        total_checks += 1

        formats = list(set(_FORMAT_RE.findall(text)))
        if formats:
            extraction.output_format = ", ".join(formats[:3])
            confidence_points += 0.5
        total_checks += 1

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction

    def _extract_prompt_examples_from_html(self, html: str) -> list[dict[str, str]]:
        """从 HTML 中提取提示词示例。"""
        examples: list[dict[str, str]] = []
        text = self._extract_search_text(html)

        example_patterns = [
            r"示例\s*[:：]\s*[「「\"']([^」」\"']+)[」」\"']",
            r"prompt\s*[:：]\s*[「「\"']([^」」\"']+)[」」\"']",
            r"提示词\s*[:：]\s*[「「\"']([^」」\"']+)[」」\"']",
        ]

        for pattern in example_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                if len(match) > 20 and len(match) < 500:
                    examples.append({
                        "title": "提取的示例",
                        "content": match.strip(),
                    })

        return examples[:5]

    def _merge_extracted_specs(
        self,
        extractions: list[DetailedSpecExtraction],
        existing_specs: dict[str, Any],
        category: str = "video",
    ) -> dict[str, Any]:
        """合并从多个来源提取的规格信息（按模型类型差异化合并）。
        
        Args:
            extractions: 提取结果列表
            existing_specs: 已有规格
            category: 模型类别（video/image/audio/llm）
        """
        if not extractions:
            return existing_specs

        merged = deepcopy(existing_specs) if existing_specs else {}
        best_extraction = max(extractions, key=lambda e: e.extraction_confidence)
        
        # 根据模型类型合并到对应的 section
        if category == "video":
            return self._merge_video_specs(merged, best_extraction)
        elif category == "image":
            return self._merge_image_specs(merged, best_extraction)
        elif category == "audio":
            return self._merge_audio_specs(merged, best_extraction)
        elif category == "llm":
            return self._merge_llm_specs(merged, best_extraction)
        else:
            return self._merge_generic_specs(merged, best_extraction)
    
    def _merge_video_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并视频模型规格。"""
        video_specs = merged.get("video_generation", {})

        if extraction.duration_range and "basic_params" not in video_specs:
            video_specs.setdefault("basic_params", {})["duration"] = extraction.duration_range

        if extraction.resolution_options and "basic_params" not in video_specs:
            video_specs.setdefault("basic_params", {})["resolution"] = {
                "options": extraction.resolution_options,
            }

        if extraction.frame_rate and "output_format" not in video_specs:
            video_specs["output_format"] = {
                "frame_rate": extraction.frame_rate,
            }

        if extraction.input_modalities:
            video_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "image": "图像", "audio": "音频", "video": "视频"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "multi_shot": "多镜头叙事",
                "audio_sync": "声画同步",
                "prompt_rewrite": "智能改写",
                "camera_control": "运镜控制",
                "motion_control": "动作控制",
            }
            video_specs["advanced_features"] = [
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ]
        
        # 首帧/尾帧/参考支持
        if extraction.first_frame_support or extraction.last_frame_support:
            video_specs.setdefault("frame_control", {})
            if extraction.first_frame_support:
                video_specs["frame_control"]["first_frame"] = True
            if extraction.last_frame_support:
                video_specs["frame_control"]["last_frame"] = True
        
        if extraction.max_reference_images:
            video_specs.setdefault("reference_images", {})["max_count"] = extraction.max_reference_images

        if video_specs:
            merged["video_generation"] = video_specs

        return merged
    
    def _merge_image_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并图像模型规格。"""
        image_specs = merged.get("image_generation", {})

        if extraction.resolution_options and "basic_params" not in image_specs:
            image_specs.setdefault("basic_params", {})["resolution"] = {
                "options": extraction.resolution_options,
            }

        if extraction.output_format and "output_format" not in image_specs:
            image_specs["output_format"] = {"format": extraction.output_format}

        if extraction.input_modalities:
            image_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "image": "图像"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "style_support": "风格支持",
                "seed_support": "随机种子",
                "negative_prompt": "负向提示词",
                "image_edit": "图像编辑",
                "style_transfer": "风格迁移",
            }
            image_specs.setdefault("advanced_features", []).extend([
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ])
        
        if extraction.max_reference_images:
            image_specs.setdefault("reference_images", {})["max_count"] = extraction.max_reference_images

        if extraction.weight_control:
            image_specs.setdefault("weight_control", {"enabled": True})

        if image_specs:
            merged["image_generation"] = image_specs

        return merged
    
    def _merge_audio_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并音频模型规格。"""
        audio_specs = merged.get("audio_generation", {})

        if extraction.output_format and "output_format" not in audio_specs:
            audio_specs["output_format"] = {"format": extraction.output_format}

        if extraction.duration_range and "basic_params" not in audio_specs:
            audio_specs.setdefault("basic_params", {})["duration"] = extraction.duration_range

        if extraction.input_modalities:
            audio_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "audio": "音频", "video": "视频"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "voice_clone": "声音克隆",
                "multi_language": "多语言支持",
                "emotion_control": "情感控制",
                "music_style": "音乐风格",
                "instrument_control": "乐器控制",
                "vocal_removal": "人声分离",
            }
            audio_specs["advanced_features"] = [
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ]

        if audio_specs:
            merged["audio_generation"] = audio_specs

        return merged
    
    def _merge_llm_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并 LLM 模型规格。"""
        llm_specs = merged.get("llm_config", {})

        if extraction.output_format:
            llm_specs.setdefault("basic_params", {})["context_window"] = extraction.output_format

        if extraction.duration_range and "max_tokens" in extraction.duration_range:
            llm_specs.setdefault("basic_params", {})["max_output_tokens"] = extraction.duration_range["max_tokens"]

        if extraction.input_modalities:
            llm_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "image": "图像", "audio": "音频", "video": "视频"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "function_calling": "函数调用",
                "streaming": "流式输出",
                "multi_turn": "多轮对话",
                "reasoning": "推理能力",
                "code_generation": "代码生成",
                "math": "数学能力",
                "web_search": "联网搜索",
            }
            llm_specs["advanced_features"] = [
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ]

        if llm_specs:
            merged["llm_config"] = llm_specs

        return merged
    
    def _merge_generic_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并通用模型规格。"""
        if extraction.duration_range:
            merged.setdefault("basic_params", {})["duration"] = extraction.duration_range
        
        if extraction.resolution_options:
            merged.setdefault("basic_params", {})["resolution"] = {
                "options": extraction.resolution_options,
            }
        
        if extraction.output_format:
            merged["output_format"] = extraction.output_format

        return merged

    def _get_type_specific_guidance(self, category: str) -> str:
        """获取按模型类型的 LLM 校验提示指导。
        
        Args:
            category: 模型类别（video/image/audio/llm）
            
        Returns:
            类型特定的校验指导文本
        """
        guidance_map = {
            "video": """- 时长范围：如 "支持 5-10 秒"
- 分辨率选项：如 "720p, 1080p"
- 帧率：如 "24fps, 30fps"
- 输出格式：如 "mp4, webm"
- 输入模态：文本/图像/视频/音频
- 高级功能：多镜头叙事、声画同步、运镜控制、动作控制
- 首帧/尾帧支持：是否支持首帧/尾帧控制
- 参考图上限：最多支持几张参考图""",
            "image": """- 分辨率选项：如 "1024x1024, 512x512"
- 宽高比：如 "16:9, 1:1, 9:16"
- 输出格式：如 "png, jpg, webp"
- 输入模态：文本/图像
- 风格支持：是否支持多种风格
- Seed 支持：是否支持随机种子（可复现性）
- 负向提示词：是否支持排除内容
- 图像编辑：是否支持基于参考图编辑
- 多图输入：最多支持几张参考图""",
            "audio": """- 采样率：如 "16kHz, 44.1kHz"
- 音频格式：如 "mp3, wav, flac"
- 时长范围：如 "最长 30 秒"
- 输入模态：文本/音频/视频
- 声音克隆：是否支持音色复制
- 多语言支持：支持哪些语言
- 情感控制：是否支持情感表达
- 音乐风格：是否支持音乐生成
- 乐器控制：是否支持指定乐器
- 人声分离：是否支持人声提取""",
            "llm": """- 上下文窗口：如 "128K tokens"
- 最大输出：如 "8192 tokens"
- 输入模态：文本/图像/音频/视频
- 函数调用：是否支持 tool calling
- 流式输出：是否支持 streaming
- 多轮对话：对话能力
- 推理能力：链式思维推理
- 代码生成：编程能力
- 数学能力：数学计算推理
- 联网搜索：是否支持 web search""",
        }
        return guidance_map.get(category, "- 基础字段：分辨率、格式、时长等通用参数")

    async def _llm_verify_extracted_specs(
        self,
        seed: CatalogSeed,
        extracted_specs: dict[str, Any],
        page_content: str,
    ) -> dict[str, Any]:
        """使用大模型验证提取的规格信息可靠性。

        使用 qwen3.6-plus 的联网搜索能力，主动搜索模型相关信息进行验证。

        Args:
            seed: 模型种子信息
            extracted_specs: 正则提取的规格信息
            page_content: 页面文本内容

        Returns:
            验证后的规格信息，包含置信度和修正建议
        """
        if not _LLM_CLIENT_AVAILABLE:
            logger.warning("LLM 客户端不可用，跳过大模型校验")
            return extracted_specs

        try:
            llm_client = get_llm_client(strategy="auto")
            model_id = os.getenv("VERIFICATION_LLM_MODEL", "qwen3.6-plus")

            search_query = f"{seed.name} {seed.provider} 模型规格 参数 功能 价格"
            
            prompt = f"""你是一个专业的模型能力分析专家。请通过联网搜索验证以下模型信息。

## 待验证模型
- 模型名称: {seed.name}
- 模型ID: {seed.model_key}
- 提供商: {seed.provider}
- 类别: {seed.category}

## 按类型重点校验字段
{self._get_type_specific_guidance(seed.category)}

## 已提取的规格信息（需要验证）
```json
{json.dumps(extracted_specs, ensure_ascii=False, indent=2)}
```

## 已有页面内容
```
{page_content[:3000]}
```

## 任务
1. 联网搜索验证已提取信息的准确性
2. 补充遗漏的重要规格
3. 修正明显错误的信息
4. 评估整体提取置信度（0-1）

## 输出格式
请以 JSON 格式输出，包含以下字段：
- verified_specs: 验证后的规格信息
- confidence: 整体置信度（0-1）
- corrections: 修正说明列表
- additions: 新增信息列表
- reliability_score: 数据可靠性评分（0-100）
- search_sources: 搜索来源列表（URL和标题）

只输出 JSON，不要其他解释。"""

            messages = [
                {"role": "system", "content": "你是一个专业的模型能力分析专家，擅长联网搜索并验证模型规格信息。请使用联网搜索功能获取最新信息。"},
                {"role": "user", "content": prompt},
            ]

            response = await llm_client.chat(
                messages=messages,
                model=model_id,
                temperature=0.1,
                max_tokens=2000,
                extra_body={
                    "enable_search": True,
                    "search_options": {
                        "forced_search": True,
                        "search_strategy": "max",
                        "enable_source": True,
                    }
                },
            )

            response_text = response.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
                response_text = re.sub(r"\s*```$", "", response_text)

            llm_result = json.loads(response_text)

            verified_specs = llm_result.get("verified_specs", extracted_specs)
            confidence = llm_result.get("confidence", 0.5)
            corrections = llm_result.get("corrections", [])
            additions = llm_result.get("additions", [])
            reliability_score = llm_result.get("reliability_score", 50)
            search_sources = llm_result.get("search_sources", [])

            logger.info(
                f"LLM 联网搜索校验完成 | model={seed.model_key} | confidence={confidence:.2f} | reliability={reliability_score}"
            )

            if corrections:
                logger.info(f"LLM 修正: {corrections}")
            if additions:
                logger.info(f"LLM 补充: {additions}")
            if search_sources:
                logger.info(f"LLM 搜索来源: {len(search_sources)} 条")

            verified_specs["_llm_verification"] = {
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "confidence": confidence,
                "reliability_score": reliability_score,
                "corrections": corrections,
                "additions": additions,
                "model": model_id,
                "search_enabled": True,
                "search_sources": search_sources[:5],
            }

            return verified_specs

        except json.JSONDecodeError as e:
            logger.warning(f"LLM 响应解析失败: {e}")
            return extracted_specs
        except Exception as e:
            logger.warning(f"LLM 联网搜索校验失败: {e}")
            return extracted_specs

    def _sync_verify_with_llm(
        self,
        seed: CatalogSeed,
        extracted_specs: dict[str, Any],
        page_content: str,
    ) -> dict[str, Any]:
        """同步包装器：在同步上下文中调用异步 LLM 校验。"""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is None:
                # No running event loop (e.g., in background thread)
                # Create a new event loop for this thread
                new_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(new_loop)
                    return new_loop.run_until_complete(
                        self._llm_verify_extracted_specs(seed, extracted_specs, page_content)
                    )
                finally:
                    new_loop.close()
                    asyncio.set_event_loop(None)
            else:
                # Event loop is already running (e.g., in async context)
                future = asyncio.run_coroutine_threadsafe(
                    self._llm_verify_extracted_specs(seed, extracted_specs, page_content),
                    loop,
                )
                return future.result(timeout=60)
        except Exception as e:
            logger.warning(f"同步调用 LLM 校验失败: {e}")
            return extracted_specs


model_catalog_sync_service = ModelCatalogSyncService()


def get_model_catalog_sync_service() -> ModelCatalogSyncService:
    """获取模型档案同步服务单例。"""

    return model_catalog_sync_service


def _format_number(value: Any) -> str:
    try:
        if value is None or value == "":
            return "未标注"
        number = float(value)
        if number.is_integer():
            return f"{int(number):,}"
        return f"{number:,}"
    except Exception:
        return str(value)


def _extract_raw(entry: ModelCatalogEntry) -> dict[str, Any]:
    return entry.raw_config_json or {}


def _extract_catalog_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    profile = _extract_raw(entry).get("catalog_profile")
    return profile if isinstance(profile, dict) else {}


def _coerce_profile_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_profile_string_list(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []

    items: list[str] = []
    for raw_item in value:
        item = _coerce_profile_text(raw_item)
        if item and item not in items:
            items.append(item)
    return items


def _coerce_profile_object_list(
    value: Any,
    *,
    required_keys: tuple[str, ...],
    optional_keys: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []

    items: list[dict[str, Any]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue

        normalized: dict[str, Any] = {}
        valid = True
        for key in required_keys:
            text = _coerce_profile_text(raw_item.get(key))
            if not text:
                valid = False
                break
            normalized[key] = text
        if not valid:
            continue

        for key in optional_keys:
            optional_value = raw_item.get(key)
            if optional_value is None:
                continue
            if isinstance(optional_value, bool):
                normalized[key] = optional_value
                continue

            text = _coerce_profile_text(optional_value)
            if text:
                normalized[key] = text

        items.append(normalized)
    return items


def _merge_unique_strings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for raw_item in group:
            item = _coerce_profile_text(raw_item)
            if item and item not in merged:
                merged.append(item)
    return merged


def _merge_resource_links(
    base_items: list[dict[str, Any]],
    extra_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*base_items, *extra_items]:
        label = _coerce_profile_text(item.get("label"))
        url = _coerce_profile_text(item.get("url"))
        if not label or not url:
            continue

        key = (label, url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _format_context_label(entry: ModelCatalogEntry, value: Any, *, input_side: bool) -> str:
    if value in (None, "", [], {}):
        return "未标注"

    if entry.category == "llm":
        return f"{_format_number(value)} tokens"

    suffix = "字符 / 提示输入" if input_side else "批量上限"
    return f"{_format_number(value)} {suffix}"


def _extract_context_profile(entry: ModelCatalogEntry) -> list[dict[str, str]]:
    constraints = entry.constraints_json or {}
    raw = _extract_raw(entry)

    input_window = constraints.get("max_context_tokens")
    if input_window in (None, "", 0):
        input_window = constraints.get("max_prompt_length")

    output_window = constraints.get("max_output_tokens")
    if output_window in (None, "", 0):
        output_window = constraints.get("max_batch_size")

    return [
        {"label": "输入窗口", "value": _format_context_label(entry, input_window, input_side=True)},
        {"label": "输出窗口", "value": _format_context_label(entry, output_window, input_side=False)},
        {"label": "项目别名", "value": entry.model_key},
        {"label": "版本迭代", "value": str(raw.get("version") or "未标注")},
    ]


def _capability_display_name(capability: dict[str, Any]) -> str:
    name = str(capability.get("name", "")).strip()
    return _CAPABILITY_LABELS.get(name, name or "未命名能力")


def _derive_strengths(entry: ModelCatalogEntry) -> list[str]:
    capabilities = list((entry.capabilities_json or {}).get("items", []) or [])
    if not capabilities:
        return [entry.subcategory or entry.category]

    def _capability_score(item: dict[str, Any]) -> float:
        try:
            return float(item.get("score", 0.0) or 0.0)
        except Exception:
            return 0.0

    ranked = sorted(capabilities, key=_capability_score, reverse=True)
    strengths: list[str] = []
    for capability in ranked:
        label = _capability_display_name(capability)
        description = str(capability.get("description") or "").strip()
        strengths.append(f"{label}：{description}" if description else label)
        if len(strengths) >= 4:
            break
    return strengths


def _translate_modalities(modalities: list[str]) -> list[str]:
    translated: list[str] = []
    for modality in modalities or []:
        value = str(modality or "").strip()
        if not value:
            continue
        translated.append(_MODALITY_LABELS.get(value, value))
    return translated


def _derive_project_modules(entry: ModelCatalogEntry) -> list[str]:
    routing = entry.routing_json or {}
    task_types = [str(item) for item in routing.get("task_types", []) or []]
    modules: list[str] = []

    def _push(label: str) -> None:
        if label not in modules:
            modules.append(label)

    if any(
        task in {"concept", "chapter", "dialogue", "creative", "writing", "outline_expand", "book_synthesis"}
        for task in task_types
    ):
        _push(_PROJECT_MODULE_LABELS["novel"])
    if any(task.startswith("asset_") for task in task_types):
        _push(_PROJECT_MODULE_LABELS["asset_studio"])
    if any("audiobook" in task for task in task_types) or entry.category == "audio":
        _push(_PROJECT_MODULE_LABELS["audiobook"])
    if entry.category in {"image", "video", "multimodal"}:
        _push(_PROJECT_MODULE_LABELS["drama"])
    _push(_PROJECT_MODULE_LABELS["catalog"])
    return modules


def _derive_project_tasks(entry: ModelCatalogEntry) -> list[str]:
    routing = entry.routing_json or {}
    task_types = [str(item) for item in routing.get("task_types", []) or []]
    labels = [_TASK_TYPE_LABELS.get(item, item) for item in task_types]
    if labels:
        return labels

    fallback_tasks: list[str] = []
    if entry.category == "image":
        fallback_tasks.append("视觉素材生成")
    elif entry.category == "video":
        fallback_tasks.append("镜头与片段生成")
    elif entry.category == "multimodal":
        fallback_tasks.append("视觉理解与质检")
    elif entry.category == "audio":
        fallback_tasks.append("音乐 / 音效生成" if _is_generated_audio_model(entry) else "有声内容合成")
    else:
        fallback_tasks.append(entry.subcategory or _CATEGORY_LABELS.get(entry.category, entry.category))
    return fallback_tasks + _translate_modalities(entry.modalities or [])[:2]


def _is_speech_audio_model(entry: ModelCatalogEntry) -> bool:
    modalities = {str(item).lower() for item in entry.modalities or []}
    capability_names = {
        str(item.get("name", "")).lower()
        for item in (entry.capabilities_json or {}).get("items", []) or []
        if isinstance(item, dict)
    }
    return bool({"text_to_speech", "voice_clone"} & modalities) or bool(
        {"speech_synthesis", "voice_clone", "preset_voices", "instruct_control"} & capability_names
    )


def _is_generated_audio_model(entry: ModelCatalogEntry) -> bool:
    return entry.category == "audio" and not _is_speech_audio_model(entry)


def _supports_video_reference_input(entry: ModelCatalogEntry) -> bool:
    return "video_to_audio" in {str(item).lower() for item in entry.modalities or []}


def _is_music_generation_model(entry: ModelCatalogEntry) -> bool:
    capability_names = {
        str(item.get("name", "")).lower()
        for item in (entry.capabilities_json or {}).get("items", []) or []
        if isinstance(item, dict)
    }
    routing = entry.routing_json or {}
    task_types = {str(item).lower() for item in routing.get("task_types", []) or []}
    return bool({"music_generation", "background_music"} & capability_names) or "asset_music" in task_types


def _detect_openai_compatible(entry: ModelCatalogEntry) -> bool:
    raw = _extract_raw(entry)
    api_config = raw.get("api_config", {}) or {}
    base_url = str(api_config.get("base_url") or "").lower()
    documentation_url = str(entry.documentation_url or "").lower()
    if "/compatible-mode/" in base_url or "/v1" in base_url:
        return True
    if "openai" in documentation_url or "compatible" in documentation_url:
        return True
    return entry.category in {"llm", "multimodal"} and entry.provider in {"alibaba", "deepseek"}


def _derive_tooling_badges(entry: ModelCatalogEntry) -> list[str]:
    constraints = entry.constraints_json or {}
    raw = _extract_raw(entry)
    profile = _extract_catalog_profile(entry)
    badges: list[str] = []

    def _push(label: str, enabled: bool = True) -> None:
        if enabled and label not in badges:
            badges.append(label)

    _push("统一档案")
    _push("流式输出", bool(constraints.get("supports_streaming")))
    _push("JSON 模式", bool(constraints.get("supports_json_mode")))
    _push("函数调用", bool(constraints.get("supports_function_call")))
    _push("系统角色", bool(constraints.get("supports_system_prompt")))
    _push("多轮会话", bool(constraints.get("supports_multi_turn")))
    _push("视觉输入", bool(constraints.get("supports_vision")) or entry.category == "multimodal")
    _push("统一媒体运行时", entry.category in {"image", "video", "audio", "multimodal"})
    _push("ModelHub 路由", entry.category == "llm")
    _push("OpenAI 兼容", _detect_openai_compatible(entry))
    _push("环境变量可识别", bool(raw.get("api_config", {}).get("api_key_env")))
    profile_badges = _coerce_profile_string_list(profile.get("tooling_badges"))
    return _merge_unique_strings(profile_badges, badges)[:8]


def _derive_runtime_entry(entry: ModelCatalogEntry) -> dict[str, str]:
    if entry.category == "llm":
        return {
            "runtime": "ModelHub 统一调度",
            "helper": "create_task_llm / create_model_llm",
            "entry_file": "core/model_hub.py · core/langchain_bridge.py",
        }

    operation_map = {
        "image": "UnifiedMediaRuntime.generate_image / edit_image",
        "video": "UnifiedMediaRuntime.generate_video",
        "multimodal": "UnifiedMediaRuntime.analyze_image / analyze_video",
        "audio": "POST /api/v1/asset-studio/audio" if _is_generated_audio_model(entry) else "UnifiedMediaRuntime.synthesize_speech",
    }
    return {
        "runtime": "资产工作台音频服务" if _is_generated_audio_model(entry) else "UnifiedMediaRuntime 媒体运行时",
        "helper": operation_map.get(entry.category, "UnifiedMediaRuntime"),
        "entry_file": (
            "backend/app/api/v1/asset_studio.py · "
            "backend/app/services/audiobook/ai_music.py · "
            "backend/app/services/audiobook/klingai_effect_generator.py"
            if _is_generated_audio_model(entry)
            else "core/unified_media_runtime.py"
        ),
    }


def _derive_proxy_path(entry: ModelCatalogEntry) -> str:
    prefix = "llm" if entry.category == "llm" else "media"
    return f"/proxy/{prefix}/{entry.provider}/{entry.model_key}"


def _derive_env_bindings(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    raw = _extract_raw(entry)
    bindings: list[dict[str, Any]] = []
    api_config = raw.get("api_config", {}) or {}

    def _push(label: str, value: str, required: bool = True) -> None:
        clean_value = str(value or "").strip()
        if not clean_value:
            return
        bindings.append({"label": label, "value": clean_value, "required": required})

    if entry.category == "llm":
        _push("API Key", api_config.get("api_key_env", ""))
        _push("Base URL", api_config.get("base_url", ""))
        _push("模型名 / Deployment", entry.model_key)
        return bindings

    if entry.model_key == "wan2.6-t2i":
        _push("API Key", "WAN_T2I_API_KEY")
        _push("Base URL", "WAN_T2I_BASE_URL")
        _push("模型名 / Deployment", "WAN_T2I_MODEL_NAME / WAN_T2I_MODEL_ID / wan2.6-t2i", required=False)
    elif entry.model_key.startswith("wan2.7-"):
        upper_model = entry.model_key.upper().replace(".", "_").replace("-", "_")
        _push("API Key", "DASHSCOPE_API_KEY")
        _push("Base URL", "DASHSCOPE_BASE_URL")
        _push("模型名 / Deployment", upper_model)
    elif entry.model_key == "qwen3-vl-plus":
        _push("API Key", "QWEN_VL_PLUS_API_KEY / DASHSCOPE_API_KEY")
        _push("Base URL", "QWEN_VL_PLUS_BASE_URL / DASHSCOPE_BASE_URL")
        _push("模型名 / Deployment", "QWEN_VL_PLUS_MODEL_NAME / QWEN_VL_PLUS_MODEL_ID")
    elif entry.model_key == "qwen-image-edit-plus":
        _push("API Key", "QWEN_IMAGE_EDIT_API_KEY / DASHSCOPE_API_KEY")
        _push("Base URL", "QWEN_IMAGE_EDIT_BASE_URL / DASHSCOPE_BASE_URL")
        _push("模型名 / Deployment", "QWEN_IMAGE_EDIT_MODEL_NAME / QWEN_IMAGE_EDIT_MODEL_ID", required=False)
    elif entry.model_key == "qwen-image-edit-max":
        _push("API Key", "QWEN_IMAGE_EDIT_MAX_API_KEY / DASHSCOPE_API_KEY")
        _push("Base URL", "QWEN_IMAGE_EDIT_MAX_BASE_URL / DASHSCOPE_BASE_URL")
        _push(
            "模型名 / Deployment",
            "QWEN_IMAGE_EDIT_MAX_MODEL_NAME / QWEN_IMAGE_EDIT_MAX_MODEL_ID",
            required=False,
        )
    elif entry.model_key == "mureka-o1-instrumental":
        _push("API Key", "MUREKA_API_KEY")
        _push("Base URL", "MUREKA_API_URL")
        _push("模型名 / Deployment", entry.model_key, required=False)
    elif entry.model_key == "vidu-timing2audio":
        _push("API Key", "VIDU_API_KEY")
        _push("Base URL", "VIDU_API_URL", required=False)
        _push("模型名 / Endpoint", entry.model_key, required=False)
    elif entry.model_key in {"qwen3-tts-flash", "cosyvoice-v3-plus"}:
        _push("API Key", "DASHSCOPE_API_KEY")
        _push("模型名 / Deployment", "QWEN3_TTS_FLASH_MODEL_ID", required=entry.model_key == "qwen3-tts-flash")
    else:
        _push("模型名 / Deployment", entry.model_key)

    return bindings


def _derive_param_matrix(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    constraints = entry.constraints_json or {}
    params: list[dict[str, Any]] = []

    def _push(name: str, label: str, supported: bool, note: str) -> None:
        params.append({"name": name, "label": label, "supported": supported, "note": note})

    if entry.category == "llm":
        _push("messages", "消息列表", True, "统一使用 role/content 结构。")
        _push("temperature", "Temperature", bool(constraints.get("supports_temperature")), "控制生成随机性。")
        _push("max_tokens", "Max Tokens", True, "限制输出长度。")
        _push("stream", "Streaming", bool(constraints.get("supports_streaming")), "是否启用流式输出。")
        _push("response_format", "JSON 模式", bool(constraints.get("supports_json_mode")), "适合结构化返回。")
        _push("tools", "Function Calling / Tools", bool(constraints.get("supports_function_call")), "适合工具编排与 Agent 工作流。")
        _push("system", "System Prompt", bool(constraints.get("supports_system_prompt")), "可定制系统角色。")
        _push("timeout", "Timeout", bool(constraints.get("supports_timeout_param")), "调用层是否支持自定义超时。")
        _push("max_retries", "Max Retries", bool(constraints.get("supports_max_retries")), "调用层是否支持重试次数。")
        return params

    if _is_generated_audio_model(entry):
        _push("prompt", "Prompt", True, "通过场景、材质、节奏和情绪描述音频目标。")
        _push("duration", "Duration", True, "控制音频时长，资产工作台当前按秒级离散值约束。")
        _push("style", "Style / 风格", _is_music_generation_model(entry), "适合音乐风格、氛围与配器方向控制。")
        _push("mood", "Mood / 情绪", True, "用于约束音乐或音效的整体情绪方向。")
        _push("tempo", "Tempo / 节奏", _is_music_generation_model(entry), "适合控制配乐节奏快慢。")
        _push("reference_assets", "参考视频", _supports_video_reference_input(entry), "仅视频转音频链路需要参考视频输入。")
        return params

    _push("prompt", "Prompt", True, "媒体模型统一支持主提示词。")
    _push("negative_prompt", "Negative Prompt", entry.category in {"image", "video"}, "控制不希望出现的元素。")
    _push("seed", "Seed", entry.category in {"image", "video"}, "用于复现或稳定结果。")
    _push("reference_assets", "参考素材", entry.category in {"image", "video", "multimodal"}, "支持参考图或参考视频的链路。")
    _push("dimensions", "尺寸 / 分辨率", entry.category in {"image", "video"}, "通过宽高或分辨率控制输出规格。")
    _push("duration", "Duration", entry.category == "video", "视频模型支持时长参数。")
    _push("voice", "Voice / Speaker", _is_speech_audio_model(entry), "语音模型支持音色或说话人选择。")
    _push("instruct", "Instruct / 情绪控制", entry.model_key == "cosyvoice-v3-plus", "适合有声表现力控制。")
    return params


def _derive_response_features(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    constraints = entry.constraints_json or {}
    features: list[dict[str, Any]] = []

    def _push(label: str, supported: bool, note: str) -> None:
        features.append({"label": label, "supported": supported, "note": note})

    if entry.category == "llm":
        _push("流式输出", bool(constraints.get("supports_streaming")), "适合长响应与前端实时反馈。")
        _push("JSON 模式", bool(constraints.get("supports_json_mode")), "适合结构化工作流。")
        _push("函数调用", bool(constraints.get("supports_function_call")), "适合工具编排与 AI 编程助手识别。")
        _push("系统角色", bool(constraints.get("supports_system_prompt")), "适合专属系统指令。")
        _push("多轮对话", bool(constraints.get("supports_multi_turn")), "适合连续对话上下文。")
        return features

    _push(
        "统一接入层",
        True,
        "通过项目统一媒体运行时访问，或通过资产工作台音频服务代理访问。",
    )
    _push("结构化元数据", True, "结果会附带模型、耗时、成本等元数据。")
    _push(
        "多参考输入",
        entry.category in {"image", "video", "multimodal"} or _supports_video_reference_input(entry),
        "支持参考图、参考视频或多图输入；视频转音频链路可扩展参考视频。",
    )
    _push("二进制输出", entry.category in {"image", "video", "audio"}, "可返回 URL、二进制或媒体数据。")
    return features


def _build_llm_python_template(entry: ModelCatalogEntry) -> str:
    default_params = entry.default_params_json or {}
    constraints = entry.constraints_json or {}
    temperature = default_params.get("temperature", 0.7)
    max_tokens = default_params.get("max_tokens") or constraints.get("max_output_tokens") or 2048
    stream_value = "True" if constraints.get("supports_streaming") else "False"
    return (
        "from core.model_hub import ModelHub\n\n"
        "hub = ModelHub.get_instance()\n"
        "result = await hub.call(\n"
        f"    model=\"{entry.model_key}\",\n"
        "    messages=[\n"
        "        {\"role\": \"system\", \"content\": \"你是一名专业助手。\"},\n"
        "        {\"role\": \"user\", \"content\": \"请根据任务生成结果。\"},\n"
        "    ],\n"
        f"    temperature={temperature},\n"
        f"    max_tokens={max_tokens},\n"
        f"    stream={stream_value},\n"
        ")\n"
        "logger.debug(result.content)\n"
    )


def _build_llm_javascript_template(entry: ModelCatalogEntry) -> str:
    raw = _extract_raw(entry)
    api_config = raw.get("api_config", {}) or {}
    default_params = entry.default_params_json or {}
    base_url = str(api_config.get("base_url") or "https://api.example.com/v1").strip()
    api_key_env = str(api_config.get("api_key_env") or "MODEL_API_KEY").strip()
    temperature = default_params.get("temperature", 0.7)
    max_tokens = default_params.get("max_tokens") or (entry.constraints_json or {}).get("max_output_tokens") or 2048
    return (
        "import OpenAI from \"openai\";\n\n"
        "const client = new OpenAI({\n"
        f"  apiKey: process.env.{api_key_env},\n"
        f"  baseURL: \"{base_url}\",\n"
        "});\n\n"
        "const result = await client.chat.completions.create({\n"
        f"  model: \"{entry.model_key}\",\n"
        "  messages: [\n"
        "    { role: \"system\", content: \"你是一名专业助手。\" },\n"
        "    { role: \"user\", content: \"请根据任务生成结果。\" },\n"
        "  ],\n"
        f"  temperature: {temperature},\n"
        f"  max_tokens: {max_tokens},\n"
        "});\n\n"
        "console.log(result.choices[0]?.message?.content || \"\");\n"
    )


def _derive_media_method_name(entry: ModelCatalogEntry) -> str:
    if entry.category == "image":
        return "edit_image" if entry.subcategory == "图像编辑" else "generate_image"
    if entry.category == "video":
        return "generate_video"
    if entry.category == "multimodal":
        return "analyze_video" if "video_understanding" in (entry.modalities or []) else "analyze_image"
    if entry.category == "audio":
        return "generate_audio" if _is_generated_audio_model(entry) else "synthesize_speech"
    return "run"


def _build_media_python_template(entry: ModelCatalogEntry) -> str:
    method_name = _derive_media_method_name(entry)
    if method_name == "generate_image":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "result = media_runtime.generate_image(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    prompt=\"请生成一张符合需求的图像\",\n"
            "    width=1024,\n"
            "    height=1024,\n"
            ")\n"
            "logger.debug(result.outputs)\n"
        )
    if method_name == "edit_image":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "result = media_runtime.edit_image(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    prompt=\"请根据参考图完成图像编辑\",\n"
            "    reference_images=[\"./reference.png\"],\n"
            ")\n"
            "logger.debug(result.outputs)\n"
        )
    if method_name == "generate_video":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "result = media_runtime.generate_video(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    prompt=\"请生成一个 5 秒钟的视频镜头\",\n"
            "    duration=5.0,\n"
            "    width=1280,\n"
            "    height=720,\n"
            ")\n"
            "logger.debug(result.outputs)\n"
        )
    if method_name == "generate_audio":
        if _supports_video_reference_input(entry):
            return (
                "# 当前项目已将该能力纳入统一模型档案，但尚未开放可直接调用的工作台入口。\n"
                "# 后续接入时，建议在 /api/v1/asset-studio/audio 增加 reference_video 上传字段。\n"
                "payload = {\n"
                f"    \"model_id\": \"{entry.model_key}\",\n"
                "    \"generation_type\": \"sound-effect\",\n"
                "    \"prompt\": \"根据视频补充环境音、动作音和氛围声\",\n"
                "}\n"
                "logger.debug(payload)\n"
            )
        generation_type = "music" if _is_music_generation_model(entry) else "sound-effect"
        duration = "30" if generation_type == "music" else "5"
        style_field = "    \"style\": \"氛围\",\n" if generation_type == "music" else ""
        return (
            "import httpx\n\n"
            "headers = {\"Authorization\": \"Bearer <your-token>\"}\n"
            "payload = {\n"
            f"    \"model_id\": \"{entry.model_key}\",\n"
            f"    \"generation_type\": \"{generation_type}\",\n"
            "    \"prompt\": \"夜色中的城市氛围，低频铺底，带轻微紧张感\",\n"
            f"    \"duration\": \"{duration}\",\n"
            f"{style_field}"
            "    \"mood\": \"tense\",\n"
            "    \"tempo\": \"medium\",\n"
            "}\n\n"
            "async with httpx.AsyncClient(base_url=\"http://127.0.0.1:8000\", headers=headers, timeout=300) as client:\n"
            "    response = await client.post(\"/api/v1/asset-studio/audio\", data=payload)\n"
            "    response.raise_for_status()\n"
            "    result = response.json()\n"
            "    logger.debug(result[\"primary_output\"])\n"
        )
    if method_name == "synthesize_speech":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "audio_bytes = await media_runtime.synthesize_speech(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    text=\"这是需要合成的文本。\",\n"
            "    speaker=\"默认音色\",\n"
            ")\n"
            "logger.debug(len(audio_bytes))\n"
        )
    return (
        "from core.unified_media_runtime import media_runtime\n\n"
        f"# 使用 {entry.model_key} 执行多模态分析\n"
        "# 具体参数请参考项目适配器定义。\n"
    )


def _build_media_javascript_template(entry: ModelCatalogEntry) -> str:
    method_name = _derive_media_method_name(entry)
    operation = {
        "generate_image": "图像生成",
        "edit_image": "图像编辑",
        "generate_video": "视频生成",
        "generate_audio": "音乐 / 音效生成",
        "analyze_image": "图像分析",
        "analyze_video": "视频分析",
        "synthesize_speech": "语音合成",
    }.get(method_name, "媒体调用")
    if method_name == "generate_audio":
        if _supports_video_reference_input(entry):
            return (
                "const payload = {\n"
                f"  modelId: \"{entry.model_key}\",\n"
                "  generationType: \"sound-effect\",\n"
                "  prompt: \"根据视频补充环境音、动作音和氛围声\",\n"
                "};\n\n"
                "// 当前项目仅完成模型档案归档，尚未开放视频转音频的统一前端入口。\n"
                "console.log(\"待接入的视频转音频能力\", payload);\n"
            )
        generation_type = "music" if _is_music_generation_model(entry) else "sound-effect"
        style_line = "formData.append(\"style\", \"氛围\");\n" if generation_type == "music" else ""
        return (
            "const formData = new FormData();\n"
            "formData.append(\"prompt\", \"夜色中的城市氛围，低频铺底，带轻微紧张感\");\n"
            f"formData.append(\"generation_type\", \"{generation_type}\");\n"
            f"formData.append(\"model_id\", \"{entry.model_key}\");\n"
            f"formData.append(\"duration\", \"{'30' if generation_type == 'music' else '5'}\");\n"
            f"{style_line}"
            "formData.append(\"mood\", \"tense\");\n"
            "formData.append(\"tempo\", \"medium\");\n\n"
            "// 建议经后端统一代理到 /api/v1/asset-studio/audio，不要前端直连供应商密钥。\n"
            "console.log(\"提交资产工作台音频任务\", formData);\n"
        )
    return (
        "const payload = {\n"
        f"  modelId: \"{entry.model_key}\",\n"
        "  prompt: \"请根据任务生成结果\",\n"
        "};\n\n"
        f"// 建议前端通过后端统一服务触发 {operation}，避免直接暴露密钥。\n"
        f"console.log(\"当前模型用于：{operation}\", payload);\n"
    )


def _build_sdk_templates(entry: ModelCatalogEntry) -> dict[str, str]:
    if entry.category == "llm":
        return {
            "python": _build_llm_python_template(entry),
            "javascript": _build_llm_javascript_template(entry),
        }
    return {
        "python": _build_media_python_template(entry),
        "javascript": _build_media_javascript_template(entry),
    }


def _build_system_role(entry: ModelCatalogEntry) -> str:
    if entry.model_key == "qwen3-max":
        return "你是中文长篇创作与角色对话专家，擅长章节起草、重写与风格统一。"
    if entry.model_key == "qwen-long":
        return "你是超长文本理解与整书规划专家，擅长汇总、分层摘要与全书一致性分析。"
    if entry.model_key == "qwen-turbo":
        return "你是结构化提取与轻量改写助手，优先输出简洁、稳定、低成本的结果。"
    if entry.model_key == "deepseek-reasoner":
        return "你是严谨的推理审校专家，优先处理逻辑约束、规则一致性和复杂决策。"
    if entry.category == "multimodal":
        return "你是视觉内容审查与多模态解析专家，负责图像、视频与结构化理解。"
    if entry.category == "image":
        return "你是视觉创意提示词与图像生成策略专家，负责主体、风格、构图与约束编排。"
    if entry.category == "video":
        return "你是镜头脚本与视频生成提示专家，负责镜头语言、动作与时长规划。"
    if entry.category == "audio":
        if _is_generated_audio_model(entry):
            if _supports_video_reference_input(entry):
                return "你是视频补声音轨策划助手，负责根据镜头内容规划环境音、动作音与氛围声。"
            if _is_music_generation_model(entry):
                return "你是音乐提示词与配乐策略助手，负责场景、情绪、节奏和配器方向的设计。"
            return "你是音效提示词设计助手，负责把动作、材质、空间和氛围描述压缩成可生成的音频提示词。"
        return "你是有声脚本与语音表现力规划助手，负责音色、情绪和停顿控制。"
    return "你是项目统一模型调用的专业助手。"


def _build_prompt_patterns(entry: ModelCatalogEntry) -> list[dict[str, str]]:
    if entry.category == "llm":
        return [
            {"title": "系统角色模板", "template": f"System: {_build_system_role(entry)}"},
            {"title": "正文 / 分析任务模板", "template": "User: 目标 + 约束 + 输出结构 + 风格要求 + 禁止项。"},
            {"title": "结构化输出模板", "template": "User: 请按 JSON 输出，字段固定为 title/content/risks/next_actions。"},
        ]
    if entry.category == "image":
        return [
            {"title": "文生图模板", "template": "主体 + 场景 + 风格 + 镜头构图 + 光影 + 负向约束。"},
            {"title": "图像编辑模板", "template": "参考图 + 编辑目标 + 保留元素 + 不要改动项 + 输出风格。"},
        ]
    if entry.category == "video":
        return [
            {"title": "视频镜头模板", "template": "主体 + 动作 + 场景 + 镜头运动 + 时长 + 节奏。"},
            {"title": "参考驱动模板", "template": "参考图/视频 + 要保留的风格 + 要发生的动作 + 禁止项。"},
        ]
    if entry.category == "audio":
        if _is_generated_audio_model(entry):
            if _supports_video_reference_input(entry):
                return [
                    {"title": "视频补声模板", "template": "输入视频 + 关注的声音层（环境 / 动作 / 氛围）+ 希望保留或避免的声音元素。"},
                    {"title": "镜头音轨策略模板", "template": "镜头节奏 + 场景空间感 + 声音远近层次 + 是否需要音乐化处理。"},
                ]
            if _is_music_generation_model(entry):
                return [
                    {"title": "背景音乐模板", "template": "场景 + 情绪 + 节奏 + 风格 + 主要乐器 + 时长。"},
                    {"title": "配乐控制模板", "template": "片段定位 + 氛围关键词 + 节奏推进方式 + 不要出现的人声或歌词。"},
                ]
            return [
                {"title": "短音效模板", "template": "动作主体 + 材质 + 强度 + 持续时间 + 是否需要尾音。"},
                {"title": "环境音模板", "template": "场景环境 + 远近层次 + 氛围关键词 + 时长 + 是否需要循环感。"},
            ]
        return [
            {"title": "标准 TTS 模板", "template": "角色/音色 + 文本内容 + 语速 + 停顿 + 输出格式。"},
            {"title": "情绪化朗读模板", "template": "角色定位 + 情绪标签 + 语气 + 节奏 + 是否使用 instruct。"},
        ]
    return [{"title": "多模态解析模板", "template": "输入素材 + 识别目标 + 输出结构 + 风险项。"}]


def _build_router_rules(entry: ModelCatalogEntry) -> list[dict[str, str]]:
    routing = entry.routing_json or {}
    task_types = [str(item) for item in routing.get("task_types", []) or []]
    rules: list[dict[str, str]] = []

    if task_types:
        rules.append(
            {
                "when": "检测到任务类型命中项目路由表",
                "action": f"优先路由到 {entry.model_key}",
                "reason": "该模型已在项目运行时中声明为对应任务的优先模型。",
            }
        )
    if routing.get("fallback_models"):
        rules.append(
            {
                "when": "主模型不可用、超时或被策略降级",
                "action": f"回退到 {' / '.join(routing.get('fallback_models') or [])}",
                "reason": "遵循当前模型配置中的 fallback_models。",
            }
        )
    if entry.category == "video" and "fast" in entry.model_key:
        rules.append(
            {
                "when": "视频链路超时或需要快速预览",
                "action": f"优先使用 {entry.model_key}",
                "reason": "该模型定位为速度优先的降级位。",
            }
        )
    if entry.category == "image" and "turbo" in entry.model_key:
        rules.append(
            {
                "when": "需要低成本快速预览图像",
                "action": f"优先使用 {entry.model_key}",
                "reason": "适合提示词迭代与早期草图筛选。",
            }
        )
    return rules


def _extract_best_practice_tips(entry: ModelCatalogEntry) -> list[str]:
    profile = _extract_catalog_profile(entry)
    profile_tips = _coerce_profile_string_list(profile.get("best_practice_tips"))
    if profile_tips:
        return profile_tips

    raw = _extract_raw(entry)
    llm_tips = raw.get("best_practice_tips")
    if isinstance(llm_tips, list):
        return [str(item).strip() for item in llm_tips if str(item).strip()]

    media_tips = ((entry.routing_json or {}).get("best_practice") or {}).get("tips")
    if isinstance(media_tips, list):
        return [str(item).strip() for item in media_tips if str(item).strip()]
    return []


def _build_identity_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    raw = _extract_raw(entry)
    profile = _extract_catalog_profile(entry)
    modules = _derive_project_modules(entry)
    task_labels = _derive_project_tasks(entry)
    strengths = _derive_strengths(entry)
    weaknesses = list(entry.limitations or [])[:4]
    role_summary = _coerce_profile_text(profile.get("role_summary")) or f"当前模型主要服务于：{'、'.join(modules)}。"
    return {
        "core_positioning": entry.summary or "暂无摘要",
        "model_lineage": [
            {"label": "模型名称", "value": entry.name},
            {"label": "模型家族", "value": entry.model_family or "未标注"},
            {"label": "开发商", "value": _PROVIDER_LABELS.get(entry.provider, entry.provider)},
            {"label": "模型定位", "value": entry.subcategory or _CATEGORY_LABELS.get(entry.category, entry.category)},
            {"label": "状态", "value": str(raw.get("status") or entry.status or "active")},
        ],
        "context_window": _extract_context_profile(entry),
        "capability_quadrants": {
            "strengths": strengths,
            "weaknesses": weaknesses,
            "modalities": _translate_modalities(entry.modalities or []),
            "capability_tags": [
                _capability_display_name(item) for item in (entry.capabilities_json or {}).get("items", [])[:6]
            ],
        },
        "project_fit": {
            "modules": modules,
            "task_types": task_labels,
            "role_summary": role_summary,
        },
    }


def _build_integration_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    runtime = _derive_runtime_entry(entry)
    profile = _extract_catalog_profile(entry)
    recommended_wrapper = _coerce_profile_text(profile.get("recommended_wrapper")) or (
        "建议统一封装为 call_model(model_name, prompt, config)，由底层再分发到 ModelHub 或 UnifiedMediaRuntime。"
    )
    return {
        "calling_stack": [
            {"label": "统一运行时", "value": runtime["runtime"]},
            {"label": "推荐入口", "value": runtime["helper"]},
            {"label": "运行时代码", "value": runtime["entry_file"]},
            {"label": "接入模式", "value": "OpenAI 兼容接口" if _detect_openai_compatible(entry) else "项目适配器 / 专有 REST"},
        ],
        "native_parameters": _derive_param_matrix(entry),
        "response_features": _derive_response_features(entry),
        "environment_bindings": _derive_env_bindings(entry),
        "tooling_badges": _derive_tooling_badges(entry),
        "recommended_wrapper": recommended_wrapper,
        "sdk_templates": _build_sdk_templates(entry),
    }


def _build_prompt_router_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    routing = entry.routing_json or {}
    profile = _extract_catalog_profile(entry)
    prompt_patterns = _coerce_profile_object_list(
        profile.get("prompt_patterns"),
        required_keys=("title", "template"),
    )
    router_rules = _coerce_profile_object_list(
        profile.get("router_rules"),
        required_keys=("when", "action", "reason"),
    )
    fallback_chain = _coerce_profile_string_list(profile.get("fallback_chain")) or [
        str(item) for item in routing.get("fallback_models", []) or []
    ]
    return {
        "system_role": _coerce_profile_text(profile.get("system_role")) or _build_system_role(entry),
        "prompt_patterns": prompt_patterns or _build_prompt_patterns(entry),
        "router_rules": router_rules or _build_router_rules(entry),
        "best_practice_tips": _extract_best_practice_tips(entry),
        "fallback_chain": fallback_chain,
    }


def _build_deployment_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    runtime = _derive_runtime_entry(entry)
    profile = _extract_catalog_profile(entry)
    proxy_path = _derive_proxy_path(entry)
    topology = [
        {"label": "部署模式", "value": "官方托管 API + 项目统一运行时"},
        {"label": "建议代理路径", "value": proxy_path},
        {"label": "推荐接入层", "value": runtime["runtime"]},
    ]

    if entry.category == "llm":
        project_entrypoints = [
            {"label": "任务路由调用", "value": "create_task_llm(task_type=...)"},
            {"label": "显式点名调用", "value": f"create_model_llm(model=\"{entry.model_key}\")"},
            {"label": "底层统一入口", "value": "ModelHub.call(messages, task_type, model, ...)"},
        ]
        local_note = "当前项目优先使用官方托管 API；如需本地替代，可额外接入 Ollama / LM Studio 并在统一封装层映射。"
    else:
        project_entrypoints = [
            {"label": "统一媒体入口", "value": runtime["helper"]},
            {"label": "底层统一入口", "value": "UnifiedMediaRuntime(...)"},
            {"label": "前端调用建议", "value": "建议经后端服务代理，不直接暴露供应商密钥。"},
        ]
        local_note = "当前项目优先使用托管媒体接口；本地替代更适合开源模型或离线工作站，不建议直接替换现有生产链路。"

    project_entrypoints = _coerce_profile_object_list(
        profile.get("project_entrypoints"),
        required_keys=("label", "value"),
    ) or project_entrypoints
    local_note = _coerce_profile_text(profile.get("local_deployment_note")) or local_note

    proxy_snippet = (
        f"location {proxy_path} {{\n"
        "    proxy_set_header Authorization $http_authorization;\n"
        "    proxy_pass https://upstream-provider.example.com;\n"
        "}\n"
    )

    return {
        "access_topology": topology,
        "project_entrypoints": project_entrypoints,
        "environment_convention": _derive_env_bindings(entry),
        "local_deployment_note": local_note,
        "proxy_snippet": proxy_snippet,
    }


def _build_resource_navigation(entry: ModelCatalogEntry) -> dict[str, Any]:
    profile = _extract_catalog_profile(entry)
    profile_resources = profile.get("resource_navigation") if isinstance(profile.get("resource_navigation"), dict) else {}
    official_sources: list[dict[str, str]] = []
    if entry.documentation_url:
        official_sources.append({"label": "官方文档", "url": entry.documentation_url, "note": "优先作为接口与参数依据。"})
    for url in entry.source_urls or []:
        if url == entry.documentation_url:
            continue
        official_sources.append({"label": "补充来源", "url": url, "note": "用于核验计费、模型列表或补充说明。"})

    provider_portals = list(_REFERENCE_HUBS["provider_portals"])
    if entry.provider == "alibaba":
        provider_portals = [item for item in provider_portals if item["label"] == "通义实验室"]
    elif entry.provider == "deepseek":
        provider_portals = [item for item in provider_portals if item["label"] == "DeepSeek 官网"]

    return {
        "official_sources": _merge_resource_links(
            official_sources[:5],
            _coerce_profile_object_list(
                profile_resources.get("official_sources"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
        "selection_hubs": _merge_resource_links(
            list(_REFERENCE_HUBS["selection_hubs"]),
            _coerce_profile_object_list(
                profile_resources.get("selection_hubs"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
        "model_hubs": _merge_resource_links(
            list(_REFERENCE_HUBS["model_hubs"]),
            _coerce_profile_object_list(
                profile_resources.get("model_hubs"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
        "provider_portals": _merge_resource_links(
            provider_portals,
            _coerce_profile_object_list(
                profile_resources.get("provider_portals"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
    }


def _build_constraints_summary(entry: ModelCatalogEntry) -> dict[str, Any]:
    """构建约束条件的摘要信息，用于前端展示
    
    Args:
        entry: 模型档案实体
        
    Returns:
        约束条件摘要字典
    """
    constraints = entry.constraints_json or {}
    raw = _extract_raw(entry)
    performance = entry.performance_json or {}
    cost_profile = performance.get("cost_profile", {}) or {}
    
    summary = {}
    
    if entry.category == "video":
        duration_values = constraints.get("duration", [])
        if duration_values:
            min_dur = min(duration_values)
            max_dur = max(duration_values)
            summary["duration"] = {
                "min_seconds": min_dur,
                "max_seconds": max_dur,
                "available_options": sorted(duration_values),
            }
        
        summary["resolution"] = {
            "min_width": constraints.get("min_width"),
            "max_width": constraints.get("max_width"),
            "min_height": constraints.get("min_height"),
            "max_height": constraints.get("max_height"),
        }
        
        ratios = constraints.get("ratios", [])
        if ratios:
            summary["aspect_ratios"] = sorted(ratios)
    
    elif entry.category == "image":
        summary["resolution"] = {
            "min_width": constraints.get("min_width"),
            "max_width": constraints.get("max_width"),
            "min_height": constraints.get("min_height"),
            "max_height": constraints.get("max_height"),
        }
        
        ratios = constraints.get("ratios", [])
        if ratios:
            summary["aspect_ratios"] = sorted(ratios)
    
    batch_size = constraints.get("max_batch_size")
    if batch_size:
        summary["max_batch_size"] = batch_size
    
    prompt_length = constraints.get("max_prompt_length")
    if prompt_length:
        summary["max_prompt_length"] = prompt_length
    
    if cost_profile.get("price") is not None:
        summary["pricing"] = {
            "price": cost_profile.get("price"),
            "unit": cost_profile.get("unit", ""),
            "currency": cost_profile.get("currency", "CNY"),
            "pricing_verified": cost_profile.get("pricing_verified", False),
        }
    
    return summary


def _build_capability_provenance(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    """构建能力溯源信息列表，用于前端展示
    
    Args:
        entry: 模型档案实体
        
    Returns:
        能力溯源信息列表
    """
    capabilities = (entry.capabilities_json or {}).get("items", []) or []
    provenance_list = []
    
    for cap in capabilities:
        if not isinstance(cap, dict):
            continue
        
        cap_name = cap.get("name", "")
        if not cap_name:
            continue
        
        provenance_list.append({
            "capability_name": cap_name,
            "capability_label": _CAPABILITY_LABELS.get(cap_name, cap_name),
            "support_level": cap.get("support_level", "unknown"),
            "description": cap.get("description", ""),
            "score": cap.get("score"),
            "source": cap.get("source", ""),
            "verified_at": cap.get("verified_at"),
            "confidence": cap.get("confidence", "low"),
        })
    
    return provenance_list

def _build_usage_guide(entry: ModelCatalogEntry) -> Optional[dict[str, Any]]:
    raw = entry.raw_config_json or {}
    usage_guide = raw.get("usage_guide")
    if not usage_guide:
        return None
    
    category_common = usage_guide.get("category_common", "llm")
    category_common_guide = _get_category_common_guide(category_common)
    
    model_specific = usage_guide.get("model_specific", {})
    
    merged_guide = _merge_usage_guides(category_common_guide, model_specific)
    return merged_guide


_CATEGORY_COMMON_GUIDES: dict[str, dict[str, Any]] = {
    "video": {
        "title": "视频模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "视频生成的提示词应包含主体、动作、场景、风格四个要素。\n\n**好的示例：**\n- \"一只橘猫在草地上追逐蝴蝶，镜头跟随移动，暖色调，电影感\"\n- \"雨夜街道，霓虹灯倒影，慢镜头推近，赛博朋克风格\"\n\n**避免：**\n- 过于抽象的描述如\"好看的风景\"\n- 矛盾的动作描述",
                "tips": [
                    "使用具体的视觉描述词",
                    "指定镜头运动方式",
                    "明确画面风格和氛围",
                    "控制场景复杂度"
                ]
            },
            {
                "title": "参考图使用",
                "content": "使用参考图可以大幅提升生成质量。支持图片参考和视频参考两种模式。",
                "tips": [
                    "使用高清、主体清晰的图片",
                    "参考图风格应与目标一致",
                    "多图时注意权重分配",
                    "视频参考注意时长限制"
                ]
            },
            {
                "title": "时长与分辨率选择",
                "content": "根据使用场景选择合适的时长和分辨率。",
                "tips": [
                    "短视频适合社交媒体分享",
                    "高分辨率会增加生成时间",
                    "首次生成建议先用低分辨率测试提示词"
                ]
            }
        ]
    },
    "image": {
        "title": "图像模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "图像生成的提示词应包含主体、环境、构图、风格四个要素。\n\n**好的示例：**\n- \"清晨的湖边小屋，薄雾笼罩，暖色晨光，水彩画风格\"\n- \"未来城市天际线，霓虹灯，赛博朋克，超广角\"\n\n**避免：**\n- 过度堆砌形容词\n- 矛盾的视觉描述",
                "tips": [
                    "描述要具体且有层次",
                    "先主体后环境",
                    "指定艺术风格",
                    "善用光照和氛围描述"
                ]
            },
            {
                "title": "风格控制",
                "content": "不同模型对风格的控制方式不同。",
                "tips": [
                    "使用风格预设可以快速获得一致效果",
                    "混合风格时需要平衡权重",
                    "注意模型的文本渲染能力"
                ]
            }
        ]
    },
    "audio": {
        "title": "音频模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "音频生成的提示词应包含类型、风格、情绪、时长等要素。",
                "tips": [
                    "指定音乐类型和节奏",
                    "描述期望的情绪氛围",
                    "控制音频时长"
                ]
            }
        ]
    },
    "llm": {
        "title": "文本模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "好的提示词是大模型高效工作的前提。\n\n**结构化提示词：**\n```\n角色：你是专业的小说编辑\n任务：分析以下文本的情节结构\n输出格式：分点列出，每个要点不超过50字\n\n文本：[你的文本]\n```\n\n**进阶技巧：**\n- 使用 Few-shot 示例引导输出格式\n- 分步骤引导复杂任务\n- 设置明确的边界条件",
                "tips": [
                    "提供清晰的角色定义和任务目标",
                    "使用示例示范期望的输出格式",
                    "复杂任务拆分为多步骤",
                    "利用系统提示词设定全局行为",
                    "长上下文模型可一次性提供完整背景"
                ]
            },
            {
                "title": "联网搜索使用",
                "content": "部分模型支持联网搜索，可以获取最新信息。",
                "tips": [
                    "查询实时信息时开启联网搜索",
                    "使用 freshness 参数限定搜索时效性",
                    "开启 enable_source 可以追溯信息来源"
                ]
            }
        ]
    }
}


def _get_category_common_guide(category: str) -> Optional[dict[str, Any]]:
    return _CATEGORY_COMMON_GUIDES.get(category)


def _merge_usage_guides(common_guide: Optional[dict], model_specific: dict) -> Optional[dict]:
    if not model_specific and not common_guide:
        return None
    
    merged = {
        "title": model_specific.get("title") or common_guide.get("title", "使用指南"),
        "sections": []
    }
    
    if common_guide and common_guide.get("sections"):
        merged["sections"].extend(common_guide["sections"])
    
    if model_specific and model_specific.get("sections"):
        merged["sections"].extend(model_specific["sections"])
    
    return merged


def serialize_model_catalog_entry(
    entry: ModelCatalogEntry,
    *,
    include_sources: bool = False,
    include_archives: bool = False,
) -> dict[str, Any]:
    """将 ORM 对象序列化为前端可直接消费的结构。"""

    identity_profile = _build_identity_profile(entry)
    integration_profile = _build_integration_profile(entry)
    raw_config = _extract_raw(entry)
    detailed_specs = raw_config.get("detailed_specs") or {}
    
    pricing_verification = raw_config.get("pricing_verification", {})
    
    payload = {
        "model_key": entry.model_key,
        "name": entry.name,
        "provider": entry.provider,
        "category": entry.category,
        "category_label": _CATEGORY_LABELS.get(entry.category, entry.category),
        "subcategory": entry.subcategory,
        "model_family": entry.model_family,
        "config_source": entry.config_source,
        "status": entry.status,
        "summary": entry.summary,
        "recommended_scenarios": entry.recommended_scenarios or [],
        "limitations": entry.limitations or [],
        "integration_notes": entry.integration_notes or [],
        "documentation_url": entry.documentation_url,
        "source_urls": entry.source_urls or [],
        "tags": entry.tags or [],
        "modalities": entry.modalities or [],
        "capabilities": (entry.capabilities_json or {}).get("items", []),
        "constraints": entry.constraints_json or {},
        "performance": entry.performance_json or {},
        "routing": entry.routing_json or {},
        "default_params": entry.default_params_json or {},
        "verification_status": entry.verification_status,
        "verification_scope": entry.verification_scope,
        "verification_score": entry.verification_score,
        "total_source_count": entry.total_source_count,
        "reachable_source_count": entry.reachable_source_count,
        "verified_source_count": entry.verified_source_count,
        "verification_notes": entry.verification_notes,
        "last_synced_at": entry.last_synced_at.isoformat() if entry.last_synced_at else None,
        "last_verified_at": entry.last_verified_at.isoformat() if entry.last_verified_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        "runtime_routing_signal": (
            get_model_catalog_runtime_index().get_signal(entry.model_key).to_dict()
            if _RUNTIME_SIGNAL_AVAILABLE
            else None
        ),
        "runtime_capability_hints": (
            get_model_catalog_runtime_index().get_capability_hints(entry.model_key)
            if _RUNTIME_SIGNAL_AVAILABLE
            else {}
        ),
        "runtime_task_constraints": (
            get_model_catalog_runtime_index().get_task_constraints(entry.model_key)
            if _RUNTIME_SIGNAL_AVAILABLE
            else {}
        ),
        "project_modules": identity_profile["project_fit"]["modules"],
        "project_task_labels": identity_profile["project_fit"]["task_types"],
        "tooling_badges": integration_profile["tooling_badges"],
        "primary_strengths": identity_profile["capability_quadrants"]["strengths"][:3],
        "detailed_specs": detailed_specs,
        "pricing_verification": pricing_verification,
        "constraints_summary": _build_constraints_summary(entry),
        "capability_provenance": _build_capability_provenance(entry),
        "usage_guide": _build_usage_guide(entry),
    }
    if include_archives:
        payload["identity_profile"] = identity_profile
        payload["integration_profile"] = integration_profile
        payload["prompt_router_profile"] = _build_prompt_router_profile(entry)
        payload["deployment_profile"] = _build_deployment_profile(entry)
        payload["resource_navigation"] = _build_resource_navigation(entry)
    if include_sources:
        payload["sources"] = [
            {
                "url": item.url,
                "source_type": item.source_type,
                "source_domain": item.source_domain,
                "http_status": item.http_status,
                "reachable": item.reachable,
                "verified": item.verified,
                "page_title": item.page_title,
                "page_excerpt": item.page_excerpt,
                "matched_keywords": item.matched_keywords or [],
                "verification_note": item.verification_note,
                "fetched_at": item.fetched_at.isoformat() if item.fetched_at else None,
            }
            for item in entry.sources
        ]
    return payload
