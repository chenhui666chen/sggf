import asyncio
import json

from app.services.zhuque_ai_detect import ZhuqueAIDetectService


def make_service() -> ZhuqueAIDetectService:
    """构造隔离配置的实例，避免读取本机 .env 中的真实网关凭证。"""
    service = ZhuqueAIDetectService()
    service.gateway_url = "https://gw.example.com"
    service.api_key = "test-key"
    return service


# 官方文档同步响应示例（zhuque-text/classify）
DOC_EXAMPLE_RESPONSE = {
    "status": "success",
    "softmax_confidence": 0.9274,
    "ratio_confidence": 1.0,
    "labels_ratio": {"0": 0.0001, "1": 0.0001, "2": 0.9999},
    "segment_labels": [
        {"text": "hello world", "label": 2, "conf": 0.9274, "order": 1, "position": [0, 11]}
    ],
    "msg": "",
}


# ── 请求构建 ──────────────────────────────────────────────────────────────

def test_build_payload_contains_text_and_default_merge():
    service = make_service()
    payload = service._build_payload("一段待检测文本")
    assert payload["text"] == "一段待检测文本"
    assert payload["is_merge"] is True


def test_build_payload_respects_merge_disabled():
    service = make_service()
    service.is_merge = False
    payload = service._build_payload("逐段检测")
    assert payload["is_merge"] is False


def test_build_headers_use_bearer_auth():
    service = make_service()
    headers = service._build_headers()
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["Content-Type"] == "application/json"


def test_classify_url_appends_zhuque_text_route():
    service = make_service()
    assert service.classify_url == "https://gw.example.com/v1/providers/zhuque-text/classify"


def test_classify_url_strips_trailing_slash_of_gateway():
    service = make_service()
    service.gateway_url = "https://gw.example.com/"
    assert service.classify_url == "https://gw.example.com/v1/providers/zhuque-text/classify"


def test_policy_version_changes_with_gateway():
    service = make_service()
    before = service.detection_policy_version
    service.gateway_url = "https://other.example.com"
    assert service.detection_policy_version != before


# ── 响应解析 ──────────────────────────────────────────────────────────────

def test_parse_response_success_contract_fields():
    service = make_service()
    result = service._parse_response(DOC_EXAMPLE_RESPONSE, "hello world")
    assert result["success"] is True
    assert result["provider"] == "zhuque-text"
    assert result["raw_response"] == DOC_EXAMPLE_RESPONSE


def test_parse_response_maps_ai_score_from_ratio_confidence():
    """ai_score 对齐项目 0-100 语义：整体疑似 AI 占比 × 100 取整。"""
    service = make_service()
    result = service._parse_response(DOC_EXAMPLE_RESPONSE, "hello world")
    assert result["ai_score"] == 100


def test_parse_response_exposes_confidences_and_labels_ratio():
    service = make_service()
    result = service._parse_response(DOC_EXAMPLE_RESPONSE, "hello world")
    assert result["softmax_confidence"] == 0.9274
    assert result["labels_ratio"] == {"0": 0.0001, "1": 0.0001, "2": 0.9999}


def test_parse_response_maps_segment_labels_with_positions():
    service = make_service()
    result = service._parse_response(DOC_EXAMPLE_RESPONSE, "hello world")
    segments = result["segment_labels"]
    assert segments == [
        {
            "text": "hello world",
            "label": 2,
            "conf": 0.9274,
            "order": 1,
            "start": 0,
            "end": 11,
        }
    ]


def test_parse_response_segment_label_is_human_when_all_zero():
    service = make_service()
    resp = {
        "status": "success",
        "softmax_confidence": 0.01,
        "ratio_confidence": 0.0,
        "labels_ratio": {"0": 0.99, "1": 0.005, "2": 0.005},
        "segment_labels": [
            {"text": "人写的", "label": 0, "conf": 0.01, "order": 1, "position": [0, 3]}
        ],
        "msg": "",
    }
    result = service._parse_response(resp, "人写的")
    assert result["ai_score"] == 0
    assert result["segment_labels"][0]["label"] == 0


def test_parse_response_failure_status_returns_error_dict():
    service = make_service()
    resp = {"status": "failed", "msg": "provider_not_allowed"}
    result = service._parse_response(resp, "x")
    assert result["success"] is False
    assert "provider_not_allowed" in result["error"]
    assert result["ai_score"] is None


def test_parse_response_missing_status_treated_as_invalid():
    service = make_service()
    result = service._parse_response({"foo": 1}, "x")
    assert result["success"] is False
    assert result["ai_score"] is None


# ── 端到端（替换传输层接缝） ──────────────────────────────────────────────

def _patch_post(service, responses):
    """替换 _post_json 接缝，返回记录到的请求列表。"""
    calls = []

    async def fake_post(url, headers, payload):
        calls.append({"url": url, "headers": headers, "payload": payload})
        resp = responses[len(calls) - 1]
        if isinstance(resp, Exception):
            raise resp
        return resp

    service._post_json = fake_post
    return calls


def test_detect_ai_content_posts_to_classify_url_with_bearer():
    service = make_service()
    calls = _patch_post(service, [DOC_EXAMPLE_RESPONSE])

    result = asyncio.run(service.detect_ai_content("hello world"))

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/v1/providers/zhuque-text/classify")
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert json.loads(json.dumps(calls[0]["payload"]))["text"] == "hello world"


def test_detect_ai_content_missing_credentials_returns_failure():
    service = make_service()
    service.api_key = ""
    _patch_post(service, [DOC_EXAMPLE_RESPONSE])

    result = asyncio.run(service.detect_ai_content("hello world"))

    assert result["success"] is False
    assert "ZHUQUE" in result["error"]


def test_detect_ai_content_retries_once_on_http_429():
    service = make_service()
    from app.services.zhuque_ai_detect import RateLimitedError
    calls = _patch_post(service, [RateLimitedError("429"), DOC_EXAMPLE_RESPONSE])

    result = asyncio.run(service.detect_ai_content("hello world"))

    assert result["success"] is True
    assert len(calls) == 2


def test_detect_ai_content_exhausted_rate_limit_marks_rate_limited():
    service = make_service()
    from app.services.zhuque_ai_detect import RateLimitedError
    calls = _patch_post(service, [RateLimitedError("429"), RateLimitedError("429")])

    result = asyncio.run(service.detect_ai_content("hello world"))

    assert result["success"] is False
    assert result["rate_limited"] is True
    assert len(calls) == 2


def test_detect_ai_content_network_error_returns_failure_dict():
    service = make_service()
    _patch_post(service, [ConnectionError("connect timeout")])

    result = asyncio.run(service.detect_ai_content("hello world"))

    assert result["success"] is False
    assert result["rate_limited"] is False
    assert "connect timeout" in result["error"]
