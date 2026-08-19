"""单片段工作台音效/配乐 AI 生成服务测试。

音效走豆包 seed-audio-1.0（与整章管线一致），配乐走 Mureka、失败回退豆包；
生成结果入素材库索引，同时作为候选音频字节返回。
"""

import base64
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


def _data_url(payload: bytes, mime: str = "audio/mpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_downloads_and_registers(monkeypatch, tmp_path):
    from app.services.audiobook import segment_asset_ai_generator as service

    captured = {}

    class FakeGenerator:
        async def generate_audio_async(self, *, prompt, duration):
            captured["prompt"] = prompt
            captured["duration"] = duration
            return SimpleNamespace(success=True, audio_url=_data_url(b"ID3fake-sfx"), error="")

    class FakeDesigner:
        def __init__(self, *_, **__):
            pass

        def download_and_register_effect(self, **kwargs):
            captured["register"] = kwargs
            relative_path = "sound_effects/action/sfx_ai_001.mp3"
            target = tmp_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"ID3fake-sfx")
            return {"id": "sfx_ai_001", "file_path": relative_path}

    monkeypatch.setattr(service, "has_doubao_sfx_api_key", lambda: True)
    monkeypatch.setattr(service, "create_doubao_sfx_generator", lambda: FakeGenerator())
    monkeypatch.setattr(service, "SoundEffectDesigner", FakeDesigner)
    monkeypatch.setattr(service, "get_audio_library_dir", lambda: tmp_path)

    result = await service.generate_segment_sfx_asset(
        {"text": "他推开门", "sound_effects_simple": ["木门吱呀声"]}
    )

    assert result.audio_bytes == b"ID3fake-sfx"
    assert result.asset_id == "sfx_ai_001"
    assert result.file_path == "sound_effects/action/sfx_ai_001.mp3"
    assert result.source == "doubao"
    assert "木门吱呀声" in captured["prompt"]
    assert captured["register"]["source"] == "ai_generated"


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_requires_doubao_key(monkeypatch):
    from fastapi import HTTPException

    from app.services.audiobook import segment_asset_ai_generator as service

    monkeypatch.setattr(service, "has_doubao_sfx_api_key", lambda: False)

    with pytest.raises(HTTPException) as error:
        await service.generate_segment_sfx_asset({"sound_effects_simple": ["door"]})
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_requires_sound_effects(monkeypatch):
    from fastapi import HTTPException

    from app.services.audiobook import segment_asset_ai_generator as service

    monkeypatch.setattr(service, "has_doubao_sfx_api_key", lambda: True)

    with pytest.raises(HTTPException) as error:
        await service.generate_segment_sfx_asset({"text": "没有音效配置的片段"})
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_generate_segment_bgm_asset_uses_mureka(monkeypatch, tmp_path):
    from app.services.audiobook import segment_asset_ai_generator as service

    captured = {}

    class FakeMusicClient:
        async def generate_music(self, request):
            captured["request"] = request
            return SimpleNamespace(
                success=True,
                audio_data=b"ID3mureka-music",
                audio_file_path="music_cache/bgmai001.mp3",
                error_message="",
            )

    class FakeMusicGenerator:
        def __init__(self):
            self.client = FakeMusicClient()

    monkeypatch.setattr(service, "create_music_generator", lambda **_: FakeMusicGenerator())

    result = await service.generate_segment_bgm_asset(
        {"text": "雨夜独行", "music_cue": {"style": "悬疑", "mood": "tense"}}
    )

    assert result.audio_bytes == b"ID3mureka-music"
    assert result.source == "mureka"
    assert result.asset_id == "bgmai001"
    assert result.file_path == "music_cache/bgmai001.mp3"
    assert "雨夜独行" in captured["request"].prompt or "悬疑" in captured["request"].prompt


@pytest.mark.asyncio
async def test_generate_segment_bgm_asset_falls_back_to_doubao(monkeypatch, tmp_path):
    from app.services.audiobook import segment_asset_ai_generator as service

    class FakeMusicGenerator:
        def __init__(self):
            self.client = self

        async def generate_music(self, request):
            return SimpleNamespace(
                success=False,
                audio_data=None,
                audio_file_path="",
                error_message="mureka unavailable",
            )

    class FakeSfxGenerator:
        async def generate_audio_async(self, *, prompt, duration):
            return SimpleNamespace(success=True, audio_url=_data_url(b"ID3doubao-bgm"), error="")

    monkeypatch.setattr(service, "create_music_generator", lambda **_: FakeMusicGenerator())
    monkeypatch.setattr(service, "has_doubao_sfx_api_key", lambda: True)
    monkeypatch.setattr(service, "create_doubao_sfx_generator", lambda: FakeSfxGenerator())
    monkeypatch.setattr(service, "get_audio_library_dir", lambda: tmp_path)

    result = await service.generate_segment_bgm_asset(
        {"text": "雨夜独行", "music_cue": {"style": "悬疑", "mood": "tense"}}
    )

    assert result.audio_bytes == b"ID3doubao-bgm"
    assert result.source == "doubao"
    assert result.file_path.startswith("music_cache/")

    index_path = tmp_path / "music_index.json"
    assert index_path.exists()
    records = json.loads(index_path.read_text(encoding="utf-8"))
    fallback_records = [r for r in records if r.get("source") == "doubao"]
    assert fallback_records and fallback_records[0]["file_path"] == result.file_path
    assert (tmp_path / result.file_path).read_bytes() == b"ID3doubao-bgm"


