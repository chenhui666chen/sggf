# -*- coding: utf-8 -*-
"""AutoDL.Art ComfyUI 适配器契约测试：用实测工作流枚举与真实响应形态驱动，不发网络请求。

实测取证（2026-10-11，%LOCALAPPDATA%/Temp/router_autodl/wf_details.json）：
- 提交 POST {base}/api/v1/comfyui/comfyui_workflow/{workflow_id}
  t2v body = {"prompt", "duration": 秒(int), "resolution": 中文枚举label}
  i2v 另加素材字段（2026-10-13 D1-D4 付费实证）：
    minimax_h3_z0902        ref_image_0..5（1-6 张公网图片 URL）
    minimax_h3_z0903        ref_image_0..5 + ref_audio_0..2（音频必填槽，1-6 图 1-3 音）
    minimax_h3_b99_002      first_frame / last_frame（恰好 2 图）
    minimax_h3_lightx2v_v5_15s  ref_image_0..8（1-9 张，1-15 秒）
    minimax_h3_zm_u24          ref_image_0..8（1-9 图）+ ref_audio_0..2（0-3 音，音频选填）
- 鉴权为裸 token（Authorization: <token>，无 Bearer 前缀）
  成功响应 {"code": "Success", "data": {"task_id": ..., "status": ...}}
- 轮询 GET {base}/api/v1/comfyui/comfyui_workflow/result/{task_id}
  data.status 实测大写 SUCCESS；成功产物在 data.results 中（type=video 或 file_type=mp4）
- 无幂等键能力：supports_idempotent_submit=False
"""
import pytest

from router_gateway.adapters.autodl import AutoDLAdapter
from router_gateway.adapters.base import (AdapterError, AssetRef,
                                          RetriableTransportError, SubmitRequest)


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        code, payload = self.responses.pop(0)
        return code, payload


def _boom_urlopen(_req, timeout=60):
    import urllib.error
    raise urllib.error.URLError("connection reset")


def _req(model="minimax_h3_z0901", resolution="480p", aspect_ratio="16:9", duration=5):
    return SubmitRequest(model=model, prompt="雪山日出", duration_seconds=duration,
                         resolution=resolution, aspect_ratio=aspect_ratio,
                         idempotency_key="idem-x")


# ---------- 提交：URL / 鉴权 / 请求体 ----------

def test_提交z0901_480p横屏_裸token与中文枚举():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "wk-1", "status": "queued"}})])
    a = AutoDLAdapter(base_url="https://autodl.art", api_key="tok", transport=t)
    r = a.submit(_req())
    assert r.upstream_task_id == "wk-1"
    assert r.phase == "queued"
    call = t.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/comfyui/comfyui_workflow/minimax_h3_z0901")
    assert call["headers"]["Authorization"] == "tok"  # 裸 token，不带 Bearer
    assert call["body"] == {"prompt": "雪山日出", "duration": 5, "resolution": "480p横(864*480)"}
    assert "Idempotency-Key" not in call["headers"]


def test_提交z0901各档位枚举映射():
    cases = [
        ("480p", "16:9", "480p横(864*480)"),
        ("480p", "9:16", "480p竖(480*864)"),
        ("768p", "16:9", "768p横(1344*768)"),
        ("768p", "9:16", "768p竖(768*1344)"),
        # 上游 1088p 对外归入 1080p 能力档
        ("1080p", "16:9", "1088p横(1920*1088)"),
        ("1080p", "9:16", "1088p竖(1088*1920)"),
    ]
    for resolution, aspect, label in cases:
        t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "x"}})])
        a = AutoDLAdapter("https://x", "tok", transport=t)
        a.submit(_req(resolution=resolution, aspect_ratio=aspect))
        assert t.calls[0]["body"]["resolution"] == label, (resolution, aspect)


