# -*- coding: utf-8 -*-
"""火爱（video.huoai2.cn）适配器测试。

协议（2026-10-15 前端 JS /api/v1 + 付费实证）：
  GET  /api/v1/models
  POST /api/v1/tasks  {model,prompt,mode,ratio,durationSeconds,
                       images:[{url}],videos:[{url}],audios:[{url}]}
  GET  /api/v1/tasks/{id} → data.status processing/succeeded/failed，
  成片 data.outputUrl（平台永久地址）；预检完备（模型/时长/比例依次 400）。
"""
import pytest

from router_gateway.adapters.base import AssetRef, SubmitRequest
from router_gateway.adapters.huoai import HuoaiAdapter, HuoaiError


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url,
                           "headers": headers, "body": body})
        return self.responses.pop(0)


def _img(i=1):
    return AssetRef("image", f"https://video.sggf.net/big{i:02d}.jpg", "public_url")


def _vid():
    return AssetRef("video", "https://video.sggf.net/short1.mp4", "public_url")


def _aud():
    return AssetRef("audio", "https://video.sggf.net/a.mp3", "public_url")


def _req(model="downstream-1", assets=(), resolution="720p", duration=5,
         aspect_ratio="16:9"):
    return SubmitRequest(model=model, prompt="橘猫举纸牌",
                         duration_seconds=duration, resolution=resolution,
                         aspect_ratio=aspect_ratio, idempotency_key="job-0",
                         reference_assets=tuple(assets))


def _adapter(responses=None):
    t = FakeTransport(responses or [(201, {"ok": True,
                                           "data": {"id": "uuid-1",
                                                    "status": "processing"}})])
    return HuoaiAdapter("https://video.huoai2.cn", "avs_x", transport=t), t


def test_文生提交体():
    a, t = _adapter()
    r = a.submit(_req(duration=30, aspect_ratio="1:1"))
    assert r.upstream_task_id == "uuid-1" and r.phase == "queued"
    c = t.calls[0]
    assert c["url"] == "https://video.huoai2.cn/api/v1/tasks"
    assert c["headers"]["Authorization"] == "Bearer avs_x"
    assert c["body"] == {"model": "downstream-1", "prompt": "橘猫举纸牌",
                         "ratio": "1:1", "durationSeconds": 30}


def test_素材对象数组url():
    a, t = _adapter()
    a.submit(_req(assets=[_img(1), _img(2), _vid(), _aud()]))
    b = t.calls[0]["body"]
    assert b["images"] == [{"url": "https://video.sggf.net/big01.jpg"},
                           {"url": "https://video.sggf.net/big02.jpg"}]
    assert b["videos"] == [{"url": "https://video.sggf.net/short1.mp4"}]
    assert b["audios"] == [{"url": "https://video.sggf.net/a.mp3"}]


def test_纯视频参考():
    a, t = _adapter()
    a.submit(_req(assets=[_vid()]))
    assert t.calls[0]["body"]["videos"] == [
        {"url": "https://video.sggf.net/short1.mp4"}]


def test_30图上限():
    a, t = _adapter(responses=[])
    with pytest.raises(HuoaiError):
        a.submit(_req(assets=[_img(i % 30 + 1) for i in range(31)],
                      duration=30))
    assert t.calls == []


def test_素材必须公网URL():
    a, t = _adapter(responses=[])
    with pytest.raises(HuoaiError):
        a.submit(_req(assets=[AssetRef("image", "https://x/a.jpg", "host_url")]))
    assert t.calls == []


def test_平台ok为false判失败():
    a, t = _adapter([(400, {"ok": False, "code": "INVALID_DURATION",
                            "error": "下游模型时长必须为 4 至 30 秒。"})])
    with pytest.raises(HuoaiError) as ei:
        a.submit(_req(duration=3))
    assert "4 至 30" in str(ei.value) and ei.value.retriable is False


def test_429可重试():
    a, _ = _adapter([(429, {"ok": False, "code": "RATE", "error": "x"}),
                     (201, {"ok": True, "data": {"id": "u2",
                                                  "status": "processing"}})])
    with pytest.raises(HuoaiError) as ei:
        a.submit(_req())
    assert ei.value.retriable is True


def test_轮询活动成功失败():
    a, _ = _adapter([
        (200, {"data": {"id": "u", "status": "processing"}}),
        (200, {"data": {"id": "u", "status": "succeeded",
                        "outputUrl": "https://cdn.hk/a.mp4", "points": 100}}),
        (200, {"data": {"id": "u", "status": "failed",
                        "errorMessage": "内容审核"}}),
    ])
    assert a.poll("u").phase == "running"
    ok = a.poll("u")
    assert ok.phase == "succeeded" and ok.content_url == "https://cdn.hk/a.mp4"
    bad = a.poll("u")
    assert bad.phase == "failed" and "内容审核" in bad.error["message"]


def test_成功但无outputUrl按内容缺失():
    a, _ = _adapter([(200, {"data": {"id": "u", "status": "succeeded",
                                     "outputUrl": None}})])
    r = a.poll("u")
    assert r.phase == "failed" and r.error["type"] == "content_missing"
