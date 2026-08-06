import base64
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _patch_candidate_registry(monkeypatch, routes_module, calls=None):
    """桩掉候选资产登记/终结，避免单元测试触碰真实 DB。"""
    if calls is None:
        calls = {"register": [], "finalize": []}

    def fake_register(db, **kwargs):
        calls["register"].append(kwargs)
        return None

    def fake_finalize(db, **kwargs):
        calls["finalize"].append(kwargs)
        return 0

    monkeypatch.setattr(routes_module, "register_segment_candidate_asset", fake_register)
    monkeypatch.setattr(routes_module, "finalize_segment_candidate_runs", fake_finalize)
    return calls


def _expected_candidate_revision():
    from app.services.audiobook.voice_identity_policy import (
        VOICE_IDENTITY_POLICY_VERSION,
    )

    return f"2:{VOICE_IDENTITY_POLICY_VERSION}"


def _compute_compiled_segment_fingerprint(segment):
    from app.services.audiobook.segment_synthesis_contract import (
        compute_compiled_segment_fingerprint,
    )

    return compute_compiled_segment_fingerprint(segment)


def test_candidate_contract_revision_binds_synthesis_and_voice_identity_policy():
    from app.services.audiobook import segment_synthesis_contract
    from app.services.audiobook.voice_identity_policy import (
        VOICE_IDENTITY_POLICY_VERSION,
    )

    assert segment_synthesis_contract.CONTRACT_VERSION == 2
    assert VOICE_IDENTITY_POLICY_VERSION == 10
    assert getattr(segment_synthesis_contract, "CANDIDATE_CONTRACT_REVISION", None) == (
        _expected_candidate_revision()
    )


def test_candidate_token_rejects_missing_or_stale_contract_revision(monkeypatch):
    from app.services.audiobook import segment_candidate_token
    expected_revision = _expected_candidate_revision()

    token = segment_candidate_token.issue_segment_candidate_token(
        chapter_audio_id=7,
        chapter_id=2,
        segment_index=0,
        run_id="candidate-current",
        content_sha1="a" * 40,
        extension="mp3",
        preview_type="voice",
        segment_fingerprint="base-fingerprint",
        effective_segment_fingerprint="effective-fingerprint",
        synthesis_fingerprint="synthesis-fingerprint",
    )
    current_payload = segment_candidate_token.verify_segment_candidate_token(
        token,
        chapter_audio_id=7,
        segment_index=0,
    )
    assert current_payload is not None
    assert current_payload["rev"] == expected_revision

    legacy_payload = dict(current_payload)
    legacy_payload.pop("rev")
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(
            legacy_payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    legacy_token = f"{payload_b64}.{segment_candidate_token._sign_payload(payload_b64)}"
    assert segment_candidate_token.verify_segment_candidate_token(
        legacy_token,
        chapter_audio_id=7,
        segment_index=0,
    ) is None

    monkeypatch.setattr(
        segment_candidate_token,
        "CANDIDATE_CONTRACT_REVISION",
        "1:4",
        raising=False,
    )
    stale_token = segment_candidate_token.issue_segment_candidate_token(
        chapter_audio_id=7,
        chapter_id=2,
        segment_index=0,
        run_id="candidate-stale",
        content_sha1="b" * 40,
        extension="mp3",
        preview_type="voice",
        segment_fingerprint="base-fingerprint",
        effective_segment_fingerprint="effective-fingerprint",
        synthesis_fingerprint="synthesis-fingerprint",
    )
    monkeypatch.setattr(
        segment_candidate_token,
        "CANDIDATE_CONTRACT_REVISION",
        expected_revision,
        raising=False,
    )
    assert segment_candidate_token.verify_segment_candidate_token(
        stale_token,
        chapter_audio_id=7,
        segment_index=0,
    ) is None


def test_legacy_voice_writeback_clears_stale_mix_asset():
    from app.api.v1.audiobook_api import routes_segment_regen

    segment = {"mix_audio_path": "persistent/stale-mix.mp3"}
    routes_segment_regen._mark_segment_regenerated(
        segment,
        audio_path="persistent/new-voice.mp3",
        reason="legacy regenerate",
    )

    assert segment["audio_path"] == "persistent/new-voice.mp3"
    assert "mix_audio_path" not in segment


def test_candidate_apply_segment_override_is_documented_as_deprecated():
    from app.schemas.audiobook import SegmentRegenerationCandidateApplyRequest

    schema = SegmentRegenerationCandidateApplyRequest.model_json_schema()
    segment_schema = schema["properties"]["segment"]
    assert segment_schema["deprecated"] is True
    assert "immutable candidate snapshot" in segment_schema["description"]


@pytest.mark.asyncio
async def test_regenerate_segment_uses_request_segment_text_and_persists_it(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

    old_text = "\u65e7\u7247\u6bb5\u6587\u672c"
    new_text = "\u65b0\u7247\u6bb5\u6587\u672c"
    chapter_audio = SimpleNamespace(
        id=7,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": old_text,
                    "speaker": "\u65c1\u767d",
                    "voice_params": {"speaker": "voice-old"},
                }
            ],
            ensure_ascii=False,
        ),
    )

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    db = FakeDb()
    captured = {}

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )

    async def fake_synthesize_speech(**kwargs):
        captured["text"] = kwargs["text"]
        captured["voice_params"] = kwargs["voice_params"]
        return b"ID3 regenerated audio"

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(
        routes_segment_regen,
        "save_persistent_segment_audio",
        lambda **_: "persistent/segment-0.mp3",
    )

    request = SegmentRegenerateRequest(
        tts_model="qwen3-tts-instruct-flash",
        voice_id="voice-new",
        segment={
            "type": "narration",
            "text": new_text,
            "speaker": "\u65c1\u767d",
            "voice_params": {"speaker": "voice-new"},
        },
    )

    response = await routes_segment_regen.regenerate_segment(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=request,
        owned=SimpleNamespace(db=db),
    )

    persisted_segments = json.loads(chapter_audio.script_json)

    assert captured["text"] == new_text
    assert captured["voice_params"]["speaker"] == "voice-new"
    assert persisted_segments[0]["text"] == new_text
    assert persisted_segments[0]["audio_path"] == "persistent/segment-0.mp3"
    assert persisted_segments[0]["audio_cache_key"]
    assert response["audio_path"] == "persistent/segment-0.mp3"
    assert db.committed is True


