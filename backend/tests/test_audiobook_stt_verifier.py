from __future__ import annotations

import pytest

from app.services.audiobook.stt_verifier import STTVerifier


def test_stt_normalizer_removes_format_noise_but_preserves_word_boundaries():
    verifier = STTVerifier(enable_whisper=False)

    assert (
        verifier._normalize_compare_text("Random emojis: 😉 in the Read😉Me😉? Well... why not?")
        == "random emojis in the readme well why not"
    )
    assert verifier._normalize_compare_text("Here's Johnny") == "heres johnny"
    assert verifier._normalize_compare_text("你好，世界！") == "你好 世界"


@pytest.mark.parametrize(
    ("source", "transcript"),
    [
        ("Look at that firefly glow.", "Look at that fire fly glow."),
        ("I went to high school yesterday.", "I went to highschool yesterday."),
        ("Here's Johnny.", "Heres Johnny"),
        ("你好，世界！", "你好世界"),
    ],
)
def test_stt_similarity_normalizes_common_transcription_spacing(source: str, transcript: str):
    verifier = STTVerifier(enable_whisper=False)

    assert verifier._calculate_similarity(source, transcript) == pytest.approx(1.0)
    assert verifier._calculate_word_error_rate(source, transcript) == pytest.approx(0.0)


def test_stt_word_error_rate_still_detects_real_content_loss():
    verifier = STTVerifier(enable_whisper=False)

    assert verifier._calculate_word_error_rate("The quick brown fox.", "The quick fox.") > 0.0
    assert verifier._calculate_similarity("The quick brown fox.", "The quick fox.") < 1.0


def test_stt_comparison_tolerates_common_english_homophones():
    verifier = STTVerifier(enable_whisper=False)

    source = "Put their book right here before two."
    transcript = "Put there book write hear before too."

    assert verifier._calculate_similarity(source, transcript) == pytest.approx(1.0)
    assert verifier._calculate_word_error_rate(source, transcript) == pytest.approx(0.0)
