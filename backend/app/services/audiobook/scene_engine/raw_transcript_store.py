"""RawTranscriptStore：原始转写静态加密存储层（指导文档 §12.2）。

按 tenant/project 隔离 + at-rest 加密 + 持久化 URI 引用 + 生命周期级联清理。
每个转写文件以 Fernet 加密 JSON 存储，路径按 project/chapter 组织以实现目录级清理。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from app.services.audiobook.hashing import content_digest


logger = logging.getLogger(__name__)


ENCRYPTION_KEY_MIN_LENGTH = 16
"""最小加密密钥长度（字节）。短于此长度拒绝初始化（失败关闭）。"""

ARTIFACT_HASH_PREFIX_LENGTH = 16
"""artifact_hash_prefix 截取长度（字节 hex 字符数 = 32）。"""

_URI_PATTERN = re.compile(
    r"^raw-transcript://store/([^/]+)/([^/]+)/([a-f0-9]+)$"
)


class EncryptionKeyError(ValueError):
    """加密密钥不满足安全要求。"""


class RawTranscriptStore:
    """原始转写持久化存储层。

    文件路径：``{storage_dir}/{project_id}/{chapter_id}/{hash_prefix}.enc``
    URI 格式：``raw-transcript://store/{project_id}/{chapter_id}/{hash_prefix}``

    一个加密文件包含 ``raw_transcript``、``raw_timeline``、
    ``filtered_provider_metadata`` 与 ``stored_at`` 字段的 JSON payload。

    同一片段的 transcript 和 timeline 共享同一文件，store 返回两个相同的 URI
    （兼容 RawTranscriptArtifact 的 ``raw_transcript_artifact_uri`` /
    ``raw_timeline_artifact_uri`` 字段）。
    """

    ENCRYPTED_EXTENSION = ".enc"

    def __init__(self, storage_dir: str, encryption_key: str) -> None:
        if not encryption_key:
            raise EncryptionKeyError("加密密钥不能为空（失败关闭，禁止明文落盘）")
        if len(encryption_key) < ENCRYPTION_KEY_MIN_LENGTH:
            raise EncryptionKeyError(
                f"加密密钥长度 {len(encryption_key)} < {ENCRYPTION_KEY_MIN_LENGTH}"
            )
        derived = hashlib.sha256(encryption_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def store(
        self,
        project_id: str,
        chapter_id: str,
        raw_transcript: str,
        raw_timeline: str,
        filtered_provider_metadata: Mapping[str, Any],
    ) -> Tuple[str, str]:
        """持久化原始转写内容，返回 (transcript_uri, timeline_uri)。

        同一内容的多次 store 返回相同 URI（幂等）。
        """
        hash_prefix = self._compute_hash_prefix(raw_transcript, raw_timeline)
        path = self._artifact_path(project_id, chapter_id, hash_prefix)
        if path.exists():
            uri = self._build_uri(project_id, chapter_id, hash_prefix)
            return uri, uri

        payload = {
            "raw_transcript": raw_transcript,
            "raw_timeline": raw_timeline,
            "filtered_provider_metadata": dict(filtered_provider_metadata),
            "stored_at": os.path.getmtime,
            "_hash_prefix": hash_prefix,
        }
        # Remove the helper placeholder before serialization
        payload.pop("_hash_prefix", None)
        payload["stored_at"] = __import__("time").time()

        encrypted = self._encrypt_payload(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, encrypted)

        uri = self._build_uri(project_id, chapter_id, hash_prefix)
        return uri, uri

    def resolve(
        self, uri: str
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """解析 URI → (raw_transcript, raw_timeline, filtered_provider_metadata)。"""
        parsed = self._parse_uri(uri)
        if parsed is None:
            return None
        project_id, chapter_id, hash_prefix = parsed
        path = self._artifact_path(project_id, chapter_id, hash_prefix)
        if not path.exists():
            return None
        try:
            payload = self._decrypt_payload(path.read_bytes())
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            logger.warning("RawTranscriptStore: 读取失败 %s: %s", uri, exc)
            return None
        return (
            payload.get("raw_transcript", ""),
            payload.get("raw_timeline", ""),
            payload.get("filtered_provider_metadata", {}),
        )

    def delete_project(self, project_id: str) -> int:
        """删除项目下所有转写文件，返回删除的文件数。"""
        project_dir = self._storage_dir / _sanitize_segment(project_id)
        if not project_dir.is_dir():
            return 0
        count = sum(1 for _ in project_dir.rglob(f"*{self.ENCRYPTED_EXTENSION}"))
        try:
            shutil.rmtree(project_dir)
        except OSError as exc:
            logger.error("RawTranscriptStore: delete_project %s failed: %s", project_id, exc)
            return 0
        if count:
            logger.info("RawTranscriptStore: deleted project %s (%d files)", project_id, count)
        return count

    def delete_chapter(self, project_id: str, chapter_id: str) -> int:
        """删除章节下所有转写文件，返回删除的文件数。"""
        chapter_dir = (
            self._storage_dir / _sanitize_segment(project_id) / _sanitize_segment(chapter_id)
        )
        if not chapter_dir.is_dir():
            return 0
        count = sum(1 for _ in chapter_dir.glob(f"*{self.ENCRYPTED_EXTENSION}"))
        try:
            shutil.rmtree(chapter_dir)
        except OSError as exc:
            logger.error(
                "RawTranscriptStore: delete_chapter %s/%s failed: %s",
                project_id, chapter_id, exc,
            )
            return 0
        if count:
            logger.info(
                "RawTranscriptStore: deleted chapter %s/%s (%d files)",
                project_id, chapter_id, count,
            )
        return count

    def list_project(self, project_id: str) -> List[str]:
        """返回项目下所有转写文件 URI 列表。"""
        project_dir = self._storage_dir / _sanitize_segment(project_id)
        if not project_dir.is_dir():
            return []
        uris: List[str] = []
        for enc_file in sorted(project_dir.rglob(f"*{self.ENCRYPTED_EXTENSION}")):
            # enc_file is {storage_dir}/{project}/{chapter}/{hash}.enc
            # extract chapter_id and hash from relative path
            try:
                rel = enc_file.relative_to(project_dir)
                chapter_id = rel.parts[0]
                hash_prefix = enc_file.stem  # filename without .enc
            except (ValueError, IndexError):
                continue
            if not _is_valid_hex(hash_prefix):
                continue
            uris.append(self._build_uri(project_id, chapter_id, hash_prefix))
        return uris

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash_prefix(raw_transcript: str, raw_timeline: str) -> str:
        combined = (raw_transcript + "\x00" + raw_timeline).encode("utf-8")
        return content_digest(combined)[:ARTIFACT_HASH_PREFIX_LENGTH]

    def _artifact_path(
        self, project_id: str, chapter_id: str, hash_prefix: str
    ) -> Path:
        return (
            self._storage_dir
            / _sanitize_segment(project_id)
            / _sanitize_segment(chapter_id)
            / f"{hash_prefix}{self.ENCRYPTED_EXTENSION}"
        )

    def _build_uri(
        self, project_id: str, chapter_id: str, hash_prefix: str
    ) -> str:
        return (
            f"raw-transcript://store/"
            f"{_sanitize_segment(project_id)}/"
            f"{_sanitize_segment(chapter_id)}/"
            f"{hash_prefix}"
        )

    def _parse_uri(
        self, uri: str
    ) -> Optional[Tuple[str, str, str]]:
        if not uri:
            return None
        m = _URI_PATTERN.match(uri)
        if not m:
            return None
        return m.group(1), m.group(2), m.group(3)

    def _encrypt_payload(self, payload: Dict[str, Any]) -> bytes:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw)

    def _decrypt_payload(self, data: bytes) -> Dict[str, Any]:
        try:
            decrypted = self._fernet.decrypt(data)
        except InvalidToken as exc:
            raise ValueError("解密失败：密钥不匹配或数据损坏") from exc
        return json.loads(decrypted.decode("utf-8"))


# ------------------------------------------------------------------
# module-level helpers
# ------------------------------------------------------------------


def _sanitize_segment(segment: str) -> str:
    """将 project_id / chapter_id 转义为安全的目录名。"""
    return segment.replace("/", "_").replace("\\", "_").replace(":", "_").replace(".", "_")


def _is_valid_hex(s: str) -> bool:
    return len(s) == ARTIFACT_HASH_PREFIX_LENGTH and all(c in "0123456789abcdef" for c in s.lower())


def _atomic_write(path: Path, data: bytes) -> None:
    """先写 tmp 再 rename，避免部分写入。"""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        shutil.move(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


__all__ = [
    "ENCRYPTION_KEY_MIN_LENGTH",
    "EncryptionKeyError",
    "RawTranscriptStore",
]