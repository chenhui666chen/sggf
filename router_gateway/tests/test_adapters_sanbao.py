# -*- coding: utf-8 -*-
"""三宝（sanbaobeauty.com）适配器契约测试。

取证：%TEMP%/router_multimodal/window_s_summary.json 与 S1/S2/S3 真实订单脚本。
- POST /openapi/v1/videos，返回 {"taskId": ...}（驼峰）；
- 提交体 model/prompt/ratio/resolution/duration/images[]；
  H3 另带 reference:"all"；视频/音频元素为 {"tag","url"}，tag 逐字为"视频N/音频N"；
- 查询 GET /openapi/v1/videos/{taskId}，status queued/preparing/processing/
  succeeded/failed，成功成片在 video_url/download_url，images 回显恒空属正常；
- 暗坑护栏：H3 仅 1-2 图且必须原生上传 URL、任何路线拒绝参考视频、
  僵尸档 sd2_0_mini_933 与不稳定档 sd2_5_once_720p_2 黑名单；
  素材总数上限按模型而异，由路线能力 + preflight 拦截（实证 wan3 按次 15 个成功）。
"""
import pytest

from router_gateway.adapters.base import AssetRef, SubmitRequest
from router_gateway.adapters.sanbao import SanbaoAdapter, SanbaoError


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url,
                           "headers": headers, "body": body})
        return self.responses.pop(0)


def _img(url="https://sanbaobeauty.com/uploads/a.jpg", ref_type="host_url"):
    return AssetRef("image", url, ref_type)


def _aud(n, url=None):
    return AssetRef("audio", url or f"https://audio.sggf.net/a{n}.wav",
                    "public_url")


def _req(model="hailuo_h3_2k", assets=(), resolution="2k", duration=5):
    return SubmitRequest(model=model, prompt="橘猫在窗台追蝴蝶",
                         duration_seconds=duration, resolution=resolution,
                         aspect_ratio="16:9", idempotency_key="job-0",
                         reference_assets=tuple(assets))


def _adapter(responses=None):
    t = FakeTransport(responses or [(200, {"taskId": "task_mv01",
                                           "status": "queued"})])
    return SanbaoAdapter("https://sanbaobeauty.com", "sk_x", transport=t), t


# ---------- 提交成功路径 ----------

def test_H3单图提交体与taskId解析():
    a, t = _adapter()
    r = a.submit(_req(assets=[_img()]))
    assert r.upstream_task_id == "task_mv01" and r.phase == "queued"
    body = t.calls[0]["body"]
    assert body == {
        "model": "hailuo_h3_2k", "prompt": "橘猫在窗台追蝴蝶",
        "ratio": "16:9", "resolution": "2k", "duration": 5,
        "reference": "all",
        "images": ["https://sanbaobeauty.com/uploads/a.jpg"]}
    assert t.calls[0]["url"] == "https://sanbaobeauty.com/openapi/v1/videos"
    assert t.calls[0]["headers"]["Authorization"] == "Bearer sk_x"


def test_H3两图允许():
    a, t = _adapter()
    a.submit(_req(assets=[_img("https://sanbaobeauty.com/u/1.jpg"),
                          _img("https://sanbaobeauty.com/u/2.jpg")]))
    assert len(t.calls[0]["body"]["images"]) == 2


def test_sd2九外链图不带reference且分辨率小写():
    # S2g 成功单实证：sd 系列可直接吃 OSS 外链，提交体没有 reference 字段
    a, t = _adapter()
    urls = [f"https://audio.sggf.net/mmprobe1012/ref_{i:02d}.jpg"
            for i in range(9)]
    a.submit(_req(model="sd2_9img_seconds_720p_real",
                  assets=[AssetRef("image", u, "public_url") for u in urls],
                  resolution="720p"))
    body = t.calls[0]["body"]
    assert body["images"] == urls
    assert body["resolution"] == "720p"
    assert "reference" not in body and "audios" not in body


def test_t2v请求体不含素材字段():
    a, t = _adapter()
    a.submit(_req(model="wan_3_0", assets=(), resolution="480p"))
    body = t.calls[0]["body"]
    assert body == {"model": "wan_3_0", "prompt": "橘猫在窗台追蝴蝶",
                    "ratio": "16:9", "resolution": "480p", "duration": 5}


