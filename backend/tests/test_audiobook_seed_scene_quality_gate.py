from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.quality_gate import SceneAudioQualityGate
from app.services.audiobook.scene_engine.quality_policy import (
    DEFAULT_SCENE_AUDIO_QUALITY_POLICY,
    SceneAudioQualityPolicy,
)


def test_quality_gate_accepts_punctuation_and_spacing_differences() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("把头抬起来。", "御医，诊断她的身体状况。"),
        subtitle_payload={
            "subtitles": [
                {"text": "把头抬起来!"},
                {"text": "御医, 诊断她的身体状况"},
            ]
        },
    )

    assert report.passed is True
    assert report.status == "passed"
    assert report.transcript_source == "provider_subtitle"
    assert report.transcript_coverage == 1.0
    assert report.missing_lines == ()
    assert report.extra_lines == ()
    assert report.order_valid is True


def test_quality_gate_rejects_missing_dialogue() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("把头抬起来。", "遵旨。", "快试药吧！"),
        subtitle_payload=[{"text": "把头抬起来。"}, {"text": "快试药吧！"}],
    )

    assert report.passed is False
    assert report.status == "failed"
    assert report.missing_lines == ("遵旨。",)
    assert report.transcript_coverage < 0.99
    assert report.fallback_reason == "transcript_fidelity_failed"


def test_quality_gate_rejects_undeclared_recognizable_speech() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("抓住她！", "是！"),
        subtitle_payload=[
            {"text": "抓住她！"},
            {"text": "她跑不掉了。"},
            {"text": "是！"},
        ],
    )

    assert report.passed is False
    assert report.missing_lines == ()
    assert report.extra_lines == ("她跑不掉了",)


def test_quality_gate_rejects_dialogue_order_changes() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("你配合我。", "我为什么要配合你？"),
        subtitle_payload=[{"text": "我为什么要配合你？"}, {"text": "你配合我。"}],
    )

    assert report.passed is False
    assert report.order_valid is False


def test_quality_gate_uses_asr_when_provider_subtitles_are_missing() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("遇上我是他最开心的一件事。",),
        subtitle_payload=None,
        asr_transcript="遇上我，是他最开心的一件事。",
    )

    assert report.passed is True
    assert report.transcript_source == "asr"


def test_quality_gate_does_not_treat_declared_vocalizations_as_extra_speech() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("不要啊！",),
        expected_vocalizations=("啊", "嗯", "喘息"),
        subtitle_payload=[{"text": "不要啊！啊，嗯。"}],
    )

    assert report.passed is True
    assert report.extra_lines == ()


def test_quality_gate_requires_asr_when_no_transcript_is_available() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(expected_texts=("试药。",), subtitle_payload=None)

    assert report.passed is False
    assert report.status == "needs_asr"
    assert report.fallback_reason == "transcript_unavailable"
    assert gate.next_action(report, render_attempt_count=1, split_attempted=False) == "run_asr"


def test_quality_gate_allows_deliberate_scene_silence_ratio() -> None:
    gate = SceneAudioQualityGate()

    report = gate.evaluate(
        expected_texts=("门外有人，先别出声。",),
        subtitle_payload={"text": "门外有人，先别出声。"},
        audio_metadata={
            "audio_decodable": True,
            "duration_s": 12.0,
            "silence_ratio": 0.75,
        },
    )

    assert report.passed is True
    assert report.fallback_reason is None


def test_quality_gate_recovery_is_finite() -> None:
    gate = SceneAudioQualityGate()
    failed = gate.evaluate(
        expected_texts=("试药。",),
        subtitle_payload=[{"text": "开始吧。"}],
    )

    assert gate.next_action(failed, render_attempt_count=0, split_attempted=False) == "retry_scene"
    assert gate.next_action(failed, render_attempt_count=1, split_attempted=False) == "split_scene"
    assert gate.next_action(failed, render_attempt_count=1, split_attempted=True) == "legacy_stems"


def test_quality_policy_hash_changes_when_threshold_changes() -> None:
    policy = DEFAULT_SCENE_AUDIO_QUALITY_POLICY
    changed = replace(policy, clipping_ratio_threshold=0.02)

    assert policy.fingerprint()
    assert policy.fingerprint() != changed.fingerprint()


def test_quality_gate_uses_versioned_policy_for_ratio_metadata() -> None:
    policy = SceneAudioQualityPolicy(
        clipping_ratio_threshold=0.5,
        silence_ratio_threshold=0.95,
    )
    gate = SceneAudioQualityGate(policy=policy)

    report = gate.evaluate(
        expected_texts=("台词完整。",),
        subtitle_payload=[{"text": "台词完整。"}],
        audio_metadata={
            "audio_decodable": True,
            "duration_s": 1.0,
            "clipping_ratio": 0.2,
            "silence_ratio": 0.92,
        },
    )

    assert report.passed is True
    assert report.clipping is False
    assert report.silence is False