def test_提交b99工作流768p档映射到736枚举():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "x"}}),
                       (200, {"code": "Success", "data": {"task_id": "y"}}),
                       (200, {"code": "Success", "data": {"task_id": "z"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_req(model="minimax_h3_b99_001", resolution="768p", aspect_ratio="16:9"))
    assert t.calls[0]["body"]["resolution"] == "736p横"
    a.submit(_req(model="minimax_h3_b99_001", resolution="768p", aspect_ratio="9:16"))
    assert t.calls[1]["body"]["resolution"] == "736p竖"
    a.submit(_req(model="minimax_h3_b99_001", resolution="768p", aspect_ratio="1:1"))
    assert t.calls[2]["body"]["resolution"] == "736p(1:1)"


def test_提交lightx2v工作流枚举():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "x"}}),
                       (200, {"code": "Success", "data": {"task_id": "y"}}),
                       (200, {"code": "Success", "data": {"task_id": "z"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_req(model="minimax_h3_lightx2v_no_pic", resolution="480p", aspect_ratio="9:16"))
    a.submit(_req(model="minimax_h3_lightx2v_no_pic", resolution="768p", aspect_ratio="16:9"))
    a.submit(_req(model="minimax_h3_lightx2v_no_pic", resolution="768p", aspect_ratio="1:1"))
    assert [c["body"]["resolution"] for c in t.calls] == ["480p竖", "768p横", "768p(1:1)"]


def test_不支持的分辨率比例组合在发请求前报错且不花钱():
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([]))
    # z0901 实测枚举没有 1:1
    with pytest.raises(AdapterError) as ei:
        a.submit(_req(model="minimax_h3_z0901", resolution="480p", aspect_ratio="1:1"))
    assert ei.value.retriable is False
    # b99 工作流只有 736p，不支持 480p
    with pytest.raises(AdapterError):
        a.submit(_req(model="minimax_h3_b99_001", resolution="480p", aspect_ratio="16:9"))
    # 未知工作流
    with pytest.raises(AdapterError):
        a.submit(_req(model="not_a_workflow", resolution="480p", aspect_ratio="16:9"))


# ---------- i2v 工作流：素材字段、枚举映射与触网前护栏（D1-D4 实证） ----------

def _i2v_req(model, *, images=(), audios=(), videos=(),
             resolution="480p", aspect_ratio="16:9", duration=5,
             ref_type="public_url"):
    assets = ([AssetRef("image", u, ref_type) for u in images]
              + [AssetRef("audio", u, ref_type) for u in audios]
              + [AssetRef("video", u, ref_type) for u in videos])
    return SubmitRequest(model=model, prompt="参考素材融合，镜头平滑推进",
                         duration_seconds=duration, resolution=resolution,
                         aspect_ratio=aspect_ratio, idempotency_key="idem-i2v",
                         reference_assets=tuple(assets))


def _imgs(n):
    return [f"https://cdn.example.com/img{i}.jpg" for i in range(n)]


def _auds(n):
    return [f"https://cdn.example.com/aud{i}.wav" for i in range(n)]


def test_提交z0902六图_编号ref_image字段透传公网URL():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "d1", "status": "queued"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req("minimax_h3_z0902", images=_imgs(6)))
    body = t.calls[0]["body"]
    assert body["resolution"] == "480p横(864*480)"
    assert body["duration"] == 5
    for i, url in enumerate(_imgs(6)):
        assert body[f"ref_image_{i}"] == url
    assert not any(k.startswith("ref_audio") for k in body)


def test_提交z0903六图三音_ref_image与ref_audio字段():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "d2", "status": "queued"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req("minimax_h3_z0903", images=_imgs(6), audios=_auds(3)))
    body = t.calls[0]["body"]
    for i, url in enumerate(_imgs(6)):
        assert body[f"ref_image_{i}"] == url
    for i, url in enumerate(_auds(3)):
        assert body[f"ref_audio_{i}"] == url


def test_提交b99_002首尾帧_first_frame与last_frame():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "d3", "status": "queued"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req("minimax_h3_b99_002", resolution="768p",
                      images=["https://cdn/first.jpg", "https://cdn/last.jpg"]))
    body = t.calls[0]["body"]
    assert body["first_frame"] == "https://cdn/first.jpg"
    assert body["last_frame"] == "https://cdn/last.jpg"
    assert body["resolution"] == "736p横"