@pytest.mark.asyncio
async def test_create_regeneration_candidate_uses_request_segment_without_persisting(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest
    from app.services.audiobook.segment_candidate_token import verify_segment_candidate_token

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)

    old_text = "\u65e7\u7247\u6bb5\u6587\u672c"
    new_text = "\u65b0\u7247\u6bb5\u6587\u672c"
    original_segments = [
        {
            "type": "narration",
            "text": old_text,
            "speaker": "\u65c1\u767d",
            "audio_path": "tmp/old-segment-0.mp3",
            "voice_params": {"speaker": "voice-old"},
        }
    ]
    original_script_json = json.dumps(original_segments, ensure_ascii=False)
    chapter_audio = SimpleNamespace(id=7, script_json=original_script_json)

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    db = FakeDb()
    captured = {}

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )

    async def fake_synthesize_speech(**kwargs):
        captured["text"] = kwargs["text"]
        captured["voice_params"] = kwargs["voice_params"]
        return b"ID3 candidate audio"

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/candidate-segment-0.mp3"}},
    )

    request = SegmentRegenerateRequest(
        tts_model="qwen3-tts-instruct-flash",
        voice_id="voice-new",
        segment={
            "type": "narration",
            "text": new_text,
            "speaker": "\u65c1\u767d",
            "voice_params": {"speaker": "voice-new"},
        },
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=request,
        owned=SimpleNamespace(db=db),
    )

    assert captured["text"] == new_text
    assert captured["voice_params"]["speaker"] == "voice-new"
    assert chapter_audio.script_json == original_script_json
    assert "candidate_audio_path" not in response
    candidate_payload = verify_segment_candidate_token(
        response["candidate_id"],
        chapter_audio_id=7,
        segment_index=0,
    )
    assert candidate_payload is not None
    assert candidate_payload["rev"] == _expected_candidate_revision()
    assert candidate_payload["run"].startswith("segment_regen_candidate_voice_7_")
    assert candidate_payload["sha1"] == hashlib.sha1(b"ID3 candidate audio").hexdigest()
    assert response["segment"]["text"] == new_text
    assert response["segment"]["audio_path"] == "tmp/old-segment-0.mp3"
    assert db.committed is False
    # 候选文件必须登记为可回收资产（到期后由 janitor 物理回收）
    assert len(registry_calls["register"]) == 1
    assert registry_calls["register"][0]["chapter_id"] == 2
    assert registry_calls["register"][0]["segment_index"] == 0
    assert registry_calls["register"][0]["temp_segment_cache"]["cached_audio_paths"][0]
    assert registry_calls["register"][0]["candidate_contract"]["revision"] == (
        _expected_candidate_revision()
    )


@pytest.mark.asyncio
async def test_regeneration_rehydrates_owned_mimo_design_asset_baseline(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest
    from app.services.audiobook import mimo_voice_assets

    captured = {}
    asset_calls = []

    async def fake_synthesize_speech(**kwargs):
        captured.update(kwargs)
        return b"ID3 fixed mimo candidate"

    def fake_resolve_asset(asset_id, *, owner_user_id=None):
        asset_calls.append((asset_id, owner_user_id))
        return {
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "服务端固定青年女性声线",
            "voice_description": "服务端固定青年女性声线",
        }

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(
        routes_segment_regen,
        "_resolve_segment_regeneration_runtime_config",
        lambda *_, **__: SimpleNamespace(voice_mapping={}, audio_fx={}),
    )
    monkeypatch.setattr(
        mimo_voice_assets,
        "resolve_mimo_voice_asset_tts_params",
        fake_resolve_asset,
    )

    result = await routes_segment_regen._generate_segment_regeneration_audio(
        SegmentRegenerateRequest(
            tts_model="mimo-v2.5-tts-voicedesign",
            voice_id="mimo_design:asset-1",
            preview_type="voice",
        ),
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "performance_notes": "改成老人声，语速缓慢，句尾拖长。",
            "voice_params": {
                "speaker": "mimo_design:asset-1",
                "tts_model": "mimo-v2.5-tts-voicedesign",
                "voice_design_prompt": "客户端伪造的老人声",
            },
        },
        SimpleNamespace(
            current_user=SimpleNamespace(id=7),
            project=SimpleNamespace(),
            audiobook_project=SimpleNamespace(voice_mapping={}),
        ),
    )

    assert result["audio_bytes"] == b"ID3 fixed mimo candidate"
    assert asset_calls == [("asset-1", 7)]
    assert captured["voice_params"]["voice_design_prompt"] == "服务端固定青年女性声线"
    serialized = json.dumps(captured["voice_params"], ensure_ascii=False)
    assert "客户端伪造的老人声" not in serialized
    assert "固定声音设定保持不变" in serialized


