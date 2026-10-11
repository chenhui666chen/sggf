"""音色画像自动打标合同：受控枚举、盲评、双模型分工、candidate 语义。

不调用供应商；网络层用 httpx.MockTransport。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.schemas.voice_tags import (
    TAXONOMY_VERSION,
    VOICE_TAG_DIMENSIONS,
    WRITABLE_TAG_DIMENSIONS,
)
from app.services.audiobook.scene_quality.audio_score_contract import (
    EMOTION_AUTHORITY_MODEL,
    VERIFIABLE_AUTHORITY_MODEL,
)
from app.services.audiobook.voice_profile_tagging import (
    PRIMARY_SCORER,
    PROFILE_SCHEMA_VERSION,
    REFERENCE_SCORER,
    TAGGING_DIMENSIONS,
    TAGGING_SCHEMA_VERSION,
    build_sidecar_document,
    build_tagging_prompt,
    fold_suspected_asr_repeat,
    parse_tagging_response,
    profile_entry_from_judgements,
    raw_cache_path,
    tag_voice_profile,
    transcript_similarity,
)

VOICE_ID = "ICL_uranus_zh_female_wenrou"
PREVIEW_TEXT = "天下事有大相反者：好名之弊，在矫激；好利之弊，在贪鄙。"
_API_KEYS = {PRIMARY_SCORER: "doubao-test-key", REFERENCE_SCORER: "qwen-test-key"}

_DEFAULT_JUDGEMENTS = {
    "gender_presentation": ["female"],
    "age_impression": ["young_adult"],
    "timbre": [],
    "style": ["natural"],
    "pitch_range": ["mid"],
    "pace": ["medium"],
    "energy": ["medium"],
    "articulation": ["clear"],
    "temperament": [],
}


def _judgement_payload(**overrides) -> dict:
    dimensions = {
        dimension: {
            "tags": list(_DEFAULT_JUDGEMENTS[dimension]),
            "evidence": "标准试听样本中可听见该表现。",
            "confidence": 0.9,
        }
        for dimension in TAGGING_DIMENSIONS
    }
    dimensions.update(overrides)
    return {"dimensions": dimensions}


def _raw(**overrides) -> str:
    return json.dumps(_judgement_payload(**overrides), ensure_ascii=False)


def _handler(raw: str):
    """qwen 走 SSE 流式，豆包走 Ark 同步 JSON。"""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"].startswith("qwen"):
            lines = [
                "data: " + json.dumps({"choices": [{"delta": {"content": raw}}], "usage": {"total_tokens": 30}}),
                "data: [DONE]",
            ]
            return httpx.Response(200, content=("\n\n".join(lines) + "\n\n").encode())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": raw}}], "usage": {"total_tokens": 41}},
        )

    return handle


def test_contract_covers_only_dimensions_a_single_sample_can_support() -> None:
    """指南 §4.2/§4.4：表演能力、题材与角色原型需多段标准样本或人工审核；
    情绪标签会被试听语录的内容主导，不代表音色本身，故一律不进入自动打标合同。"""
    assert set(TAGGING_DIMENSIONS) <= set(WRITABLE_TAG_DIMENSIONS)
    for excluded in ("performance", "scenario", "role_archetype", "emotion"):
        assert excluded in VOICE_TAG_DIMENSIONS
        assert excluded not in TAGGING_DIMENSIONS


def test_prompt_lists_every_allowed_code_per_dimension() -> None:
    prompt = build_tagging_prompt(text=PREVIEW_TEXT)
    assert PREVIEW_TEXT in prompt
    for dimension in TAGGING_DIMENSIONS:
        assert dimension in prompt
        for code in WRITABLE_TAG_DIMENSIONS[dimension]:
            assert code in prompt
    assert "markdown" in prompt


def test_tagging_scorers_reuse_the_single_source_authority_split() -> None:
    """打标分工沿用评分器的事实源：听感维度只采信豆包，qwen3.8 只做参考。"""
    assert PRIMARY_SCORER == EMOTION_AUTHORITY_MODEL
    assert REFERENCE_SCORER == VERIFIABLE_AUTHORITY_MODEL


def test_parse_normalizes_case_and_dedupes() -> None:
    parsed = parse_tagging_response(
        _raw(timbre={"tags": [" Warm ", "warm"], "evidence": "中低频泛音丰富。", "confidence": 0.7})
    )
    assert parsed["timbre"].tags == ("warm",)
    assert parsed["timbre"].confidence == pytest.approx(0.7)


def test_parse_rejects_non_json_and_unknown_shapes() -> None:
    for raw in ("not json", "[]", '{"dimensions": []}', '{"dimensions": {}, "extra": 1}'):
        with pytest.raises(ValueError):
            parse_tagging_response(raw)


def test_parse_rejects_unknown_dimension_or_code() -> None:
    with pytest.raises(ValueError, match="emotion"):
        parse_tagging_response(
            json.dumps(
                {
                    "dimensions": {
                        **_judgement_payload()["dimensions"],
                        "emotion": {"tags": ["happy"], "evidence": "愉悦。", "confidence": 0.9},
                    }
                },
                ensure_ascii=False,
            )
        )
    with pytest.raises(ValueError, match="unsupported"):
        parse_tagging_response(_raw(timbre={"tags": ["chrome"], "evidence": "金属感。", "confidence": 0.9}))


def test_parse_rejects_legacy_scenario_value() -> None:
    """§4.4：旁白/对白属 performance，即使词表为兼容仍保留读取，写入合同也必须拒收。"""
    with pytest.raises(ValueError):
        parse_tagging_response(
            json.dumps(
                {
                    "dimensions": {
                        **_judgement_payload()["dimensions"],
                        "scenario": {"tags": ["narration"], "evidence": "旁白。", "confidence": 0.9},
                    }
                },
                ensure_ascii=False,
            )
        )


def test_parse_repairs_trailing_content_after_the_json_object() -> None:
    """豆包偶尔在对象后面多吐一个右括号，主体完好时必须按可采信处理。"""
    parsed = parse_tagging_response(_raw() + "}")
    assert parsed["gender_presentation"].tags == ("female",)


def test_parse_recovers_misspelled_dimensions_key() -> None:
    payload = _judgement_payload()
    payload["dimments"] = payload.pop("dimensions")
    parsed = parse_tagging_response(json.dumps(payload, ensure_ascii=False))
    assert parsed["pace"].tags == ("medium",)


def test_parse_maps_reversed_pitch_range_word_order() -> None:
    """词表把音高定为 low_mid 而能量定为 medium_low，模型会顺着后者写成 mid_low。"""
    parsed = parse_tagging_response(
        _raw(pitch_range={"tags": ["mid_low"], "evidence": "整体音高处于中低区间。", "confidence": 0.9})
    )
    assert parsed["pitch_range"].tags == ("low_mid",)


def test_parse_drops_code_that_belongs_to_another_dimension() -> None:
    """气质维度混进风格词时只丢那一个取值，不作废整份画像。"""
    parsed = parse_tagging_response(
        _raw(temperament={"tags": ["approachable", "elegant"], "evidence": "亲和且优雅。", "confidence": 0.85})
    )
    assert parsed["temperament"].tags == ("approachable",)
    assert parsed["style"].tags == ("natural",)

    abstained = parse_tagging_response(
        _raw(temperament={"tags": ["innocent"], "evidence": "带天真的听感。", "confidence": 0.85})
    )
    assert abstained["temperament"].tags == ()


def test_parse_rejects_missing_dimension_over_limit_and_empty_evidence() -> None:
    missing = _judgement_payload()
    missing["dimensions"].pop("pace")
    with pytest.raises(ValueError, match="pace"):
        parse_tagging_response(json.dumps(missing, ensure_ascii=False))

    with pytest.raises(ValueError, match="at most"):
        parse_tagging_response(_raw(pace={"tags": ["slow", "fast"], "evidence": "忽慢忽快。", "confidence": 0.6}))

    with pytest.raises(ValueError, match="evidence"):
        parse_tagging_response(_raw(style={"tags": ["natural"], "evidence": "  ", "confidence": 0.6}))

    with pytest.raises(ValueError, match="confidence"):
        parse_tagging_response(_raw(style={"tags": ["natural"], "evidence": "自然。", "confidence": 1.4}))


def test_transcript_similarity_ignores_punctuation_and_case() -> None:
    stripped = PREVIEW_TEXT.replace("：", "").replace("；", "").replace("，", "")
    assert transcript_similarity(expected=PREVIEW_TEXT, transcript=stripped) > 0.9
    assert transcript_similarity(expected="Hello world.", transcript="hello world") > 0.9
    assert transcript_similarity(expected=PREVIEW_TEXT, transcript="完全无关的一句话") < 0.5


def test_transcript_similarity_maps_chinese_numerals_to_digits() -> None:
    """ASR 把"一千八百"写成"1800"不是漏读，逐字比较必须先做数字口径归一。"""
    assert transcript_similarity(
        expected="坏毛病有一千八百种。", transcript="坏毛病有1800种"
    ) == pytest.approx(1.0)
    assert transcript_similarity(
        expected="要花上六十年来学会闭嘴。", transcript="要花上60年来学会闭嘴"
    ) == pytest.approx(1.0)


def test_transcript_similarity_maps_pronoun_and_structural_particle_homophones() -> None:
    """它/他/她 与 的/地/得 在中文听写里无法区分，不构成内容差异。"""
    assert transcript_similarity(
        expected="它真讨厌，只有一点好，爱你。", transcript="他真讨厌只有一点好爱你"
    ) == pytest.approx(1.0)
    assert transcript_similarity(
        expected="我来不及认真地年轻。", transcript="我来不及认真的年轻"
    ) == pytest.approx(1.0)


def test_transcript_similarity_still_penalises_real_content_loss() -> None:
    """归一化不能把漏读整句也判成一致，门槛的判别力必须保留。"""
    assert transcript_similarity(
        expected="道虽迩，不行不至；事虽小，不为不成。", transcript="道虽迩不行不至"
    ) < 0.9


def test_profile_entry_adopts_primary_tags_and_keeps_reference_separate() -> None:
    primary = parse_tagging_response(_raw(timbre={"tags": ["warm"], "evidence": "中低频泛音丰富。", "confidence": 0.8}))
    reference = parse_tagging_response(
        _raw(timbre={"tags": ["bright"], "evidence": "偏亮。", "confidence": 0.9})
    )
    entry = profile_entry_from_judgements(
        model="qwen-audio-3.1-tts-flash",
        voice_id=VOICE_ID,
        preview_text=PREVIEW_TEXT,
        audio_sha256="a" * 64,
        primary=primary,
        reference=reference,
        objective={"passed": True, "reason": "ok", "duration_ms": 6200, "transcript_similarity": 0.98},
    )

    assert entry["tags"]["gender_presentation"] == ["female"]
    assert entry["tags"]["timbre"] == ["warm"]
    assert entry["tag_evidence"]["timbre"]["confidence"] == pytest.approx(0.8)
    assert entry["reference"]["dimensions"]["timbre"]["tags"] == ["bright"]
    assert entry["review_status"] == "candidate"
    assert entry["profile_status"] == "ready"
    assert entry["taxonomy_version"] == TAXONOMY_VERSION
    assert entry["needs_review"] is True
    assert "single_sample_evidence" in entry["needs_review_reasons"]


def test_profile_entry_abstained_dimensions_are_omitted() -> None:
    entry = profile_entry_from_judgements(
        model="mimo-v2.5-tts",
        voice_id="Mia",
        preview_text=PREVIEW_TEXT,
        audio_sha256="b" * 64,
        primary=parse_tagging_response(_raw()),
        reference=None,
        objective={"passed": True, "reason": "ok"},
    )
    assert "timbre" not in entry["tags"]
    assert "temperament" not in entry["tags"]
    assert entry["needs_review_reasons"] == ["single_sample_evidence"]


def test_low_confidence_and_disagreement_are_flagged_for_human_review() -> None:
    primary = parse_tagging_response(
        _raw(gender_presentation={"tags": ["female"], "evidence": "听感偏女。", "confidence": 0.3})
    )
    reference = parse_tagging_response(
        _raw(gender_presentation={"tags": ["neutral"], "evidence": "中性。", "confidence": 0.9})
    )
    entry = profile_entry_from_judgements(
        model="stepaudio-3-tts",
        voice_id="cathena",
        preview_text=PREVIEW_TEXT,
        audio_sha256="c" * 64,
        primary=primary,
        reference=reference,
        objective={"passed": True, "reason": "ok"},
    )
    assert entry["needs_review"] is True
    assert "low_confidence:gender_presentation" in entry["needs_review_reasons"]
    assert "scorer_disagreement:gender_presentation" in entry["needs_review_reasons"]
    assert entry["tags"]["gender_presentation"] == ["female"]


def test_single_value_disagreement_only_flagged_when_both_models_answer() -> None:
    """参考模型弃权、或主模型明确"听不出来"时不构成冲突，不额外制造人工负担。"""
    primary = parse_tagging_response(
        _raw(pitch_range={"tags": [], "evidence": "音高无明显倾向。", "confidence": 0.4})
    )
    reference = parse_tagging_response(_raw(pitch_range={"tags": ["mid"], "evidence": "中音。", "confidence": 0.9}))
    entry = profile_entry_from_judgements(
        model="seed-tts-2.0-expressive",
        voice_id="ICL_x",
        preview_text=PREVIEW_TEXT,
        audio_sha256="d" * 64,
        primary=primary,
        reference=reference,
        objective={"passed": True, "reason": "ok"},
    )
    assert not [reason for reason in entry["needs_review_reasons"] if reason.endswith("pitch_range")]


def test_failed_objective_gate_yields_pending_entry_without_tags() -> None:
    entry = profile_entry_from_judgements(
        model="qwen-audio-3.1-tts-flash",
        voice_id=VOICE_ID,
        preview_text=PREVIEW_TEXT,
        audio_sha256="e" * 64,
        primary=None,
        reference=None,
        objective={"passed": False, "reason": "duration_outlier"},
    )
    assert entry["profile_status"] == "pending"
    assert entry["tags"] == {}
    assert entry["needs_review"] is True
    assert "objective_gate_failed" in entry["needs_review_reasons"]
    # §7.1：pending 不得伪造默认画像，运行时字段必须缺省。
    assert "age_group" not in entry and "timbre_traits" not in entry


def test_sidecar_document_carries_revision_metadata() -> None:
    doc = build_sidecar_document(
        model="minimax-speech-2.8-hd",
        catalog_filename="minimax_speech_2_8_voices.json",
        catalog_revision="f" * 16,
        entries={"voice_a": {"profile_status": "ready"}},
        generated_by=(PRIMARY_SCORER, REFERENCE_SCORER),
    )
    assert doc["schema_version"] == PROFILE_SCHEMA_VERSION
    assert doc["tagging_schema_version"] == TAGGING_SCHEMA_VERSION
    assert doc["taxonomy_version"] == TAXONOMY_VERSION
    assert doc["model"] == "minimax-speech-2.8-hd"
    assert doc["catalog_filename"] == "minimax_speech_2_8_voices.json"
    assert doc["catalog_revision"] == "f" * 16
    assert doc["generated_by"] == [PRIMARY_SCORER, REFERENCE_SCORER]
    assert doc["voice_profiles"] == {"voice_a": {"profile_status": "ready"}}
    assert doc["profile_version"].startswith("sha256:")


def test_raw_cache_key_is_scoped_by_prompt_and_audio() -> None:
    def key(scorer=PRIMARY_SCORER, audio_sha256="a" * 64, text=PREVIEW_TEXT):
        return raw_cache_path(
            Path("/tmp/x"),
            scorer=scorer,
            model="mimo-v2.5-tts",
            voice_id="Mia",
            text=text,
            audio_sha256=audio_sha256,
        )

    assert key() == key()
    assert key() != key(audio_sha256="b" * 64)
    assert key() != key(scorer=REFERENCE_SCORER)
    assert key() != key(text=PREVIEW_TEXT + "改动一个字")
    assert key().name.endswith(".json")


def test_tag_voice_profile_calls_both_scorers_blindly_and_caches_raw(tmp_path: Path) -> None:
    audio = tmp_path / "preview.mp3"
    audio.write_bytes(b"ID3 fixture audio")
    requests: list[dict] = []

    def record_and_handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return _handler(_raw())(request)

    with httpx.Client(transport=httpx.MockTransport(record_and_handle)) as client:
        primary, reference, cache_paths = tag_voice_profile(
            audio_path=audio,
            text=PREVIEW_TEXT,
            model="qwen-audio-3.1-tts-flash",
            voice_id=VOICE_ID,
            api_keys=_API_KEYS,
            cache_dir=tmp_path / "raw",
            client=client,
        )

    assert primary["gender_presentation"].tags == ("female",)
    assert reference["age_impression"].tags == ("young_adult",)
    assert reference["timbre"].tags == ()
    # 主模型先问、参考模型后问；豆包的实际请求体使用带日期的快照 ID，由传输层映射。
    assert requests[0]["model"].startswith("doubao")
    assert requests[1]["model"] == REFERENCE_SCORER
    for body in requests:
        serialized = json.dumps(body, ensure_ascii=False)
        assert VOICE_ID not in serialized
    assert all(path.exists() for path in cache_paths)

    requests.clear()

    def fail_on_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("命中 raw 缓存后不应再发请求")

    with httpx.Client(transport=httpx.MockTransport(fail_on_request)) as cached_client:
        again_primary, again_reference, _ = tag_voice_profile(
            audio_path=audio,
            text=PREVIEW_TEXT,
            model="qwen-audio-3.1-tts-flash",
            voice_id=VOICE_ID,
            api_keys=_API_KEYS,
            cache_dir=tmp_path / "raw",
            client=cached_client,
        )

    assert again_primary == primary
    assert again_reference == reference


def test_each_scorer_is_called_with_its_own_provider_key(tmp_path: Path) -> None:
    """豆包与百炼是两套密钥，不允许把任一侧的 key 透传给另一侧。"""
    audio = tmp_path / "preview.mp3"
    audio.write_bytes(b"ID3 fixture")
    auth: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        auth.append(request.headers["authorization"])
        return _handler(_raw())(request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        tag_voice_profile(
            audio_path=audio,
            text=PREVIEW_TEXT,
            model="minimax-speech-2.8-hd",
            voice_id="male-qn-qingse",
            api_keys=_API_KEYS,
            client=client,
        )

    assert auth == ["Bearer doubao-test-key", "Bearer qwen-test-key"]


def test_missing_primary_key_fails_before_any_request(tmp_path: Path) -> None:
    audio = tmp_path / "preview.mp3"
    audio.write_bytes(b"ID3 fixture")

    def fail(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("主模型缺密钥时不应发出请求")

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ValueError, match="primary"):
            tag_voice_profile(
                audio_path=audio,
                text=PREVIEW_TEXT,
                model="mimo-v2.5-tts",
                voice_id="Mia",
                api_keys={REFERENCE_SCORER: "qwen-test-key"},
                client=client,
            )


def test_tag_voice_profile_degrades_when_reference_fails(tmp_path: Path) -> None:
    """参考模型不可用不阻塞打标：主模型（豆包）结果仍然落盘，只把缺失记进审计字段。"""
    audio = tmp_path / "preview.wav"
    audio.write_bytes(b"RIFF fixture")

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"].startswith("qwen"):
            return httpx.Response(429, json={"error": {"code": "rate_limit"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _raw()}}], "usage": {"total_tokens": 41}},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        primary, reference, _ = tag_voice_profile(
            audio_path=audio,
            text=PREVIEW_TEXT,
            model="seed-tts-2.0-expressive",
            voice_id="ICL_uranus_en_br_adam",
            api_keys=_API_KEYS,
            client=client,
        )

    assert primary["gender_presentation"].tags == ("female",)
    assert reference is None


def test_tag_voice_profile_requires_primary_success(tmp_path: Path) -> None:
    audio = tmp_path / "preview.wav"
    audio.write_bytes(b"RIFF fixture")

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"].startswith("qwen"):
            lines = ["data: " + json.dumps({"choices": [{"delta": {"content": _raw()}}]}), "data: [DONE]"]
            return httpx.Response(200, content=("\n\n".join(lines) + "\n\n").encode())
        return httpx.Response(500, json={"error": {"code": "internal"}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="primary"):
            tag_voice_profile(
                audio_path=audio,
                text=PREVIEW_TEXT,
                model="stepaudio-3-tts",
                voice_id="cathena",
                api_keys=_API_KEYS,
                client=client,
            )


# --- ASR 整句重复幻觉：时长反证下的重复折叠 -------------------------------

SOUL_TEXT = (
    "我把我整个灵魂都给你，连同它的怪癖，耍小脾气，忽明忽暗，一千八百种坏毛病。"
    "它真讨厌，只有一点好，爱你。"
)
# qwen-audio-3.1-asr-flash 在 3 条音色上逐字节复现的同一形状：中间整句被转写两遍。
SOUL_DOUBLED_TRANSCRIPT = (
    "我把我整个灵魂都给你，连同他的怪癖，耍小脾气，忽明忽暗，1800种坏毛病。"
    "我把我整个灵魂都给你，连同他的怪癖，耍小脾气，忽明忽暗，1800种坏毛病。"
    "他真讨厌，只有一点好，爱你。"
)


def test_fold_recovers_repeated_clause_when_audio_cannot_hold_it() -> None:
    """发声时长装不下整句重复时，按重复折叠并恢复到可通过的相似度。"""
    fold = fold_suspected_asr_repeat(
        expected=SOUL_TEXT, transcript=SOUL_DOUBLED_TRANSCRIPT, voiced_duration_ms=8819
    )

    assert fold is not None
    assert fold.similarity >= 0.99
    assert len(fold.removed_block) >= 8


def test_fold_refused_when_audio_is_long_enough_for_the_repeat() -> None:
    """真复读必须还能被门禁拒掉：时长装得下重复就不许折叠。"""
    assert (
        fold_suspected_asr_repeat(
            expected=SOUL_TEXT, transcript=SOUL_DOUBLED_TRANSCRIPT, voiced_duration_ms=21224
        )
        is None
    )


def test_fold_requires_a_long_adjacent_duplicate() -> None:
    """短重叠与跨句非相邻重复都不算 ASR 整句幻觉。"""
    assert (
        fold_suspected_asr_repeat(
            expected="好好说话，别急。", transcript="好好，好好说话，别急。", voiced_duration_ms=1200
        )
        is None
    )
    assert (
        fold_suspected_asr_repeat(
            expected=SOUL_TEXT,
            transcript=SOUL_TEXT.replace("它真讨厌", "他真讨厌") + "完全无关的另一句话。",
            voiced_duration_ms=1200,
        )
        is None
    )


def test_fold_never_invents_content_when_transcript_has_no_duplicate() -> None:
    assert (
        fold_suspected_asr_repeat(
            expected=SOUL_TEXT, transcript="道虽迩不行不至", voiced_duration_ms=8819
        )
        is None
    )


def test_entry_marks_asr_repeat_suspect_when_gate_folded() -> None:
    primary = parse_tagging_response(_raw(timbre={"tags": ["warm"], "evidence": "中低频泛音丰富。", "confidence": 0.8}))
    entry = profile_entry_from_judgements(
        model="qwen-audio-3.1-tts-flash",
        voice_id=VOICE_ID,
        preview_text=PREVIEW_TEXT,
        audio_sha256="c" * 64,
        primary=primary,
        reference=None,
        objective={
            "passed": True,
            "reason": "ok",
            "duration_ms": 9984,
            "transcript_similarity": 1.0,
            "transcript_similarity_raw": 0.7288,
            "asr_repeat_suspect": True,
        },
    )

    assert entry["profile_status"] == "ready"
    assert "asr_repeat_suspect" in entry["needs_review_reasons"]


def _gate_job(preview_text: str) -> "object":
    from app.scripts import tag_voice_profiles as script

    return script.VoiceJob(
        model="stepaudio-3-tts",
        voice_id="qingniandaxuesheng",
        label="青年大学生",
        preview_text=preview_text,
        cache_key="cache-key",
        profile_filename="stepaudio_3_tts_voice_profiles.json",
    )


class _GateCheck:
    def __init__(self, *, duration_ms: int, silence_ratio: float) -> None:
        self.passed = True
        self.reason = "ok"
        self.duration_ms = duration_ms
        self.expected_duration_ms = 10612
        self.silence_ratio = silence_ratio
        self.rms_dbfs = -22.0


class _GateAsr:
    def __init__(self, transcript: str) -> None:
        self._transcript = transcript

    def transcribe(self, audio_path: str):
        class _Result:
            transcript = self._transcript

        return _Result


def test_objective_gate_folds_hallucinated_repeat_under_duration_proof(monkeypatch) -> None:
    """转写所需时长 > 实测发声时长：折叠重复后放行，并留下 asr_repeat_suspect 证据。"""
    from app.scripts import tag_voice_profiles as script

    monkeypatch.setattr(
        script, "validate_tts_audio", lambda audio, text: _GateCheck(duration_ms=9984, silence_ratio=0.1166)
    )

    objective = script._objective_gate(
        _gate_job(SOUL_TEXT), b"audio", Path("preview.wav"), "cached", _GateAsr(SOUL_DOUBLED_TRANSCRIPT)
    )

    assert objective["passed"] is True
    assert objective["asr_repeat_suspect"] is True
    assert objective["transcript_similarity_raw"] == pytest.approx(0.7288, abs=0.001)
    assert objective["transcript_similarity"] >= 0.99
    assert objective["asr_repeat_removed"]


def test_objective_gate_keeps_rejecting_genuine_repetition(monkeypatch) -> None:
    """音频长到装得下整句重复时不能折叠：真复读继续按 transcript_mismatch 拒。"""
    from app.scripts import tag_voice_profiles as script

    monkeypatch.setattr(
        script, "validate_tts_audio", lambda audio, text: _GateCheck(duration_ms=24000, silence_ratio=0.0)
    )

    objective = script._objective_gate(
        _gate_job(SOUL_TEXT), b"audio", Path("preview.wav"), "cached", _GateAsr(SOUL_DOUBLED_TRANSCRIPT)
    )

    assert objective["passed"] is False
    assert objective["reason"] == "transcript_mismatch"
    assert "asr_repeat_suspect" not in objective
