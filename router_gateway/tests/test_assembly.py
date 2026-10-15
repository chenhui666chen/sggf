# -*- coding: utf-8 -*-
"""g5 装配工厂单测：env/凭证文件 → 适配器 + 目录 + Orchestrator。不触网、不连库。"""
import os

import pytest

from router_gateway.assembly import (
    Gateway,
    build_gateway,
    resolve_vendor_token,
)
from router_gateway.decision import DecisionModelClient

_ENV_KEYS = [
    "ROUTER_GATEWAY_ERCHUN_TOKEN", "ROUTER_GATEWAY_AUTODL_TOKEN",
    "ROUTER_GATEWAY_SUANLIAI_TOKEN", "ROUTER_GATEWAY_GRSAI_TOKEN",
    "ROUTER_GATEWAY_SANBAO_TOKEN",
    "ROUTER_GATEWAY_DECISION_BASE_URL", "DASHSCOPE_API_KEY",
    "ROUTER_GATEWAY_INTENT_CONFIDENCE", "ROUTER_GATEWAY_CONTENT_RISK_THRESHOLD",
    "APP_ENV", "ROUTER_GATEWAY_REDIS_URL",
    "ROUTER_GATEWAY_OSS_BUCKET", "ROUTER_GATEWAY_OSS_ENDPOINT",
    "ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET",
    "ROUTER_GATEWAY_OSS_PUBLIC_HOST",
    "AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT",
    "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID",
    "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET",
    "AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST",
]


@pytest.fixture()
def env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def _write_token(tmp_path, vendor, token):
    temp = tmp_path / "Temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / f"{vendor}_token.txt").write_text(token, encoding="utf-8")


def test_token读取环境变量优先于凭证文件(env, tmp_path):
    env.setenv("ROUTER_GATEWAY_ERCHUN_TOKEN", "env-token")
    _write_token(tmp_path, "erchun", "file-token")
    assert resolve_vendor_token("erchun", localappdata=str(tmp_path)) == "env-token"


def test_token缺环境变量时回退凭证文件(env, tmp_path):
    _write_token(tmp_path, "grsai", "file-token")
    assert resolve_vendor_token("grsai", localappdata=str(tmp_path)) == "file-token"


def test_token都没有时返回None(env, tmp_path):
    assert resolve_vendor_token("autodl", localappdata=str(tmp_path)) is None


def test_仅贰春有凭证时只装贰春适配器并过滤路线(env, tmp_path):
    env.setenv("ROUTER_GATEWAY_ERCHUN_TOKEN", "tok")
    gateway = build_gateway(localappdata=str(tmp_path))
    assert isinstance(gateway, Gateway)
    assert set(gateway.adapters) == {"erchun"}
    assert gateway.routes
    assert all(r.provider == "erchun" for r in gateway.routes)
    assert gateway.decision is None
    gateway.engine.dispose()


def test_无任何凭证时不装适配器且路线为空但不报错(env, tmp_path):
    gateway = build_gateway(localappdata=str(tmp_path))
    assert gateway.adapters == {} and gateway.routes == []
    assert gateway.asset_registrar is None
    gateway.engine.dispose()


def test_生产环境缺OSS成片转存配置时拒绝启动(env, tmp_path):
    env.setenv("APP_ENV", "production")
    env.setenv("ROUTER_GATEWAY_REDIS_URL", "redis://localhost:6379/0")
    with pytest.raises(RuntimeError, match="OSS"):
        build_gateway(localappdata=str(tmp_path))


