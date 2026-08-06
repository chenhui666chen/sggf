"""segment_timeline_preview：管线时间线按片段试听渲染测试。"""

import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import segment_timeline_preview  # noqa: E402
from app.services.audiobook.engine_pkg import _music_mixin, _sfx_mixin  # noqa: E402
from app.services.audiobook.segment_timeline_preview import (  # noqa: E402
    render_segment_timeline_preview,
)


class FakeMixer:
    def __init__(self):
        self.silence_ms = []
        self.sound_effects = []
        self.background_music = []

    def create_silence(self, duration_ms, output_format=None, bitrate=None):
        self.silence_ms.append(duration_ms)
        return b"SILENCE"

    def add_sound_effect(self, base_audio, effect_audio, **kwargs):
        self.sound_effects.append(kwargs)
        return base_audio + b"E"

    def add_background_music(self, base_audio, bgm_audio, **kwargs):
        self.background_music.append(kwargs)
        return base_audio + b"M"


@pytest.fixture()
def audio_library_files(tmp_path, monkeypatch):
    """让引擎叠加逻辑能解析到真实存在的素材文件。"""
    effect_file = tmp_path / "effect.mp3"
    effect_file.write_bytes(b"ID3effect")
    music_file = tmp_path / "music.mp3"
    music_file.write_bytes(b"ID3music")

    def resolve_effect(file_ref, base_dir):
        return effect_file if file_ref else None

    def resolve_music(file_ref, base_dir):
        return music_file if file_ref else None

    monkeypatch.setattr(_sfx_mixin, "resolve_audio_library_file_path", resolve_effect)
    monkeypatch.setattr(_music_mixin, "resolve_audio_library_file_path", resolve_music)
    monkeypatch.setattr(_sfx_mixin, "get_audio_library_dir", lambda: tmp_path)
    monkeypatch.setattr(_music_mixin, "get_audio_library_dir", lambda: tmp_path)
    return tmp_path


def _checkpoint(effect_items=None, music_items=None, timings=None):
    checkpoint = {
        "segment_timings": timings
        if timings is not None
        else [
            {"index": 0, "start": 0.0, "end": 10.0, "duration": 10.0},
            {"index": 1, "start": 10.0, "end": 18.0, "duration": 8.0},
        ],
    }
    if effect_items is not None:
        checkpoint["effect_timeline"] = {"timeline": effect_items}
    if music_items is not None:
        checkpoint["music_timeline"] = {"timeline": music_items}
    return checkpoint


def test_sfx_preview_selects_items_within_segment_window(audio_library_files):
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        effect_items=[
            {"timestamp": 2.0, "type": "action", "file": "e1.mp3", "volume": 0.5, "duration": 3.0},
            {"timestamp": 12.0, "type": "action", "file": "e2.mp3", "volume": 0.5, "duration": 1.0},
            {"timestamp": 25.0, "type": "action", "file": "e3.mp3", "volume": 0.5, "duration": 1.0},
        ]
    )

    rendered = render_segment_timeline_preview(
        checkpoint=checkpoint,
        segment_index=0,
        preview_type="sfx",
        audio_mixer=mixer,
    )

    assert rendered == b"SILENCEE"
    assert mixer.silence_ms == [10000]
    # 仅窗口内条目被叠加，时间戳已转为片段内相对时间
    assert len(mixer.sound_effects) == 1
    assert mixer.sound_effects[0]["position_ms"] == 2000
    assert mixer.sound_effects[0]["effect_duration_ms"] == 3000


def test_sfx_preview_clamps_long_loop_to_segment_window(audio_library_files):
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        effect_items=[
            {
                "timestamp": 12.0,
                "type": "environment",
                "file": "loop.mp3",
                "volume": 0.15,
                "duration": 114.7,
                "loop": True,
            }
        ]
    )

    rendered = render_segment_timeline_preview(
        checkpoint=checkpoint,
        segment_index=1,
        preview_type="sfx",
        audio_mixer=mixer,
    )

    assert rendered == b"SILENCEE"
    assert mixer.silence_ms == [8000]
    # 长循环素材截断到片段窗口剩余时长（18-12=6s）
    assert mixer.sound_effects[0]["effect_duration_ms"] == 6000
    assert mixer.sound_effects[0]["loop_fill"] is True


