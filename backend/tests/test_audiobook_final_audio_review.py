import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.audio_mixer import (
    AudioQualityGrade,
    AudioQualityIssue,
    AudioQualityReport,
)
from app.services.audiobook.engine_pkg._review_mixin import ReviewMixin


class FakeAudioMixer:
    def __init__(self, report, expected_audio_data=b"audio"):
        self.report = report
        self.expected_audio_data = expected_audio_data

    def analyze_quality(self, audio_data):
        assert audio_data == self.expected_audio_data
        return self.report


class ReviewHarness(ReviewMixin):
    def __init__(self, report, expected_audio_data=b"audio"):
        self.audio_mixer = FakeAudioMixer(report, expected_audio_data)
        self.audio_quality_reviewer = SimpleNamespace(
            quality_standards={
                "min_episode_duration": 600,
                "max_episode_duration": 2100,
            }
        )


def test_final_audio_review_includes_prompt_audio_quality_feedback_by_model():
    report = AudioQualityReport(
        grade=AudioQualityGrade.EXCELLENT,
        score=98.0,
        issues=[],
        metrics={},
        passed=True,
    )
    segments = [
        SimpleNamespace(
            voice_params={
                "resolved_tts_model": "mimo-v2.5-tts",
                "provider_prompt_snapshot": {
                    "model": "mimo-v2.5-tts",
                    "provider_prompt": {
                        "inline_tag_strategy": {
                            "model_family": "mimo",
                            "placement": "assistant_prefix",
                            "style_tags": ["tense", "tense"],
                            "inline_tags": ["whisper"],
                            "use_tag_parser": False,
                        }
                    },
                },
            }
        ),
        {
            "voice_params": {
                "resolved_tts_model": "seed-tts-2.0-expressive",
                "provider_prompt_snapshot": {
                    "model": "seed-tts-2.0-expressive",
                    "provider_prompt": {
                        "inline_tag_strategy": {
                            "model_family": "doubao",
                            "placement": "text_prefix",
                            "style_tags": ["narration"],
                            "inline_tags": ["whisper"],
                            "use_tag_parser": True,
                        }
                    },
                },
            }
        },
        SimpleNamespace(
            voice_params={
                "resolved_tts_model": "qwen3-tts-instruct-flash",
                "provider_prompt_snapshot": {
                    "model": "qwen3-tts-instruct-flash",
                    "provider_prompt": {"instructions": "Read calmly."},
                },
            }
        ),
    ]

    review = ReviewHarness(report)._final_audio_review(
        audio_info={"duration_seconds": 120.0},
        file_size=2048,
        audio_data=None,
        script_segments=segments,
        audio_list=[b"mimo-audio", b"doubao-audio", b""],
    )

    feedback = review["prompt_audio_quality"]

    assert feedback["available"] is True
    assert feedback["coverage"] == {
        "segments_count": 3,
        "audio_segments_count": 2,
        "missing_audio_count": 1,
        "provider_prompt_snapshot_count": 3,
        "inline_tag_strategy_count": 2,
        "manual_review_pending_count": 2,
    }
    assert feedback["by_model"]["mimo-v2.5-tts"] == {
        "model_family": "mimo",
        "segments_count": 1,
        "audio_segments_count": 1,
        "missing_audio_count": 0,
        "provider_prompt_snapshot_count": 1,
        "inline_tag_strategy_count": 1,
        "use_tag_parser_count": 0,
        "tag_count": 2,
        "manual_review_segment_indices": [0],
        "manual_review_fields": {
            "tag_parse_success": None,
            "text_contamination": None,
            "score": None,
        },
    }
    assert feedback["by_model"]["seed-tts-2.0-expressive"]["model_family"] == "doubao"
    assert feedback["by_model"]["seed-tts-2.0-expressive"]["use_tag_parser_count"] == 1
    assert feedback["by_model"]["qwen3-tts-instruct-flash"]["manual_review_segment_indices"] == []


def test_final_audio_review_uses_audio_presence_without_segment_bytes():
    report = AudioQualityReport(
        grade=AudioQualityGrade.EXCELLENT,
        score=98.0,
        issues=[],
        metrics={},
        passed=True,
    )
    segments = [
        SimpleNamespace(voice_params={"resolved_tts_model": "seed-audio-1.0"}),
        SimpleNamespace(voice_params={"resolved_tts_model": "seed-audio-1.0"}),
    ]

    review = ReviewHarness(report)._final_audio_review(
        audio_info={"duration_seconds": 120.0},
        file_size=2048,
        audio_data=None,
        script_segments=segments,
        audio_list=None,
        audio_presence=[True, False],
    )

    assert review["prompt_audio_quality"]["coverage"] == {
        "segments_count": 2,
        "audio_segments_count": 1,
        "missing_audio_count": 1,
        "provider_prompt_snapshot_count": 0,
        "inline_tag_strategy_count": 0,
        "manual_review_pending_count": 0,
    }


def test_final_audio_review_includes_waveform_quality_metrics():
    report = AudioQualityReport(
        grade=AudioQualityGrade.POOR,
        score=45.0,
        issues=[
            AudioQualityIssue(
                severity="high",
                category="clipping",
                description="检测到音频削波",
                suggestion="降低音量",
            )
        ],
        metrics={
            "loudness_dbfs": -2.0,
            "max_dbfs": -0.1,
            "sample_rate": 44100,
            "channels": 2,
        },
        passed=False,
    )

    review = ReviewHarness(report)._final_audio_review(
        audio_info={"duration_seconds": 30.0, "sample_rate": 44100},
        file_size=1024,
        audio_data=b"audio",
    )

    assert review["severity"] == "error"
    assert review["summary"] == "存在音频质量问题"
    assert review["waveform_quality"]["available"] is True
    assert review["waveform_quality"]["grade"] == "D"
    assert review["waveform_quality"]["score"] == 45.0
    assert review["waveform_quality"]["metrics"]["max_dbfs"] == -0.1
    assert review["waveform_quality"]["issues"][0]["category"] == "clipping"
    assert any("检测到音频削波" in warning for warning in review["warnings"])


def test_final_audio_review_keeps_basic_duration_guard_without_audio_data():
    review = ReviewHarness(
        AudioQualityReport(
            grade=AudioQualityGrade.EXCELLENT,
            score=100.0,
            issues=[],
            metrics={},
            passed=True,
        )
    )._final_audio_review(
        audio_info={"duration_seconds": 20.0},
        file_size=0,
        audio_data=None,
    )

    assert review["severity"] == "warning"
    assert review["waveform_quality"] == {
        "available": False,
        "reason": "missing_audio_data",
    }
    assert any("音频时长偏短" in warning for warning in review["warnings"])


def test_final_audio_review_analyzes_empty_audio_bytes():
    report = AudioQualityReport(
        grade=AudioQualityGrade.POOR,
        score=0.0,
        issues=[
            AudioQualityIssue(
                severity="high",
                category="format",
                description="无法分析音频：pydub 不可用或音频为空",
                suggestion="检查最终混音输出",
            )
        ],
        metrics={},
        passed=False,
    )

    review = ReviewHarness(report, expected_audio_data=b"")._final_audio_review(
        audio_info={"duration_seconds": 0.0},
        file_size=0,
        audio_data=b"",
    )

    assert review["severity"] == "error"
    assert review["summary"] == "存在音频质量问题"
    assert review["waveform_quality"]["available"] is True
    assert review["waveform_quality"]["score"] == 0.0
    assert review["waveform_quality"]["issues"][0]["category"] == "format"
    assert any("音频为空" in warning for warning in review["warnings"])
