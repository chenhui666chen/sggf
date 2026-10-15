# -*- coding: utf-8 -*-
"""真实 OSS 端到端验收（默认 skip）。

开启方式（PowerShell）：
  $env:ROUTER_GATEWAY_RUN_OSS_INTEGRATION="1"; python -m pytest router_gateway/tests/test_assets_oss_integration.py -q

验证事实（2026-10-12 探针结论）：shared/audio_library/ 前缀策略公共读；
生产 OssClient 签名 PUT 成功后，第三方匿名 GET 必须 200，release 后 404。
"""
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from router_gateway.assets.asset_store import AssetStore
from router_gateway.assets.oss_client import OssClient, OssConfig


pytestmark = pytest.mark.integration

_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8ffff3f0005fe02fea79d1b0b0000000049454e44ae426082"
)


def _load_backend_env():
    env_path = Path(__file__).resolve().parents[2] / "backend" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _anon_get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture(scope="module")
def client():
    if os.getenv("ROUTER_GATEWAY_RUN_OSS_INTEGRATION") != "1":
        pytest.skip("未设置 ROUTER_GATEWAY_RUN_OSS_INTEGRATION=1")
    _load_backend_env()
    try:
        return OssClient(OssConfig.from_env())
    except RuntimeError as exc:
        pytest.skip(f"OSS 配置缺失: {exc}")


def test_签名PUT后匿名可读_删除后404(client):
    key = f"shared/audio_library/router_refs/integ_test/probe_{int(time.time())}.png"
    try:
        url = client.put_bytes(key, _PNG_1X1, "image/png")
        status, body = _anon_get(url)
        assert status == 200
        assert body == _PNG_1X1
    finally:
        client.delete(key)
    assert _anon_get(url)[0] == 404


def test_AssetStore端到端_stage后匿名可读_release后404(client, tmp_path):
    p = tmp_path / "ref.png"
    p.write_bytes(_PNG_1X1)
    store = AssetStore(client)

    asset = store.stage_path(p, job_id="integ")
    try:
        assert asset.object_key.startswith("shared/audio_library/router_refs/")
        status, body = _anon_get(asset.public_url)
        assert status == 200 and body == _PNG_1X1
    finally:
        store.release(asset.object_key)
    assert _anon_get(asset.public_url)[0] == 404
