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
        "save_segment_audio_map",
        lambda **_: {"cached_audio_paths": {0: "tmp/segment-0.mp3"}},
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
    assert persisted_segments[0]["audio_path"] == "tmp/segment-0.mp3"
    assert response["audio_path"] == "tmp/segment-0.mp3"
    assert db.committed is True


@pytest.mark.asyncio
async def test_create_regeneration_candidate_uses_request_segment_without_persisting(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

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
    assert response["candidate_audio_path"] == "tmp/candidate-segment-0.mp3"
    assert response["segment"]["text"] == new_text
    assert response["segment"]["audio_path"] == "tmp/old-segment-0.mp3"
    assert db.committed is False


@pytest.mark.asyncio
async def test_create_mix_regeneration_candidate_uses_preview_service_without_persisting(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen
    from app.schemas.audiobook import SegmentRegenerateRequest

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
    assert response["candidate_audio_path"] == "tmp/candidate-mix-0.mp3"
    assert chapter_audio.script_json == original_script_json
    assert db.committed is False


@pytest.mark.asyncio
async def test_upload_voice_recording_candidate_saves_voice_candidate_without_persisting(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen

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
    assert response["candidate_audio_path"] == "tmp/manual-voice-0.webm"
    assert response["preview_type"] == "voice"
    assert response["segment"]["text"] == new_text
    assert chapter_audio.script_json == original_script_json
    assert db.committed is False


@pytest.mark.asyncio
async def test_apply_regeneration_candidate_persists_candidate_path(monkeypatch):
    from app.api.v1.audiobook_api import routes_segment_regen

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

    request = SimpleNamespace(
        candidate_audio_path="tmp/candidate-segment-0.mp3",
        reason="\u4fee\u6539\u6587\u672c\u540e\u91cd\u65b0\u751f\u6210",
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

    assert persisted_segments[0]["text"] == new_text
    assert persisted_segments[0]["audio_path"] == "tmp/candidate-segment-0.mp3"
    assert persisted_segments[0]["regenerated"] is True
    assert persisted_segments[0]["regenerate_reason"] == "\u4fee\u6539\u6587\u672c\u540e\u91cd\u65b0\u751f\u6210"
    assert response["audio_path"] == "tmp/candidate-segment-0.mp3"
    assert response["segment"]["text"] == new_text
    assert db.committed is True