@pytest.mark.asyncio
async def test_mimo_design_candidate_checkpoint_binds_authoritative_recipe(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest
    from app.services.audiobook import mimo_voice_assets

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    chapter_audio = SimpleNamespace(
        id=17,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "speaker": "旁白",
                    "text": "别回头。",
                    "voice_params": {
                        "speaker": "mimo_design:asset-1",
                        "tts_model": "mimo-v2.5-tts-voicedesign",
                        "voice_design_prompt": "客户端伪造配方",
                    },
                }
            ],
            ensure_ascii=False,
        ),
    )

    class FakeDb:
        def commit(self):
            raise AssertionError("生成候选不应提交章节剧本")

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "_resolve_segment_regeneration_runtime_config",
        lambda *_, **__: SimpleNamespace(voice_mapping={}, audio_fx={}),
    )

    async def fake_synthesize_speech(**_):
        return b"ID3 fixed mimo candidate"

    monkeypatch.setattr(
        routes_segment_regen,
        "runtime_synthesize_speech",
        fake_synthesize_speech,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/fixed-mimo-candidate.mp3"}},
    )
    monkeypatch.setattr(
        mimo_voice_assets,
        "resolve_mimo_voice_asset_tts_params",
        lambda asset_id, *, owner_user_id=None: {
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "服务端固定青年女性声线",
            "voice_description": "服务端固定青年女性声线",
        },
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SegmentRegenerateRequest(
            tts_model="mimo-v2.5-tts-voicedesign",
            voice_id="mimo_design:asset-1",
            preview_type="voice",
        ),
        owned=SimpleNamespace(
            db=FakeDb(),
            current_user=SimpleNamespace(id=7),
            project=SimpleNamespace(),
            audiobook_project=SimpleNamespace(voice_mapping={}),
        ),
    )

    binding = {
        "asset_type": "design",
        "mimo_voice_asset_id": "asset-1",
        "voice_design_prompt_sha1": hashlib.sha1(
            "服务端固定青年女性声线".encode("utf-8")
        ).hexdigest(),
    }
    assert response["segment"]["voice_params"]["voice_design_prompt"] == (
        "服务端固定青年女性声线"
    )
    contract = registry_calls["register"][0]["candidate_contract"]
    assert contract["voice_identity_binding"] == binding
    assert "客户端伪造配方" not in json.dumps(contract, ensure_ascii=False)


def test_candidate_saves_use_unique_asset_namespaces(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen

    captured_run_ids = []

    def fake_save_segment_audio_map(**kwargs):
        captured_run_ids.append(kwargs["run_id"])
        return {
            "cached_audio_paths": {
                0: f"tmp/{kwargs['run_id']}/segment_00000.mp3",
            }
        }

    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        fake_save_segment_audio_map,
    )
    chapter_audio = SimpleNamespace(id=7)
    common = {
        "chapter_audio": chapter_audio,
        "chapter_id": 2,
        "segment_index": 0,
        "audio_bytes": b"ID3 candidate audio",
        "run_id_prefix": "segment_regen_candidate_voice",
        "preview_type": "voice",
    }

    routes_segment_regen._save_regenerated_segment_audio(**common)
    routes_segment_regen._save_regenerated_segment_audio(**common)

    assert len(captured_run_ids) == 2
    assert captured_run_ids[0] != captured_run_ids[1]
    assert all(
        run_id.startswith("segment_regen_candidate_voice_7_")
        for run_id in captured_run_ids
    )


@pytest.mark.asyncio
async def test_create_mix_regeneration_candidate_uses_preview_service_without_persisting(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest
    from app.services.audiobook.segment_candidate_token import verify_segment_candidate_token

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)

    original_script_json = json.dumps(
        [
            {
                "type": "narration",
                "text": "\u878d\u5408\u5019\u9009\u6587\u672c",
                "speaker": "\u65c1\u767d",
                "audio_path": "tmp/old-voice.mp3",
                "sound_effects_simple": ["door"],
                "music_cue_simple": "suspense",
            }
        ],
        ensure_ascii=False,
    )
    chapter_audio = SimpleNamespace(id=9, script_json=original_script_json)

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    class FakePreviewService:
        def __init__(self, **kwargs):
            captured["service_kwargs"] = kwargs

        async def generate_preview(self, segment, *, preview_type):
            captured["segment"] = segment
            captured["preview_type"] = preview_type
            return SimpleNamespace(audio=b"ID3 mixed preview", media_type="audio/mpeg")

    db = FakeDb()
    captured = {}

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "resolve_project_audio_runtime_config",
        lambda *_, **__: SimpleNamespace(voice_mapping={}, audio_fx={}),
        raising=False,
    )
    monkeypatch.setattr(routes_segment_regen, "SegmentPreviewService", FakePreviewService, raising=False)
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/candidate-mix-0.mp3"}},
    )

    async def fail_if_tts_only_path_is_used(**kwargs):
        raise AssertionError("mix candidate should use SegmentPreviewService")

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fail_if_tts_only_path_is_used)

    request = SegmentRegenerateRequest(
        tts_model="qwen3-tts-instruct-flash",
        preview_type="mix",
        segment={
            "type": "narration",
            "text": "\u878d\u5408\u5019\u9009\u6587\u672c",
            "speaker": "\u65c1\u767d",
            "sound_effects_simple": ["door"],
            "music_cue_simple": "suspense",
        },
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=request,
        owned=SimpleNamespace(
            db=db,
            project=SimpleNamespace(id=3),
            audiobook_project=SimpleNamespace(voice_mapping={}),
        ),
    )

    assert captured["preview_type"] == "mix"
    assert response["preview_type"] == "mix"
    assert "candidate_audio_path" not in response
    candidate_payload = verify_segment_candidate_token(
        response["candidate_id"],
        chapter_audio_id=9,
        segment_index=0,
    )
    assert candidate_payload is not None
    assert candidate_payload["rev"] == _expected_candidate_revision()
    assert candidate_payload["run"].startswith("segment_regen_candidate_mix_9_")
    assert registry_calls["register"][0]["candidate_contract"]["revision"] == (
        _expected_candidate_revision()
    )
    assert chapter_audio.script_json == original_script_json
    assert db.committed is False


