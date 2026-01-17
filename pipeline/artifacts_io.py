from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import requests


def _retry_sleep_s(attempt: int, *, base_s: float = 1.2, max_s: float = 8.0) -> float:
    value = float(base_s) * (2.0 ** max(0, int(attempt)))
    return float(min(max_s, max(0.0, value)))


def download_url_to_path(
    url: str,
    out_path: Path,
    *,
    timeout_s: float = 300.0,
    max_retries: int = 2,
    chunk_size: int = 256 * 1024,
) -> None:
    """
    下载 URL 到文件（stream + 原子落盘 + 简单重试）。

    约定：
    - 对 429 与 5xx 做重试；对其它 4xx 直接抛错（避免无意义重试）。
    - 写入使用临时文件，再 os.replace()，避免中断留下半文件。
    """
    resolved = str(url or "").strip()
    if not resolved:
        raise ValueError("empty url")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    attempts = max(0, int(max_retries)) + 1
    last_exc: Optional[Exception] = None

    for attempt in range(attempts):
        tmp_path = out_path.with_suffix(
            f"{out_path.suffix}.tmp.{os.getpid()}.{int(time.time() * 1000)}.{attempt}"
        )
        try:
            resp = requests.get(resolved, stream=True, timeout=float(timeout_s))
            try:
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=int(chunk_size)):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp_path, out_path)
                return
            finally:
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass
        except requests.exceptions.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and int(status) < 500 and int(status) != 429:
                raise
            last_exc = exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:  # noqa: BLE001
                pass

        if attempt < attempts - 1:
            time.sleep(_retry_sleep_s(attempt))

    raise RuntimeError("download failed") from last_exc

