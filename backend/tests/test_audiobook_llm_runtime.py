import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


class DummyLLM:
    def __init__(self, response='{"ok": true}'):
        self.response = response
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_audiobook_llm_model_default_and_configured_official_id(monkeypatch):
    from app.services.audiobook.llm_config import get_audiobook_llm_model

    monkeypatch.delenv("AUDIOBOOK_LLM_MODEL", raising=False)
    assert get_audiobook_llm_model() == "deepseek-v4-flash"

    monkeypatch.setenv("AUDIOBOOK_LLM_MODEL", "deepseek-v4-flash")
    assert get_audiobook_llm_model() == "deepseek-v4-flash"


def test_audiobook_script_review_env_switch(monkeypatch):
    from app.services.audiobook.llm_config import is_audiobook_script_review_enabled

    monkeypatch.delenv("AUDIOBOOK_ENABLE_SCRIPT_REVIEW", raising=False)
    assert is_audiobook_script_review_enabled() is True

    monkeypatch.setenv("AUDIOBOOK_ENABLE_SCRIPT_REVIEW", "false")
    assert is_audiobook_script_review_enabled() is False

    monkeypatch.setenv("AUDIOBOOK_ENABLE_SCRIPT_REVIEW", "on")
    assert is_audiobook_script_review_enabled() is True


@pytest.mark.asyncio
async def test_call_audiobook_llm_async_uses_flash_model():
    from app.services.audiobook.llm_client import call_audiobook_llm_async

    llm = DummyLLM()
    response = await call_audiobook_llm_async(
        llm,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=5,
        use_cache=False,
    )

    assert response == '{"ok": true}'
    assert llm.calls[0]["model"] == "deepseek-v4-flash"
    assert llm.calls[0]["max_tokens"] == 5
    assert llm.calls[0]["use_cache"] is False