@pytest.mark.asyncio
async def test_regenerate_candidate_prefers_segment_bound_tts_model(monkeypatch):
    """片段绑定的音色模型（如克隆音色所属模型）必须优先于页面选择的 TTS 模型。

    否则克隆音色会被传给不支持它的模型（如 Qwen3-TTS），导致 400 Voice not supported。
    """
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

    _patch_candidate_registry(monkeypatch, routes_segment_regen)

    chapter_audio = SimpleNamespace(
        id=7,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": "\u514b\u9686\u97f3\u8272\u7247\u6bb5\u6587\u672c",
                    "speaker": "\u65c1\u767d",
                    "voice_params": {
                        "speaker": "ICL_uranus_zh_male_chunhoudiyin_tob",
                        "tts_model": "seed-tts-2.0-expressive",
                    },
                }
            ],
            ensure_ascii=False,
        ),
    )

    class FakeDb:
        def commit(self):
            pass

    captured = {}

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )

    async def fake_synthesize_speech(**kwargs):
        captured["model_id"] = kwargs["model_id"]
        captured["voice_params"] = kwargs["voice_params"]
        return b"ID3 candidate audio"

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/candidate-segment-0.mp3"}},
    )

    request = SegmentRegenerateRequest(
        tts_model="qwen3-tts-instruct-flash",
        segment=None,
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=request,
        owned=SimpleNamespace(db=FakeDb()),
    )

    assert captured["model_id"] == "seed-tts-2.0-expressive"
    assert response["model_used"] == "seed-tts-2.0-expressive"


@pytest.mark.asyncio
async def test_upload_voice_recording_candidate_saves_voice_candidate_without_persisting(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)

    old_text = "\u65e7\u7247\u6bb5\u6587\u672c"
    new_text = "\u65b0\u7247\u6bb5\u771f\u4eba\u914d\u97f3"
    original_script_json = json.dumps(
        [
            {
                "type": "narration",
                "text": old_text,
                "speaker": "\u65c1\u767d",
                "audio_path": "tmp/old-segment-0.mp3",
                "voice_params": {"speaker": "voice-old"},
            }
        ],
        ensure_ascii=False,
    )
    chapter_audio = SimpleNamespace(id=7, script_json=original_script_json)

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    class FakeUploadFile:
        filename = "manual_take.webm"
        content_type = "audio/webm"

        async def read(self):
            return b"WEBM manual voice recording"

    db = FakeDb()
    captured = {}

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )

    def fake_save_segment_audio_map(**kwargs):
        captured.update(kwargs)
        return {"cached_audio_paths": {0: "tmp/manual-voice-0.webm"}}

    monkeypatch.setattr(routes_segment_regen, "save_segment_audio_map", fake_save_segment_audio_map)

    response = await routes_segment_regen.upload_segment_voice_recording_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        file=FakeUploadFile(),
        segment=json.dumps(
            {
                "type": "narration",
                "text": new_text,
                "speaker": "\u65c1\u767d",
                "voice_params": {"speaker": "voice-new"},
            },
            ensure_ascii=False,
        ),
        reason="\u771f\u4eba\u914d\u97f3",
        owned=SimpleNamespace(db=db),
    )

    assert captured["audio_map"][0] == b"WEBM manual voice recording"
    assert captured["format"] == "webm"
    assert "candidate_audio_path" not in response
    assert response["candidate_id"]
    assert response["preview_type"] == "voice"
    assert response["segment"]["text"] == new_text
    assert chapter_audio.script_json == original_script_json
    assert db.committed is False
    assert len(registry_calls["register"]) == 1
    candidate_payload = routes_segment_regen.verify_segment_candidate_token(
        response["candidate_id"],
        chapter_audio_id=7,
        segment_index=0,
    )
    assert candidate_payload is not None
    assert candidate_payload["rev"] == _expected_candidate_revision()
    assert registry_calls["register"][0]["candidate_contract"]["revision"] == (
        _expected_candidate_revision()
    )


