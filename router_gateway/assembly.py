# -*- coding: utf-8 -*-
"""g5 组合根：从环境变量/凭证文件装配适配器、目录、仓储与编排器。

配置契约（见 docs 路由指南 §12.3 与 .env.example）：
- 供应商 token：ROUTER_GATEWAY_{VENDOR}_TOKEN，
  缺省回退 %LOCALAPPDATA%/Temp/{vendor}_token.txt（与云验收脚本同一约定）；
- 数据库：ROUTER_GATEWAY_DATABASE_URL；
- 决策模型（可选）：ROUTER_GATEWAY_DECISION_BASE_URL + DASHSCOPE_API_KEY，
  两者齐全才构造，同一客户端同时注入意图分类与风险评分两个 Port；
- 阈值：ROUTER_GATEWAY_INTENT_CONFIDENCE（默认 0.6）、
  ROUTER_GATEWAY_CONTENT_RISK_THRESHOLD（默认 0.9）。

只有拿到凭证的供应商才会被装配，目录中其余供应商的路线同步剔除——
网关绝不承诺一条调用时会因缺适配器而报错的路线。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .adapters.autodl import AutoDLAdapter
from .adapters.erchun import ErchunAdapter
from .adapters.grsai import GrsaiAdapter
from .adapters.lingke import LingkeAnmiaoAdapter, LingkeMediaAdapter
from .adapters.sanbao import SanbaoAdapter
from .adapters.suanliai import SuanliaiAdapter
from .adapters.zhiqi import ZhiqiAdapter
from .assets import (
    ProviderAssetRegistrar,
    ProviderEndpoint,
    UrllibAssetHttpClient,
)
from .assets.delivery import build_deliverer
from .assets.oss_client import OssConfig
from .catalog import load_catalog
from .db import DEFAULT_DATABASE_URL, JobRepository, get_engine, make_session_factory
from .decision import DecisionModelClient
from .orchestrator.service import Orchestrator
from .quota import RedisTokenBucket

# 供应商 →（适配器类, 实测 base_url 常量）
PROVIDERS = {
    "erchun": (ErchunAdapter, "https://api.erchun.youkou.cc"),
    "autodl": (AutoDLAdapter, "https://autodl.art"),
    "suanliai": (SuanliaiAdapter, "https://suanliai.top"),
    "grsai": (GrsaiAdapter, "https://grsaiapi.com"),
    "sanbao": (SanbaoAdapter, "https://sanbaobeauty.com"),
    # 灵客（聚合引擎AIGC）：线路由密钥决定，DMC/MT 走 media 协议、
    # SD2.5 按秒 MC-S 走火山 anmiao 协议；凭证 lingke_{dmc,mt,sd}_token.txt
    "lingke_dmc": (LingkeMediaAdapter, "https://api.lk888.ai"),
    "lingke_mt": (LingkeMediaAdapter, "https://api.lk888.ai"),
    "lingke_sd": (LingkeAnmiaoAdapter, "https://api.lk888.ai"),
    "zhiqi": (ZhiqiAdapter, "https://zhiqiapi.com"),
}

# 需要供应商侧素材登记的供应商（public_url 直传的 autodl/grsai 不在此列）
_ASSET_UPLOAD_VENDORS = ("erchun", "suanliai", "sanbao")


@dataclass(frozen=True)
class Gateway:
    orchestrator: Orchestrator
    repo: JobRepository
    engine: object
    routes: list
    adapters: dict
    decision: Optional[DecisionModelClient]
    asset_registrar: Optional[ProviderAssetRegistrar]
    deliverer: Optional[object]
    rate_limiter: Optional[object]


def resolve_vendor_token(vendor: str, *, env=None,
                         localappdata: Optional[str] = None) -> Optional[str]:
    env = os.environ if env is None else env
    env_value = (env.get(f"ROUTER_GATEWAY_{vendor.upper()}_TOKEN") or "").strip()
    if env_value:
        return env_value
    base = localappdata if localappdata is not None else env.get("LOCALAPPDATA")
    if base:
        path = Path(base) / "Temp" / f"{vendor}_token.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def _build_adapters(env, localappdata) -> dict:
    adapters = {}
    for vendor, (cls, base_url) in PROVIDERS.items():
        token = resolve_vendor_token(vendor, env=env, localappdata=localappdata)
        if token:
            adapters[vendor] = cls(base_url=base_url, api_key=token)
    return adapters


def _build_asset_registrar(adapters: dict) -> Optional[ProviderAssetRegistrar]:
    """为需要供应商侧素材登记的供应商构造端点（复用已装配适配器的凭证）。"""
    endpoints = {}
    for vendor in _ASSET_UPLOAD_VENDORS:
        adapter = adapters.get(vendor)
        if adapter is None:
            continue
        endpoints[vendor] = ProviderEndpoint(
            provider=vendor, base_url=PROVIDERS[vendor][1],
            api_key=adapter.api_key)
    if not endpoints:
        return None
    return ProviderAssetRegistrar(
        endpoints=endpoints, http=UrllibAssetHttpClient())


def _build_deliverer(env) -> Optional[object]:
    """OSS 配置齐全才装配成片转存器；缺配置时为 None（维持上游直链交付）。"""
    try:
        config = OssConfig.from_env(env)
    except RuntimeError:
        return None
    return build_deliverer(config)


def _build_decision(env) -> Optional[DecisionModelClient]:
    base_url = (env.get("ROUTER_GATEWAY_DECISION_BASE_URL") or "").strip()
    api_key = (env.get("DASHSCOPE_API_KEY") or "").strip()
    if not base_url or not api_key:
        return None
    return DecisionModelClient(base_url=base_url, api_key=api_key)


def _as_float(env, key: str, default: float) -> float:
    raw = env.get(key)
    return float(raw) if raw else default


def _as_bool(env, key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{key} must be a boolean")


def build_gateway(*, env=None, localappdata: Optional[str] = None,
                  catalog_path: Optional[Path] = None) -> Gateway:
    env = os.environ if env is None else env
    app_env = (env.get("APP_ENV") or "development").strip().lower()
    redis_url = (env.get("ROUTER_GATEWAY_REDIS_URL") or "").strip()
    if app_env in {"production", "staging"} and not redis_url:
        raise RuntimeError("production/staging requires ROUTER_GATEWAY_REDIS_URL")
    adapters = _build_adapters(env, localappdata)

    all_routes = load_catalog(catalog_path)
    routes = [r for r in all_routes if r.provider in adapters]

    engine = get_engine(env.get("ROUTER_GATEWAY_DATABASE_URL")
                        or DEFAULT_DATABASE_URL)
    repo = JobRepository(make_session_factory(engine))

    rate_limiter = RedisTokenBucket.from_url(redis_url) if redis_url else None

    decision = _build_decision(env)
    asset_registrar = _build_asset_registrar(adapters)
    deliverer = _build_deliverer(env)
    if app_env in {"production", "staging"} and deliverer is None:
        # 无转存器时成片会以上游原始 URL 直透交付，暴露渠道供应商；
        # 生产/预发必须配齐 ROUTER_GATEWAY_OSS_*，拒绝带病启动
        raise RuntimeError(
            "production/staging requires ROUTER_GATEWAY_OSS_* "
            "(content re-host OSS) to avoid leaking upstream providers")
    if deliverer is not None and not shutil.which("ffmpeg"):
        # 转存前用 ffmpeg 流复制剥离 mp4 厂商元数据；缺工具会 fail-closed
        # 导致成片永远无法交付，故在装配期直接拒绝启动
        raise RuntimeError(
            "ffmpeg binary is required for content metadata sanitization")
    if deliverer is not None and not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe binary is required for content structure validation")
    orchestrator = Orchestrator(
        repo=repo, routes=routes, adapters=adapters,
        intent_classifier=decision,
        intent_confidence_threshold=_as_float(env, "ROUTER_GATEWAY_INTENT_CONFIDENCE", 0.6),
        content_risk_scorer=decision,
        content_risk_threshold=_as_float(env, "ROUTER_GATEWAY_CONTENT_RISK_THRESHOLD", 0.9),
        content_risk_fail_closed=_as_bool(
            env, "ROUTER_GATEWAY_CONTENT_RISK_FAIL_CLOSED", app_env in {"production", "staging"}),
        max_attempts=int(env.get("ROUTER_GATEWAY_MAX_ATTEMPTS", "3")),
        asset_registrar=asset_registrar,
        deliverer=deliverer)

    return Gateway(orchestrator=orchestrator, repo=repo, engine=engine,
                   routes=routes, adapters=adapters, decision=decision,
                   asset_registrar=asset_registrar, deliverer=deliverer,
                   rate_limiter=rate_limiter)
