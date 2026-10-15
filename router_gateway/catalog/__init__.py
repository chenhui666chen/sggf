# -*- coding: utf-8 -*-
"""能力目录：对外能力统一，内部每条路线单独登记硬条件与价格。

设计原则（见 docs/VIDEO_API_SMART_ROUTING_GUIDE.md）：
- 同名模型即使支持时长/参考元素不同，也可以共用一个对外接口；
- 每次请求只从“同时满足本次全部硬条件”的路线中选择和切换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

from ..pricing import PerSecond, PerUse


class Mode(str, Enum):
    """对外归一化的六类输入模式（彼此不可互换，见 docs 路由指南）。"""

    TEXT = "text"                                  # 纯文生
    FIRST_LAST_FRAME = "first_last_frame"          # 首尾帧强约束（恰好 2 图）
    MULTI_IMAGE = "multi_image"                    # 1-N 张参考图
    VIDEO_REFERENCE = "video_reference"            # 参考视频（无音频）
    IMAGE_AUDIO_LIPSYNC = "image_audio_lipsync"    # 单图 + 单音频对口型
    MIXED_MULTIMODAL = "mixed_multimodal"          # 图/视/音任意混合的叙事多参


# 素材接入方式：外链直传 / 供应商原生上传换本站引用 / 先 review 转存再提交
ASSET_ACCESS_MODES = ("public_url", "provider_upload", "review_then_ref")


@dataclass(frozen=True)
class DurationRange:
    min_seconds: int
    max_seconds: int

    def accepts(self, seconds: int) -> bool:
        return self.min_seconds <= seconds <= self.max_seconds


@dataclass(frozen=True)
class RouteCapability:
    billing: str  # per_second / per_use
    duration: DurationRange
    resolutions: tuple[str, ...]
    aspect_ratios: tuple[str, ...]
    input_modes: frozenset[Mode]
    max_images: int = 0
    max_videos: int = 0
    max_audios: int = 0
    asset_access: str = "public_url"   # 素材接入方式，取值见 ASSET_ACCESS_MODES
    max_total_assets: int = 0          # 素材总数硬上限（图+视+音），0=不限
    duration_field: Optional[str] = None  # 提交时长字段名（duration/seconds），None=适配器启发式


@dataclass(frozen=True)
class Route:
    route_id: str
    provider: str            # erchun / autodl / suanliai / volcengine
    upstream_model: str      # 供应商侧模型或工作流标识
    quality_group: str       # 质量可替代组，同组且抽检合格才允许互相切换
    capability: RouteCapability
    pricing: object          # dict[str,str]（按秒分分辨率）或 str（按条金额）
    enabled: bool = True
    standby: bool = False    # 兜底路线：排序沉到正常路线之后，但仍保留在故障切换链中
    supports_cancel: bool = False   # 是否支持排队期取消并退款（本批仅声明）
    supports_balance: bool = False  # 是否提供余额查询接口（本批仅声明）
    note: str = ""

    def price_plan(self):
        if self.capability.billing == "per_second":
            return PerSecond(self.pricing)
        return PerUse(self.pricing)


@dataclass
class VideoSpec:
    """一次视频生成请求的硬条件（对外接口入参归一化后）。

    mode 为意图仲裁后的确定模式（见 catalog.intent.resolve_mode），
    候选过滤直接按它执行，不再在决策层猜测用户意图。
    """
    prompt: str
    duration_seconds: int
    resolution: str
    aspect_ratio: str
    mode: Mode = Mode.TEXT
    quality_group: Optional[str] = None   # 对外模型接口（model），指定时只允许同组路线
    reference_images: int = 0
    reference_videos: int = 0
    reference_audios: int = 0


def _parse_route(raw: dict) -> Route:
    asset_access = raw.get("asset_access", "public_url")
    if asset_access not in ASSET_ACCESS_MODES:
        raise ValueError(
            f"路线 {raw.get('route_id')} 的 asset_access 非法: {asset_access}，"
            f"允许值: {ASSET_ACCESS_MODES}")
    duration_field = raw.get("duration_field")
    if duration_field is not None and duration_field not in ("duration", "seconds"):
        raise ValueError(
            f"路线 {raw.get('route_id')} 的 duration_field 非法: {duration_field}，"
            f"允许值: duration / seconds")
    cap = RouteCapability(
        billing=raw["billing"],
        duration=DurationRange(**raw["duration"]),
        resolutions=tuple(r.lower() for r in raw["resolutions"]),
        aspect_ratios=tuple(raw["aspect_ratios"]),
        input_modes=frozenset(Mode(m) for m in raw.get("input_modes", ["text"])),
        max_images=int(raw.get("max_images", 0)),
        max_videos=int(raw.get("max_videos", 0)),
        max_audios=int(raw.get("max_audios", 0)),
        asset_access=asset_access,
        max_total_assets=int(raw.get("max_total_assets", 0)),
        duration_field=raw.get("duration_field"),
    )
    return Route(
        route_id=raw["route_id"],
        provider=raw["provider"],
        upstream_model=raw["upstream_model"],
        quality_group=raw["quality_group"],
        capability=cap,
        pricing=raw["pricing"],
        enabled=raw.get("enabled", True),
        standby=bool(raw.get("standby", False)),
        supports_cancel=bool(raw.get("supports_cancel", False)),
        supports_balance=bool(raw.get("supports_balance", False)),
        note=raw.get("note", ""),
    )


def load_catalog(path: Optional[Path] = None) -> list[Route]:
    path = path or Path(__file__).resolve().parent / "routes.yaml"
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [_parse_route(item) for item in data["routes"]]