@pytest.mark.asyncio
async def test_call_audiobook_llm_sync_inside_running_loop():
    from app.services.audiobook.llm_client import call_audiobook_llm_sync

    llm = DummyLLM()
    response = call_audiobook_llm_sync(
        llm,
        messages=[{"role": "user", "content": "ping"}],
        timeout_seconds=10,
    )

    assert response == '{"ok": true}'
    assert llm.calls[0]["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_call_audiobook_llm_sync_inside_running_loop_honors_timeout():
    import asyncio
    import concurrent.futures

    from app.services.audiobook.llm_client import call_audiobook_llm_sync

    class SlowLLM:
        async def chat(self, **kwargs):
            await asyncio.sleep(0.2)
            return '{"ok": true}'

    started_at = time.perf_counter()
    with pytest.raises((TimeoutError, asyncio.TimeoutError, concurrent.futures.TimeoutError)):
        call_audiobook_llm_sync(
            SlowLLM(),
            messages=[{"role": "user", "content": "ping"}],
            timeout_seconds=0.01,
        )

    assert time.perf_counter() - started_at < 0.15


@pytest.mark.asyncio
async def test_audiobook_llm_health_uses_configured_model():
    from app.services.audiobook.llm_client import check_audiobook_llm_health

    llm = DummyLLM()
    health = await check_audiobook_llm_health(llm, timeout_seconds=10)

    assert health.ok is True
    assert health.model == "deepseek-v4-flash"
    assert llm.calls[0]["model"] == "deepseek-v4-flash"


def test_llm_json_parser_handles_fences_comments_and_trailing_commas():
    from app.services.audiobook.llm_json import parse_llm_json_object

    payload = """
before
```json
{
  "theme": "x", // line comment
  "items": [1, 2,],
}
```
after
"""

    assert parse_llm_json_object(payload) == {"theme": "x", "items": [1, 2]}


def test_llm_json_parser_salvages_truncated_array():
    from app.services.audiobook.llm_json import parse_llm_json_array

    payload = '[{"text": "a"}, {"text": "b"}'

    assert parse_llm_json_array(payload) == [{"text": "a"}, {"text": "b"}]


def test_llm_json_parser_accepts_common_array_wrappers():
    from app.services.audiobook.llm_json import parse_llm_json_array

    assert parse_llm_json_array('{"segments": [{"text": "a"}]}') == [{"text": "a"}]
    assert parse_llm_json_array('{"payload": [{"text": "b"}]}') == [{"text": "b"}]


def test_llm_json_parser_ignores_thinking_tags_before_json():
    from app.services.audiobook.llm_json import parse_llm_json_array

    payload = """
<think>
模型内部推理里可能出现 [not json] 这类符号。
</think>
{"segments": [{"text": "a"}]}
"""

    assert parse_llm_json_array(payload) == [{"text": "a"}]


def test_llm_json_parser_handles_orphan_thinking_close_tag():
    from app.services.audiobook.llm_json import parse_llm_json_object

    payload = "前置推理残片 </think> {\"ok\": true}"

    assert parse_llm_json_object(payload) == {"ok": True}


def test_tts_prompt_normalizer_compacts_text_and_substitutes_words():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "\u200b\u4f60\u597d . . .   AI"

    assert normalize_tts_prompt(text) == "\u4f60\u597d\u2026\u2026\u4eba\u5de5\u667a\u80fd"


def test_tts_prompt_normalizer_respects_protected_words():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    assert normalize_tts_prompt("AI", protected_words={"AI"}) == "AI"


def test_tts_prompt_normalizer_replaces_latin_whole_words_only():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "PAID AI API APIs AI's"

    assert normalize_tts_prompt(text) == "PAID 人工智能 应用程序接口 应用程序接口 人工智能的"


def test_tts_prompt_normalizer_reads_percent_in_chinese_order():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "完成率50%，剩余 12.5% AI"

    assert normalize_tts_prompt(text) == "完成率百分之50，剩余 百分之12.5 人工智能"


def test_tts_prompt_normalizer_removes_thousands_separators():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "库存 1,000 件，增长 12,500%."

    assert normalize_tts_prompt(text, enable_word_substitution=False) == "库存 1000 件，增长 百分之12500."


def test_tts_prompt_normalizer_shortens_urls_to_domains():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "详见 https://www.example.com/books/1?q=abc，备用 www.docs.example.org/path。"

    assert (
        normalize_tts_prompt(text, enable_word_substitution=False)
        == "详见 example.com，备用 docs.example.org。"
    )


def test_tts_prompt_normalizer_expands_common_latin_abbreviations():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "Dr. Ada met Mr. Smith vs. Prof. Turing, etc."

    assert (
        normalize_tts_prompt(text, enable_word_substitution=False)
        == "Doctor Ada met Mister Smith versus Professor Turing, etcetera"
    )


def test_tts_prompt_normalizer_sentence_cases_shouting_latin_text():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "THE QUICK BROWN FOX JUMPED. THEN IT VANISHED!"

    assert (
        normalize_tts_prompt(text, enable_word_substitution=False)
        == "The quick brown fox jumped. Then it vanished!"
    )


def test_tts_prompt_normalizer_preserves_common_latin_acronyms_in_caps():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    text = "NASA FBI CIA"

    assert normalize_tts_prompt(text, enable_word_substitution=False) == "NASA FBI CIA"


def test_tts_prompt_normalizer_applies_custom_plural_substitutions():
    from app.services.audiobook.prompt_normalizer import normalize_tts_prompt

    assert (
        normalize_tts_prompt(
            "Kilohours away from Ariekei's home.",
            substitutions={"kilohour": "kilo hour", "Ariekei": "AriaKay"},
        )
        == "Kilo hours away from AriaKay's home."
    )


def test_tts_batch_item_uses_segment_level_pronunciation_overrides():
    from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin

    segment = SimpleNamespace(
        text="The Ariekei's API stayed PAID.",
        voice_params={
            "word_substitutions": {"Ariekei": "AriaKay"},
            "protected_words": ["API"],
        },
        emotion="neutral",
    )

    item = TTSMixin()._build_tts_batch_item(segment)

    assert item["text"] == "The AriaKay's API stayed PAID."


def test_tts_batch_item_auto_detects_language_type_when_missing():
    from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin

    segment = SimpleNamespace(
        text="第一章，星河在窗外缓慢旋转。",
        voice_params={},
        emotion="neutral",
    )

    item = TTSMixin()._build_tts_batch_item(segment)

    assert item["voice_params"]["language_type"] == "Chinese"
    assert item["voice_params"]["language_type_auto_detected"] is True


def test_tts_batch_item_preserves_explicit_language_type():
    from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin

    segment = SimpleNamespace(
        text="第一章，星河在窗外缓慢旋转。",
        voice_params={"language_type": "en"},
        emotion="neutral",
    )

    item = TTSMixin()._build_tts_batch_item(segment)

    assert item["voice_params"]["language_type"] == "English"
    assert "language_type_auto_detected" not in item["voice_params"]


def test_tts_batch_item_strips_spoken_pause_directives_before_synthesis():
    from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin

    segment = SimpleNamespace(
        text="必须走。（停顿一秒）继续。",
        voice_params={},
        emotion="neutral",
    )

    item = TTSMixin()._build_tts_batch_item(segment)

    assert item["text"] == "必须走。继续。"
    assert item["voice_params"]["pause_after_ms"] == 1000
    assert item["voice_params"]["pause_tag_applied"] is True
    assert "停顿" not in item["text"]


def test_qwen_language_detection_handles_non_chinese_scripts():
    from app.services.audiobook.tts_language import detect_qwen_language_type

    assert detect_qwen_language_type("彼は静かに夜空を見上げた。") == "Japanese"
    assert detect_qwen_language_type("그는 조용히 별을 바라보았다.") == "Korean"
    assert detect_qwen_language_type("Она тихо посмотрела на звезды.") == "Russian"


def test_segment_review_requests_accept_path_segment_index():
    from app.schemas.audiobook import SegmentRegenerateRequest, SegmentReviewRequest

    regenerate_request = SegmentRegenerateRequest(reason="retry", tts_model="qwen3-tts-instruct-flash")
    review_request = SegmentReviewRequest(quality_score=4.0)

    assert regenerate_request.segment_index is None
    assert review_request.segment_index is None


@pytest.mark.asyncio
async def test_voice_manager_chapter_analysis_inside_running_loop_uses_flash_model():
    from app.services.audiobook.voice_manager import VoiceManager

    llm = DummyLLM(
        '{"ZhangSan": {"gender": "male", "age_group": "adult", '
        '"personality": "calm", "confidence": 0.9}}'
    )
    manager = VoiceManager(llm_client=llm)
    segments = [
        SimpleNamespace(speaker="ZhangSan", text="I am here.", emotion="neutral")
    ]

    result = manager.analyze_chapter_characters(segments)

    assert result["ZhangSan"]["source"] == "chapter_analysis"
    assert llm.calls[0]["model"] == "deepseek-v4-flash"
