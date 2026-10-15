# -*- coding: utf-8 -*-
"""三家供应商真实云端到端验收（默认 skip，会产生真实扣费）。

开启方式（PowerShell）：
  $env:ROUTER_GATEWAY_RUN_PROVIDER_INTEGRATION="1"
  python -m pytest router_gateway/tests/test_adapters_provider_integration.py -q -s

成本（高峰价，单任务 5s 480p 横屏）：
  AutoDL z0901 ≈ ¥0.20 / 算力AI 007-sd2.5 ≈ ¥1.60 / Grsai h3 ≈ ¥0.50
Token 读取顺序：环境变量 ROUTER_GATEWAY_{VENDOR}_TOKEN，
其次 %LOCALAPPDATA%/Temp/{vendor}_token.txt（实测留存）。

已验收事实（2026-10-12）：
- AutoDL / Grsai 提交响应形态与适配器一致，成片直链任意 UA 可下载；
- 算力AI 成片 /content 307 跳转到 media.suanliai.cc，该域名经 Cloudflare
  浏览器签名校验（error 1010）：Python-urllib/curl 默认 UA 返回 403，
  浏览器 UA 200。成片可公开分享但下游必须使用浏览器 UA（交付层需知）。
"""
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from router_gateway.adapters.autodl import AutoDLAdapter
from router_gateway.adapters.base import NormalizedResult, SubmitRequest
from router_gateway.adapters.grsai import GrsaiAdapter
from router_gateway.adapters.suanliai import SuanliaiAdapter

pytestmark = pytest.mark.integration

_POLL_TIMEOUT_SECONDS = 600
_POLL_INTERVAL_SECONDS = 8
# 算力AI 存储域名对非浏览器 UA 返回 Cloudflare 1010；统一用浏览器 UA 校验成片
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _token(vendor: str) -> str | None:
    env_value = os.getenv(f"ROUTER_GATEWAY_{vendor.upper()}_TOKEN")
    if env_value:
        return env_value.strip()
    path = Path(os.environ["LOCALAPPDATA"]) / "Temp" / f"{vendor}_token.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def _require(vendor: str):
    if os.getenv("ROUTER_GATEWAY_RUN_PROVIDER_INTEGRATION") != "1":
        pytest.skip("未设置 ROUTER_GATEWAY_RUN_PROVIDER_INTEGRATION=1（真实扣费验收）")
    token = _token(vendor)
    if not token:
        pytest.skip(f"缺少 {vendor} token")
    return token


def _wait_terminal(adapter, upstream_task_id: str) -> NormalizedResult:
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    last_phase = None
    while time.monotonic() < deadline:
        result = adapter.poll(upstream_task_id)
        if result.phase != last_phase:
            print(f"\n  {adapter.provider} {upstream_task_id} -> {result.phase}")
            last_phase = result.phase
        if result.phase in ("succeeded", "failed"):
            return result
        time.sleep(_POLL_INTERVAL_SECONDS)
    pytest.fail(f"{adapter.provider} 轮询超时（{_POLL_TIMEOUT_SECONDS}s）")


def _assert_video_downloadable(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            head = resp.read(32)
    except urllib.error.HTTPError as exc:
        pytest.fail(f"成片链接不可达 HTTP {exc.code}")
    # ISO BMFF 魔数：第 4-8 字节为 ftyp
    assert head[4:8] == b"ftyp", f"产物不是 MP4: {head[:16]!r}"


def test_autodl_提交到成片全链路():
    token = _require("autodl")
    adapter = AutoDLAdapter("https://autodl.art", token)
    req = SubmitRequest(model="minimax_h3_z0901", prompt="雪山日出航拍，电影级画质",
                        duration_seconds=5, resolution="480p", aspect_ratio="16:9",
                        idempotency_key=f"itg-autodl-{int(time.time())}")
    submitted = adapter.submit(req)
    print(f"\n  AutoDL task_id={submitted.upstream_task_id} submit_raw={submitted.raw}")
    result = _wait_terminal(adapter, submitted.upstream_task_id)
    assert result.phase == "succeeded", result.error
    _assert_video_downloadable(result.content_url)


def test_suanliai_提交到成片全链路():
    token = _require("suanliai")
    adapter = SuanliaiAdapter("https://suanliai.top", token)
    req = SubmitRequest(model="007系列/sd2.5(满血全参/480P)",
                        prompt="雪山日出航拍，电影级画质",
                        duration_seconds=5, resolution="480p", aspect_ratio="16:9",
                        idempotency_key=f"itg-sl-{int(time.time())}")
    submitted = adapter.submit(req)
    print(f"\n  算力AI task_id={submitted.upstream_task_id} submit_raw={submitted.raw}")
    result = _wait_terminal(adapter, submitted.upstream_task_id)
    assert result.phase == "succeeded", result.error
    _assert_video_downloadable(result.content_url)
    # 固化交付层事实：默认 urllib UA 必须被 Cloudflare 1010 拒绝
    try:
        urllib.request.urlopen(result.content_url, timeout=60)
        raise AssertionError("算力AI 存储竟允许默认 UA 访问，1010 事实可能已变化")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403, f"预期 403 实际 {exc.code}"


def test_grsai_提交到成片全链路():
    token = _require("grsai")
    adapter = GrsaiAdapter("https://grsaiapi.com", token)
    req = SubmitRequest(model="minimax-h3", prompt="雪山日出航拍，电影级画质",
                        duration_seconds=5, resolution="480p", aspect_ratio="16:9",
                        idempotency_key=f"itg-gr-{int(time.time())}")
    submitted = adapter.submit(req)
    # 重点取证：打印提交响应原始形态，用于验收后精简双兼容解析
    print(f"\n  Grsai task_id={submitted.upstream_task_id} submit_raw={submitted.raw}")
    result = _wait_terminal(adapter, submitted.upstream_task_id)
    assert result.phase == "succeeded", result.error
    _assert_video_downloadable(result.content_url)
