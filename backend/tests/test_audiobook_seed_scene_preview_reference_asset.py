from __future__ import annotations

import base64
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceMaterializer,
    PreviewReferenceMaterializationError,
)


def _wav_bytes(*, duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    frame_count = int(duration_s * sample_rate)
    frames = bytearray()
    for index in range(frame_count):
        sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))

    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


def test_materializer_persists_base64_preview_as_seed_audio_data(tmp_path: Path) -> None:
    audio_bytes = _wav_bytes()
    data_url = "data:audio/wav;base64," + base64.b64encode(audio_bytes).decode("ascii")

    asset = PreviewReferenceMaterializer(output_root=tmp_path).materialize(
        {
            "tts_model": "qwen-audio-3.1-tts-flash",
            "voice_id": "voice-a",
            "preview_audio_data": data_url,
        }
    )

    assert asset.reference == {
        "audio_data": base64.b64encode(audio_bytes).decode("ascii"),
    }
    assert asset.storage_path.exists()
    assert asset.storage_path.read_bytes() == audio_bytes
    assert asset.duration_s == 1.0
    assert asset.sha256
    assert asset.source_url is None


def test_materializer_downloads_url_but_does_not_pass_temporary_url_to_seed_audio(
    tmp_path: Path,
) -> None:
    audio_bytes = _wav_bytes()
    downloaded_urls: list[str] = []

    def downloader(url: str) -> bytes:
        downloaded_urls.append(url)
        return audio_bytes

    asset = PreviewReferenceMaterializer(
        output_root=tmp_path,
        downloader=downloader,
    ).materialize(
        {
            "tts_model": "cosyvoice-v3.5-plus",
            "voice_id": "voice-b",
            "preview_audio_url": "https://cdn.example.test/preview.wav",
        }
    )

    assert downloaded_urls == ["https://cdn.example.test/preview.wav"]
    assert asset.source_url == "https://cdn.example.test/preview.wav"
    assert "audio_url" not in asset.reference
    assert asset.reference["audio_data"] == base64.b64encode(audio_bytes).decode("ascii")


def test_materializer_rejects_invalid_base64(tmp_path: Path) -> None:
    with pytest.raises(PreviewReferenceMaterializationError, match="invalid_base64"):
        PreviewReferenceMaterializer(output_root=tmp_path).materialize(
            {"preview_audio_data": "data:audio/wav;base64,not-base64"}
        )


def test_materializer_rejects_empty_audio(tmp_path: Path) -> None:
    with pytest.raises(PreviewReferenceMaterializationError, match="empty_audio"):
        PreviewReferenceMaterializer(output_root=tmp_path).materialize(
            {"preview_audio_data": "data:audio/wav;base64,"}
        )


def test_materializer_rejects_audio_over_size_limit(tmp_path: Path) -> None:
    with pytest.raises(PreviewReferenceMaterializationError, match="audio_too_large"):
        PreviewReferenceMaterializer(
            output_root=tmp_path,
            max_audio_bytes=4,
        ).materialize({"preview_audio_data": base64.b64encode(b"12345").decode("ascii")})


def test_materializer_rejects_audio_over_duration_limit(tmp_path: Path) -> None:
    audio_bytes = _wav_bytes()

    class LongAudioAnalyzer:
        def analyze(self, _path: Path):
            return type(
                "Report",
                (),
                {"audio_decodable": True, "duration_s": 30.001},
            )()

    with pytest.raises(PreviewReferenceMaterializationError, match="audio_too_long"):
        PreviewReferenceMaterializer(
            output_root=tmp_path,
            technical_analyzer=LongAudioAnalyzer(),
        ).materialize({"preview_audio_data": base64.b64encode(audio_bytes).decode("ascii")})


def test_materializer_reuses_stable_path_and_sha256_for_same_preview(tmp_path: Path) -> None:
    audio_bytes = _wav_bytes()
    config = {"preview_audio_data": base64.b64encode(audio_bytes).decode("ascii")}
    materializer = PreviewReferenceMaterializer(output_root=tmp_path)

    first = materializer.materialize(config)
    second = materializer.materialize(config)

    assert first.storage_path == second.storage_path
    assert first.sha256 == second.sha256


def test_materializer_uses_shared_preview_cache_when_mapping_has_no_inline_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    audio_bytes = _wav_bytes()
    requested_urls: list[str] = []

    monkeypatch.setattr(
        "app.services.audiobook.scene_engine.preview_reference_asset.build_default_preview_cache_key",
        lambda **_kwargs: "cache-key-for-preview",
    )
    monkeypatch.setattr(
        "app.services.audiobook.scene_engine.preview_reference_asset.check_oss_preview_exists",
        lambda cache_key, ext="mp3": "https://cdn.example.test/cached.wav"
        if cache_key == "cache-key-for-preview" and ext == "wav"
        else None,
    )

    def downloader(url: str) -> bytes:
        requested_urls.append(url)
        return audio_bytes

    asset = PreviewReferenceMaterializer(
        output_root=tmp_path,
        downloader=downloader,
    ).materialize({"tts_model": "qwen-audio-3.1-tts-flash", "voice_id": "voice-c"})

    assert requested_urls == ["https://cdn.example.test/cached.wav"]
    assert asset.source_preview_cache_key == "cache-key-for-preview"
