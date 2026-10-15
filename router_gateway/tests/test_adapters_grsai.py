# -*- coding: utf-8 -*-
"""Grsai 适配器契约测试，响应形态取自实测档案 gr_results.json（2026-10-11）。

实测契约：
- 提交 POST {base}/v1/api/generate，Bearer 鉴权，无幂等键。
  body: {"model": "minimax-h3", "prompt", "aspectRatio": landscape|portrait,
          "resolution": 480p|768p|1080p, "duration": int, "replyType": "async"}
- 轮询 GET {base}/v1/api/result?id={task_id}，裸对象：
  {"id", "status": running|succeeded|failed|violation, "results": [{"url"}], "progress"}
  成片为 file*.aitohumanize.com 永久地址；任务结果平台只保留约 2 小时（查询窗口内 404 按可重试异常）。
- 1080p 路线上游最多 10 秒（由目录硬条件约束）。
"""
import pytest

from router_gateway.adapters.base import AdapterError, AssetRef, SubmitRequest
from router_gateway.adapters.grsai import GrsaiAdapter


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        code, payload = self.responses.pop(0)
        return code, payload


def _req(resolution="480p", aspect_ratio="16:9", duration=5):
    return SubmitRequest(model="minimax-h3", prompt="雨夜霓虹街道", duration_seconds=duration,
                         resolution=resolution, aspect_ratio=aspect_ratio,
                         idempotency_key="idem-g")


def test_提交横屏异步任务请求体与裸对象响应():
    t = FakeTransport([(200, {"id": "11-uuid-x", "status": "running", "progress": 0})])
    a = GrsaiAdapter("https://grsaiapi.com", "tok", transport=t)
    r = a.submit(_req())
    assert r.upstream_task_id == "11-uuid-x"
    assert r.phase == "running"
    call = t.calls[0]
    assert call["url"].endswith("/v1/api/generate")
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["body"] == {
        "model": "minimax-h3", "prompt": "雨夜霓虹街道",
        "aspectRatio": "landscape", "resolution": "480p",
        "duration": 5, "replyType": "async"}


def test_提交竖屏与1080p字段():
    t = FakeTransport([(200, {"id": "6-u", "status": "running"})])
    a = GrsaiAdapter("https://x", "tok", transport=t)
    a.submit(_req(resolution="1080p", aspect_ratio="9:16", duration=10))
    assert t.calls[0]["body"]["aspectRatio"] == "portrait"
    assert t.calls[0]["body"]["resolution"] == "1080p"
    assert t.calls[0]["body"]["duration"] == 10


def test_提交响应为实测裸对象形态():
    # 2026-10-12 真实云验收固定：提交响应即裸对象，无 data 包裹
    t = FakeTransport([(200, {"id": "14-uuid", "status": "running"})])
    a = GrsaiAdapter("https://x", "tok", transport=t)
    r = a.submit(_req())
    assert r.upstream_task_id == "14-uuid"
    assert r.phase == "running"


def test_非裸对象响应按提交失败处理():
    # 平台契约固定为裸对象；包裹形态视为异常响应而非猜测解析
    t = FakeTransport([(200, {"code": 0, "data": {"id": "1-uuid", "status": "running"}})])
    a = GrsaiAdapter("https://x", "tok", transport=t)
    with pytest.raises(AdapterError):
        a.submit(_req())


def test_grsai不支持1比1比例_提交前拦截():
    a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([]))
    with pytest.raises(AdapterError) as ei:
        a.submit(_req(aspect_ratio="1:1"))
    assert ei.value.retriable is False


def test_提交402积分不足永久失败():
    t = FakeTransport([(402, {"error": "insufficient points"})])
    a = GrsaiAdapter("https://x", "tok", transport=t)
    with pytest.raises(AdapterError) as ei:
        a.submit(_req())
    assert ei.value.retriable is False


