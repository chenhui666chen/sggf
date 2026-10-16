# -*- coding: utf-8 -*-
"""灵客（聚合引擎AIGC，api.lk888.ai）适配器测试。

两条协议族（2026-10-15 站内接入文档 + 零成本探测取证）：
- H3 全形态：POST /v1/media/generate（model/prompt/params 三段式），
  轮询 GET /v1/media/status?task_id=，state/is_final/result_url；
  线路由密钥决定（DMC/MT 各一把，同一协议）。
- SD2.5 按秒（MC-S 线路）：火山 Ark 兼容
  POST /api/v3/anmiao/contents/generations/tasks，content role 数组，
  轮询 GET .../tasks/{id}，status/content.video_url。
"""
import pytest

from router_gateway.adapters.base import AssetRef, SubmitRequest
from router_gateway.adapters.lingke import (LingkeAnmiaoAdapter,
                                           LingkeMediaAdapter,
                                           LingkeError)

_BASE = "https://api.lk888.ai"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url,
                           "headers": headers, "body": body})
        return self.responses.pop(0)


def _img(i=1, url=None):
    return AssetRef("image", url or f"https://video.sggf.net/card{i:02d}.jpg",
                    "public_url")


def _vid(i=1):
    return AssetRef("video", f"https://video.sggf.net/motion{i}.mp4", "public_url")


def _aud(i=1):
    return AssetRef("audio", f"https://video.sggf.net/tone{i}.mp3", "public_url")


def _req(model="minimax-h3", assets=(), resolution="768p", duration=5,
         aspect_ratio="16:9"):
    return SubmitRequest(model=model, prompt="橘猫举纸牌",
                         duration_seconds=duration, resolution=resolution,
                         aspect_ratio=aspect_ratio, idempotency_key="job-0",
                         reference_assets=tuple(assets))


def _media(responses=None):
    t = FakeTransport(responses or [(200, {"code": 200,
                                           "data": {"task_id": "778899"}})])
    return LingkeMediaAdapter(_BASE, "sk-dmc", transport=t), t


# ---------- H3 media 协议 ----------

def test_H3文生_三段式请求体与task_id():
    a, t = _media()
    r = a.submit(_req(duration=15))
    assert r.upstream_task_id == "778899" and r.phase == "queued"
    c = t.calls[0]
    assert c["url"] == f"{_BASE}/v1/media/generate"
    assert c["headers"]["Authorization"] == "Bearer sk-dmc"
    assert c["body"] == {
        "model": "minimax-h3", "prompt": "橘猫举纸牌",
        "params": {"duration": 15, "resolution": "768P",
                   "aspect_ratio": "16:9"}}


def test_H3首尾帧_shouweizhen模式images两张():
    a, t = _media()
    a.submit(_req(assets=[_img(1), _img(2)], aspect_ratio="9:16"))
    p = t.calls[0]["body"]["params"]
    assert p["mode"] == "shouweizhen"
    assert p["images"] == ["https://video.sggf.net/card01.jpg",
                          "https://video.sggf.net/card02.jpg"]
    assert "image_url" not in p


def test_H3多图参考_cankaosheng_image_url数组():
    a, t = _media()
    a.submit(_req(assets=[_img(i) for i in range(1, 10)]))
    p = t.calls[0]["body"]["params"]
    assert p["mode"] == "cankaosheng" and len(p["image_url"]) == 9


def test_H3纯参考视频_cankaosheng_video_url():
    a, t = _media()
    a.submit(_req(assets=[_vid(1)]))
    p = t.calls[0]["body"]["params"]
    assert p["mode"] == "cankaosheng" and p["video_url"] == [
        "https://video.sggf.net/motion1.mp4"]
    assert "image_url" not in p


def test_H3全能参考_图音视频任意组合():
    a, t = _media()
    a.submit(_req(assets=[_img(1), _img(2), _vid(1), _vid(2), _vid(3),
                          _aud(1), _aud(2), _aud(3)]))
    p = t.calls[0]["body"]["params"]
    assert p["mode"] == "cankaosheng"
    assert len(p["image_url"]) == 2 and len(p["video_url"]) == 3 \
        and len(p["audio_url"]) == 3


def test_H3_2K文生_resolution大写():
    a, t = _media()
    a.submit(_req(resolution="2k", duration=15))
    assert t.calls[0]["body"]["params"]["resolution"] == "2K"


def test_H3护栏_对口型不支持():
    a, t = _media(responses=[])
    with pytest.raises(LingkeError):
        a.submit(_req(assets=[_img(1), _aud(1)]))
    assert t.calls == []


@pytest.mark.parametrize("assets", [
    [_img(i) for i in range(10)],                # 参考图超 9
    [_img(1), _img(2), _img(3), _vid(1), _vid(2), _vid(3), _vid(4)],  # 视频超 3
    [_aud(i) for i in range(4)],                 # 音频超 3
    [AssetRef("image", "https://h/x", "host_url")],  # 仅公网URL
])
def test_H3护栏_槽位上限与素材类型(assets):
    a, t = _media(responses=[])
    with pytest.raises(LingkeError):
        a.submit(_req(assets=assets))
    assert t.calls == []


