# -*- coding: utf-8 -*-
"""音效响度归一化合同测试。

背景：音效素材源能量参差（实测 -13 ~ -32dBFS），按资产绝对能量口径叠加
固定偏移时，触发类音效被人声（约 -28dBFS）听觉掩蔽、静音底轨试听近乎
无声。修复改为响度归一化口径：素材统一到类型响度基准，volume 参数成为
真实相对响度偏移。
"""

import io
import math
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

from app.services.audiobook.audio_mixer import (  # noqa: E402
    SFX_TARGET_LOUDNESS_DBFS,
    AudioMixer,
    sfx_loudness_plan,
)
from app.services.audiobook.engine_pkg import _sfx_mixin  # noqa: E402
from app.services.audiobook.engine_pkg._sfx_mixin import SfxMixin  # noqa: E402


def _to_wav_bytes(segment: AudioSegment) -> bytes:
    buf = io.BytesIO()
    segment.export(buf, format="wav")
    return buf.getvalue()


def test_loudness_plan_targets_from_type_table():
    # (类型, volume) -> 目标响度必须来自类型基准表
    assert sfx_loudness_plan("action", 0.5) == (SFX_TARGET_LOUDNESS_DBFS["action"], 0.0)
    assert sfx_loudness_plan("environment", 0.5) == (
        SFX_TARGET_LOUDNESS_DBFS["environment"],
        0.0,
    )


def test_loudness_plan_volume_is_relative_offset():
    """volume 参数换算为相对默认音量（0.5）的 dB 偏移，与类型基准解耦。"""
    target, offset = sfx_loudness_plan("action", 0.25)
    assert target == SFX_TARGET_LOUDNESS_DBFS["action"]
    assert abs(offset - 20 * math.log10(0.25 / 0.5)) < 1e-6


def test_loudness_plan_tolerates_bad_volume_and_type():
    target, offset = sfx_loudness_plan("unknown_type", "not-a-number")
    assert offset == 0.0
    assert target <= -27.0  # 未知类型不得比过渡音更响
    target_low, _ = sfx_loudness_plan("action", 0)
    assert target_low == SFX_TARGET_LOUDNESS_DBFS["action"]


def test_normalization_unifies_assets_of_different_source_energy():
    """不同源能量的素材归一化后叠加响度应接近一致（±2dB）。"""
    mixer = AudioMixer(force_pydub=True)
    voice = _to_wav_bytes(AudioSegment.silent(duration=2000, frame_rate=44100))
    loud = _to_wav_bytes(Sine(880).to_audio_segment(duration=500, volume=-6))
    quiet = _to_wav_bytes(Sine(880).to_audio_segment(duration=500, volume=-30))

    def measure(effect_bytes: bytes) -> float:
        mixed = mixer.add_sound_effect(
            voice,
            effect_bytes,
            position_ms=500,
            effect_volume_offset=0.0,
            effect_duration_ms=500,
            ducking_enabled=False,
            normalize_target_dbfs=-22.0,
        )
        out = AudioSegment.from_file(io.BytesIO(mixed))
        return out[500:1000].dBFS

    loud_db, quiet_db = measure(loud), measure(quiet)
    assert abs(loud_db - quiet_db) < 2.0
    assert abs(loud_db - (-22.0)) < 2.0


def test_normalization_respects_relative_volume_offset():
    """归一化后 volume 偏移仍生效：0.25 应比 0.5 低约 6dB。"""
    mixer = AudioMixer(force_pydub=True)
    voice = _to_wav_bytes(AudioSegment.silent(duration=2000, frame_rate=44100))
    effect = _to_wav_bytes(Sine(880).to_audio_segment(duration=500, volume=-18))

    def measure(offset_db: float) -> float:
        mixed = mixer.add_sound_effect(
            voice,
            effect,
            position_ms=500,
            effect_volume_offset=offset_db,
            effect_duration_ms=500,
            ducking_enabled=False,
            normalize_target_dbfs=-22.0,
        )
        out = AudioSegment.from_file(io.BytesIO(mixed))
        return out[500:1000].dBFS

    default_db = measure(0.0)
    halved_db = measure(20 * math.log10(0.25 / 0.5))
    assert abs((default_db - halved_db) - 6.0) < 1.5


def test_no_normalize_target_keeps_legacy_absolute_offset():
    """未提供归一化目标时保持旧绝对偏移语义（stem 重混等调用方不受影响）。"""
    mixer = AudioMixer(force_pydub=True)
    voice = _to_wav_bytes(AudioSegment.silent(duration=2000, frame_rate=44100))
    effect = _to_wav_bytes(Sine(880).to_audio_segment(duration=500, volume=-18))

    mixed = mixer.add_sound_effect(
        voice,
        effect,
        position_ms=500,
        effect_volume_offset=-6,
        effect_duration_ms=500,
        ducking_enabled=False,
    )
    out = AudioSegment.from_file(io.BytesIO(mixed))
    # 绝对口径：-18dB 素材叠加 -6dB 偏移，约 -24dB（叠加底噪略有抬升）
    assert -30.0 < out[500:1000].dBFS < -20.0


def test_normalization_survives_silent_effect():
    """全静素材 dBFS 为 -inf：归一化须跳过且不抛异常、不改变结果。"""
    mixer = AudioMixer(force_pydub=True)
    voice = _to_wav_bytes(AudioSegment.silent(duration=1000, frame_rate=44100))
    effect = _to_wav_bytes(AudioSegment.silent(duration=300, frame_rate=44100))

    mixed = mixer.add_sound_effect(
        voice,
        effect,
        position_ms=100,
        effect_volume_offset=0.0,
        effect_duration_ms=300,
        ducking_enabled=False,
        normalize_target_dbfs=-22.0,
    )
    assert mixed is not voice
    out = AudioSegment.from_file(io.BytesIO(mixed))
    assert out.max_dBFS < -40.0


class _Renderer(SfxMixin):
    def __init__(self, mixer):
        self.audio_mixer = mixer
        self._audio_fx_config = {}


def test_apply_sound_effects_passes_normalization_plan(tmp_path, monkeypatch):
    """mixin 须把归一化目标与相对音量偏移传给混音器，不再携带资产能量偏差。"""
    effect_file = tmp_path / "sfx.mp3"
    effect_file.write_bytes(b"ID3effect")
    monkeypatch.setattr(_sfx_mixin, "resolve_audio_library_file_path", lambda ref, base: effect_file)
    monkeypatch.setattr(_sfx_mixin, "get_audio_library_dir", lambda: tmp_path)

    calls = []

    class _CapturingMixer:
        def add_sound_effect(self, voice_audio, effect_audio, **kwargs):
            calls.append(kwargs)
            return voice_audio + b"E"

    renderer = _Renderer(_CapturingMixer())
    timeline = {"timeline": [
        {"timestamp": 1.0, "type": "action", "file": "sfx.mp3", "volume": 0.25},
    ]}
    renderer._apply_sound_effects(b"BASE", timeline)

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["normalize_target_dbfs"] == SFX_TARGET_LOUDNESS_DBFS["action"]
    assert abs(kwargs["effect_volume_offset"] - 20 * math.log10(0.25 / 0.5)) < 1e-6
