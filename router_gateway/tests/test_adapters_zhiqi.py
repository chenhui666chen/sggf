# -*- coding: utf-8 -*-
"""志奇引擎（zhiqiapi.com）适配器测试。

协议（站内开发者文档 + 2026-10-15 零成本探测）：
  Base https://zhiqiapi.com/v1，Bearer 鉴权，仅收公网素材 URL。
  POST /v1/videos → {"id":"vidtask_...","status":"queued"}
  GET  /v1/videos/{id} → status queued/in_progress/succeeded/failed/expired，
  成功成片在 data[].url。
请求字段：duration(别名 seconds)、resolution、aspect_ratio(别名 ratio)、
  first_frame_image_url/last_frame_image_url、
  reference_image_urls / reference_video_urls / reference_audio_urls。
"""
import pytest

from router_gateway.adapters.base import AssetRef, SubmitRequest
from router_gateway.adapters.zhiqi import ZhiqiAdapter, ZhiqiError


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


def _aud(i=1):
    return AssetRef("audio", f"https://video.sggf.net/a{i}.mp3", "public_url")


def _req(model="H3", assets=(), resolution="720p", duration=5,
         aspect_ratio="16:9"):
    return SubmitRequest(model=model, prompt="橘猫举纸牌",
                         duration_seconds=duration, resolution=resolution,
                         aspect_ratio=aspect_ratio, idempotency_key="job-0",
                         reference_assets=tuple(assets))


def _adapter(responses=None):
    t = FakeTransport(responses or [(200, {"id": "vidtask_abc",
                                           "status": "queued"})])
    return ZhiqiAdapter("https://zhiqiapi.com", "sk-z", transport=t), t


def test_文生提交体():
    a, t = _adapter()
    r = a.submit(_req(model="seedance-2.5", resolution="1080p",
                      duration=30, aspect_ratio="9:16"))
    assert r.upstream_task_id == "vidtask_abc"
    c = t.calls[0]
    assert c["url"] == "https://zhiqiapi.com/v1/videos"
    assert c["headers"]["Authorization"] == "Bearer sk-z"
    assert c["body"] == {"model": "seedance-2.5", "prompt": "橘猫举纸牌",
                         "duration": 30, "resolution": "1080p",
                         "aspect_ratio": "9:16"}


def test_首尾帧专用字段():
    a, t = _adapter()
    a.submit(_req(assets=[_img(1), _img(2)]))
    b = t.calls[0]["body"]
    assert b["first_frame_image_url"] == "https://video.sggf.net/big01.jpg"
    assert b["last_frame_image_url"] == "https://video.sggf.net/big02.jpg"
    assert "reference_image_urls" not in b


def test_多图参考数组():
    a, t = _adapter()
    a.submit(_req(assets=[_img(i) for i in range(1, 10)]))
    b = t.calls[0]["body"]
    assert len(b["reference_image_urls"]) == 9
    assert "first_frame_image_url" not in b


def test_纯视频参考():
    a, t = _adapter()
    a.submit(_req(model="seedance-2.5", resolution="720p", assets=[_vid()]))
    b = t.calls[0]["body"]
    assert b["reference_video_urls"] == ["https://video.sggf.net/short1.mp4"]
    assert "reference_image_urls" not in b


def test_全能参考三类数组齐传():
    a, t = _adapter()
    a.submit(_req(model="seedance-2.5", resolution="720p",
                  assets=[_img(1), _img(2), _vid(), _aud(1), _aud(2)]))
    b = t.calls[0]["body"]
    assert b["reference_image_urls"] == [
        "https://video.sggf.net/big01.jpg", "https://video.sggf.net/big02.jpg"]
    assert b["reference_video_urls"] == ["https://video.sggf.net/short1.mp4"]
    assert len(b["reference_audio_urls"]) == 2


def test_单图1音对口型诉求拒绝():
    a, t = _adapter(responses=[])
    with pytest.raises(ZhiqiError):
        a.submit(_req(assets=[_img(1), _aud(1)]))
    assert t.calls == []


def test_非公网素材拒绝():
    a, t = _adapter(responses=[])
    with pytest.raises(ZhiqiError):
        a.submit(_req(assets=[AssetRef("video", "https://x/v.mp4", "media_id")]))
    assert t.calls == []


def test_400参数错误映射不可重试():
    a, _ = _adapter([(400, {"code": "unsupported_parameter",
                            "message": "duration outside capability"}),
                     (429, {"code": "rate_limit", "message": "slow"})])
    with pytest.raises(ZhiqiError) as ei:
        a.submit(_req())
    assert ei.value.retriable is False
    with pytest.raises(ZhiqiError) as ei2:
        a.submit(_req())
    assert ei2.value.retriable is True


def test_轮询活动态成功与失败():
    a, _ = _adapter([
        (200, {"id": "1", "status": "in_progress"}),
        (200, {"id": "1", "status": "succeeded",
               "data": [{"url": "https://cdn.zq/a.mp4"}]}),
        (200, {"id": "1", "status": "failed",
               "error": {"message": "上游失败"}}),
        (200, {"id": "1", "status": "expired"}),
    ])
    assert a.poll("1").phase == "running"
    ok = a.poll("1")
    assert ok.phase == "succeeded" and ok.content_url == "https://cdn.zq/a.mp4"
    assert a.poll("1").phase == "failed"
    assert a.poll("1").phase == "failed"  # expired 按失败处理


def test_成功但无data链接按内容缺失失败():
    a, _ = _adapter([(200, {"id": "1", "status": "succeeded", "data": []})])
    r = a.poll("1")
    assert r.phase == "failed" and r.error["type"] == "content_missing"