def test_H3_HTTP200但业务码非200判失败():
    # 探测实证：参数错误时平台 HTTP 200 包体 {"code":400,"msg":...}
    a, t = _media([(200, {"code": 400, "data": None,
                          "msg": "duration 必须是4~15之间的整数"})])
    with pytest.raises(LingkeError) as ei:
        a.submit(_req(duration=3))
    assert "4~15" in str(ei.value)


def test_H3轮询_is_final与result_url():
    a, _ = _media([
        (200, {"state": "running", "is_final": False, "result_url": ""}),
        (200, {"state": "success", "is_final": True,
               "result_url": "https://cdn.lk/x.mp4"}),
        (200, {"state": "failed", "is_final": True, "error": "审核拒绝"}),
    ])
    r1 = a.poll("778899")
    assert r1.phase in ("queued", "running") and r1.content_url is None
    r2 = a.poll("778899")
    assert r2.phase == "succeeded" and r2.content_url == "https://cdn.lk/x.mp4"
    r3 = a.poll("778899")
    assert r3.phase == "failed" and "审核拒绝" in r3.error["message"]


# ---------- SD2.5 anmiao（Ark 兼容）协议 ----------

def _anmiao(responses=None):
    t = FakeTransport(responses or [(200, {"id": "99936297"})])
    return LingkeAnmiaoAdapter(_BASE, "sk-mcs", transport=t), t


def test_SD文生_content文本与端点():
    a, t = _anmiao()
    r = a.submit(_req(model="doubao-seedance-2-5-260628",
                      resolution="1080p", duration=30,
                      aspect_ratio="9:16"))
    assert r.upstream_task_id == "99936297"
    c = t.calls[0]
    assert c["url"].endswith("/api/v3/anmiao/contents/generations/tasks")
    assert c["body"] == {
        "model": "doubao-seedance-2-5-260628",
        "content": [{"type": "text", "text": "橘猫举纸牌"}],
        "resolution": "1080p", "ratio": "9:16", "duration": 30}


def test_SD全能参考_content角色齐全():
    a, t = _anmiao()
    assets = tuple(_img(i) for i in range(1, 11)) + (
        _vid(1), _vid(2)) + tuple(_aud(i) for i in range(1, 4))
    a.submit(_req(model="doubao-seedance-2-5-260628", assets=assets,
                  resolution="1080p", duration=30))
    content = t.calls[0]["body"]["content"]
    by = {}
    for item in content:
        by.setdefault(item["type"], []).append(item)
    assert len(by["text"]) == 1
    assert len(by["image_url"]) == 10
    assert all(i.get("role") == "reference_image" for i in by["image_url"])
    assert all(i["image_url"]["url"].startswith("https://") for i in by["image_url"])
    assert len(by["video_url"]) == 2 and all(
        i.get("role") == "reference_video" for i in by["video_url"])
    assert len(by["audio_url"]) == 3 and all(
        i.get("role") == "reference_audio" for i in by["audio_url"])


def test_SD首尾帧_content角色first_last():
    a, t = _anmiao()
    a.submit(_req(model="doubao-seedance-2-5-260628",
                  assets=[_img(1), _img(2)], resolution="720p",
                  aspect_ratio="adaptive"))
    roles = [(i["type"], i["role"]) for i in t.calls[0]["body"]["content"]
             if i["type"] == "image_url"]
    assert roles == [("image_url", "first_frame"),
                     ("image_url", "last_frame")]


def test_SD护栏_素材上限():
    a, t = _anmiao(responses=[])
    with pytest.raises(LingkeError):
        a.submit(_req(model="doubao-seedance-2-5-260628",
                      assets=tuple(_img(i) for i in range(31)), duration=30))
    with pytest.raises(LingkeError):
        a.submit(_req(model="doubao-seedance-2-5-260628",
                      assets=tuple(_vid(i % 5 + 1) for i in range(11)),
                      duration=30))
    assert t.calls == []


def test_SD轮询_status与content_video_url():
    a, _ = _anmiao([
        (200, {"id": "1", "status": "running"}),
        (200, {"id": "1", "status": "succeeded",
               "content": {"video_url": "https://tos.lk/y.mp4"}}),
        (200, {"id": "1", "status": "failed",
               "error": {"code": "SensitiveContentDetected",
                         "message": "审核"}}),
    ])
    assert a.poll("1").phase == "running"
    ok = a.poll("1")
    assert ok.phase == "succeeded" and ok.content_url == "https://tos.lk/y.mp4"
    bad = a.poll("1")
    assert bad.phase == "failed" and "审核" in bad.error["message"]
