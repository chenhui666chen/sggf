from app.services.tencent_ai_detect import TencentAIDetectService


def test_detection_text_keeps_up_to_ten_thousand_unicode_characters():
    text = "文" * 12000

    prepared = TencentAIDetectService.prepare_text(text)

    assert len(prepared) == 10000
    assert prepared == text[:10000]


def test_detection_text_does_not_truncate_text_below_limit():
    text = "文" * 8000

    assert TencentAIDetectService.prepare_text(text) == text