def test_bgm_preview_renders_music_cue_of_segment(audio_library_files):
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        music_items=[
            {
                "timestamp": 0.0,
                "type": "opening",
                "mood": "peaceful",
                "file": "m1.mp3",
                "volume": 0.3,
                "duration": 15.0,
                "fade_in": 2.0,
                "fade_out": 4.0,
            },
            {"timestamp": 12.0, "type": "underscore", "mood": "tense", "file": "m2.mp3", "volume": 0.2},
        ]
    )

    rendered = render_segment_timeline_preview(
        checkpoint=checkpoint,
        segment_index=0,
        preview_type="bgm",
        audio_mixer=mixer,
    )

    assert rendered == b"SILENCEM"
    assert len(mixer.background_music) == 1
    assert mixer.background_music[0]["position_ms"] == 0
    # 窗口内唯一 cue 按“延续到结尾”语义播放（duration=None），实际可听边界由 10s 窗口底轨截断保底
    assert mixer.background_music[0]["duration_ms"] is None
    assert mixer.background_music[0]["fade_out_ms"] >= 2500
    assert mixer.background_music[0]["fade_in_ms"] == 2000


def test_bgm_preview_includes_continuing_cue_from_previous_window(audio_library_files):
    """配乐跨片段持续：后续片段也能试听延续中的 cue（从头播放剩余时长）。"""
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        music_items=[
            # 在片段0窗口内触发，持续20s，覆盖片段1（10-18）
            {"timestamp": 8.0, "type": "underscore", "mood": "tense", "file": "m1.mp3",
             "volume": 0.2, "duration": 20.0, "fade_in": 2.0}
        ]
    )

    rendered = render_segment_timeline_preview(
        checkpoint=checkpoint,
        segment_index=1,
        preview_type="bgm",
        audio_mixer=mixer,
    )

    assert rendered == b"SILENCEM"
    assert len(mixer.background_music) == 1
    # 延续 cue 从片段开头播放，去掉淡入；作为当前时间线最后一个 cue 延续到结尾（窗口 8s 底轨截断保底）
    assert mixer.background_music[0]["position_ms"] == 0
    assert mixer.background_music[0]["fade_in_ms"] == 0
    assert mixer.background_music[0]["duration_ms"] is None
    assert mixer.background_music[0]["fade_out_ms"] >= 2500


def test_bgm_preview_skips_expired_cue(audio_library_files):
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        music_items=[
            # 已在片段1开始前结束，不属于该片段
            {"timestamp": 0.0, "type": "underscore", "mood": "tense", "file": "m1.mp3",
             "volume": 0.2, "duration": 5.0}
        ]
    )

    assert (
        render_segment_timeline_preview(
            checkpoint=checkpoint,
            segment_index=1,
            preview_type="bgm",
            audio_mixer=mixer,
        )
        is None
    )


def test_sfx_preview_ignores_continuation_semantics(audio_library_files):
    """音效不做延续归属：窗口前触发的长音效不归属后续片段。"""
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        effect_items=[
            {"timestamp": 2.0, "type": "environment", "file": "loop.mp3",
             "volume": 0.2, "duration": 100.0, "loop": True}
        ]
    )

    assert (
        render_segment_timeline_preview(
            checkpoint=checkpoint,
            segment_index=1,
            preview_type="sfx",
            audio_mixer=mixer,
        )
        is None
    )


def test_preview_returns_none_when_segment_has_no_timeline_items(audio_library_files):
    mixer = FakeMixer()
    checkpoint = _checkpoint(
        effect_items=[{"timestamp": 2.0, "type": "action", "file": "e1.mp3", "volume": 0.5}]
    )

    assert (
        render_segment_timeline_preview(
            checkpoint=checkpoint,
            segment_index=1,
            preview_type="sfx",
            audio_mixer=mixer,
        )
        is None
    )
    assert mixer.silence_ms == []


def test_preview_returns_none_without_segment_timings(audio_library_files):
    checkpoint = _checkpoint(
        effect_items=[{"timestamp": 2.0, "type": "action", "file": "e1.mp3", "volume": 0.5}],
        timings=[],
    )

    assert (
        render_segment_timeline_preview(
            checkpoint=checkpoint,
            segment_index=0,
            preview_type="sfx",
            audio_mixer=FakeMixer(),
        )
        is None
    )


def test_preview_rejects_unknown_preview_type(audio_library_files):
    checkpoint = _checkpoint()
    assert (
        render_segment_timeline_preview(
            checkpoint=checkpoint,
            segment_index=0,
            preview_type="voice",
            audio_mixer=FakeMixer(),
        )
        is None
    )