# ---------- 护栏：全部触网前失败 ----------

def test_H3三图拒绝():
    a, t = _adapter(responses=[])
    with pytest.raises(SanbaoError) as ei:
        a.submit(_req(assets=[_img(f"https://b/{i}.jpg") for i in range(3)]))
    assert "hailuo" in str(ei.value)
    assert t.calls == []


def test_H3外链图拒绝必须原生上传():
    a, t = _adapter(responses=[])
    with pytest.raises(SanbaoError):
        a.submit(_req(assets=[AssetRef("image", "https://oss/a.jpg",
                                       "public_url")]))
    assert t.calls == []


def test_任何模型参考视频直接拒绝():
    a, t = _adapter(responses=[])
    with pytest.raises(SanbaoError):
        a.submit(_req(model="sd2_9img_seconds_720p_real",
                      assets=[_img("https://b/1.jpg"),
                              AssetRef("video", "https://b/v.mp4",
                                       "host_url")],
                      resolution="720p"))
    assert t.calls == []


def test_素材总数限制由路线能力负责适配器不做平台级误杀():
    # 实证 S3：wan_3_0_once_480p 接受 10图+5音=15 个素材并成功出片；
    # ≤12 仅是 sd2_9img 等档位的模型级限制，应由 routes.yaml 的
    # max_total_assets + preflight 按路线拦截，适配器不得平台级一刀切。
    a, t = _adapter()
    assets = [AssetRef("image", f"https://x/{i}.jpg", "public_url")
              for i in range(10)] + [_aud(i + 1) for i in range(5)]
    a.submit(_req(model="wan_3_0_once_480p", assets=assets,
                  resolution="480p", duration=30))
    assert len(t.calls) == 1
    assert len(t.calls[0]["body"]["images"]) == 10
    assert t.calls[0]["body"]["audios"][0] == {
        "tag": "音频1", "url": "https://audio.sggf.net/a1.wav"}
    assert len(t.calls[0]["body"]["audios"]) == 5
    assert "reference" not in t.calls[0]["body"]


@pytest.mark.parametrize("model", ["sd2_0_mini_933", "sd2_5_once_720p_2"])
def test_僵尸与不稳定档黑名单(model):
    a, t = _adapter(responses=[])
    with pytest.raises(SanbaoError):
        a.submit(_req(model=model, assets=[_img("https://x/1.jpg",
                                               "public_url")]))
    assert t.calls == []


# ---------- 查询状态机 ----------

def test_轮询活动态映射():
    for raw, phase in [("queued", "queued"), ("preparing", "running"),
                       ("processing", "running"), ("running", "running")]:
        a, _ = _adapter([(200, {"taskId": "t1", "status": raw})])
        assert a.poll("t1").phase == phase


def test_轮询成功取video_url且images回显空不判失败():
    a, _ = _adapter([(200, {"taskId": "t1", "status": "succeeded",
                            "video_url": "https://cdn/x.mp4",
                            "images": []})])  # 回显恒空，成功样例亦然
    r = a.poll("t1")
    assert r.phase == "succeeded" and r.content_url == "https://cdn/x.mp4"


def test_轮询成功取download_url回退():
    a, _ = _adapter([(200, {"taskId": "t1", "status": "succeeded",
                            "download_url": "https://cdn/y.mp4"})])
    assert a.poll("t1").content_url == "https://cdn/y.mp4"


def test_轮询失败映射错误串():
    a, _ = _adapter([(200, {"taskId": "t1", "status": "failed",
                            "error": "reference video could not be measured",
                            "refund_status": "refunded"})])
    r = a.poll("t1")
    assert r.phase == "failed"
    assert r.error["type"] == "upstream_failed"
    assert "measured" in r.error["message"]


def test_提交非2xx错误分型():
    a, _ = _adapter([(402, {"error": "insufficient balance",
                            "error_code": 4020})])
    with pytest.raises(SanbaoError) as ei:
        a.submit(_req(assets=[_img()]))
    assert ei.value.status == 402 and ei.value.retriable is False


def test_适配器无幂等能力():
    a, _ = _adapter()
    assert a.supports_idempotent_submit is False