def test_生产环境OSS四项齐全时装配成片转存器(env, tmp_path, monkeypatch):
    env.setenv("APP_ENV", "production")
    env.setenv("ROUTER_GATEWAY_REDIS_URL", "redis://localhost:6379/0")
    env.setenv("ROUTER_GATEWAY_OSS_BUCKET", "sggf-router-video")
    env.setenv("ROUTER_GATEWAY_OSS_ENDPOINT",
               "oss-cn-shanghai.aliyuncs.com")
    env.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ak")
    env.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setattr(
        "router_gateway.assembly.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None)
    gateway = build_gateway(localappdata=str(tmp_path))
    assert gateway.deliverer is not None
    gateway.engine.dispose()


def test_生产环境缺少ffmpeg元数据剥离工具时拒绝启动(env, tmp_path, monkeypatch):
    env.setenv("APP_ENV", "production")
    env.setenv("ROUTER_GATEWAY_REDIS_URL", "redis://localhost:6379/0")
    env.setenv("ROUTER_GATEWAY_OSS_BUCKET", "sggf-router-video")
    env.setenv("ROUTER_GATEWAY_OSS_ENDPOINT",
               "oss-cn-shanghai.aliyuncs.com")
    env.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ak")
    env.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setattr("router_gateway.assembly.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        build_gateway(localappdata=str(tmp_path))


def test_需要登记素材的供应商有凭证时装配登记器且公网直传商不入端点(env, tmp_path):
    env.setenv("ROUTER_GATEWAY_ERCHUN_TOKEN", "tok-e")
    env.setenv("ROUTER_GATEWAY_SANBAO_TOKEN", "tok-b")
    env.setenv("ROUTER_GATEWAY_GRSAI_TOKEN", "tok-g")  # public_url，无需登记端点
    gateway = build_gateway(localappdata=str(tmp_path))
    registrar = gateway.asset_registrar
    assert registrar is not None
    endpoints = registrar._endpoints
    assert set(endpoints) == {"erchun", "sanbao"}
    assert endpoints["erchun"].api_key == "tok-e"
    assert endpoints["sanbao"].base_url == "https://sanbaobeauty.com"
    assert gateway.orchestrator._asset_registrar is registrar
    gateway.engine.dispose()


def test_决策模型配置齐全时注入为两个Port且阈值可读(env, tmp_path):
    env.setenv("ROUTER_GATEWAY_ERCHUN_TOKEN", "tok")
    env.setenv("ROUTER_GATEWAY_DECISION_BASE_URL",
               "https://ws.cn-beijing.maas.aliyuncs.com/compatible-mode")
    env.setenv("DASHSCOPE_API_KEY", "sk-x")
    env.setenv("ROUTER_GATEWAY_CONTENT_RISK_THRESHOLD", "0.8")
    gateway = build_gateway(localappdata=str(tmp_path))
    assert isinstance(gateway.decision, DecisionModelClient)
    orch = gateway.orchestrator
    assert orch._intent_classifier is gateway.decision
    assert orch._content_risk_scorer is gateway.decision
    assert orch._content_risk_threshold == 0.8
    gateway.engine.dispose()


def test_OSS配置齐全时装配成片转存器且自有域名含桶域与公共域(env, tmp_path):
    from router_gateway.assets.delivery import FileContentDeliverer

    env.setenv("ROUTER_GATEWAY_OSS_BUCKET", "sggf-router-video")
    env.setenv("ROUTER_GATEWAY_OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
    env.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ak")
    env.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET", "sk")
    env.setenv("ROUTER_GATEWAY_OSS_PUBLIC_HOST", "https://video.sggf.net")
    gateway = build_gateway(localappdata=str(tmp_path))

    assert isinstance(gateway.deliverer, FileContentDeliverer)
    assert gateway.orchestrator._deliverer is gateway.deliverer
    assert gateway.deliverer._own_hosts == (
        "sggf-router-video.oss-cn-shanghai.aliyuncs.com", "video.sggf.net")
    gateway.engine.dispose()


def test_OSS配置缺失时不装配转存器维持上游直链交付(env, tmp_path):
    gateway = build_gateway(localappdata=str(tmp_path))
    assert gateway.deliverer is None
    assert gateway.orchestrator._deliverer is None
    gateway.engine.dispose()
