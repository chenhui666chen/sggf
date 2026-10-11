"""音色画像文件的落盘口径测试：按目录文件名派生、minimax 两档共用、缺失时不伪造。"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.audiobook import voice_catalog
from app.services.audiobook.voice_catalog import (
    _filename_for_model,
    _merge_voice_profiles,
    _profile_filename_for_model,
    _read_voice_profiles_for_model,
)

SYSTEM_VOICE_MODELS = (
    "qwen-audio-3.1-tts-flash",
    "minimax-speech-2.8-hd",
    "minimax-speech-2.8-turbo",
    "mimo-v2.5-tts",
    "stepaudio-3-tts",
    "seed-tts-2.0-expressive",
)


def test_every_system_voice_model_resolves_a_profile_filename() -> None:
    for model in SYSTEM_VOICE_MODELS:
        filename = _profile_filename_for_model(model)
        assert filename, model
        assert filename == _filename_for_model(model).replace("_voices.json", "_voice_profiles.json")


def test_minimax_hd_and_turbo_share_one_profile_file() -> None:
    assert (
        _profile_filename_for_model("minimax-speech-2.8-hd")
        == _profile_filename_for_model("minimax-speech-2.8-turbo")
    )


def test_missing_profile_file_yields_empty_table_not_default_tags(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        voice_catalog,
        "_resolve_voice_library_path",
        lambda filename: tmp_path / filename,
    )
    assert _read_voice_profiles_for_model("qwen-audio-3.1-tts-flash") == {}


def test_profile_file_is_read_from_shared_layout_with_voice_profiles_key(
    monkeypatch, tmp_path: Path
) -> None:
    payload = {
        "schema_version": "voice-profile-v1",
        "voice_profiles": {
            "longanhuan_v3.1": {"tags": {"timbre": ["warm"]}},
        },
    }
    (tmp_path / _profile_filename_for_model("qwen-audio-3.1-tts-flash")).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        voice_catalog,
        "_resolve_voice_library_path",
        lambda filename: tmp_path / filename,
    )
    profiles = _read_voice_profiles_for_model("qwen-audio-3.1-tts-flash")
    assert profiles["longanhuan_v3.1"]["tags"]["timbre"] == ["warm"]


def test_all_catalog_voices_carry_frozen_preview_text() -> None:
    """试听文本必须写死在目录条目里。

    get_preview_quote_for_voice 会在条目缺文本时按目录位置取模选名言，
    目录任何增删重排都会让其后全部音色的试听文本位移，缓存键随之改变，
    已付费的预览音频与已打好的标签整批错位作废。
    """
    seen: set[str] = set()
    for model in SYSTEM_VOICE_MODELS:
        filename = _filename_for_model(model)
        if filename in seen:
            continue
        seen.add(filename)
        path = voice_catalog._resolve_voice_library_path(filename)
        voices = json.loads(path.read_text(encoding="utf-8")).get("voices") or []
        for voice in voices:
            assert str(voice.get("preview_text") or "").strip(), f"{filename}:{voice.get('id')}"


def test_tags_project_into_runtime_voice_profile_fields(monkeypatch, tmp_path: Path) -> None:
    """受控 code 在 adapter 里投影成运行时中文画像，词表仍是唯一事实源。"""
    profile = {
        "profile_status": "candidate",
        "tags": {
            "age_impression": ["young_adult"],
            "pitch_range": ["low_mid"],
            "pace": ["medium_fast"],
            "timbre": ["warm", "clear"],
            "role_archetype": ["mentor"],
        },
    }
    (tmp_path / _profile_filename_for_model("mimo-v2.5-tts")).write_text(
        json.dumps({"voice_profiles": {"冰糖": profile}}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        voice_catalog,
        "_resolve_voice_library_path",
        lambda filename: tmp_path / filename,
    )

    merged = _merge_voice_profiles("mimo-v2.5-tts", [{"id": "冰糖"}])
    projected = merged[0]["voice_profile"]
    assert projected["age_group"] == "青年"
    assert projected["pitch"] == "中低音"
    assert projected["pace"] == "偏快"
    assert projected["timbre_traits"] == ["温暖", "清亮"]
    assert projected["tags"]["role_archetype"] == ["mentor"]


def test_profile_without_tags_projects_no_runtime_fields(monkeypatch, tmp_path: Path) -> None:
    """pending 画像不得伪造运行时字段。"""
    (tmp_path / _profile_filename_for_model("mimo-v2.5-tts")).write_text(
        json.dumps(
            {"voice_profiles": {"冰糖": {"profile_status": "pending", "tags": {}}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        voice_catalog,
        "_resolve_voice_library_path",
        lambda filename: tmp_path / filename,
    )

    merged = _merge_voice_profiles("mimo-v2.5-tts", [{"id": "冰糖"}])
    projected = merged[0]["voice_profile"]
    assert "age_group" not in projected
    assert "pitch" not in projected
    assert "pace" not in projected
    assert "timbre_traits" not in projected


def test_manual_runtime_fields_win_over_projection(monkeypatch, tmp_path: Path) -> None:
    profile = {
        "tags": {"age_impression": ["young_adult"], "timbre": ["warm"]},
        "age_group": "熟年",
        "timbre_traits": ["人工修订"],
    }
    (tmp_path / _profile_filename_for_model("mimo-v2.5-tts")).write_text(
        json.dumps({"voice_profiles": {"冰糖": profile}}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        voice_catalog,
        "_resolve_voice_library_path",
        lambda filename: tmp_path / filename,
    )

    projected = _merge_voice_profiles("mimo-v2.5-tts", [{"id": "冰糖"}])[0]["voice_profile"]
    assert projected["age_group"] == "熟年"
    assert projected["timbre_traits"] == ["人工修订"]
    assert "pitch" not in projected


def test_merge_voice_projects_profile_into_entry_without_overwriting_existing(
    monkeypatch, tmp_path: Path
) -> None:
    profile = {"tags": {"role_archetype": ["antagonist"]}}
    (tmp_path / _profile_filename_for_model("seed-tts-2.0-expressive")).write_text(
        json.dumps({"voice_profiles": {"old_man": profile}}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        voice_catalog,
        "_resolve_voice_library_path",
        lambda filename: tmp_path / filename,
    )
    merged = _merge_voice_profiles(
        "seed-tts-2.0-expressive",
        [{"id": "old_man"}, {"id": "untagged"}, {"id": "manual", "voice_profile": {"tags": {}}}],
    )
    by_id = {entry["id"]: entry for entry in merged}
    assert by_id["old_man"]["voice_profile"] == profile
    assert "voice_profile" not in by_id["untagged"]
    assert by_id["manual"]["voice_profile"] == {"tags": {}}