@pytest.mark.asyncio
async def test_apply_regeneration_candidate_persists_candidate_path(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.services.audiobook.segment_candidate_token import issue_segment_candidate_token

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)

    old_text = "\u65e7\u7247\u6bb5\u6587\u672c"
    new_text = "\u65b0\u7247\u6bb5\u6587\u672c"
    chapter_audio = SimpleNamespace(
        id=7,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": old_text,
                    "speaker": "\u65c1\u767d",
                    "audio_path": "tmp/old-segment-0.mp3",
                    "voice_params": {"speaker": "voice-old"},
                }
            ],
            ensure_ascii=False,
        ),
    )

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    db = FakeDb()

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_persistent_segment_audio",
        lambda ref: b"ID3 candidate audio",
    )
    captured = {}

    def fake_save_persistent(**kwargs):
        captured.update(kwargs)
        return "persistent/candidate-segment-0.mp3"

    monkeypatch.setattr(
        routes_segment_regen,
        "save_persistent_segment_audio",
        fake_save_persistent,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "delete_temp_segment_prefix",
        lambda *_, **__: None,
    )

    candidate_bytes = b"ID3 candidate audio"
    base_segment = json.loads(chapter_audio.script_json)[0]
    effective_segment = {
        "type": "narration",
        "text": new_text,
        "speaker": "\u65c1\u767d",
        "voice_params": {"speaker": "voice-new"},
    }
    base_fingerprint = routes_segment_regen._compute_segment_candidate_fingerprint(
        base_segment
    )
    effective_fingerprint = _compute_compiled_segment_fingerprint(
        effective_segment
    )
    synthesis_fingerprint = "candidate-synthesis-fingerprint"
    candidate_id = issue_segment_candidate_token(
        chapter_audio_id=7,
        chapter_id=2,
        segment_index=0,
        run_id="segment_regen_candidate_voice_7",
        content_sha1=hashlib.sha1(candidate_bytes).hexdigest(),
        extension="mp3",
        preview_type="voice",
        segment_fingerprint=base_fingerprint,
        effective_segment_fingerprint=effective_fingerprint,
        synthesis_fingerprint=synthesis_fingerprint,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_segment_candidate_contract",
        lambda *_, **__: {
            "revision": _expected_candidate_revision(),
            "base_segment_fingerprint": base_fingerprint,
            "effective_segment": effective_segment,
            "effective_segment_fingerprint": effective_fingerprint,
            "synthesis_fingerprint": synthesis_fingerprint,
            "preview_type": "voice",
        },
    )

    request = SimpleNamespace(
        candidate_id=candidate_id,
        reason="\u4fee\u6539\u6587\u672c\u540e\u91cd\u65b0\u751f\u6210",
        preview_type="voice",
        segment={
            "type": "narration",
            "text": new_text,
            "speaker": "\u65c1\u767d",
            "voice_params": {"speaker": "voice-new"},
        },
    )

    response = await routes_segment_regen.apply_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=request,
        owned=SimpleNamespace(db=db),
    )

    persisted_segments = json.loads(chapter_audio.script_json)

    # 候选音频必须固化到持久化片段存储，供管线复用与整章混音使用
    assert captured["audio_bytes"] == b"ID3 candidate audio"
    assert captured["chapter_audio_id"] == 7
    assert captured["segment_index"] == 0
    assert persisted_segments[0]["text"] == new_text
    assert persisted_segments[0]["audio_path"] == "persistent/candidate-segment-0.mp3"
    assert persisted_segments[0]["audio_cache_key"]
    assert persisted_segments[0]["regenerated"] is True
    assert persisted_segments[0]["regenerate_reason"] == "\u4fee\u6539\u6587\u672c\u540e\u91cd\u65b0\u751f\u6210"
    assert response["audio_path"] == "persistent/candidate-segment-0.mp3"
    assert response["chapter_audio_stale"] is True
    assert response["segment"]["text"] == new_text
    assert db.committed is True
    # apply 后对应候选登记记录必须被终结，避免 janitor 重复回收
    assert len(registry_calls["finalize"]) == 1
    assert registry_calls["finalize"][0]["segment_index"] == 0
    assert registry_calls["finalize"][0]["asset_ref"]


@pytest.mark.asyncio
async def test_create_candidate_registers_compiled_effective_segment_and_rebuilds_client_derived_fields(
    monkeypatch,
):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest
    from app.services.audiobook.segment_candidate_token import verify_segment_candidate_token

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    chapter_audio = SimpleNamespace(
        id=17,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": "A: old text",
                    "speaker": "narrator",
                    "voice_params": {
                        "speaker": "voice-old",
                        "delivery_plan": {"text": "stale stored plan"},
                        "provider_prompt_snapshot": {"mode": "stale-stored"},
                    },
                }
            ]
        ),
    )

    class FakeDb:
        def commit(self):
            raise AssertionError("candidate creation must not persist script_json")

    captured = {}
    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )

    async def fake_synthesize_speech(**kwargs):
        captured.update(kwargs)
        return b"ID3 immutable candidate"

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/immutable-candidate.mp3"}},
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SegmentRegenerateRequest(
            tts_model="qwen3-tts-instruct-flash",
            voice_id="voice-new",
            emotion="painful",
            segment={
                "type": "narration",
                "text": "B: generated text",
                "speaker": "narrator",
                "performance_notes": "slow and painful",
                "voice_params": {
                    "speaker": "voice-new",
                    "delivery_plan": {"text": "CLIENT-INJECTED-PLAN"},
                    "provider_prompt_snapshot": {"mode": "CLIENT-INJECTED-SNAPSHOT"},
                    "resolved_tts_model": "CLIENT-INJECTED-MODEL",
                    "use_instruct_mode": False,
                },
            },
        ),
        owned=SimpleNamespace(db=FakeDb()),
    )

    assert captured["text"] == "B: generated text"
    assert captured["voice_params"]["delivery_plan"]["text"] == "B: generated text"
    assert captured["voice_params"]["provider_prompt_snapshot"]["mode"] != "CLIENT-INJECTED-SNAPSHOT"
    assert captured["voice_params"]["resolved_tts_model"] == "qwen3-tts-instruct-flash"

    contract = registry_calls["register"][0]["candidate_contract"]
    assert contract["effective_segment"]["text"] == "B: generated text"
    assert contract["effective_segment"]["voice_params"] == captured["voice_params"]
    assert contract["base_segment_fingerprint"]
    assert contract["effective_segment_fingerprint"]
    assert contract["synthesis_fingerprint"]

    token_payload = verify_segment_candidate_token(
        response["candidate_id"], chapter_audio_id=17, segment_index=0
    )
    assert token_payload["efp"] == contract["effective_segment_fingerprint"]
    assert token_payload["sfp"] == contract["synthesis_fingerprint"]


