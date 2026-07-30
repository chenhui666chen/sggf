"""Technical validation for materialized scene audio files."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Dict

import numpy as np
from pydub import AudioSegment
from pydub.silence import detect_silence

from app.services.audiobook.atomic_files import write_bytes_atomic

from .quality_policy import (
    DEFAULT_SCENE_AUDIO_QUALITY_POLICY,
    SceneAudioQualityPolicy,
)


ABNORMAL_SILENCE_RATIO_THRESHOLD = (
    DEFAULT_SCENE_AUDIO_QUALITY_POLICY.silence_ratio_threshold
)

# 声学检测内部实现常量（区别于 SceneAudioQualityPolicy 中由 §12-11 收敛的判定阈值）。
_ANALYSIS_FRAME_MS = 30
_MIN_ACOUSTIC_FRAMES = 8
_PEAK_PERCENTILE = 95.0
_FLOOR_PERCENTILE = 5.0
# 混响拖尾：帧能量高于峰值该比例视为语音活跃，低于地板附近该比例视为衰减结束。
_REVERB_SPEECH_ACTIVE_RATIO = 0.3
_REVERB_DECAY_FLOOR_RATIO = 0.1


@dataclass(frozen=True)
class SceneAudioTechnicalReport:
    audio_decodable: bool
    duration_s: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    clipping: bool | None = None
    clipping_ratio: float | None = None
    silence: bool | None = None
    silence_ratio: float | None = None
    channel_correlation: float | None = None
    single_voice: bool | None = None
    background_energy_ratio: float | None = None
    background_music: bool | None = None
    reverb_tail_s: float | None = None
    reverb: bool | None = None
    error: str | None = None

    def to_quality_metadata(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {"audio_decodable": self.audio_decodable}
        if not self.audio_decodable:
            return metadata
        for key in (
            "duration_s",
            "sample_rate",
            "channels",
            "clipping",
            "clipping_ratio",
            "silence",
            "silence_ratio",
            "channel_correlation",
            "single_voice",
            "background_energy_ratio",
            "background_music",
            "reverb_tail_s",
            "reverb",
        ):
            value = getattr(self, key)
            if value is not None:
                metadata[key] = value
        return metadata


class SceneAudioAnalysisCache:
    """按音频内容 SHA-256 持久化技术分析结果，跨运行复用避免重复解码。

    缓存尽力而为：读写失败均静默降级为未命中，不影响主流程正确性。
    """

    _FIELD_NAMES = frozenset(field.name for field in fields(SceneAudioTechnicalReport))

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)

    def _path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> SceneAudioTechnicalReport | None:
        if not key:
            return None
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        filtered = {k: v for k, v in payload.items() if k in self._FIELD_NAMES}
        try:
            return SceneAudioTechnicalReport(**filtered)
        except TypeError:
            return None

    def put(self, key: str, report: SceneAudioTechnicalReport) -> None:
        if not key:
            return
        try:
            data = json.dumps(asdict(report), ensure_ascii=False).encode("utf-8")
            write_bytes_atomic(self._path_for(key), data)
        except OSError:
            return


class SceneAudioTechnicalAnalyzer:
    """Decode an audio file and calculate inexpensive scene-quality signals."""

    def __init__(
        self,
        *,
        policy: SceneAudioQualityPolicy | None = None,
        clipping_ratio_threshold: float | None = None,
        silence_ratio_threshold: float | None = None,
        minimum_silence_ms: int | None = None,
        cache: SceneAudioAnalysisCache | None = None,
    ) -> None:
        resolved_policy = policy or DEFAULT_SCENE_AUDIO_QUALITY_POLICY
        overrides = {}
        if clipping_ratio_threshold is not None:
            overrides["clipping_ratio_threshold"] = clipping_ratio_threshold
        if silence_ratio_threshold is not None:
            overrides["silence_ratio_threshold"] = silence_ratio_threshold
        if minimum_silence_ms is not None:
            overrides["minimum_silence_ms"] = minimum_silence_ms
        self.policy = replace(resolved_policy, **overrides) if overrides else resolved_policy
        self.clipping_ratio_threshold = self.policy.clipping_ratio_threshold
        self.silence_ratio_threshold = self.policy.silence_ratio_threshold
        self.minimum_silence_ms = self.policy.minimum_silence_ms
        self.cache = cache

    @staticmethod
    def _file_sha256(path: str | Path) -> str | None:
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            return None

    def analyze(self, audio_path: str | Path) -> SceneAudioTechnicalReport:
        cache_key = None
        if self.cache is not None:
            cache_key = self._file_sha256(audio_path)
            if cache_key:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    return cached
        report = self._analyze_uncached(audio_path)
        if self.cache is not None and cache_key and report.audio_decodable:
            self.cache.put(cache_key, report)
        return report

    def _analyze_uncached(self, audio_path: str | Path) -> SceneAudioTechnicalReport:
        path = Path(audio_path)

        try:
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"scene audio file not found: {path}")
            audio = AudioSegment.from_file(path)
            if len(audio) <= 0:
                raise ValueError("scene audio is empty")
        except Exception as exc:
            return SceneAudioTechnicalReport(
                audio_decodable=False,
                error=str(exc),
            )

        samples = audio.get_array_of_samples()
        sample_values = np.asarray(samples, dtype=np.float64)
        max_amplitude = float(1 << (8 * audio.sample_width - 1))
        if sample_values.size:
            clipping_count = int(
                np.count_nonzero(
                    np.abs(sample_values)
                    >= max_amplitude * self.policy.clipping_amplitude_ratio
                )
            )
            clipping_ratio = clipping_count / sample_values.size
        else:
            clipping_ratio = 0.0

        if math.isinf(audio.dBFS) and audio.dBFS < 0:
            silence_ratio = 1.0
        else:
            silence_threshold = min(-40.0, float(audio.dBFS) - 16.0)
            silence_ranges = detect_silence(
                audio,
                min_silence_len=self.minimum_silence_ms,
                silence_thresh=silence_threshold,
            )
            silent_ms = sum(max(0, end - start) for start, end in silence_ranges)
            silence_ratio = min(1.0, silent_ms / len(audio))

        channels = int(audio.channels)
        channel_correlation, mono = self._downmix_and_correlate(
            sample_values, channels
        )
        single_voice = (
            True
            if channel_correlation is None
            else channel_correlation >= self.policy.channel_correlation_min
        )
        background_energy_ratio, reverb_tail_s = self._acoustic_signals(
            mono, int(audio.frame_rate)
        )
        background_music = (
            None
            if background_energy_ratio is None
            else background_energy_ratio > self.policy.background_energy_ratio_threshold
        )
        reverb = (
            None
            if reverb_tail_s is None
            else reverb_tail_s > self.policy.reverb_tail_s_threshold
        )

        return SceneAudioTechnicalReport(
            audio_decodable=True,
            duration_s=round(len(audio) / 1000.0, 3),
            sample_rate=int(audio.frame_rate),
            channels=channels,
            clipping=clipping_ratio > self.clipping_ratio_threshold,
            clipping_ratio=round(clipping_ratio, 6),
            silence=silence_ratio > self.silence_ratio_threshold,
            silence_ratio=round(silence_ratio, 6),
            channel_correlation=channel_correlation,
            single_voice=single_voice,
            background_energy_ratio=background_energy_ratio,
            background_music=background_music,
            reverb_tail_s=reverb_tail_s,
            reverb=reverb,
        )

    @staticmethod
    def _downmix_and_correlate(
        sample_values: "np.ndarray", channels: int
    ) -> tuple[float | None, "np.ndarray"]:
        """返回（左右声道皮尔逊相关, 单声道混合）。

        单声道无法廉价判别同轨多说话人，相关性返回 None、由上层按单声源处理；
        立体声以左右声道去相关程度作为多声源（背景乐/多人）代理信号。
        """
        if sample_values.size == 0:
            return None, sample_values
        if channels < 2:
            return None, sample_values
        usable = (sample_values.size // channels) * channels
        if usable <= 0:
            return None, sample_values
        per_channel = sample_values[:usable].reshape(-1, channels)
        mono = per_channel.mean(axis=1)
        left = per_channel[:, 0]
        right = per_channel[:, 1]
        left_centered = left - left.mean()
        right_centered = right - right.mean()
        denom = math.sqrt(
            float(np.dot(left_centered, left_centered))
            * float(np.dot(right_centered, right_centered))
        )
        if denom <= 0:
            return None, mono
        correlation = float(np.dot(left_centered, right_centered) / denom)
        return round(max(-1.0, min(1.0, correlation)), 6), mono

    @classmethod
    def _acoustic_signals(
        cls, mono: "np.ndarray", frame_rate: int
    ) -> tuple[float | None, float | None]:
        """基于帧级 RMS 计算（背景能量地板比, 混响拖尾秒数）。

        帧数不足或全静音时返回 (None, None)，避免对过短样本做不可靠判断。
        """
        if mono.size == 0 or frame_rate <= 0:
            return None, None
        frame_len = max(1, int(round(frame_rate * _ANALYSIS_FRAME_MS / 1000.0)))
        n_frames = mono.size // frame_len
        if n_frames < _MIN_ACOUSTIC_FRAMES:
            return None, None
        frames = mono[: n_frames * frame_len].reshape(n_frames, frame_len)
        frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
        peak = float(np.percentile(frame_rms, _PEAK_PERCENTILE))
        if peak <= 0:
            return None, None
        floor = float(np.percentile(frame_rms, _FLOOR_PERCENTILE))
        background_energy_ratio = round(min(1.0, floor / peak), 6)
        reverb_tail_s = cls._estimate_reverb_tail_s(
            frame_rms, peak, floor, frame_len, frame_rate
        )
        return background_energy_ratio, reverb_tail_s

    @staticmethod
    def _estimate_reverb_tail_s(
        frame_rms: "np.ndarray",
        peak: float,
        floor: float,
        frame_len: int,
        frame_rate: int,
    ) -> float | None:
        """语音活跃段结束后能量衰减到地板附近所需时长的中位值（秒）。

        干声在语音结束后能量骤降，拖尾接近 0；混响会让能量缓慢衰减，拖尾更长。
        无可用衰减段时返回 None。
        """
        speech_thresh = peak * _REVERB_SPEECH_ACTIVE_RATIO
        quiet_thresh = floor + (peak - floor) * _REVERB_DECAY_FLOOR_RATIO
        active = frame_rms >= speech_thresh
        n = frame_rms.size
        tails: list[int] = []
        index = 1
        while index < n:
            if active[index - 1] and not active[index]:
                cursor = index
                while (
                    cursor < n
                    and not active[cursor]
                    and frame_rms[cursor] > quiet_thresh
                ):
                    cursor += 1
                tails.append(cursor - index)
                index = max(cursor, index + 1)
            else:
                index += 1
        if not tails:
            return None
        median_frames = float(np.median(tails))
        return round(median_frames * frame_len / frame_rate, 4)
