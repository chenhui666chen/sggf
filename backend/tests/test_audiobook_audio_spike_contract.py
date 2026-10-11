"""离线音频评测语料及已知缺陷检出力合同。"""

import pytest

from app.services.audiobook.scene_quality.audio_spike_contract import (
    STANDARD_CORPUS,
    SPIKE_CASES,
    assess_spike_detection,
    build_blind_manifest,
    build_voice_identity_scopes,
    validate_ab_pair,
)


def test_standard_corpus_covers_modes_emotions_and_pauses() -> None:
    assert len(STANDARD_CORPUS) == 7
    assert len({case.case_id for case in STANDARD_CORPUS}) == 7
    assert {case.mode for case in STANDARD_CORPUS} == {"narration", "dialogue", "monologue"}
    assert all(case.text and case.emotion and case.pause_expectation for case in STANDARD_CORPUS)
    assert all(case.audible_delivery_cue for case in STANDARD_CORPUS)
    assert all("[#" not in case.text for case in STANDARD_CORPUS)


def test_spike_cases_have_clean_controls_and_explicit_defect_dimensions() -> None:
    assert {case.defect for case in SPIKE_CASES} == {
        "omission", "substitution", "tag_leak", "pause_mismatch", "emotion_mismatch"
    }
    assert all(case.clean_id in {item.case_id for item in STANDARD_CORPUS} for case in SPIKE_CASES)
    assert all(case.dimension for case in SPIKE_CASES)


def test_blind_manifest_is_deterministic_and_hides_defect_labels() -> None:
    first, key = build_blind_manifest(["clean-1", "spike-1"], seed=42)
    second, second_key = build_blind_manifest(["clean-1", "spike-1"], seed=42)
    assert first == second and key == second_key
    assert set(key.values()) == {"clean-1", "spike-1"}
    assert all("clean" not in item and "spike" not in item for item in first)
    assert len(set(first)) == 2
    with pytest.raises(ValueError, match="duplicate"):
        build_blind_manifest(["same", "same"], seed=1)


def test_detection_counts_misses_false_alarms_and_abstentions_separately() -> None:
    result = assess_spike_detection({
        "clean-1": "pass", "clean-2": "fail",
        "spike-1": "fail", "spike-2": "pass", "spike-3": "not_assessable",
    }, clean_ids={"clean-1", "clean-2"}, spike_ids={"spike-1", "spike-2", "spike-3"})
    assert result == {
        "true_positive": 1, "false_negative": 1, "false_positive": 1,
        "true_negative": 1, "abstained": 1,
        "detection_rate": 1 / 3, "false_alarm_rate": 1 / 2,
    }


def test_detection_rejects_missing_or_unknown_verdicts() -> None:
    with pytest.raises(ValueError, match="missing"):
        assess_spike_detection({}, clean_ids={"a"}, spike_ids={"b"})
    with pytest.raises(ValueError, match="invalid"):
        assess_spike_detection({"a": "maybe", "b": "fail"}, clean_ids={"a"}, spike_ids={"b"})


def test_ab_pair_changes_only_prompt_and_preserves_processing() -> None:
    baseline = {
        "text_hash": "t", "voice_id": "voice", "model_id": "model",
        "audio_settings_hash": "settings", "postprocess_hash": "mix-v1",
        "prompt_hash": "before", "audio_path": "before.wav",
    }
    optimized = {**baseline, "prompt_hash": "after", "audio_path": "after.wav"}
    validate_ab_pair(baseline, optimized)
    with pytest.raises(ValueError, match="postprocess_hash"):
        validate_ab_pair(baseline, {**optimized, "postprocess_hash": "mix-v2"})
    with pytest.raises(ValueError, match="prompt_hash"):
        validate_ab_pair(baseline, {**optimized, "prompt_hash": "before"})
    with pytest.raises(ValueError, match="missing"):
        validate_ab_pair(baseline, {k: v for k, v in optimized.items() if k != "voice_id"})


def test_voice_identity_needs_multiple_segments_from_same_speaker_and_variant() -> None:
    samples = [
        {"sample_id": "a1", "speaker_id": "narrator", "variant": "A", "voice_id": "v"},
        {"sample_id": "a2", "speaker_id": "narrator", "variant": "A", "voice_id": "v"},
        {"sample_id": "b1", "speaker_id": "narrator", "variant": "B", "voice_id": "v"},
        {"sample_id": "b2", "speaker_id": "narrator", "variant": "B", "voice_id": "v"},
        {"sample_id": "other", "speaker_id": "guest", "variant": "A", "voice_id": "g"},
    ]
    scopes = build_voice_identity_scopes(samples)
    assert [(scope.speaker_id, scope.variant, scope.sample_ids, scope.status) for scope in scopes] == [
        ("guest", "A", ("other",), "not_assessable"),
        ("narrator", "A", ("a1", "a2"), "pending_sequence_review"),
        ("narrator", "B", ("b1", "b2"), "pending_sequence_review"),
    ]
    assert all(not hasattr(scope, "verdict") for scope in scopes)


def test_voice_identity_rejects_duplicate_samples_and_mixed_voice_assets() -> None:
    one = {"sample_id": "one", "speaker_id": "narrator", "variant": "A", "voice_id": "v"}
    with pytest.raises(ValueError, match="duplicate"):
        build_voice_identity_scopes([one, one])
    with pytest.raises(ValueError, match="voice_id"):
        build_voice_identity_scopes([one, {**one, "sample_id": "two", "voice_id": "other"}])