@pytest.mark.asyncio
async def test_apply_candidate_uses_registered_effective_segment_and_ignores_second_override(
    monkeypatch,
):
    from app.api.v1.audiobook_api import routes_segment_regen

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    base_segment = {
        "type": "narration",
        "text": "A: stored text",
        "speaker": "narrator",
        "voice_params": {"speaker": "voice-a"},
    }
    effective_segment = {
        "type": "narration",
        "text": "B: generated text",
        "speaker": "narrator",
        "performance_notes": "slow",
        "voice_params": {"speaker": "voice-b", "tts_model": "qwen3-tts-instruct-flash"},
    }
    chapter_audio = SimpleNamespace(id=27, script_json=json.dumps([base_segment]))

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    db = FakeDb()
    base_fingerprint = routes_segment_regen._compute_segment_candidate_fingerprint(base_segment)
    effective_fingerprint = routes_segment_regen._compute_segment_candidate_fingerprint(
        effective_segment
    )
    candidate_payload = {
        "cai": 27,
        "chi": 2,
        "si": 0,
        "run": "segment_regen_candidate_voice_27",
        "sha1": hashlib.sha1(b"ID3 immutable candidate").hexdigest(),
        "ext": "mp3",
        "pt": "voice",
        "fp": base_fingerprint,
        "efp": effective_fingerprint,
        "sfp": "stable-synthesis-fingerprint",
        "rev": _expected_candidate_revision(),
    }
    candidate_contract = {
        "revision": _expected_candidate_revision(),
        "base_segment_fingerprint": base_fingerprint,
        "effective_segment": effective_segment,
        "effective_segment_fingerprint": effective_fingerprint,
        "synthesis_fingerprint": "stable-synthesis-fingerprint",
        "preview_type": "voice",
    }

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "verify_segment_candidate_token",
        lambda *_, **__: candidate_payload,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_segment_candidate_contract",
        lambda *_, **__: candidate_contract,
        raising=False,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_persistent_segment_audio",
        lambda _: b"ID3 immutable candidate",
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "save_persistent_segment_audio",
        lambda **_: "persistent/immutable-candidate.mp3",
    )
    monkeypatch.setattr(routes_segment_regen, "delete_temp_segment_prefix", lambda *_, **__: None)

    response = await routes_segment_regen.apply_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SimpleNamespace(
            candidate_id="signed-candidate",
            reason="apply B",
            preview_type="voice",
            segment={
                "type": "narration",
                "text": "C: apply-time replacement",
                "speaker": "narrator",
                "voice_params": {
                    "speaker": "voice-c",
                    "provider_prompt_snapshot": {"mode": "CLIENT-INJECTED-AT-APPLY"},
                },
            },
        ),
        owned=SimpleNamespace(db=db),
    )

    persisted_segment = json.loads(chapter_audio.script_json)[0]
    assert persisted_segment["text"] == "B: generated text"
    assert persisted_segment["voice_params"]["speaker"] == "voice-b"
    assert persisted_segment["audio_path"] == "persistent/immutable-candidate.mp3"
    assert response["segment"]["text"] == "B: generated text"
    assert db.committed is True
    assert registry_calls["finalize"]