def test_提交lightx2v_v5_15s九图_无括号枚举():
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "d4", "status": "queued"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req("minimax_h3_lightx2v_v5_15s", images=_imgs(9)))
    body = t.calls[0]["body"]
    assert body["resolution"] == "480p横"
    for i, url in enumerate(_imgs(9)):
        assert body[f"ref_image_{i}"] == url


def test_提交zm_u24九图三音_图片与选填音频字段齐透传():
    # Z1 实证工作流（升级画质）：音频槽选填，满槽 9 图 3 音
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "z1", "status": "queued"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req("minimax_h3_zm_u24", images=_imgs(9), audios=_auds(3)))
    body = t.calls[0]["body"]
    assert body["resolution"] == "480p横"
    for i, url in enumerate(_imgs(9)):
        assert body[f"ref_image_{i}"] == url
    for i, url in enumerate(_auds(3)):
        assert body[f"ref_audio_{i}"] == url


def test_提交zm_u24单图无音_仅ref_image_0不带音频字段():
    # Z1 实际付费实证形态：1 图 0 音（task 797cf1af）
    t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "z1b", "status": "queued"}})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    a.submit(_i2v_req("minimax_h3_zm_u24", images=_imgs(1)))
    body = t.calls[0]["body"]
    assert body["ref_image_0"] == _imgs(1)[0]
    assert not any(k.startswith("ref_audio") for k in body)


def test_i2v工作流分辨率比例枚举映射():
    cases = [
        ("minimax_h3_z0902", "768p", "16:9", "768p横(1376*768)"),
        ("minimax_h3_z0902", "1080p", "16:9", "1088p横(1920*1088)"),
        ("minimax_h3_z0902", "2k", "16:9", "1440p横(2560*1440)"),
        ("minimax_h3_z0902", "480p", "9:16", "480p竖(480*864)"),
        ("minimax_h3_z0902", "1080p", "9:16", "1088p竖(1088*1920)"),
        ("minimax_h3_z0903", "768p", "9:16", "768p竖(768*1376)"),
        ("minimax_h3_b99_002", "768p", "9:16", "736p竖"),
        ("minimax_h3_b99_002", "768p", "1:1", "736p(1:1)"),
        ("minimax_h3_lightx2v_v5_15s", "768p", "16:9", "768p横"),
        ("minimax_h3_lightx2v_v5_15s", "480p", "1:1", "480p(1:1)"),
        ("minimax_h3_zm_u24", "768p", "1:1", "768p(1:1)"),
    ]
    for model, res, aspect, label in cases:
        t = FakeTransport([(200, {"code": "Success", "data": {"task_id": "x"}})])
        a = AutoDLAdapter("https://x", "tok", transport=t)
        audios = _auds(1) if model == "minimax_h3_z0903" else ()
        a.submit(_i2v_req(model, images=_imgs(2), audios=audios,
                          aspect_ratio=aspect, resolution=res))
        assert t.calls[0]["body"]["resolution"] == label, (model, res, aspect)


def test_i2v工作流护栏_非法素材组合触网前拒绝且不花钱():
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([]))
    # z0902：至少 1 图、至多 6 图，无音频/视频槽
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0902"))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0902", images=_imgs(7)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0902", images=_imgs(2), audios=_auds(1)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0902", images=_imgs(2), videos=["https://x/v.mp4"]))
    # z0903：1-6 图 + 1-3 音，无视频槽（ref_audio_0 工作流必填）
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0903", audios=_auds(1)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0903", images=_imgs(6)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0903", images=_imgs(6), audios=_auds(4)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0903", images=_imgs(2), audios=_auds(1),
                          videos=["https://x/v.mp4"]))
    # b99_002：恰好 2 图，无音频/视频
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_b99_002", images=_imgs(1)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_b99_002", images=_imgs(3)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_b99_002", images=_imgs(2), audios=_auds(1)))
    # lightx2v_v5_15s：1-9 图，无音频/视频
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_lightx2v_v5_15s"))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_lightx2v_v5_15s", images=_imgs(10)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_lightx2v_v5_15s", images=_imgs(2), audios=_auds(1)))
    # zm_u24：1-9 图 + 0-3 音（音频选填），无视频槽
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_zm_u24"))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_zm_u24", images=_imgs(10)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_zm_u24", images=_imgs(1), audios=_auds(4)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_zm_u24", audios=_auds(1)))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_zm_u24", images=_imgs(2),
                          videos=["https://x/v.mp4"]))


