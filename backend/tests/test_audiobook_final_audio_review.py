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