@pytest.mark.asyncio
async def test_apply_candidate_rejects_stale_registry_contract_revision(monkeypatch):
    from fastapi import HTTPException

    from app.api.v1.audiobook_api import routes_segment_regen

    _patch_candidate_registry(monkeypatch, routes_segment_regen)
    base_segment = {
        "type": "narration",
        "text": "stored text",
        "speaker": "narrator",
        "voice_params": {"speaker": "voice-a"},
    }
    effective_segment = {
        **base_segment,
        "performance_notes": "slow",
    }
    chapter_audio = SimpleNamespace(id=28, script_json=json.dumps([base_segment]))
    base_fingerprint = routes_segment_regen._compute_segment_candidate_fingerprint(
        base_segment
    )
    effective_fingerprint = _compute_compiled_segment_fingerprint(
        effective_segment
    )
    candidate_payload = {
        "chi": 2,
        "run": "segment_regen_candidate_voice_28",
        "sha1": "a" * 40,
        "ext": "mp3",
        "pt": "voice",
        "fp": base_fingerprint,
        "efp": effective_fingerprint,
        "sfp": "synthesis-fingerprint",
        "rev": _expected_candidate_revision(),
    }
    candidate_contract = {
        "revision": "1:4",
        "base_segment_fingerprint": base_fingerprint,
        "effective_segment": effective_segment,
        "effective_segment_fingerprint": effective_fingerprint,
        "synthesis_fingerprint": "synthesis-fingerprint",
        "preview_type": "voice",
    }

    class FakeDb:
        def commit(self):
            pass

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "verify_segment_candidate_token",
        lambda *_, **__: candidate_payload,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_segment_candidate_contract",
        lambda *_, **__: candidate_contract,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "_persist_applied_candidate_audio",
        lambda **_: "persistent/should-not-be-applied.mp3",
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "_cleanup_replaced_persistent_segment_assets",
        lambda *_, **__: None,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "_cleanup_candidate_asset",
        lambda *_, **__: "candidate-ref",
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_segment_regen.apply_segment_regeneration_candidate(
            audiobook_project_id=1,
            chapter_id=2,
            segment_index=0,
            request=SimpleNamespace(
                candidate_id="signed-candidate",
                reason=None,
                preview_type="voice",
                segment=None,
            ),
            owned=SimpleNamespace(db=FakeDb()),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_apply_non_voice_candidate_preserves_latest_server_managed_assets(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    current_segment = {
        "type": "narration",
        "text": "same text",
        "speaker": "narrator",
        "audio_path": "persistent/latest-voice.mp3",
        "mix_audio_path": "persistent/chapter_segments_persistent_mix/stale-mix.mp3",
        "voice_params": {"speaker": "voice-a"},
    }
    effective_segment = {
        **current_segment,
        "audio_path": "persistent/voice-at-candidate-creation.mp3",
        "sound_effects": [{"name": "door"}],
    }
    chapter_audio = SimpleNamespace(id=37, script_json=json.dumps([current_segment]))

    class FakeDb:
        def commit(self):
            pass

    base_fingerprint = routes_segment_regen._compute_segment_candidate_fingerprint(
        current_segment
    )
    effective_fingerprint = _compute_compiled_segment_fingerprint(
        effective_segment
    )
    candidate_payload = {
        "chi": 2,
        "run": "segment_regen_candidate_sfx_37",
        "sha1": hashlib.sha1(b"ID3 sfx candidate").hexdigest(),
        "ext": "mp3",
        "pt": "sfx",
        "fp": base_fingerprint,
        "efp": effective_fingerprint,
        "sfp": "sfx-synthesis-fingerprint",
        "rev": _expected_candidate_revision(),
    }
    contract = {
        "revision": _expected_candidate_revision(),
        "base_segment_fingerprint": base_fingerprint,
        "effective_segment": effective_segment,
        "effective_segment_fingerprint": effective_fingerprint,
        "synthesis_fingerprint": "sfx-synthesis-fingerprint",
        "preview_type": "sfx",
    }

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "verify_segment_candidate_token",
        lambda *_, **__: candidate_payload,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_segment_candidate_contract",
        lambda *_, **__: contract,
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "load_persistent_segment_audio",
        lambda _: b"ID3 sfx candidate",
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "save_persistent_segment_audio",
        lambda **_: "persistent/latest-sfx.mp3",
    )
    removed_refs = []
    monkeypatch.setattr(
        routes_segment_regen,
        "delete_replaced_segment_asset_refs",
        lambda previous, current: removed_refs.extend(sorted(set(previous) - set(current)))
        or len(removed_refs),
    )
    monkeypatch.setattr(routes_segment_regen, "delete_temp_segment_prefix", lambda *_, **__: None)

    response = await routes_segment_regen.apply_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SimpleNamespace(
            candidate_id="signed-sfx-candidate",
            reason=None,
            preview_type="sfx",
            segment=None,
        ),
        owned=SimpleNamespace(db=FakeDb()),
    )

    persisted_segment = json.loads(chapter_audio.script_json)[0]
    assert persisted_segment["audio_path"] == "persistent/latest-voice.mp3"
    assert persisted_segment["sfx_audio_path"] == "persistent/latest-sfx.mp3"
    assert "mix_audio_path" not in persisted_segment
    assert removed_refs == [
        "persistent/chapter_segments_persistent_mix/stale-mix.mp3"
    ]
    assert response["chapter_audio_stale"] is True


@pytest.mark.asyncio
async def test_create_sfx_candidate_does_not_require_tts_voice_selection(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    chapter_audio = SimpleNamespace(
        id=47,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": "sound cue only",
                    "speaker": "narrator",
                    "sound_effects_simple": ["door"],
                    "voice_params": {"tts_model": "cosyvoice-v3.5-plus"},
                }
            ]
        ),
    )

    class FakeDb:
        def commit(self):
            pass

    class FakePreviewService:
        def __init__(self, **kwargs):
            pass

        async def generate_preview(self, segment, *, preview_type):
            assert preview_type == "sfx"
            return SimpleNamespace(audio=b"ID3 sfx only", media_type="audio/mpeg")

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(routes_segment_regen, "SegmentPreviewService", FakePreviewService)
    monkeypatch.setattr(
        routes_segment_regen,
        "resolve_project_audio_runtime_config",
        lambda *_, **__: SimpleNamespace(voice_mapping={}, audio_fx={}),
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/sfx-only.mp3"}},
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SegmentRegenerateRequest(
            preview_type="sfx",
            tts_model="cosyvoice-v3.5-plus",
            segment={"sound_effects_simple": ["door"]},
        ),
        owned=SimpleNamespace(
            db=FakeDb(),
            project=SimpleNamespace(id=3),
            audiobook_project=SimpleNamespace(voice_mapping={}),
        ),
    )

    assert response["preview_type"] == "sfx"
    candidate_payload = routes_segment_regen.verify_segment_candidate_token(
        response["candidate_id"],
        chapter_audio_id=47,
        segment_index=0,
    )
    assert candidate_payload is not None
    assert candidate_payload["rev"] == _expected_candidate_revision()
    assert registry_calls["register"][0]["candidate_contract"]["revision"] == (
        _expected_candidate_revision()
    )


