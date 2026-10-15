# -*- coding: utf-8 -*-
"""贰春适配器契约测试：用录制的真实响应驱动，不发网络请求。"""
import pytest

from router_gateway.adapters.base import AssetRef, SubmitRequest
from router_gateway.adapters.erchun import ErchunAdapter, ErchunError


class FakeTransport:
    def __init__(self, responses):
        # responses: list of (status, payload)
        self.responses = responses
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        code, payload = self.responses.pop(0)
        return code, payload


SUBMIT_202 = {
    "id": "72193", "object": "generation.task", "status": "queued",
    "created_at": 1791725236, "status_url": "/v1/tasks/72193", "content_url": None,
    "request_id": "req_x", "idempotent_replay": False,
}
COMPLETED = {
    "id": "72193", "object": "generation.task", "status": "completed",
    "billing_status": "settled", "model": "mdl_x",
    "created_at": 1, "updated_at": 2, "completed_at": 2, "error": None,
    "content_url": "/v1/tasks/72193/content", "request_id": "req_y",
}
FAILED = {
    "id": "9", "status": "failed", "billing_status": "refunded",
    "error": {"code": "upstream_error", "message": "boom"}, "content_url": None,
}


def _req():
    return SubmitRequest(model="mdl_x", prompt="雪山日出", duration_seconds=5,
                         resolution="720p", aspect_ratio="16:9",
                         idempotency_key="idem-123")


def test_提交202解析任务号与排队态():
    t = FakeTransport([(202, SUBMIT_202)])
    a = ErchunAdapter(base_url="https://api.erchun.youkou.cc", api_key="k", transport=t)
    r = a.submit(_req())
    assert r.upstream_task_id == "72193"
    assert r.phase == "queued"
    # 分辨率上送大写、幂等头必填
    assert t.calls[0]["body"]["resolution"] == "720P"
    assert t.calls[0]["headers"]["Idempotency-Key"] == "idem-123"
    assert t.calls[0]["body"]["duration_seconds"] == 5


def test_轮询状态机映射():
    a = ErchunAdapter("https://x", "k", transport=FakeTransport([]))
    assert a._normalize({"status": "queued"}).phase == "queued"
    assert a._normalize({"status": "in_progress"}).phase == "running"
    ok = a._normalize(COMPLETED)
    assert ok.phase == "succeeded" and ok.billing_status == "settled"
    # 上游返回根相对路径时必须补全为可直接访问的绝对地址（W5 实证缺陷）
    assert ok.content_url == "https://x/v1/tasks/72193/content"
    bad = a._normalize(FAILED)
    assert bad.phase == "failed" and bad.billing_status == "refunded"
    assert bad.error["code"] == "upstream_error"


def test_content_url归一化边界():
    a = ErchunAdapter("https://api.erchun.youkou.cc", "k",
                      transport=FakeTransport([]))
    # 绝对地址原样透传，不重复拼接
    abs_url = a._normalize({"status": "completed",
                            "content_url": "https://cdn.example.com/a.mp4"})
    assert abs_url.content_url == "https://cdn.example.com/a.mp4"
    # 根相对路径补 base
    rel = a._normalize({"status": "completed",
                        "content_url": "/v1/tasks/9/content"})
    assert rel.content_url == "https://api.erchun.youkou.cc/v1/tasks/9/content"
    # 未出片/失败时为 None 不补
    none_case = a._normalize({"status": "queued", "content_url": None})
    assert none_case.content_url is None


def test_轮询终态拉取():
    t = FakeTransport([(200, {"task": COMPLETED})])
    a = ErchunAdapter("https://x", "k", transport=t)
    r = a.poll("72193")
    assert r.phase == "succeeded"
    assert "/v1/tasks/72193" in t.calls[0]["url"]


def test_402余额不足判定永久错误不重试():
    t = FakeTransport([(402, {"error": {"code": "insufficient_balance"}})])
    a = ErchunAdapter("https://x", "k", transport=t)
    with pytest.raises(ErchunError) as ei:
        a.submit(_req())
    assert ei.value.retriable is False


def test_429判定可重试():
    t = FakeTransport([(429, {"error": {"code": "rate_limited"}})])
    a = ErchunAdapter("https://x", "k", transport=t)
    with pytest.raises(ErchunError) as ei:
        a.submit(_req())
    assert ei.value.retriable is True


# ---------- i2v：对象式 med_id 素材 ----------

def _i2v_req(assets):
    return SubmitRequest(model="wf-happyhorse", prompt="角色走向镜头",
                         duration_seconds=5, resolution="480p",
                         aspect_ratio="16:9", idempotency_key="job-0",
                         reference_assets=tuple(assets))


def test_i2v三类素材以对象式med_id上送且保持顺序():
    t = FakeTransport([(202, SUBMIT_202)])
    a = ErchunAdapter("https://x", "k", transport=t)
    a.submit(_i2v_req([
        AssetRef("image", "med_aaa", "media_id"),
        AssetRef("image", "med_bbb", "media_id"),
        AssetRef("video", "med_vvv", "media_id"),
        AssetRef("audio", "med_ccc", "media_id"),
    ]))
    body = t.calls[0]["body"]
    assert body["input_images"] == [
        {"media_id": "med_aaa"}, {"media_id": "med_bbb"}]
    assert body["input_videos"] == [{"media_id": "med_vvv"}]
    assert body["input_audios"] == [{"media_id": "med_ccc"}]
    assert body["resolution"] == "480P"          # 大写归一化不丢
    assert t.calls[0]["headers"]["Idempotency-Key"] == "job-0"


def test_i2v空槽位不带对应字段():
    t = FakeTransport([(202, SUBMIT_202)])
    a = ErchunAdapter("https://x", "k", transport=t)
    a.submit(_i2v_req([AssetRef("image", "med_aaa", "media_id")]))
    body = t.calls[0]["body"]
    assert body["input_images"] == [{"media_id": "med_aaa"}]
    assert "input_videos" not in body and "input_audios" not in body


def test_t2v请求体不含任何素材字段():
    t = FakeTransport([(202, SUBMIT_202)])
    a = ErchunAdapter("https://x", "k", transport=t)
    a.submit(_req())
    body = t.calls[0]["body"]
    assert not any(k in body for k in
                   ("input_images", "input_videos", "input_audios"))


def test_i2v收到非media_id引用直接拒绝不触网():
    t = FakeTransport([])   # 若触网会 IndexError
    a = ErchunAdapter("https://x", "k", transport=t)
    with pytest.raises(ErchunError):
        a.submit(_i2v_req([AssetRef("image", "https://oss/a.jpg", "public_url")]))
    assert t.calls == []
