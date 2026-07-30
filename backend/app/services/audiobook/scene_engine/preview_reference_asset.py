"""Materialize existing TTS previews as stable Seed Audio references."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import httpx

from app.services.audiobook.atomic_files import write_bytes_atomic
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.audiobook.tts_preview_cache import (
    build_default_preview_cache_key,
    check_oss_preview_exists,
)

from .audio_analysis import SceneAudioAnalysisCache, SceneAudioTechnicalAnalyzer


_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[^,;]+(?:;[^,;]+)*);base64,(?P<data>.*)$",
    re.DOTALL,
)
_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
}
_MIME_EXTENSIONS = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/x-mp3": "mp3",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
}


class PreviewReferenceMaterializationError(ValueError):
    """Raised when an existing preview cannot become a Seed Audio reference."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        message = code if not detail else f"{code}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class PreviewReferenceAsset:
    source_model: str
    source_voice_id: str
    source_preview_cache_key: str | None
    storage_path: Path
    source_url: str | None
    sha256: str
    duration_s: float
    content_type: str
    reference: dict[str, str]


Downloader = Callable[[str], bytes | tuple[bytes, str | None]]


class PreviewReferenceMaterializer:
    """Validate and persist existing previews without synthesizing new speech."""

    def __init__(
        self,
        *,
        output_root: str | Path,
        downloader: Downloader | None = None,
        technical_analyzer: SceneAudioTechnicalAnalyzer | None = None,
        max_audio_bytes: int = 10 * 1024 * 1024,
        max_duration_s: float = 30.0,
        download_timeout_s: float = 30.0,
    ) -> None:
        if max_audio_bytes <= 0:
            raise ValueError("max_audio_bytes must be positive")
        if max_duration_s <= 0:
            raise ValueError("max_duration_s must be positive")
        self.output_root = Path(output_root)
        self.downloader = downloader
        self.technical_analyzer = technical_analyzer or SceneAudioTechnicalAnalyzer(
            cache=SceneAudioAnalysisCache(self.output_root / ".analysis-cache")
        )
        self.max_audio_bytes = int(max_audio_bytes)
        self.max_duration_s = float(max_duration_s)
        self.download_timeout_s = float(download_timeout_s)

    def materialize(self, config: Mapping[str, Any]) -> PreviewReferenceAsset:
        source_model = normalize_audiobook_tts_model(
            str(config.get("tts_model") or ""),
            default="",
        )
        source_voice_id = str(config.get("voice_id") or "").strip()
        cache_key = self._resolve_cache_key(
            config,
            source_model=source_model,
            source_voice_id=source_voice_id,
        )
        audio_url, audio_data = self._preview_source(config)

        if not audio_url and not audio_data and cache_key:
            for extension in ("mp3", "wav"):
                audio_url = check_oss_preview_exists(cache_key, ext=extension)
                if audio_url:
                    break

        source_url = audio_url or None
        if audio_url:
            audio_bytes, content_type = self._download_audio(audio_url)
        elif audio_data is not None:
            audio_bytes, content_type = self._decode_audio_data(audio_data)
        else:
            raise PreviewReferenceMaterializationError(
                "preview_reference_unavailable",
                "no inline preview or shared preview cache entry exists",
            )

        if not audio_bytes:
            raise PreviewReferenceMaterializationError("empty_audio")
        if len(audio_bytes) > self.max_audio_bytes:
            raise PreviewReferenceMaterializationError(
                "audio_too_large",
                f"{len(audio_bytes)} bytes exceeds {self.max_audio_bytes}",
            )

        extension = self._detect_extension(
            audio_bytes,
            content_type=content_type,
            source_url=source_url,
        )
        content_type = self._normalize_content_type(content_type, extension)
        report = self._analyze_bytes(audio_bytes, extension)
        if not report.audio_decodable:
            raise PreviewReferenceMaterializationError(
                "audio_not_decodable",
                str(getattr(report, "error", "") or "preview decoding failed"),
            )
        duration_s = float(report.duration_s or 0.0)
        if duration_s <= 0:
            raise PreviewReferenceMaterializationError("empty_audio")
        if duration_s > self.max_duration_s:
            raise PreviewReferenceMaterializationError(
                "audio_too_long",
                f"{duration_s:.3f}s exceeds {self.max_duration_s:.3f}s",
            )
        if getattr(report, "clipping", False) is True:
            raise PreviewReferenceMaterializationError("audio_clipping_detected")
        if getattr(report, "silence", False) is True:
            raise PreviewReferenceMaterializationError("abnormal_silence_detected")

        sha256 = hashlib.sha256(audio_bytes).hexdigest()
        model_dir = self._safe_path_component(source_model or "unknown-model")
        storage_path = self.output_root / model_dir / f"{sha256}.{extension}"
        if not storage_path.exists() or storage_path.stat().st_size != len(audio_bytes):
            write_bytes_atomic(storage_path, audio_bytes)

        encoded_audio = base64.b64encode(audio_bytes).decode("ascii")
        return PreviewReferenceAsset(
            source_model=source_model,
            source_voice_id=source_voice_id,
            source_preview_cache_key=cache_key,
            storage_path=storage_path,
            source_url=source_url,
            sha256=sha256,
            duration_s=duration_s,
            content_type=content_type,
            reference={"audio_data": encoded_audio},
        )

    @staticmethod
    def _preview_source(config: Mapping[str, Any]) -> tuple[str, str | None]:
        preview_value = config.get("preview")
        preview = preview_value if isinstance(preview_value, Mapping) else {}
        audio_url = str(
            config.get("preview_audio_url")
            or preview.get("audio_url")
            or ""
        ).strip()
        if audio_url and not audio_url.startswith(("http://", "https://")):
            raise PreviewReferenceMaterializationError(
                "invalid_preview_url",
                "preview URL must use HTTP(S)",
            )
        audio_data_value = (
            config.get("preview_audio_data")
            if config.get("preview_audio_data") is not None
            else preview.get("audio_data")
        )
        if audio_data_value is None:
            audio_data_value = preview.get("blob")
        audio_data = None if audio_data_value is None else str(audio_data_value).strip()
        return audio_url, audio_data

    @staticmethod
    def _resolve_cache_key(
        config: Mapping[str, Any],
        *,
        source_model: str,
        source_voice_id: str,
    ) -> str | None:
        explicit = str(config.get("preview_cache_key") or "").strip()
        if explicit:
            return explicit
        if not source_model or not source_voice_id:
            return None
        try:
            return build_default_preview_cache_key(
                model=source_model,
                voice_id=source_voice_id,
            )
        except Exception as exc:
            raise PreviewReferenceMaterializationError(
                "preview_cache_identity_failed",
                str(exc),
            ) from exc

    def _download_audio(self, url: str) -> tuple[bytes, str | None]:
        try:
            result = self.downloader(url) if self.downloader else self._download_http(url)
        except PreviewReferenceMaterializationError:
            raise
        except Exception as exc:
            raise PreviewReferenceMaterializationError("preview_download_failed", str(exc)) from exc

        if isinstance(result, tuple):
            audio_bytes, content_type = result
        else:
            audio_bytes, content_type = result, None
        payload = bytes(audio_bytes or b"")
        if len(payload) > self.max_audio_bytes:
            raise PreviewReferenceMaterializationError(
                "audio_too_large",
                f"{len(payload)} bytes exceeds {self.max_audio_bytes}",
            )
        return payload, str(content_type or "").split(";", 1)[0].strip().lower() or None

    def _download_http(self, url: str) -> tuple[bytes, str | None]:
        chunks = []
        total_bytes = 0
        with httpx.stream(
            "GET",
            url,
            timeout=self.download_timeout_s,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.max_audio_bytes:
                raise PreviewReferenceMaterializationError(
                    "audio_too_large",
                    f"content-length {content_length} exceeds {self.max_audio_bytes}",
                )
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > self.max_audio_bytes:
                    raise PreviewReferenceMaterializationError(
                        "audio_too_large",
                        f"download exceeds {self.max_audio_bytes} bytes",
                    )
                chunks.append(chunk)
            content_type = response.headers.get("content-type")
        return b"".join(chunks), content_type

    @staticmethod
    def _decode_audio_data(value: str) -> tuple[bytes, str | None]:
        raw_value = str(value or "").strip()
        content_type = None
        match = _DATA_URL_RE.match(raw_value)
        if match:
            content_type = match.group("mime").split(";", 1)[0].strip().lower()
            encoded = match.group("data")
        else:
            encoded = raw_value
        encoded = re.sub(r"\s+", "", encoded)
        try:
            return base64.b64decode(encoded, validate=True), content_type
        except (binascii.Error, ValueError) as exc:
            raise PreviewReferenceMaterializationError("invalid_base64", str(exc)) from exc

    def _analyze_bytes(self, audio_bytes: bytes, extension: str):
        self.output_root.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=f".{extension}",
                dir=self.output_root,
                delete=False,
            ) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = Path(temp_file.name)
            return self.technical_analyzer.analyze(temp_path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _detect_extension(
        audio_bytes: bytes,
        *,
        content_type: str | None,
        source_url: str | None,
    ) -> str:
        if audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE":
            return "wav"
        if audio_bytes.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "mp3"
        if audio_bytes.startswith(b"OggS"):
            return "ogg"
        normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
        if normalized_content_type in _MIME_EXTENSIONS:
            return _MIME_EXTENSIONS[normalized_content_type]
        suffix = Path(urlparse(source_url or "").path).suffix.lower().lstrip(".")
        if suffix in {"mp3", "wav", "ogg", "opus"}:
            return suffix
        return "mp3"

    @staticmethod
    def _normalize_content_type(content_type: str | None, extension: str) -> str:
        normalized = str(content_type or "").split(";", 1)[0].strip().lower()
        return normalized or _CONTENT_TYPES.get(extension, "application/octet-stream")

    @staticmethod
    def _safe_path_component(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
        return normalized.strip(".-") or "unknown-model"


__all__ = [
    "PreviewReferenceAsset",
    "PreviewReferenceMaterializationError",
    "PreviewReferenceMaterializer",
]
