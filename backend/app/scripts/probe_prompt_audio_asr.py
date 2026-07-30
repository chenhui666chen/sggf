"""使用非用户测试音频探测时间戳 ASR 真实接口合同。

运行方式（在 backend 目录）：
    python -m app.scripts.probe_prompt_audio_asr --provider aliyun --audio-url https://...
    python -m app.scripts.probe_prompt_audio_asr --provider doubao --audio-url https://...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _bootstrap_environment() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    project_root = backend_root.parent
    for path in (backend_root, project_root):
        path_string = str(path)
        if path_string not in sys.path:
            sys.path.insert(0, path_string)

    from app.core.env_loader import load_project_env

    load_project_env(override=False)


_bootstrap_environment()

from app.services.audiobook.prompt_audio_asr_provider import (
    PromptAudioAsrProviderError,
    create_prompt_audio_asr_provider,
    sanitize_asr_audit_metadata,
)


def _validate_audio_url(audio_url: str) -> str:
    normalized = str(audio_url or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("audio_url must be a public HTTPS URL")
    return normalized


def probe_prompt_audio_asr(
    *,
    provider_name: str,
    audio_url: str,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    normalized_audio_url = _validate_audio_url(audio_url)
    provider = create_prompt_audio_asr_provider(provider_name)
    if provider is None:
        raise RuntimeError(f"ASR provider is not configured: {provider_name}")
    if hasattr(provider, "timeout_seconds"):
        provider.timeout_seconds = float(timeout_seconds)

    started = time.perf_counter()
    result = provider.transcribe(
        "remote-contract-probe",
        audio_url=normalized_audio_url,
    )
    return {
        "ok": True,
        "provider": str(result.provider or ""),
        "model": str(result.model or ""),
        "transcript": str(result.transcript or ""),
        "subtitle_payload": result.subtitle_payload,
        "metadata": sanitize_asr_audit_metadata(result.metadata),
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


def _write_probe_payload(output_path: str, payload: dict[str, Any]) -> None:
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json.tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        os.replace(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe a timestamp ASR provider")
    parser.add_argument("--provider", choices=("aliyun", "doubao"), required=True)
    parser.add_argument("--audio-url", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    try:
        payload = probe_prompt_audio_asr(
            provider_name=args.provider,
            audio_url=args.audio_url,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "provider": args.provider,
            "error_type": exc.__class__.__name__,
            "error_code": str(getattr(exc, "code", "") or ""),
            "error": str(exc),
            "timeout_s": float(args.timeout),
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        if args.output:
            _write_probe_payload(args.output, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 1

    if args.output:
        _write_probe_payload(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
