# -*- coding: utf-8 -*-
import asyncio
import math
import os
import random
import subprocess
import sys
import wave
from array import array
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_import_path() -> None:
    backend_dir = _repo_root() / "backend"
    sys.path.insert(0, str(backend_dir))


def _load_dotenv() -> None:
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


def _write_wav(path: Path, samples: list[float], sample_rate: int) -> None:
    frames = array("h")
    for value in samples:
        clamped = max(-1.0, min(1.0, value))
        frames.append(int(clamped * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames.tobytes())


def _piano_envelope(t: float, attack: float = 0.02, decay: float = 2.6) -> float:
    if t <= 0:
        return 0.0
    if t < attack:
        return t / attack
    return math.exp(-t / decay)


def _generate_piano_bgm(path: Path, duration: float, sample_rate: int) -> None:
    total_samples = int(duration * sample_rate)
    samples = [0.0] * total_samples
    two_pi = 2.0 * math.pi
    chord_duration = 4.0
    chord_samples = int(chord_duration * sample_rate)
    chords = [
        (261.63, 329.63, 392.00),
        (196.00, 246.94, 392.00),
        (220.00, 261.63, 329.63),
        (174.61, 220.00, 349.23),
    ]
    for chord_index, start in enumerate(range(0, total_samples, chord_samples)):
        chord = chords[chord_index % len(chords)]
        remaining = total_samples - start
        count = min(chord_samples, remaining)
        for i in range(count):
            t = i / sample_rate
            env = _piano_envelope(t)
            value = 0.0
            for freq in chord:
                value += math.sin(two_pi * freq * t)
                value += 0.35 * math.sin(two_pi * (freq * 2.0) * t)
            value /= (len(chord) * 1.35)
            samples[start + i] += value * env * 0.12
    _write_wav(path, samples, sample_rate)


def _add_chirp(
    samples: list[float],
    start_index: int,
    length: int,
    sample_rate: int,
    freq_start: float,
    freq_end: float,
    amplitude: float,
) -> None:
    two_pi = 2.0 * math.pi
    for i in range(length):
        t = i / sample_rate
        progress = i / max(1, length - 1)
        freq = freq_start + (freq_end - freq_start) * progress
        env = math.sin(math.pi * progress)
        samples[start_index + i] += amplitude * env * math.sin(two_pi * freq * t)


def _generate_bird_sfx(path: Path, duration: float, sample_rate: int) -> None:
    total_samples = int(duration * sample_rate)
    samples = [0.0] * total_samples
    chirp_duration = 0.6
    chirp_samples = int(chirp_duration * sample_rate)
    chirp_times = [3.0, 9.5, 16.5, 23.0, 27.5]
    for start_time in chirp_times:
        start_index = int(start_time * sample_rate)
        if start_index + chirp_samples > total_samples:
            continue
        _add_chirp(
            samples,
            start_index,
            chirp_samples,
            sample_rate,
            freq_start=520.0,
            freq_end=680.0,
            amplitude=0.08,
        )
    _write_wav(path, samples, sample_rate)


def _generate_water_pour_sfx(path: Path, duration: float, sample_rate: int) -> None:
    total_samples = int(duration * sample_rate)
    samples = [0.0] * total_samples
    rng = random.Random(7)
    pour_events = [(6.5, 0.8), (19.0, 0.7)]
    for start_time, event_duration in pour_events:
        start_index = int(start_time * sample_rate)
        length = int(event_duration * sample_rate)
        if start_index + length > total_samples:
            continue
        prev = 0.0
        for i in range(length):
            progress = i / max(1, length - 1)
            noise = rng.uniform(-1.0, 1.0)
            prev = prev * 0.9 + noise * 0.1
            env = math.sin(math.pi * progress) * math.exp(-2.0 * progress)
            samples[start_index + i] += prev * env * 0.28
    _write_wav(path, samples, sample_rate)


async def main() -> None:
    _ensure_import_path()
    _load_dotenv()
    from app.services.audiobook.tts_engine import TTSEngine

    output_dir = _repo_root() / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    duration_seconds = 30.0
    sample_rate = 44100

    text = "窗外的阳光真好，泡一杯热茶，享受这片刻的宁静吧"
    engine = TTSEngine(enable_cache=False, max_concurrent=1, model="cosyvoice-v3-plus", request_delay=0.0)
    voice_params = {
        "speaker": "longanhuan",
        "volume": 50,
        "instruct_scene": "闲聊互动",
        "instruct_emotion": "neutral",
    }

    voice_audio = await engine.synthesize(text, voice_params)
    if not voice_audio:
        raise RuntimeError("empty audio response")

    voice_path = output_dir / "tts_voice_30s.mp3"
    voice_path.write_bytes(voice_audio)

    bgm_path = output_dir / "bgm_piano_30s.wav"
    birds_path = output_dir / "sfx_birds_30s.wav"
    pour_path = output_dir / "sfx_pour_30s.wav"
    _generate_piano_bgm(bgm_path, duration_seconds, sample_rate)
    _generate_bird_sfx(birds_path, duration_seconds, sample_rate)
    _generate_water_pour_sfx(pour_path, duration_seconds, sample_rate)

    output_path = output_dir / "voice_bgm_sfx_30s.mp3"
    filter_complex = (
        "[1:a]volume=0.3[bgm];"
        "[2:a]volume=0.12[birds];"
        "[3:a]volume=0.2[pour];"
        "[0:a][bgm][birds][pour]"
        "amix=inputs=4:duration=longest:dropout_transition=2,"
        "aresample=44100"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(voice_path),
        "-i",
        str(bgm_path),
        "-i",
        str(birds_path),
        "-i",
        str(pour_path),
        "-filter_complex",
        filter_complex,
        "-t",
        str(int(duration_seconds)),
        "-ar",
        str(sample_rate),
        "-b:a",
        "128k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    print(f"saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
