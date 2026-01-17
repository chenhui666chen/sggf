from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Sequence


def _quote_arg(value: str) -> str:
    s = str(value or "")
    if not s:
        return '""'
    if any(ch.isspace() for ch in s) or any(ch in s for ch in ['"', "'"]):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _format_cmd(cmd: Sequence[str]) -> str:
    return " ".join(_quote_arg(str(arg)) for arg in cmd)


def _truncate(text: str, *, limit: int = 200_000) -> str:
    value = str(text or "")
    if limit <= 0 or len(value) <= int(limit):
        return value
    omitted = len(value) - int(limit)
    return value[: int(limit)] + f"\n...[truncated {omitted} chars]"


def _next_log_path(log_dir: Path, *, prefix: str) -> Path:
    safe_prefix = "".join(ch for ch in str(prefix or "ffmpeg").strip() if ch.isalnum() or ch in {"_", "-", "."})
    if not safe_prefix:
        safe_prefix = "ffmpeg"
    stem = f"{safe_prefix}.{os.getpid()}.{int(time.time() * 1000)}"
    path = log_dir / f"{stem}.log"
    # 极端并发下避免同名冲突
    for i in range(20):
        if not path.exists():
            return path
        path = log_dir / f"{stem}.{i}.log"
    return log_dir / f"{stem}.{int(time.time() * 1000)}.log"


def run_ffmpeg(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    log_dir: Optional[Path] = None,
    log_prefix: str = "ffmpeg",
) -> None:
    """
    运行 ffmpeg 命令；失败时将 stdout/stderr 落盘到 log_dir 并抛出 RuntimeError（便于定位字幕/合成问题）。
    """
    try:
        subprocess.run(
            list(cmd),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
        cmd_text = _format_cmd(list(cmd))

        log_path: Optional[Path] = None
        if log_dir is not None:
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = _next_log_path(log_dir, prefix=log_prefix)
                content = "\n".join(
                    [
                        "# ffmpeg failed",
                        f"returncode: {getattr(exc, 'returncode', None)}",
                        f"cmd: {cmd_text}",
                        "",
                        "## stderr",
                        _truncate(stderr),
                        "",
                        "## stdout",
                        _truncate(stdout),
                        "",
                    ]
                )
                log_path.write_text(content, encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                log_path = None

        msg = f"ffmpeg 执行失败（code={getattr(exc, 'returncode', None)}）"
        if log_path is not None:
            msg += f"，详见日志：{log_path.as_posix()}"
        raise RuntimeError(msg) from exc
