# -*- coding: utf-8 -*-
"""算力AI（suanliai.top）适配器契约测试，响应形态取自实测档案 collected_results.json。

实测取证（2026-10-11）：
- 提交 POST {base}/v1/videos，Bearer 鉴权，无幂等键。
  Seedance 2.5 系列请求体用 seconds 字段；MiniMax H3 系列用 duration 字段，
  且 H3 必须显式 aspect_ratio（pro 路线不传时上游默认出竖屏 768x1376）。
- 轮询 GET {base}/v1/videos/{task_id}，返回裸 video 对象：
  status: queued -> in_progress -> completed/failed
  成功成片链接在 url/video_url/download_url/result_url（签名 URL，约 24h 有效）；
  失败为 error: {"message": ...}，平台失败全额退款。
"""
import pytest

from router_gateway.adapters.base import AdapterError, AssetRef, SubmitRequest
from router_gateway.adapters.suanliai import SuanliaiAdapter


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        code, payload = self.responses.pop(0)
        return code, payload


def _req(model, duration=5, resolution="720p", aspect_ratio="16:9"):
    return SubmitRequest(model=model, prompt="航拍雪山", duration_seconds=duration,
                         resolution=resolution, aspect_ratio=aspect_ratio,
                         idempotency_key="idem-s")


def test_提交sd25用seconds字段且不传比例():
    t = FakeTransport([(200, {"id": "task_abc", "status": "queued"})])
    a = SuanliaiAdapter("https://suanliai.top", "tok", transport=t)
    r = a.submit(_req("007系列/sd2.5(满血全参/720P)"))
    assert r.upstream_task_id == "task_abc"
    assert r.phase == "queued"
    call = t.calls[0]
    assert call["url"].endswith("/v1/videos")
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["body"] == {"model": "007系列/sd2.5(满血全参/720P)",
                            "prompt": "航拍雪山", "seconds": 5}


