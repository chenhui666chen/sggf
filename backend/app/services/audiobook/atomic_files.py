from __future__ import annotations

import os
import logging
import uuid
from pathlib import Path
from typing import Union


PathLike = Union[str, os.PathLike[str]]
logger = logging.getLogger(__name__)


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    """先写入同目录临时文件，再原子替换目标文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = bytes(data or b"")
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.part")

    try:
        temp_path.write_bytes(payload)
        if temp_path.stat().st_size != len(payload):
            raise IOError(f"atomic write size mismatch for {target}")
        os.replace(str(temp_path), str(target))
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception as exc:
            logger.debug(
                "清理原子写入临时文件失败，已忽略: temp_path=%s target=%s error=%s",
                temp_path,
                target,
                exc,
            )

    return target


__all__ = ["write_bytes_atomic"]
