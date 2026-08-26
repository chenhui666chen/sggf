import asyncio
import base64
import json

from app.services.tencent_ai_detect import TencentAIDetectService


def make_service() -> TencentAIDetectService:
    """构造隔离配置的实例，避免读取本机 .env 中的真实策略。"""
    service = TencentAIDetectService()
    service.secret_id = "test-id"
    service.secret_key = "test-key"
    service.biztype = ""
    return service


# 官方文档示例响应（精简）：含 HitInfos.Type 归因与 HitSnippetInfos 命中片段位置
DOC_EXAMPLE_RESPONSE = {
    "Response": {
        "RequestId": "req-1",
        "BizType": "content_input",
        "Label": "Illegal",
        "SubLabel": "Drug",
        "Suggestion": "Block",
        "Keywords": [],
        "Score": 87,
        "DataId": "YIumnjV2MZibqk6G",
        "DetailResults": [
            {
                "Label": "Illegal",
                "SubLabel": "Drug",
                "Suggestion": "Block",
                "Keywords": [],
                "Score": 87,
                "LibType": 0,
                "LibId": "",
                "LibName": "",
                "HitInfos": [
                    {"Type": "Keyword", "Keyword": "你好呀", "LibName": "",
                     "Positions": [{"Start": 0, "End": 3}]},
                    {"Type": "Model", "Keyword": "", "LibName": "",
                     "Positions": [{"Start": 0, "End": 3}]},
                ],
                "HitSnippetInfos": [],
            }
        ],
        "HitType": "text_nlp_tianji",
        "SentimentAnalysis": {},
        "HitSnippetInfos": [
            {"Snippet": "你好呀", "AtomicName": "", "AtomicId": "",
             "Positions": [{"Start": 0, "End": 3}]}
        ],
    }
}

RATE_LIMIT_ERROR = {
    "Response": {
        "Error": {"Code": "RequestLimitExceeded", "Message": "频率超限"},
        "RequestId": "req-err",
    }
}


def test_detection_text_keeps_up_to_ten_thousand_unicode_characters():
    text = "文" * 12000

    prepared = TencentAIDetectService.prepare_text(text)

    assert len(prepared) == 10000
    assert prepared == text[:10000]


def test_detection_text_does_not_truncate_text_below_limit():
    text = "文" * 8000

    assert TencentAIDetectService.prepare_text(text) == text


def test_build_payload_sets_aigc_type_and_source_language():
    payload = make_service()._build_payload("测试文本")
    assert payload["Type"] == "TEXT_AIGC"
    assert payload["SourceLanguage"] == "zh"
    assert base64.b64decode(payload["Content"]).decode("utf-8") == "测试文本"
    assert "DataId" not in payload
    assert "BizType" not in payload


def test_build_payload_truncates_long_text_before_encoding():
    payload = make_service()._build_payload("文" * 12000)
    assert len(base64.b64decode(payload["Content"]).decode("utf-8")) == 10000


def test_sanitize_data_id_keeps_allowed_characters_only():
    assert TencentAIDetectService.sanitize_data_id("sample-01_A@#") == "sample-01_A@#"
    assert TencentAIDetectService.sanitize_data_id("bad chars!$%") == "badchars"


def test_sanitize_data_id_truncates_to_64_characters():
    assert len(TencentAIDetectService.sanitize_data_id("a" * 80)) == 64


def test_build_payload_skips_data_id_when_sanitization_yields_empty():
    payload = make_service()._build_payload("文本", data_id="$$%%")
    assert "DataId" not in payload


def test_parse_response_keeps_existing_contract_fields():
    result = make_service()._parse_response(DOC_EXAMPLE_RESPONSE, "你好呀")
    assert result["success"] is True
    assert result["ai_score"] == 87
    assert result["label"] == "Illegal"
    assert result["sub_label"] == "Drug"
    assert result["suggestion"] == "Block"
    assert result["hit_type"] == "text_nlp_tianji"


def test_parse_response_extracts_hit_snippet_positions():
    result = make_service()._parse_response(DOC_EXAMPLE_RESPONSE, "你好呀")
    assert result["hit_snippets"] == [
        {"snippet": "你好呀", "positions": [{"start": 0, "end": 3}]}
    ]


def test_parse_response_attributes_hits_to_keyword_or_model():
    result = make_service()._parse_response(DOC_EXAMPLE_RESPONSE, "你好呀")
    segments = result["ai_trace_details"]["problematic_segments"]
    assert [s["hit_type"] for s in segments] == ["Keyword", "Model"]
    assert segments[0]["keyword"] == "你好呀"


def test_parse_response_records_library_attribution_per_label():
    result = make_service()._parse_response(DOC_EXAMPLE_RESPONSE, "你好呀")
    assert result["ai_trace_details"]["label_scores"] == {"Illegal": 87}
    assert result["ai_trace_details"]["label_libraries"] == {
        "Illegal": {"lib_type": 0, "lib_id": "", "lib_name": ""}
    }


def test_parse_response_marks_rate_limited_errors():
    result = make_service()._parse_response(RATE_LIMIT_ERROR, "文本")
    assert result["success"] is False
    assert result["rate_limited"] is True
    assert "RequestLimitExceeded" in result["error"]


def test_parse_response_other_errors_are_not_rate_limited():
    resp = {"Response": {"Error": {"Code": "UnauthorizedOperation.Unauthorized",
                                   "Message": "未开通"}}}
    result = make_service()._parse_response(resp, "文本")
    assert result["success"] is False
    assert result["rate_limited"] is False


def test_detect_ai_content_sends_data_id_and_source_language_in_payload():
    service = make_service()
    captured = {}

    async def fake_post(headers, payload_str):
        captured.update(json.loads(payload_str))
        return DOC_EXAMPLE_RESPONSE

    service._post_payload = fake_post
    result = asyncio.run(service.detect_ai_content("你好呀", data_id="sample-1"))
    assert result["success"] is True
    assert captured["DataId"] == "sample-1"
    assert captured["SourceLanguage"] == "zh"


def test_detect_ai_content_retries_once_when_rate_limited():
    service = make_service()
    service.RATE_LIMIT_BACKOFF_SECONDS = 0
    calls = []

    async def fake_post(headers, payload_str):
        calls.append(payload_str)
        if len(calls) == 1:
            return RATE_LIMIT_ERROR
        return DOC_EXAMPLE_RESPONSE

    service._post_payload = fake_post
    result = asyncio.run(service.detect_ai_content("你好呀"))
    assert result["success"] is True
    assert len(calls) == 2


def test_detect_ai_content_gives_up_after_single_rate_limit_retry():
    service = make_service()
    service.RATE_LIMIT_BACKOFF_SECONDS = 0
    calls = []

    async def fake_post(headers, payload_str):
        calls.append(payload_str)
        return RATE_LIMIT_ERROR

    service._post_payload = fake_post
    result = asyncio.run(service.detect_ai_content("你好呀"))
    assert result["success"] is False
    assert result["rate_limited"] is True
    assert len(calls) == 2
