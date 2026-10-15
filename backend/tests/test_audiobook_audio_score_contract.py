"""离线音频评分 JSON 合同；不调用供应商。"""

import json

import httpx
import pytest

from app.services.audiobook.scene_quality.audio_score_contract import (
    AUDIOGEN_DIMENSIONS,
    EMOTION_AUTHORITY_MODEL,
    SCORER_MODELS,
    TTS_DIMENSIONS,
    TTS_EMOTION_DIMENSIONS,
    TTS_VERIFIABLE_DIMENSIONS,
    VERIFIABLE_AUTHORITY_MODEL,
    parse_audio_score,
    parse_scoring_batch,
    tts_dimension_authority,
)
from app.services.audiobook.scene_quality.omni_audio_scorer import score_audio


def _payload(kind="tts"):
    names = TTS_DIMENSIONS if kind == "tts" else AUDIOGEN_DIMENSIONS
    return {
        "dimensions": {name: {"score": 4, "evidence": "音频中能听见目标表现。", "confidence": 0.8} for name in names},
    }


def test_tts_and_audiogen_use_distinct_complete_rubrics() -> None:
    assert "fidelity" in TTS_DIMENSIONS
    assert "fidelity" not in AUDIOGEN_DIMENSIONS
    assert "prompt_adherence" in AUDIOGEN_DIMENSIONS
    assert "prompt_adherence" not in TTS_DIMENSIONS
    assert parse_audio_score(json.dumps(_payload(), ensure_ascii=False), kind="tts", scope="sequence").dimensions["fidelity"].score == 4
    assert parse_audio_score(json.dumps(_payload("audiogen"), ensure_ascii=False), kind="audiogen").dimensions["prompt_adherence"].score == 4


def test_single_clip_voice_identity_must_abstain() -> None:
    payload = _payload()
    with pytest.raises(ValueError, match="voice_identity"):
        parse_audio_score(json.dumps(payload), kind="tts", scope="single_clip")
    payload["dimensions"]["voice_identity"] = {"score": None, "evidence": "单片段无法比较音色稳定性。", "confidence": 0.8}
    assert parse_audio_score(json.dumps(payload, ensure_ascii=False), kind="tts", scope="single_clip").dimensions["voice_identity"].score is None


def test_sequence_can_assess_voice_identity() -> None:
    score = parse_audio_score(json.dumps(_payload(), ensure_ascii=False), kind="tts", scope="sequence")
    assert score.dimensions["voice_identity"].score == 4


@pytest.mark.parametrize("mutation", [
    lambda p: p["dimensions"].pop("fidelity"),
    lambda p: p["dimensions"].update({"extra": {"score": 3, "evidence": "x", "confidence": 0.8}}),
    lambda p: p["dimensions"]["fidelity"].update({"score": True}),
    lambda p: p["dimensions"]["fidelity"].update({"score": 6}),
    lambda p: p["dimensions"]["fidelity"].update({"confidence": 2}),
    lambda p: p["dimensions"]["fidelity"].update({"evidence": ""}),
    lambda p: p["dimensions"]["fidelity"].update({"unknown": "x"}),
])
def test_invalid_dimension_payload_is_rejected(mutation) -> None:
    payload = _payload()
    mutation(payload)
    with pytest.raises(ValueError):
        parse_audio_score(json.dumps(payload), kind="tts", scope="sequence")


def test_abstention_requires_reason_and_does_not_receive_numeric_score() -> None:
    payload = _payload()
    payload["dimensions"]["voice_identity"] = {"score": None, "evidence": "无法听清说话人。", "confidence": 0.4}
    parsed = parse_audio_score(json.dumps(payload, ensure_ascii=False), kind="tts", scope="sequence")
    assert parsed.dimensions["voice_identity"].score is None
    payload["dimensions"]["voice_identity"]["evidence"] = ""
    with pytest.raises(ValueError):
        parse_audio_score(json.dumps(payload), kind="tts", scope="sequence")


def test_non_json_and_unknown_scope_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_audio_score("not-json", kind="tts")
    with pytest.raises(ValueError):
        parse_audio_score("[]", kind="tts")
    with pytest.raises(ValueError):
        parse_audio_score(json.dumps(_payload()), kind="tts", scope="invalid")


def test_two_scorers_keep_errors_out_of_score_statistics() -> None:
    assert len(SCORER_MODELS) == 2
    valid = json.dumps(_payload(), ensure_ascii=False)
    results = parse_scoring_batch(
        {SCORER_MODELS[0]: valid, SCORER_MODELS[1]: "not-json"},
        kind="tts", scope="sequence",
    )
    assert results[SCORER_MODELS[0]].status == "reviewed"
    assert results[SCORER_MODELS[0]].score is not None
    assert results[SCORER_MODELS[1]].status == "recorded_error"
    assert results[SCORER_MODELS[1]].score is None
    missing = parse_scoring_batch({SCORER_MODELS[0]: valid}, kind="tts", scope="sequence")
    assert missing[SCORER_MODELS[1]].status == "recorded_error"
    assert missing[SCORER_MODELS[1]].error_kind == "missing_response"