@pytest.mark.asyncio
async def test_generate_segment_bgm_asset_requires_music_cue(monkeypatch):
    from fastapi import HTTPException

    from app.services.audiobook import segment_asset_ai_generator as service

    with pytest.raises(HTTPException) as error:
        await service.generate_segment_bgm_asset({"text": "没有配乐配置的片段"})
    assert error.value.status_code == 400


def test_build_text_prompt_skips_duration_suffix_when_none():
    """描述自带时长时不得再追加“时长约X秒”，避免矛盾时长。"""
    from app.services.audiobook.doubao_sfx_generator import DoubaoSfxGenerator

    prompt = DoubaoSfxGenerator.build_text_prompt(
        "一个男性低声轻笑，2秒左右", None)
    assert prompt == "一个男性低声轻笑，2秒左右。"
    prompt_with = DoubaoSfxGenerator.build_text_prompt("木门吱呀声", 4.0)
    assert prompt_with == "木门吱呀声。时长约4秒。"


def _patch_sfx_generation(monkeypatch, tmp_path, captured):
    from app.services.audiobook import segment_asset_ai_generator as service

    class FakeGenerator:
        async def generate_audio_async(self, *, prompt, duration):
            captured["prompt"] = prompt
            captured["duration"] = duration
            return SimpleNamespace(success=True, audio_url=_data_url(b"ID3fake-sfx"), error="")

    class FakeDesigner:
        def __init__(self, *_, **__):
            pass

        def download_and_register_effect(self, **kwargs):
            relative_path = "sound_effects/action/sfx_ai_001.mp3"
            target = tmp_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"ID3fake-sfx")
            return {"id": "sfx_ai_001", "file_path": relative_path}

    monkeypatch.setattr(service, "has_doubao_sfx_api_key", lambda: True)
    monkeypatch.setattr(service, "create_doubao_sfx_generator", lambda: FakeGenerator())
    monkeypatch.setattr(service, "SoundEffectDesigner", FakeDesigner)
    monkeypatch.setattr(service, "get_audio_library_dir", lambda: tmp_path)
    return service


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_respects_user_stated_duration(monkeypatch, tmp_path):
    """用户描述已含“2秒左右”：时长参数须为 None，最终提示词不追加时长。"""
    captured = {}
    service = _patch_sfx_generation(monkeypatch, tmp_path, captured)

    await service.generate_segment_sfx_asset({
        "text": "他苦笑着摇头",
        "sound_effects": [{"name": "一个男性，低声自嘲般的一声轻笑，2秒左右，无其他杂音"}],
    })

    assert captured["duration"] is None
    from app.services.audiobook.doubao_sfx_generator import DoubaoSfxGenerator
    final_prompt = DoubaoSfxGenerator.build_text_prompt(
        captured["prompt"], captured["duration"])
    assert "时长约" not in final_prompt
    assert "2秒左右" in final_prompt


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_drops_no_voice_guardrail_for_human_vocal(monkeypatch, tmp_path):
    """轻笑等人声音效不得追加“无人声”约束，但保留纯音效/无背景音乐护栏。"""
    captured = {}
    service = _patch_sfx_generation(monkeypatch, tmp_path, captured)

    await service.generate_segment_sfx_asset({
        "text": "他苦笑着摇头",
        "sound_effects": [{"name": "一声轻笑"}],
    })

    assert "无人声" not in captured["prompt"]
    assert "纯音效" in captured["prompt"]
    assert "无背景音乐" in captured["prompt"]


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_keeps_no_voice_guardrail_by_default(monkeypatch, tmp_path):
    """普通物件音效保持“无人声”护栏；无明确时长时不追加时长提示，
    避免拿旁白时长估算去拉伸短促触发音。"""
    captured = {}
    service = _patch_sfx_generation(monkeypatch, tmp_path, captured)

    await service.generate_segment_sfx_asset(
        {"text": "他推开门", "sound_effects_simple": ["木门吱呀声"]}
    )

    assert "无人声" in captured["prompt"]
    assert captured["duration"] is None
    from app.services.audiobook.doubao_sfx_generator import DoubaoSfxGenerator
    final_prompt = DoubaoSfxGenerator.build_text_prompt(
        captured["prompt"], captured["duration"])
    assert "时长约" not in final_prompt


@pytest.mark.asyncio
async def test_generate_segment_sfx_asset_uses_effect_configured_duration(monkeypatch, tmp_path):
    """描述无时长但工作台配置了 duration：优先于旁白估算。"""
    captured = {}
    service = _patch_sfx_generation(monkeypatch, tmp_path, captured)

    await service.generate_segment_sfx_asset({
        "text": "很长一段旁白文本" * 20,
        "sound_effects": [{"name": "一声轻笑", "duration": 2.0}],
    })

    assert captured["duration"] == 2.0