def test_提交sd25其他命名同样识别():
    t = FakeTransport([(200, {"task_id": "t1", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_req("sd2.5-720p-ch3(30-10-10不卡脸/4-30秒无限并发)"))
    assert "seconds" in t.calls[0]["body"] and "duration" not in t.calls[0]["body"]


def test_提交h3用duration字段且显式横屏():
    t = FakeTransport([(200, {"id": "task_h3", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_req("稳定minimax-h3-pro-768p(930不排队不卡脸)", resolution="768p"))
    assert t.calls[0]["body"] == {
        "model": "稳定minimax-h3-pro-768p(930不排队不卡脸)",
        "prompt": "航拍雪山", "duration": 5, "aspect_ratio": "16:9"}


def test_提交h3竖屏透传9比16():
    t = FakeTransport([(200, {"id": "t", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_req("特价/minimax_h3-768p", aspect_ratio="9:16"))
    assert t.calls[0]["body"]["aspect_ratio"] == "9:16"


def test_提交响应直接是失败对象按明确失败处理():
    t = FakeTransport([(200, {"id": "task_bad", "status": "failed",
                              "error": {"message": "当前生成服务繁忙，请稍后重试。"}})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    with pytest.raises(AdapterError) as ei:
        a.submit(_req("sd2.5-720p-ch3"))
    assert ei.value.retriable is False
    assert "繁忙" in str(ei.value)


def test_http错误码可重试性分类():
    for http_code, retriable in [(400, False), (402, False), (401, False),
                                 (429, True), (503, True)]:
        a = SuanliaiAdapter("https://x", "tok",
                            transport=FakeTransport([(http_code, {"error": {"message": "x"}})]))
        with pytest.raises(AdapterError) as ei:
            a.submit(_req("007系列/sd2.5(满血全参/720P)"))
        assert ei.value.retriable is retriable, http_code


def test_适配器无幂等能力():
    assert SuanliaiAdapter("https://x", "tok", transport=FakeTransport([])).supports_idempotent_submit is False


# ---------- i2v：review 转存引用 + 小写分辨率 + wan3 时长字段 ----------

WAN3 = "高质量稳定系列wan3.0-video(官转多参/480P)"


def _i2v_req(model=WAN3, assets=(), resolution="480p", duration_field=None):
    return SubmitRequest(model=model, prompt="角色走向镜头", duration_seconds=5,
                         resolution=resolution, aspect_ratio="16:9",
                         idempotency_key="job-0",
                         reference_assets=tuple(assets),
                         duration_field=duration_field)


def test_wan3图生提交用duration且素材为字符串数组与小写分辨率():
    t = FakeTransport([(200, {"id": "t_w3", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req(assets=[
        AssetRef("image", "https://suanliai.top/api/media/input/a.jpg", "review_url"),
        AssetRef("image", "https://suanliai.top/api/media/input/b.jpg", "review_url"),
        AssetRef("audio", "https://suanliai.top/api/media/input/c.wav", "review_url"),
    ]))
    body = t.calls[0]["body"]
    assert body["model"] == WAN3                 # 中文名逐字照抄，不做任何改写
    assert body["duration"] == 5 and "seconds" not in body
    assert body["aspect_ratio"] == "16:9"
    assert body["resolution"] == "480p"          # 小写，不得大写
    assert body["images"] == [
        "https://suanliai.top/api/media/input/a.jpg",
        "https://suanliai.top/api/media/input/b.jpg"]
    assert body["audios"] == [
        "https://suanliai.top/api/media/input/c.wav"]
    assert "videos" not in body


def test_i2v参考视频进videos数组():
    t = FakeTransport([(200, {"id": "t1", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req(assets=[
        AssetRef("image", "https://x/a.jpg", "review_url"),
        AssetRef("video", "https://x/v.mp4", "review_url"),
    ]))
    body = t.calls[0]["body"]
    assert body["images"] == ["https://x/a.jpg"]
    assert body["videos"] == ["https://x/v.mp4"]


def test_显式duration_field覆盖模型名启发式():
    t = FakeTransport([(200, {"id": "t1", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req(model="某新工作流(无sd2.5字样)", duration_field="seconds"))
    body = t.calls[0]["body"]
    assert "seconds" in body and "duration" not in body


def test_t2v请求体保持原样不带素材与分辨率字段():
    t = FakeTransport([(200, {"id": "task_abc", "status": "queued"})])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    a.submit(_req("007系列/sd2.5(满血全参/720P)"))
    body = t.calls[0]["body"]
    assert body == {"model": "007系列/sd2.5(满血全参/720P)",
                    "prompt": "航拍雪山", "seconds": 5}
    assert not any(k in body for k in
                   ("images", "videos", "audios", "resolution", "aspect_ratio"))


def test_轮询活动态映射():
    for raw, phase in [("queued", "queued"), ("in_progress", "running"),
                       ("running", "running"), ("pending", "queued")]:
        a = SuanliaiAdapter("https://x", "tok",
                            transport=FakeTransport([(200, {"id": "t", "status": raw})]))
        assert a.poll("t").phase == phase, raw


def test_轮询完成提取签名成片地址():
    url = ("https://suanliai.top/v1/videos/task_x/content?expires=999&owner=1"
           "&video_signature=abc")
    payload = {"id": "task_x", "status": "completed", "progress": 100,
               "url": url, "video_url": url, "download_url": url, "result_url": url}
    t = FakeTransport([(200, payload)])
    a = SuanliaiAdapter("https://x", "tok", transport=t)
    r = a.poll("task_x")
    assert r.phase == "succeeded"
    assert r.content_url == url
    assert t.calls[0]["url"].endswith("/v1/videos/task_x")


def test_轮询完成但仅有download_url字段也能提取():
    payload = {"task_id": "t2", "status": "completed",
               "download_url": "https://x/t2/content?s=1"}
    a = SuanliaiAdapter("https://x", "tok", transport=FakeTransport([(200, payload)]))
    r = a.poll("t2")
    assert r.phase == "succeeded" and r.content_url == "https://x/t2/content?s=1"


def test_轮询失败提取错误消息():
    payload = {"id": "t3", "status": "failed",
               "error": {"message": "当前生成服务繁忙，请稍后重试。"}}
    a = SuanliaiAdapter("https://x", "tok", transport=FakeTransport([(200, payload)]))
    r = a.poll("t3")
    assert r.phase == "failed"
    assert r.error["message"] == "当前生成服务繁忙，请稍后重试。"


def test_轮询完成但缺少成片链接按失败处理():
    a = SuanliaiAdapter("https://x", "tok",
                        transport=FakeTransport([(200, {"id": "t4", "status": "completed"})]))
    r = a.poll("t4")
    assert r.phase == "failed"
