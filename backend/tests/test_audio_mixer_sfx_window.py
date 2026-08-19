# -*- coding: utf-8 -*-
"""音效叠加高能窗口选取与失败计数诚实性测试。

背景：一次性音效的声体常位于素材中后段，按 duration 盲取头部会只剩
静默前奏，叠加/试听均不可闻；add_sound_effect 静默失败时 applied 计数
仍自增，误导排查。
"""

import io
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from pydub import AudioSegment  # noqa: E402
from pydub.generators import Sine  # noqa: E402

from app.services.audiobook.audio_mixer import AudioMixer  # noqa: E402
from app.services.audiobook.engine_pkg import _sfx_mixin  # noqa: E402
from app.services.audiobook.engine_pkg._sfx_mixin import SfxMixin  # noqa: E402


def _to_wav_bytes(segment: AudioSegment) -> bytes:
    buf = io.BytesIO()
    segment.export(buf, format="wav")
    return buf.getvalue()


def _make_late_transient_effect() -> AudioSegment:
    """1.5s 静默头 + 0.5s 响亮声体 + 1s 静默尾（模拟骨裂声类素材）。"""
    silence = AudioSegment.silent(duration=1500, frame_rate=44100)
    burst = Sine(880).to_audio_segment(duration=500, volume=-8)
    tail = AudioSegment.silent(duration=1000, frame_rate=44100)
    return silence + burst + tail


def test_select_energetic_window_picks_late_transient():
    effect = _make_late_transient_effect()
    selected = AudioMixer._select_energetic_window(effect, 500)
    assert len(selected) == 500
    # 选中窗口必须覆盖声体（静默头约 -inf/-50dB，声体 -8dB）
    assert selected.dBFS > -25.0


def test_select_energetic_window_prefers_earlier_when_close():
    """能量接近（6dB 内）时优先取更早窗口，保留音效起始手感。"""
    burst_a = Sine(880).to_audio_segment(duration=400, volume=-10)
    gap = AudioSegment.silent(duration=800, frame_rate=44100)
    burst_b = Sine(880).to_audio_segment(duration=400, volume=-11)
    effect = burst_a + gap + burst_b
    selected = AudioMixer._select_energetic_window(effect, 400)
    assert selected.dBFS > -25.0
    # 早窗口起始位置应明显早于后段 burst
    head = effect[:400]
    assert abs(selected.dBFS - head.dBFS) < 1.0


def test_select_energetic_window_returns_unchanged_when_not_truncated():
    effect = _make_late_transient_effect()
    assert AudioMixer._select_energetic_window(effect, 5000) is effect


def test_add_sound_effect_truncation_keeps_transient_audible():
    """duration 截断不得只剩静默头：叠加结果峰值应可闻。"""
    mixer = AudioMixer(force_pydub=True)
    voice = _to_wav_bytes(AudioSegment.silent(duration=3000, frame_rate=44100))
    effect = _to_wav_bytes(_make_late_transient_effect())

    mixed = mixer.add_sound_effect(
        voice,
        effect,
        position_ms=500,
        effect_volume_offset=-7,
        effect_duration_ms=500,
        loop_fill=False,
        ducking_enabled=False,
    )

    assert mixed is not voice
    out = AudioSegment.from_file(io.BytesIO(mixed))
    # 修复前：只截到静默头，输出约等于静音；修复后声体入窗，峰值显著
    assert out.max_dBFS > -30.0


def test_add_sound_effect_loop_not_affected_by_window_selection():
    """循环环境床不走高能窗口（避免相位跳变）：头部起播保持不变。"""
    mixer = AudioMixer(force_pydub=True)
    voice = _to_wav_bytes(AudioSegment.silent(duration=3000, frame_rate=44100))
    effect_seg = _make_late_transient_effect()
    effect = _to_wav_bytes(effect_seg)

    mixed = mixer.add_sound_effect(
        voice,
        effect,
        position_ms=0,
        effect_volume_offset=0,
        effect_duration_ms=2000,
        loop_fill=True,
        ducking_enabled=False,
    )
    out = AudioSegment.from_file(io.BytesIO(mixed))
    # loop 截断取素材头部 1.5s 静默 + 0.5s 声体起点，头部 1s 应接近静音
    assert out[:1000].max_dBFS < -40.0


class _Renderer(SfxMixin):
    def __init__(self, mixer):
        self.audio_mixer = mixer
        self._audio_fx_config = {}


class _NoopMixer:
    """模拟 add_sound_effect 静默失败：原样返回入参对象。"""

    def add_sound_effect(self, voice_audio, effect_audio, **kwargs):
        return voice_audio


class _RealishMixer:
    """模拟叠加成功：返回新对象。"""

    def add_sound_effect(self, voice_audio, effect_audio, **kwargs):
        return voice_audio + b"E"


def test_apply_sound_effects_counts_silent_noop_as_skipped(tmp_path, monkeypatch, caplog):
    effect_file = tmp_path / "sfx.mp3"
    effect_file.write_bytes(b"ID3effect")
    monkeypatch.setattr(_sfx_mixin, "resolve_audio_library_file_path", lambda ref, base: effect_file)
    monkeypatch.setattr(_sfx_mixin, "get_audio_library_dir", lambda: tmp_path)

    renderer = _Renderer(_NoopMixer())
    timeline = {"timeline": [{"timestamp": 1.0, "type": "action", "file": "sfx.mp3", "volume": 0.5}]}
    import logging

    with caplog.at_level(logging.INFO, logger="app.services.audiobook.engine_pkg._sfx_mixin"):
        result = renderer._apply_sound_effects(b"BASE", timeline)

    assert result == b"BASE"  # 静默失败不得改变音频
    summary = [r.message for r in caplog.records if "音效时间线处理完成" in r.message]
    assert summary and "applied=0" in summary[0] and "skipped=1" in summary[0]


def test_apply_sound_effects_counts_real_overlay_as_applied(tmp_path, monkeypatch, caplog):
    effect_file = tmp_path / "sfx.mp3"
    effect_file.write_bytes(b"ID3effect")
    monkeypatch.setattr(_sfx_mixin, "resolve_audio_library_file_path", lambda ref, base: effect_file)
    monkeypatch.setattr(_sfx_mixin, "get_audio_library_dir", lambda: tmp_path)

    renderer = _Renderer(_RealishMixer())
    timeline = {"timeline": [{"timestamp": 1.0, "type": "action", "file": "sfx.mp3", "volume": 0.5}]}
    import logging

    with caplog.at_level(logging.INFO, logger="app.services.audiobook.engine_pkg._sfx_mixin"):
        result = renderer._apply_sound_effects(b"BASE", timeline)

    assert result == b"BASEE"
    summary = [r.message for r in caplog.records if "音效时间线处理完成" in r.message]
    assert summary and "applied=1" in summary[0] and "skipped=0" in summary[0]