def test_适配器无幂等能力():
    assert GrsaiAdapter("https://x", "tok", transport=FakeTransport([])).supports_idempotent_submit is False


def test_轮询成功提取永久成片地址():
    payload = {"id": "11-uuid-x", "status": "succeeded", "progress": 100,
               "results": [{"url": "https://file1.aitohumanize.com/file/abc.mp4"}]}
    t = FakeTransport([(200, payload)])
    a = GrsaiAdapter("https://x", "tok", transport=t)
    r = a.poll("11-uuid-x")
    assert r.phase == "succeeded"
    assert r.content_url == "https://file1.aitohumanize.com/file/abc.mp4"
    assert t.calls[0]["url"].endswith("/v1/api/result?id=11-uuid-x")


def test_轮询活动态():
    for raw, phase in [("running", "running"), ("queued", "running"),
                       ("pending", "running"), ("processing", "running")]:
        a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([
            (200, {"id": "t", "status": raw, "results": []})]))
        assert a.poll("t").phase == phase, raw


def test_轮询失败与内容违规():
    for raw in ("failed", "violation"):
        a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([
            (200, {"id": "t", "status": raw, "results": [], "error": "x"})]))
        assert a.poll("t").phase == "failed", raw


def test_轮询成功但results为空按失败处理():
    a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([
        (200, {"id": "t", "status": "succeeded", "results": []})]))
    assert a.poll("t").phase == "failed"


def test_查询窗口内404按可重试异常等待下一拍():
    a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([
        (404, {"error": "result not exist, valid for 2 hours"})]))
    with pytest.raises(AdapterError) as ei:
        a.poll("t")
    assert ei.value.retriable is True


def test_提交单张参考图_请求体透传image公网地址():
    # W8：minimax-h3 i2v 契约（待付费实证）——单张参考图放 image 字段，公网 URL 直传
    img = AssetRef(kind="image",
                   ref="https://video.sggf.net/probe/w8_ref.jpg",
                   ref_type="public_url")
    req = SubmitRequest(model="minimax-h3", prompt="紫底W7纸牌轻微推近",
                        duration_seconds=5, resolution="480p",
                        aspect_ratio="16:9", idempotency_key="idem-g",
                        reference_assets=(img,))
    t = FakeTransport([(200, {"id": "21-uuid", "status": "running"})])
    a = GrsaiAdapter("https://x", "tok", transport=t)
    a.submit(req)
    body = t.calls[0]["body"]
    assert body["image"] == "https://video.sggf.net/probe/w8_ref.jpg"


def test_非public_url图片引用_提交前拦截():
    img = AssetRef(kind="image", ref="med_xxx", ref_type="media_id")
    req = SubmitRequest(model="minimax-h3", prompt="x", duration_seconds=5,
                        resolution="480p", aspect_ratio="16:9",
                        idempotency_key="idem-g", reference_assets=(img,))
    a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([]))
    with pytest.raises(AdapterError) as ei:
        a.submit(req)
    assert ei.value.retriable is False


def test_多张参考图_未实证提交前拦截():
    imgs = tuple(AssetRef(kind="image", ref=f"https://x/{i}.jpg",
                          ref_type="public_url") for i in range(2))
    req = SubmitRequest(model="minimax-h3", prompt="x", duration_seconds=5,
                        resolution="480p", aspect_ratio="16:9",
                        idempotency_key="idem-g", reference_assets=imgs)
    a = GrsaiAdapter("https://x", "tok", transport=FakeTransport([]))
    with pytest.raises(AdapterError) as ei:
        a.submit(req)
    assert ei.value.retriable is False


def test_国内站基址可配置():
    t = FakeTransport([(200, {"id": "t", "status": "running"})])
    a = GrsaiAdapter("https://grsai.dakka.com.cn", "tok", transport=t)
    a.submit(_req())
    assert t.calls[0]["url"] == "https://grsai.dakka.com.cn/v1/api/generate"
