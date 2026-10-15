# -*- coding: utf-8 -*-
"""OSS V1 客户端契约测试：签名固化向量 + 注入传输，不发真实网络请求。"""
import pytest

from router_gateway.assets.oss_client import OssClient, OssConfig, OssError, build_authorization


FIXED_DATE = "Mon, 12 Oct 2026 10:00:00 GMT"
KEY = "shared/audio_library/router_refs/2026-10-12/job-1/abc123def456.png"


class FakeTransport:
    def __init__(self, responses):
        # responses: list of (status, headers, body_bytes)
        self.responses = responses
        self.calls = []

    def send(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url,
                           "headers": dict(headers or {}), "body": body})
        return self.responses.pop(0)


def _cfg(**over):
    base = dict(bucket="sggf-audio-library", endpoint="oss-cn-shanghai.aliyuncs.com",
                access_key_id="AKID", access_key_secret="test-secret",
                public_host="https://audio.sggf.net")
    base.update(over)
    return OssConfig(**base)


def test_PUT签名固化向量():
    auth = build_authorization(method="PUT", bucket="sggf-audio-library", object_key=KEY,
                               content_type="image/png", date_header=FIXED_DATE,
                               access_key_id="AKID", access_key_secret="test-secret")
    assert auth == "OSS AKID:AJcdv8aFnf2Mb+C6O0dTt91b55c="


def test_STS安全令牌头必须参与签名():
    auth = build_authorization(
        method="DELETE", bucket="sggf-audio-library", object_key="k",
        content_type="", date_header=FIXED_DATE,
        access_key_id="AKID", access_key_secret="test-secret",
        oss_headers={"x-oss-security-token": "tok-123"})
    assert auth == "OSS AKID:eSM/51w8A85Vm4aL9tI/di3WZIQ="


def test_公网URL优先走自定义域名并对空格编码():
    c = _cfg()
    url = c.public_url("shared/audio_library/router_refs/2026-10-12/j/a b.png")
    assert url == "https://audio.sggf.net/shared/audio_library/router_refs/2026-10-12/j/a%20b.png"


def test_未配置自定义域名时回退OSS默认域名():
    c = _cfg(public_host="")
    assert c.public_url("k.png").startswith(
        "https://sggf-audio-library.oss-cn-shanghai.aliyuncs.com/k.png")


def test_put_bytes发送带签名的PUT并返回公网URL():
    t = FakeTransport([(200, {}, b"")])
    client = OssClient(_cfg(), transport=t)
    url = client.put_bytes(KEY, b"\x89PNG", "image/png")

    call = t.calls[0]
    assert call["method"] == "PUT"
    assert call["url"].startswith(
        "https://sggf-audio-library.oss-cn-shanghai.aliyuncs.com/")
    assert call["headers"]["Authorization"].startswith("OSS AKID:")
    assert call["headers"]["Content-Type"] == "image/png"
    assert "Date" in call["headers"]
    assert call["body"] == b"\x89PNG"
    assert url == "https://audio.sggf.net/" + KEY


def test_put_bytes携带STS安全令牌头():
    t = FakeTransport([(200, {}, b"")])
    client = OssClient(_cfg(security_token="tok-123"), transport=t)
    client.put_bytes(KEY, b"x", "image/png")
    assert t.calls[0]["headers"]["x-oss-security-token"] == "tok-123"


def test_put_bytes非2xx抛OssError并保留状态码():
    t = FakeTransport([(403, {}, b"<Error>denied</Error>")])
    client = OssClient(_cfg(), transport=t)
    with pytest.raises(OssError) as ei:
        client.put_bytes(KEY, b"x", "image/png")
    assert ei.value.status == 403


def test_head_200解析为存在并取字节数():
    t = FakeTransport([(200, {"content-length": "1234",
                              "content-type": "image/png"}, b"")])
    client = OssClient(_cfg(), transport=t)
    meta = client.head(KEY)
    assert meta["exists"] is True
    assert meta["content_length"] == 1234
    assert t.calls[0]["method"] == "HEAD"


def test_head_404解析为不存在():
    t = FakeTransport([(404, {}, b"")])
    client = OssClient(_cfg(), transport=t)
    assert client.head(KEY)["exists"] is False


def test_head_403抛错():
    t = FakeTransport([(403, {}, b"")])
    client = OssClient(_cfg(), transport=t)
    with pytest.raises(OssError):
        client.head(KEY)


def test_delete_204成功():
    t = FakeTransport([(204, {}, b"")])
    client = OssClient(_cfg(), transport=t)
    client.delete(KEY)
    assert t.calls[0]["method"] == "DELETE"


def test_delete_404静默不抛():
    t = FakeTransport([(404, {}, b"")])
    client = OssClient(_cfg(), transport=t)
    client.delete(KEY)  # 不抛异常即可


def test_delete_403抛错():
    t = FakeTransport([(403, {}, b"")])
    client = OssClient(_cfg(), transport=t)
    with pytest.raises(OssError):
        client.delete(KEY)


def test_from_env网关自有变量优先(monkeypatch):
    for k in ["ROUTER_GATEWAY_OSS_BUCKET", "ROUTER_GATEWAY_OSS_ENDPOINT",
              "ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET",
              "ROUTER_GATEWAY_OSS_PUBLIC_HOST", "ROUTER_GATEWAY_OSS_SECURITY_TOKEN",
              "AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ROUTER_GATEWAY_OSS_BUCKET", "gw-bucket")
    monkeypatch.setenv("ROUTER_GATEWAY_OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
    monkeypatch.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "gw-ak")
    monkeypatch.setenv("ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET", "gw-sk")
    cfg = OssConfig.from_env()
    assert cfg.bucket == "gw-bucket"
    assert cfg.endpoint == "oss-cn-beijing.aliyuncs.com"
    assert cfg.access_key_id == "gw-ak"


def test_from_env回退音频库变量与默认公网域名(monkeypatch):
    gw_vars = ["ROUTER_GATEWAY_OSS_BUCKET", "ROUTER_GATEWAY_OSS_ENDPOINT",
               "ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET",
               "ROUTER_GATEWAY_OSS_PUBLIC_HOST", "ROUTER_GATEWAY_OSS_SECURITY_TOKEN"]
    for k in gw_vars:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "sggf-audio-library")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT",
                       "https://oss-cn-shanghai.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID", "lib-ak")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET", "lib-sk")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net/")

    cfg = OssConfig.from_env()
    assert cfg.bucket == "sggf-audio-library"
    # endpoint 带协议头要归一化掉
    assert cfg.endpoint == "oss-cn-shanghai.aliyuncs.com"
    assert cfg.public_host == "https://audio.sggf.net"


def test_from_env缺必填凭证抛错(monkeypatch):
    for k in ["ROUTER_GATEWAY_OSS_BUCKET", "ROUTER_GATEWAY_OSS_ENDPOINT",
              "ROUTER_GATEWAY_OSS_ACCESS_KEY_ID", "ROUTER_GATEWAY_OSS_ACCESS_KEY_SECRET",
              "AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT",
              "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID",
              "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET"]:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError):
        OssConfig.from_env()