def test_sfx_candidate_payload_allows_empty_spoken_text():
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

    payload = routes_segment_regen._build_segment_synthesis_payload(
        SegmentRegenerateRequest(
            preview_type="sfx",
            tts_model="cosyvoice-v3.5-plus",
        ),
        {
            "type": "sound_effect",
            "text": "",
            "sound_effects_simple": ["持续水滴声"],
        },
    )

    assert payload["text"] == ""
    assert payload["segment"]["sound_effects_simple"] == ["持续水滴声"]


def test_segment_regenerate_request_defaults_source_mode_to_library():
    from app.schemas.audiobook import SegmentRegenerateRequest

    request = SegmentRegenerateRequest(preview_type="sfx")
    assert request.source_mode == "library"

    ai_request = SegmentRegenerateRequest(preview_type="sfx", source_mode="ai_generate")
    assert ai_request.source_mode == "ai_generate"


@pytest.mark.asyncio
async def test_create_sfx_candidate_with_ai_generate_uses_generator(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    chapter_audio = SimpleNamespace(
        id=48,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": "sound cue only",
                    "speaker": "narrator",
                    "sound_effects_simple": ["door"],
                    "voice_params": {"tts_model": "cosyvoice-v3.5-plus"},
                }
            ]
        ),
    )

    class FakeDb:
        def commit(self):
            pass

    calls = {"preview": 0, "generator": 0}

    class FakePreviewService:
        def __init__(self, **kwargs):
            calls["preview"] += 1

        async def generate_preview(self, segment, *, preview_type):
            raise AssertionError("ai_generate 不应再走素材库匹配预览")

    async def fake_generate_sfx(segment):
        calls["generator"] += 1
        return SimpleNamespace(
            audio_bytes=b"ID3 ai-sfx",
            asset_id="sfx_ai_1",
            file_path="sound_effects/action/sfx_ai_1.mp3",
            source="doubao",
        )

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(routes_segment_regen, "SegmentPreviewService", FakePreviewService)
    monkeypatch.setattr(routes_segment_regen, "generate_segment_sfx_asset", fake_generate_sfx)
    monkeypatch.setattr(
        routes_segment_regen,
        "resolve_project_audio_runtime_config",
        lambda *_, **__: SimpleNamespace(voice_mapping={}, audio_fx={}),
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/ai-sfx.mp3"}},
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SegmentRegenerateRequest(
            preview_type="sfx",
            tts_model="cosyvoice-v3.5-plus",
            source_mode="ai_generate",
            segment={"sound_effects_simple": ["door"]},
        ),
        owned=SimpleNamespace(
            db=FakeDb(),
            project=SimpleNamespace(id=3),
            audiobook_project=SimpleNamespace(voice_mapping={}),
        ),
    )

    assert response["preview_type"] == "sfx"
    assert response["audio_size"] == len(b"ID3 ai-sfx")
    assert calls == {"preview": 0, "generator": 1}
    sound_effects = response["segment"]["sound_effects"]
    assert sound_effects[0]["asset_id"] == "sfx_ai_1"
    assert sound_effects[0]["file"] == "sound_effects/action/sfx_ai_1.mp3"
    assert registry_calls["register"][0]["candidate_contract"]["revision"] == (
        _expected_candidate_revision()
    )


@pytest.mark.asyncio
async def test_create_bgm_candidate_with_ai_generate_uses_generator(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

    registry_calls = _patch_candidate_registry(monkeypatch, routes_segment_regen)
    chapter_audio = SimpleNamespace(
        id=49,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": "rainy night",
                    "speaker": "narrator",
                    "music_cue": {"style": "悬疑", "mood": "tense"},
                    "voice_params": {"tts_model": "cosyvoice-v3.5-plus"},
                }
            ]
        ),
    )

    class FakeDb:
        def commit(self):
            pass

    async def fake_generate_bgm(segment):
        return SimpleNamespace(
            audio_bytes=b"ID3 ai-bgm",
            asset_id="bgm_ai_1",
            file_path="music_cache/bgm_ai_1.mp3",
            source="mureka",
        )

    monkeypatch.setattr(
        routes_segment_regen,
        "get_active_chapter_audio_for_project",
        lambda **_: chapter_audio,
    )
    monkeypatch.setattr(routes_segment_regen, "generate_segment_bgm_asset", fake_generate_bgm)
    monkeypatch.setattr(
        routes_segment_regen,
        "resolve_project_audio_runtime_config",
        lambda *_, **__: SimpleNamespace(voice_mapping={}, audio_fx={}),
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/ai-bgm.mp3"}},
    )

    response = await routes_segment_regen.create_segment_regeneration_candidate(
        audiobook_project_id=1,
        chapter_id=2,
        segment_index=0,
        request=SegmentRegenerateRequest(
            preview_type="bgm",
            tts_model="cosyvoice-v3.5-plus",
            source_mode="ai_generate",
        ),
        owned=SimpleNamespace(
            db=FakeDb(),
            project=SimpleNamespace(id=3),
            audiobook_project=SimpleNamespace(voice_mapping={}),
        ),
    )

    assert response["preview_type"] == "bgm"
    assert response["audio_size"] == len(b"ID3 ai-bgm")
    music_cue = response["segment"]["music_cue"]
    assert music_cue["asset_id"] == "bgm_ai_1"
    assert music_cue["file"] == "music_cache/bgm_ai_1.mp3"
    candidate_payload = routes_segment_regen.verify_segment_candidate_token(
        response["candidate_id"],
        chapter_audio_id=49,
        segment_index=0,
    )
    assert candidate_payload is not None
    assert candidate_payload["rev"] == _expected_candidate_revision()
    assert registry_calls["register"][0]["candidate_contract"]["revision"] == (
        _expected_candidate_revision()
    )
