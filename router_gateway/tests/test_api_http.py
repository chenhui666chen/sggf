# -*- coding: utf-8 -*-
"""g5 最小 HTTP 边界测试：POST /v1/videos、GET /v1/tasks/{id}、错误映射与脱敏。"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from router_gateway.api import create_app
from router_gateway.catalog.intent import IntentError
from router_gateway.db import IdempotencyKeyConflict
from router_gateway.db import ClientConcurrencyLimitExceeded
from router_gateway.db import ClientTaskLimitExceeded
from router_gateway.quota import RateLimitExceeded
from router_gateway.orchestrator.service import JobView, OrchestratorError


def _view(job_id="job-1", status="running", semantic_error=None,
          content_url=None, error=None, quality_group="seedance-2.5"):
    return JobView(id=job_id, status=status, semantic_error=semantic_error,
                   quality_group=quality_group, content_url=content_url,
                   error=error, attempts=())


class StubOrchestrator:
    def __init__(self, *, view=None, raise_exc=None, owner="client-id-1"):
        self._view = view if view is not None else _view()
        self._raise = raise_exc
        # 模拟任务归属：仅该 client.id 可查，其余与不存在同样抛错
        self._owner = owner
        self.submitted = []
        self.view_queries = []

    def submit_job(self, client_key, idempotency_key, spec):
        self.submitted.append((client_key, idempotency_key, spec))
        if self._raise is not None:
            raise self._raise
        return self._view

    def get_view(self, job_id, client_key):
        self.view_queries.append((job_id, client_key))
        if self._view.id != job_id or client_key != self._owner:
            raise OrchestratorError(f"job not found: {job_id}")
        return self._view


# 假 client 解析器：rg-live 启用、rg-off 禁用，其余视为不存在
_LIVE_CLIENT = SimpleNamespace(id="client-id-1", enabled=True,
                               max_parallel_attempts=2)
_DISABLED_CLIENT = SimpleNamespace(id="client-id-2", enabled=False)


def _resolve_client(table=None):
    table = table or {"rg-live": _LIVE_CLIENT, "rg-off": _DISABLED_CLIENT}
    return lambda api_key: table.get(api_key)


def _client(orch, resolve_client=None):
    return TestClient(create_app(orch, resolve_client=resolve_client
                                 or _resolve_client()))


def _client_with_rate_limiter(rate_limiter):
    return TestClient(create_app(StubOrchestrator(),
                                 resolve_client=_resolve_client(),
                                 rate_limiter=rate_limiter))


def test_生产关闭公开文档时docs与openapi均404():
    client = TestClient(create_app(
        StubOrchestrator(), resolve_client=_resolve_client(),
        expose_docs=False))
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_默认仍开放交互式文档与schema():
    client = _client(StubOrchestrator())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


_AUTH = {"Authorization": "Bearer rg-live", "Idempotency-Key": "test-idem"}


def _body(**over):
    base = dict(model="seedance-2.5", prompt="雪山日出航拍", duration_seconds=5,
                resolution="720p", aspect_ratio="16:9")
    base.update(over)
    return base


def test_POST合法请求返回202且以client_id提交并透传终端用户标识():
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=_body(),
                           headers={"Idempotency-Key": "idem-1",
                                    "Authorization": "Bearer rg-live",
                                    "X-Client-Key": "client-7"})
    assert r.status_code == 202
    data = r.json()
    assert data["id"] == "job-1" and data["status"] == "running"
    assert r.headers["location"] == "/v1/tasks/job-1"
    client_id, idem, spec = orch.submitted[0]
    assert client_id == "client-id-1" and idem == "idem-1"
    assert spec["prompt"] == "雪山日出航拍"
    # W3 起边界不再硬编码 mode：空素材透传 None，由编排器仲裁为 text
    assert spec["mode"] is None
    assert spec["quality_group"] == "seedance-2.5"
    assert spec["reference_images"] == ()
    assert spec["end_user_key"] == "client-7"


def test_POST将客户级对冲并发上限写入任务规格():
    client = SimpleNamespace(id="client-id-1", enabled=True,
                             max_parallel_attempts=1)
    orch = StubOrchestrator()
    response = _client(orch, resolve_client=lambda key: client if key == "rg-live" else None).post(
        "/v1/videos", json=_body(allow_hedge=True), headers=_AUTH)
    assert response.status_code == 202
    assert orch.submitted[0][2]["max_parallel_attempts"] == 1


def test_POST缺少prompt返回422():
    r = _client(StubOrchestrator()).post("/v1/videos", json=_body(prompt=None),
                                         headers=_AUTH)
    assert r.status_code == 422


def test_POST客户活动任务超限返回429和Retry_After():
    orch = StubOrchestrator(
        raise_exc=ClientConcurrencyLimitExceeded(current=5, limit=5))
    r = _client(orch).post("/v1/videos", json=_body(), headers=_AUTH)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "10"
    assert r.json()["error"]["code"] == "client_concurrency_limit_exceeded"


def test_total_trial_quota_exhaustion_returns_stable_429():
    response = _client(StubOrchestrator(raise_exc=ClientTaskLimitExceeded(100, 100))).post(
        "/v1/videos", json=_body(), headers=_AUTH)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "client_task_limit_exceeded"


def test_safety_service_failure_returns_503_without_internal_details():
    response = _client(StubOrchestrator(view=_view(status="failed",
        semantic_error="content_safety_unavailable", error={"secret": "do not expose"}))).post(
        "/v1/videos", json=_body(), headers=_AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "content_safety_unavailable"
    assert "do not expose" not in response.text


class _RejectingRateLimiter:
    def check(self, **kwargs):
        raise RateLimitExceeded(retry_after=3)


def test_POST客户速率超限返回429和动态Retry_After():
    r = _client_with_rate_limiter(_RejectingRateLimiter()).post(
        "/v1/videos", json=_body(), headers=_AUTH)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "3"
    assert r.json()["error"]["code"] == "client_rate_limit_exceeded"


def test_POST意图矛盾映射422且错误码为invalid_intent():
    orch = StubOrchestrator(raise_exc=IntentError("mode 'text' 与携带的素材矛盾"))
    r = _client(orch).post("/v1/videos", json=_body(), headers=_AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_intent"


def test_POST同步命中风险阻断映射422且不泄露内部错误文本():
    orch = StubOrchestrator(view=_view(status="failed",
                                       semantic_error="content_risk_blocked",
                                       error="grsai blocked: policy violation"))
    r = _client(orch).post("/v1/videos", json=_body(), headers=_AUTH)
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "content_risk_blocked"
    assert "grsai" not in str(body) and "policy violation" not in str(body)


def test_POST能力不支持映射422不支持状态():
    orch = StubOrchestrator(view=_view(status="failed",
                                       semantic_error="unsupported_capability"))
    r = _client(orch).post("/v1/videos", json=_body(resolution="4k"),
                           headers=_AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unsupported_capability"


def test_GET运行中返回200统一状态且以client_id查询():
    orch = StubOrchestrator(view=_view(status="running"))
    r = _client(orch).get("/v1/tasks/job-1", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert orch.view_queries == [("job-1", "client-id-1")]


def test_GET成功返回成片地址():
    view = _view(status="succeeded",
                 content_url="https://cdn.example.com/a.mp4")
    r = _client(StubOrchestrator(view=view)).get("/v1/tasks/job-1",
                                                 headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["content_url"] == "https://cdn.example.com/a.mp4"


def test_GET未知任务返回404():
    r = _client(StubOrchestrator()).get("/v1/tasks/nope", headers=_AUTH)
    assert r.status_code == 404


def test_GET查询他人任务返回404task_not_found且与不存在不可区分():
    orch = StubOrchestrator(owner="other-client-id")
    r = _client(orch).get("/v1/tasks/job-1", headers=_AUTH)
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "task_not_found"
    # 错误体与任务不存在时完全一致，不泄露归属信息
    assert body == {"error": {"code": "task_not_found", "message": "任务不存在"}}
    assert orch.view_queries == [("job-1", "client-id-1")]


def test_GET失败任务只给错误码不泄露供应商与URL():
    view = _view(status="failed", semantic_error="all_candidates_failed",
                 error="autodl https://autodl.art 500 key=sk-secret")
    r = _client(StubOrchestrator(view=view)).get("/v1/tasks/job-1",
                                                 headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "all_candidates_failed"
    text = str(body)
    assert "autodl" not in text and "sk-secret" not in text


def test_GETpending状态对外呈现accepted():
    r = _client(StubOrchestrator(view=_view(status="pending"))) \
        .get("/v1/tasks/job-1", headers=_AUTH)
    assert r.json()["status"] == "accepted"


def test_HEALTH由应用真实应答():
    r = _client(StubOrchestrator()).get("/health")
    assert r.status_code == 200
    assert r.text == "gateway healthy"


def test_POST幂等键复用不同请求返回409():
    orch = StubOrchestrator(
        raise_exc=IdempotencyKeyConflict(
            "idempotency key reused with different request"))
    r = _client(orch).post("/v1/videos", json=_body(), headers={
        **_AUTH, "Idempotency-Key": "same-order"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_key_reused"


def test_POST未知字段返回422():
    r = _client(StubOrchestrator()).post(
        "/v1/videos", json=_body(unexpected="must reject"),
        headers={**_AUTH, "Idempotency-Key": "strict-fields"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


# ---------- W2 鉴权边界 ----------

_INVALID_KEY_BODY = {"error": {"code": "invalid_api_key",
                               "message": "无效或已禁用的 API Key"}}


def test_POST无Authorization头返回固定401且不进入编排器():
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=_body())
    assert r.status_code == 401
    assert r.json() == _INVALID_KEY_BODY
    assert r.headers["www-authenticate"] == "Bearer"
    assert orch.submitted == []


def test_POST缺少Idempotency_Key返回422且不创建任务():
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=_body(),
                           headers={"Authorization": "Bearer rg-live"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert orch.submitted == []


@pytest.mark.parametrize("header", [
    {},
    {"Authorization": "Basic rg-live"},
    {"Authorization": "Bearer rg-missing"},
    {"Authorization": "Bearer rg-off"},
])
def test_POST鉴权失败一律401固定错误码(header):
    r = _client(StubOrchestrator()).post("/v1/videos", json=_body(),
                                         headers=header)
    assert r.status_code == 401
    assert r.json() == _INVALID_KEY_BODY


@pytest.mark.parametrize("header", [
    {},
    {"Authorization": "Bearer rg-missing"},
    {"Authorization": "Bearer rg-off"},
])
def test_GET无有效key一律401且先于404(header):
    r = _client(StubOrchestrator()).get("/v1/tasks/job-1", headers=header)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_POST不带x_client_key时透传值为None():
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=_body(), headers=_AUTH)
    assert r.status_code == 202
    assert orch.submitted[0][2]["end_user_key"] is None


# ---------- W3 g5b 素材参考接口 ----------

def _asset(url, duration_seconds=None):
    item = {"url": url}
    if duration_seconds is not None:
        item["duration_seconds"] = duration_seconds
    return item


_IMG_A = _asset("https://cdn.example.com/a.jpg")
_IMG_B = _asset("https://cdn.example.com/b.png")
_VID_10S = _asset("https://cdn.example.com/ref.mp4", duration_seconds=10)
_AUD = _asset("https://cdn.example.com/line.wav")


def test_POST不带mode与素材时mode透传None且三组素材为空元组():
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=_body(), headers=_AUTH)
    assert r.status_code == 202
    spec = orch.submitted[0][2]
    # 空素材等价 g5a：是否为 text 由编排器 resolve_mode 仲裁，边界只透传 None
    assert spec["mode"] is None
    assert spec["reference_images"] == ()
    assert spec["reference_videos"] == ()
    assert spec["reference_audios"] == ()


def test_POST未显式mode时透传None交由编排器按素材结构仲裁():
    orch = StubOrchestrator()
    body = _body(reference_images=[_IMG_A])
    r = _client(orch).post("/v1/videos", json=body, headers=_AUTH)
    assert r.status_code == 202
    spec = orch.submitted[0][2]
    assert spec["mode"] is None
    assert spec["reference_images"] == ("https://cdn.example.com/a.jpg",)
    assert spec["reference_videos"] == ()
    assert spec["reference_audios"] == ()


@pytest.mark.parametrize("mode,payload", [
    ("text", {}),
    ("first_last_frame", {"reference_images": [_IMG_A, _IMG_B]}),
    ("multi_image", {"reference_images": [_IMG_A, _IMG_B]}),
    ("video_reference", {"reference_videos": [_VID_10S]}),
    ("image_audio_lipsync",
     {"reference_images": [_IMG_A], "reference_audios": [_AUD]}),
    ("mixed_multimodal",
     {"reference_images": [_IMG_A], "reference_videos": [_VID_10S],
      "reference_audios": [_AUD]}),
])
def test_POST显式mode与各组素材URL元组按契约透传(mode, payload):
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=_body(mode=mode, **payload),
                           headers=_AUTH)
    assert r.status_code == 202
    spec = orch.submitted[0][2]
    assert spec["mode"] == mode
    for key, items in payload.items():
        assert spec[key] == tuple(item["url"] for item in items)
    for key in ({"reference_images", "reference_videos",
                 "reference_audios"} - set(payload)):
        assert spec[key] == ()


def test_POST参考视频时长元数据在合法范围内不影响受理():
    orch = StubOrchestrator()
    body = _body(mode="video_reference",
                 reference_videos=[_asset("https://cdn.example.com/r.mp4",
                                          duration_seconds=15)])
    r = _client(orch).post("/v1/videos", json=body, headers=_AUTH)
    assert r.status_code == 202
    assert orch.submitted[0][2]["reference_videos"] == (
        "https://cdn.example.com/r.mp4",)


_INVALID_REQUEST = "invalid_request"


def _expect_422(body):
    orch = StubOrchestrator()
    r = _client(orch).post("/v1/videos", json=body, headers=_AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == _INVALID_REQUEST
    assert orch.submitted == []  # 边界拒绝不进入编排器、不产生任何费用
    return r


def test_POST非http_scheme的素材URL返回422():
    _expect_422(_body(mode="multi_image",
                      reference_images=[_asset("ftp://cdn.example.com/a.jpg")]))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8088/file.mp4",
    "http://169.254.169.254/latest/meta-data",
])
def test_POST内网素材URL返回422(url):
    _expect_422(_body(mode="video_reference",
                      reference_videos=[_asset(url, duration_seconds=5)]))


def test_POST无scheme的素材URL返回422():
    _expect_422(_body(mode="multi_image",
                      reference_images=[_asset("not-a-url")]))


def test_POST单组素材超过30个返回422():
    _expect_422(_body(
        mode="multi_image",
        reference_images=[_asset(f"https://cdn.example.com/{i}.jpg")
                          for i in range(31)]))


def test_POST素材总数超过40个返回422():
    _expect_422(_body(
        mode="mixed_multimodal",
        reference_images=[_asset(f"https://cdn.example.com/{i}.jpg")
                          for i in range(30)],
        reference_videos=[_asset(f"https://cdn.example.com/{i}.mp4")
                          for i in range(11)]))


def test_POST参考视频超过15秒返回422():
    _expect_422(_body(
        mode="video_reference",
        reference_videos=[_asset("https://cdn.example.com/r.mp4",
                                 duration_seconds=15.1)]))


def test_POSTprompt超长返回422():
    _expect_422(_body(prompt="雪" * 8001))


def test_POST素材字段结构错误返回统一422错误体():
    # reference_images 传字符串而非数组：Pydantic 结构错误也必须是统一错误体
    _expect_422(_body(reference_images="https://cdn.example.com/a.jpg"))


def test_POST素材项缺少url返回统一422错误体():
    _expect_422(_body(reference_images=[{"duration_seconds": 5}]))


def test_POST参考视频时长非正数返回统一422错误体():
    _expect_422(_body(
        mode="video_reference",
        reference_videos=[_asset("https://cdn.example.com/r.mp4",
                                 duration_seconds=0)]))