def test_two_scorer_batch_rejects_unknown_models() -> None:
    with pytest.raises(ValueError, match="unknown"):
        parse_scoring_batch({"made-up-model": "{}"}, kind="tts")


def test_offline_scorer_sends_audio_and_parses_both_provider_responses(tmp_path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF fixture")
    requests = []
    payload = _payload()
    payload["dimensions"]["voice_identity"] = {
        "score": None, "evidence": "单片段不可评估。", "confidence": 0.7,
    }

    def handle(request):
        body = json.loads(request.content)
        requests.append((request, body))
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["messages"][0]["content"][1]["type"] == "input_audio"
        if body["model"].startswith("qwen"):
            assert body["stream"] is True
            assert body["messages"][0]["content"][1]["input_audio"]["data"].startswith("data:audio/wav;base64,")
            text = json.dumps(payload, ensure_ascii=False)
            chunks = [text[:24], text[24:]]
            lines = ["data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) for chunk in chunks]
            lines.append('data: {"choices": [], "usage": {"total_tokens": 12}}')
            lines.append("data: [DONE]")
            return httpx.Response(200, content=("\n\n".join(lines) + "\n\n").encode())
        assert body["model"] == "doubao-seed-2-1-lite-260915"
        assert not body.get("stream")
        assert body["messages"][0]["content"][1]["input_audio"]["data"] == "UklGRiBmaXh0dXJl"
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
            "usage": {"total_tokens": 21},
        }).encode()))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        outcomes = [score_audio(audio_path=audio, prompt="请评分", model=model, kind="tts",
                                api_key="test-key", client=client) for model in SCORER_MODELS]
    assert len(requests) == 2
    assert all(outcome.status == "reviewed" for outcome in outcomes)
    assert [outcome.usage["total_tokens"] for outcome in outcomes] == [12, 21]


def test_offline_scorer_isolates_provider_and_schema_errors(tmp_path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF fixture")
    def handle(request):
        model = json.loads(request.content)["model"]
        if model.startswith("doubao"):
            return httpx.Response(429, json={"error": {"code": "rate_limit"}})
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"not-json"}}]}\n\ndata: [DONE]\n\n')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        schema = score_audio(audio_path=audio, prompt="评审", model=SCORER_MODELS[0], kind="tts", api_key="test-key", client=client)
        provider = score_audio(audio_path=audio, prompt="评审", model=SCORER_MODELS[1], kind="tts", api_key="test-key", client=client)
    assert (schema.status, schema.error_kind, schema.score) == ("recorded_error", "schema_invalid", None)
    assert (provider.status, provider.error_kind, provider.score) == ("recorded_error", "provider_error", None)


def test_offline_scorer_rejects_unknown_model_before_request(tmp_path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="unknown"):
        score_audio(audio_path=audio, prompt="评审", model="unknown", kind="tts", api_key="test-key")


def test_emotion_dimensions_are_adopted_from_the_doubao_reviewer() -> None:
    """G1–G7 盲评复测证实 qwen3.8-omni-flash 会把提示词里的指令复述成听感（锚定回声）。

    情绪与表演类维度只有豆包复核接近人耳，因此采信方改成豆包。
    """
    for name in ("emotion_match", "prosody_pause", "voice_identity", "overall_naturalness"):
        assert tts_dimension_authority(name) == EMOTION_AUTHORITY_MODEL == "doubao-seed-2-1-lite"


def test_asr_checkable_dimensions_stay_with_qwen38() -> None:
    """fidelity/contamination 能与 ASR 逐字转写交叉验证，仍采信 qwen3.8-omni-flash。"""
    for name in ("fidelity", "contamination"):
        assert tts_dimension_authority(name) == VERIFIABLE_AUTHORITY_MODEL == "qwen3.8-omni-flash"


def test_authority_split_covers_the_whole_tts_rubric_without_overlap() -> None:
    assert set(TTS_EMOTION_DIMENSIONS) | set(TTS_VERIFIABLE_DIMENSIONS) == set(TTS_DIMENSIONS)
    assert not set(TTS_EMOTION_DIMENSIONS) & set(TTS_VERIFIABLE_DIMENSIONS)
    assert EMOTION_AUTHORITY_MODEL in SCORER_MODELS
    assert VERIFIABLE_AUTHORITY_MODEL in SCORER_MODELS


def test_audiogen_dimensions_have_no_tts_authority() -> None:
    """跨 rubric 询问必须报错，不能默认回落到某个模型。"""
    with pytest.raises(ValueError):
        tts_dimension_authority("prompt_adherence")