def test_i2v工作流只接受公网URL引用_media_id触网前拒绝():
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([]))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0902", images=_imgs(2), ref_type="media_id"))


def test_t2v工作流携带素材时拒绝_防止素材静默丢弃():
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([]))
    with pytest.raises(AdapterError):
        a.submit(_i2v_req("minimax_h3_z0901", images=_imgs(1)))


# ---------- 提交响应错误 ----------

def test_提交业务码非Success判永久失败():
    t = FakeTransport([(200, {"code": "Fail", "msg": "余额不足"})])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    with pytest.raises(AdapterError) as ei:
        a.submit(_req())
    assert ei.value.retriable is False
    assert "余额不足" in str(ei.value)


def test_提交402与400不可重试_429与503可重试():
    for http_code, retriable in [(402, False), (400, False), (429, True), (503, True)]:
        a = AutoDLAdapter("https://x", "tok",
                          transport=FakeTransport([(http_code, {"code": "Fail", "msg": "x"})]))
        with pytest.raises(AdapterError) as ei:
            a.submit(_req())
        assert ei.value.retriable is retriable, http_code


def test_传输层异常上抛未知错误(monkeypatch):
    import router_gateway.adapters.base as base_mod
    monkeypatch.setattr(base_mod.urllib.request, "urlopen", _boom_urlopen)
    a = AutoDLAdapter("https://x", "tok")  # 真实 UrllibTransport
    with pytest.raises(RetriableTransportError):
        a.submit(_req())


def test_适配器无幂等能力():
    assert AutoDLAdapter("https://x", "tok", transport=FakeTransport([])).supports_idempotent_submit is False


# ---------- 轮询 ----------

def test_轮询成功大写状态与视频产物提取():
    payload = {"code": "Success", "data": {
        "status": "SUCCESS",
        "results": [
            {"type": "image", "url": "https://cdn/cover.jpg"},
            {"type": "video", "file_type": "mp4", "url": "https://cdn/out.mp4"},
        ]}}
    t = FakeTransport([(200, payload)])
    a = AutoDLAdapter("https://x", "tok", transport=t)
    r = a.poll("wk-1")
    assert r.phase == "succeeded"
    assert r.content_url == "https://cdn/out.mp4"
    assert t.calls[0]["url"].endswith("/api/v1/comfyui/comfyui_workflow/result/wk-1")


def test_轮询成功但results无类型信息时回退首个带url产物():
    payload = {"code": "Success", "data": {
        "status": "success", "results": [{"url": "https://cdn/first.mp4"}]}}
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([(200, payload)]))
    r = a.poll("wk-2")
    assert r.phase == "succeeded" and r.content_url == "https://cdn/first.mp4"


def test_轮询活动态与未知状态继续等待():
    for raw_status, phase in [("QUEUED", "queued"), ("RUNNING", "running"),
                              ("waiting", "running"), ("", "running")]:
        payload = {"code": "Success", "data": {"status": raw_status}}
        a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([(200, payload)]))
        assert a.poll("w").phase == phase, raw_status


def test_轮询失败提取message():
    payload = {"code": "Success", "data": {"status": "FAILED", "message": "生成失败原因X"}}
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([(200, payload)]))
    r = a.poll("w")
    assert r.phase == "failed"
    assert r.error["message"] == "生成失败原因X"


def test_轮询成功状态但缺少视频链接按失败处理():
    payload = {"code": "Success", "data": {"status": "SUCCESS", "results": []}}
    a = AutoDLAdapter("https://x", "tok", transport=FakeTransport([(200, payload)]))
    r = a.poll("w")
    assert r.phase == "failed"
