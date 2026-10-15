# -*- coding: utf-8 -*-
"""素材托管服务：本地素材 -> 公共读 OSS 公网 URL。

- object key 全服务端生成，内容寻址（sha256 前 12 位），同内容自动去重；
- key 落在已验证公共读的 shared/audio_library/ 前缀策略范围内（2026-10-12 探针实测），
  新顶层前缀 router_gateway/ 公共读 403，禁止把默认前缀改出去；
- 云端副本仅用于供应商拉取，任务终态由编排层调 release() 清理（本地原件不动）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .oss_client import OssClient


DEFAULT_PREFIX = "shared/audio_library/router_refs"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}
_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA_PREFIX_LEN = 12


class AssetError(Exception):
    pass


@dataclass(frozen=True)
class StagedAsset:
    public_url: str
    object_key: str
    sha256: str
    size: int
    content_type: str


def validate_job_id(job_id: str) -> str:
    normalized = str(job_id or "").strip()
    if not _JOB_ID_PATTERN.fullmatch(normalized):
        raise AssetError("job_id 只能包含字母数字、下划线、连字符，长度 1-64")
    return normalized


def build_object_key(*, prefix: str, job_id: str, sha256: str,
                     extension: str, now: Optional[datetime] = None) -> str:
    safe_job = validate_job_id(job_id)
    moment = now or datetime.now(timezone.utc)
    day = moment.strftime("%Y-%m-%d")
    return (f"{prefix.strip().strip('/')}/{day}/{safe_job}/"
            f"{sha256[:_SHA_PREFIX_LEN]}{extension.lower()}")


class AssetStore:
    def __init__(self, client: OssClient, *, prefix: str = DEFAULT_PREFIX,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 clock: Optional[Callable[[], datetime]] = None):
        self._client = client
        self._prefix = prefix.strip().strip("/")
        self._max_bytes = int(max_bytes)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def stage_path(self, local_path: Path | str, *, job_id: str) -> StagedAsset:
        path = Path(local_path)
        safe_job = validate_job_id(job_id)

        extension = path.suffix.lower()
        content_type = _CONTENT_TYPES.get(extension)
        if content_type is None:
            raise AssetError(f"不支持的素材类型: {extension or '(无扩展名)'}")
        if not path.is_file():
            raise AssetError(f"素材文件不存在: {path}")

        content = path.read_bytes()
        size = len(content)
        if size > self._max_bytes:
            raise AssetError(f"素材大小 {size} 字节超过上限 {self._max_bytes} 字节")

        digest = hashlib.sha256(content).hexdigest()
        object_key = build_object_key(
            prefix=self._prefix, job_id=safe_job, sha256=digest,
            extension=extension, now=self._clock())

        remote = self._client.head(object_key)
        if not remote.get("exists") or remote.get("content_length") != size:
            # 不存在或云端字节数不一致（碰撞/脏对象）时上传（同名覆盖）
            public_url = self._client.put_bytes(object_key, content, content_type)
        else:
            public_url = self._client.public_url(object_key)

        return StagedAsset(
            public_url=public_url,
            object_key=object_key,
            sha256=digest,
            size=size,
            content_type=content_type,
        )

    def release(self, object_key: str) -> None:
        self._client.delete(object_key)
