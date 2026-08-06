from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import mimetypes
import os
import re
import shutil
from email.utils import formatdate
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple
from urllib.parse import quote, urlparse

import httpx

from app.services.audiobook.cosyvoice_clone_client import (
    COSYVOICE_V35_PLUS_MODEL_ID,
    _build_public_oss_url,
    _get_dashscope_upload_policy,
)


_DRIVER_LOCAL_FS = "local_fs"
_DRIVER_DASHSCOPE_OSS = "dashscope_oss"
_SUPPORTED_DRIVERS = {_DRIVER_LOCAL_FS, _DRIVER_DASHSCOPE_OSS}
_DEFAULT_LOCAL_ROOT_REL = Path("backend/data/tmp/audiobook_runs")
_DEFAULT_OSS_PREFIX = "tmp/audiobook_runs"
_DEFAULT_OSS_POLICY_MODEL = COSYVOICE_V35_PLUS_MODEL_ID
_SEGMENT_FILE_STEM = "segment"

_CURRENT_FILE = Path(__file__).resolve()
_BACKEND_ROOT = _CURRENT_FILE.parents[3]
_REPO_ROOT = _CURRENT_FILE.parents[4]
_LOCAL_TEMP_ROOT_ABS = (_REPO_ROOT / _DEFAULT_LOCAL_ROOT_REL).resolve()
logger = logging.getLogger(__name__)


class TempSegmentStoreError(RuntimeError):
    pass


class TempSegmentStorageBackend(Protocol):
    def build_prefix(self, *, run_id: str, chapter_id: int) -> str:
        ...

    def save_audio_map(
        self,
        *,
        run_id: str,
        chapter_id: int,
        audio_map: Dict[int, bytes],
        extension: str,
    ) -> Dict[str, Any]:
        ...

    def load_bytes(self, asset_ref: str) -> Optional[bytes]:
        ...

    def asset_exists(self, asset_ref: str) -> bool:
        ...

    def delete_prefix(
        self,
        temp_asset_prefix: Optional[str],
        checkpoint_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        ...


def normalize_audio_extension(format_value: Optional[str]) -> str:
    raw = str(format_value or "").strip().lower()
    if not raw:
        return "mp3"
    if raw.startswith("audio/"):
        raw = raw.split("/", 1)[1]
    raw = raw.lstrip(".")
    aliases = {
        "mpeg": "mp3",
        "mpga": "mp3",
        "x-m4a": "m4a",
        "mp4": "m4a",
        "x-wav": "wav",
    }
    normalized = aliases.get(raw, raw)
    if not re.fullmatch(r"[a-z0-9]+", normalized):
        return "mp3"
    return normalized


def _normalize_segment_index(value: Any) -> Optional[int]:
    try:
        index = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if index < 0:
        return None
    return index


def _normalize_audio_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return bytes(value)


def _iter_normalized_audio_items(audio_map: Dict[Any, Any]) -> List[Tuple[int, bytes]]:
    normalized_items: Dict[int, bytes] = {}
    for raw_index, raw_audio in dict(audio_map or {}).items():
        index = _normalize_segment_index(raw_index)
        if index is None:
            continue
        audio_bytes = _normalize_audio_bytes(raw_audio)
        if not audio_bytes:
            continue
        normalized_items[index] = audio_bytes
    return sorted(normalized_items.items(), key=lambda item: item[0])


def _sanitize_run_id(run_id: Any) -> str:
    raw = str(run_id or "").strip()
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return sanitized or "run"


def _normalize_chapter_id(chapter_id: Any) -> int:
    try:
        return max(int(chapter_id), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _build_local_prefix_path(*, run_id: str, chapter_id: int) -> Path:
    return _DEFAULT_LOCAL_ROOT_REL / _sanitize_run_id(run_id) / f"chapter_{_normalize_chapter_id(chapter_id):05d}"


def _build_oss_prefix_key(*, run_id: str, chapter_id: int) -> str:
    base_prefix = str(os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_PREFIX") or _DEFAULT_OSS_PREFIX).strip().strip("/")
    if not base_prefix:
        base_prefix = _DEFAULT_OSS_PREFIX
    return f"{base_prefix}/{_sanitize_run_id(run_id)}/chapter_{_normalize_chapter_id(chapter_id):05d}"


def _build_segment_filename(index: int, audio_bytes: bytes, extension: str) -> str:
    digest = hashlib.sha1(audio_bytes).hexdigest()[:12]
    return f"{_SEGMENT_FILE_STEM}_{index:05d}_{digest}.{extension}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _iter_local_candidate_paths(path_value: str) -> Iterable[Path]:
    raw = str(path_value or "").strip()
    if not raw:
        return []

    path = Path(raw)
    if path.is_absolute():
        return [path]

    candidates: List[Path] = []
    seen: set[str] = set()
    for relative_candidate in (
        path,
        Path("backend") / path,
        Path("data") / path,
        Path("backend/data") / path,
    ):
        candidate = (_REPO_ROOT / relative_candidate).resolve(strict=False)
        key = candidate.as_posix()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _resolve_safe_local_path(path_value: str) -> Optional[Path]:
    for candidate in _iter_local_candidate_paths(path_value):
        if _is_relative_to(candidate, _LOCAL_TEMP_ROOT_ABS):
            return candidate
    return None


def _to_relative_repo_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(_REPO_ROOT.resolve(strict=False)).as_posix()
    except (OSError, RuntimeError, ValueError):
        return path.as_posix()


def _build_segment_payload(
    *,
    index: int,
    asset_ref: str,
    extension: str,
    audio_bytes: bytes,
) -> Dict[str, Any]:
    return {
        "index": index,
        "status": "cached",
        "output_format": extension,
        "file_size": len(audio_bytes),
        "content_sha1": hashlib.sha1(audio_bytes).hexdigest(),
        "temp_object_key": asset_ref,
    }


def _resolve_active_driver_name() -> str:
    raw = str(os.getenv("AUDIOBOOK_TEMP_SEGMENT_STORAGE_DRIVER") or "").strip().lower()
    if raw in _SUPPORTED_DRIVERS:
        return raw
    return _DRIVER_LOCAL_FS


def _guess_content_type(extension: str) -> str:
    guessed, _ = mimetypes.guess_type(f"temp.{extension}")
    return guessed or "application/octet-stream"


def _extract_oss_key(asset_ref: str) -> str:
    raw = str(asset_ref or "").strip()
    if raw.startswith("oss://"):
        return raw[len("oss://") :].lstrip("/")
    return ""


def _normalize_public_host(host_value: str) -> str:
    host = str(host_value or "").strip()
    if not host:
        return ""
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"
    return host.rstrip("/")


def _resolve_oss_public_url(asset_ref: str) -> Optional[str]:
    raw = str(asset_ref or "").strip()
    if not raw:
        return None
    # 安全约束：拒绝客户端可控的任意 HTTP(S) URL，防止跨资产读取与 SSRF；
    # 仅允许 oss:// 受控 key 由服务端拼接公共访问地址。
    if raw.startswith("http://") or raw.startswith("https://"):
        logger.warning("拒绝加载任意 HTTP 资产引用: asset_ref=%s", raw[:160])
        return None

    key = _extract_oss_key(raw)
    if not key:
        return None

    configured_host = _normalize_public_host(os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_PUBLIC_HOST") or "")
    if configured_host:
        return f"{configured_host}/{key}"

    policy_model = str(
        os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_POLICY_MODEL") or _DEFAULT_OSS_POLICY_MODEL
    ).strip() or _DEFAULT_OSS_POLICY_MODEL
    policy = _get_dashscope_upload_policy(policy_model)
    public_url = _build_public_oss_url(str(policy.get("upload_host") or ""), key)
    return public_url or None


def _extract_host_from_url(host_value: str) -> str:
    raw = str(host_value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return str(parsed.netloc or parsed.path or "").strip().strip("/")


def _resolve_oss_delete_host() -> str:
    explicit_host = _extract_host_from_url(os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_HOST") or "")
    if explicit_host:
        return explicit_host

    policy_model = str(
        os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_POLICY_MODEL") or _DEFAULT_OSS_POLICY_MODEL
    ).strip() or _DEFAULT_OSS_POLICY_MODEL
    policy = _get_dashscope_upload_policy(policy_model)
    return _extract_host_from_url(str(policy.get("upload_host") or ""))


def _resolve_oss_delete_bucket() -> str:
    explicit_bucket = str(os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_BUCKET") or "").strip()
    if explicit_bucket:
        return explicit_bucket

    host = _resolve_oss_delete_host()
    if not host:
        return ""
    return host.split(".", 1)[0].strip()


def _resolve_oss_delete_credentials() -> Optional[Dict[str, str]]:
    access_key_id = str(
        os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_ACCESS_KEY_ID")
        or os.getenv("ALIYUN_ACCESS_KEY_ID")
        or os.getenv("OSS_ACCESS_KEY_ID")
        or ""
    ).strip()
    access_key_secret = str(
        os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_ACCESS_KEY_SECRET")
        or os.getenv("ALIYUN_ACCESS_KEY_SECRET")
        or os.getenv("OSS_ACCESS_KEY_SECRET")
        or ""
    ).strip()
    security_token = str(
        os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_SECURITY_TOKEN")
        or os.getenv("ALIYUN_SECURITY_TOKEN")
        or os.getenv("OSS_SECURITY_TOKEN")
        or ""
    ).strip()

    if not access_key_id or not access_key_secret:
        return None

    return {
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "security_token": security_token,
    }


def _build_oss_delete_headers(*, object_key: str) -> Optional[Tuple[str, Dict[str, str]]]:
    credentials = _resolve_oss_delete_credentials()
    if not credentials:
        return None

    try:
        host = _resolve_oss_delete_host()
        bucket = _resolve_oss_delete_bucket()
    except Exception as exc:
        logger.debug("构造临时片段 OSS 删除请求头失败，跳过远端清理: object_key=%s error=%s", object_key, exc)
        return None
    if not host or not bucket:
        return None

    date_value = formatdate(usegmt=True)
    canonicalized_headers = ""
    headers = {
        "Date": date_value,
        "Host": host,
    }
    security_token = credentials.get("security_token") or ""
    if security_token:
        headers["x-oss-security-token"] = security_token
        canonicalized_headers = f"x-oss-security-token:{security_token}\n"

    canonicalized_resource = f"/{bucket}/{object_key.lstrip('/')}"
    string_to_sign = "\n".join(
        [
            "DELETE",
            "",
            "",
            date_value,
            f"{canonicalized_headers}{canonicalized_resource}",
        ]
    )
    signature = base64.b64encode(
        hmac.new(
            credentials["access_key_secret"].encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
    headers["Authorization"] = f"OSS {credentials['access_key_id']}:{signature}"
    return host, headers


def _iter_matching_oss_asset_refs(
    temp_asset_prefix: Optional[str],
    checkpoint_json: Optional[Dict[str, Any]],
) -> List[str]:
    prefix = str(temp_asset_prefix or "").strip()
    normalized_prefix = f"{prefix.rstrip('/')}/" if prefix else ""
    matched_refs: List[str] = []
    seen_refs: set[str] = set()

    for asset_ref in extract_cached_segment_paths(checkpoint_json).values():
        raw = str(asset_ref or "").strip()
        if not raw.startswith("oss://"):
            continue
        if normalized_prefix and not raw.startswith(normalized_prefix):
            continue
        if raw in seen_refs:
            continue
        seen_refs.add(raw)
        matched_refs.append(raw)

    return matched_refs


class LocalFSTempSegmentStorageBackend:
    def build_prefix(self, *, run_id: str, chapter_id: int) -> str:
        return _build_local_prefix_path(run_id=run_id, chapter_id=chapter_id).as_posix()

    def save_audio_map(
        self,
        *,
        run_id: str,
        chapter_id: int,
        audio_map: Dict[int, bytes],
        extension: str,
    ) -> Dict[str, Any]:
        prefix_rel = _build_local_prefix_path(run_id=run_id, chapter_id=chapter_id)
        prefix_abs = (_REPO_ROOT / prefix_rel).resolve(strict=False)
        prefix_abs.mkdir(parents=True, exist_ok=True)

        cached_audio_paths: Dict[int, str] = {}
        segments: Dict[str, Dict[str, Any]] = {}

        for index, audio_bytes in _iter_normalized_audio_items(audio_map):
            filename = _build_segment_filename(index, audio_bytes, extension)
            file_path = prefix_abs / filename
            # 跨扩展名清理同一片段的旧版本：切换输出格式后旧格式文件也应及时释放
            pattern = f"{_SEGMENT_FILE_STEM}_{index:05d}_*.*"
            for stale_path in prefix_abs.glob(pattern):
                if stale_path.name == filename:
                    continue
                if stale_path.is_file():
                    stale_path.unlink(missing_ok=True)

            file_path.write_bytes(audio_bytes)
            asset_ref = _to_relative_repo_path(file_path)
            cached_audio_paths[index] = asset_ref
            segments[str(index)] = _build_segment_payload(
                index=index,
                asset_ref=asset_ref,
                extension=extension,
                audio_bytes=audio_bytes,
            )

        return {
            "storage_driver": _DRIVER_LOCAL_FS,
            "temp_asset_prefix": prefix_rel.as_posix(),
            "output_format": extension,
            "segment_count": len(cached_audio_paths),
            "cached_audio_paths": cached_audio_paths,
            "segments": segments,
        }

    def load_bytes(self, asset_ref: str) -> Optional[bytes]:
        path = _resolve_safe_local_path(asset_ref)
        if path is None or not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.debug("读取临时片段音频失败: asset_ref=%s path=%s error=%s", asset_ref, path, exc)
            return None

    def asset_exists(self, asset_ref: str) -> bool:
        path = _resolve_safe_local_path(asset_ref)
        if path is None:
            return False
        try:
            return path.exists()
        except OSError as exc:
            logger.debug("检查临时片段资源失败: asset_ref=%s path=%s error=%s", asset_ref, path, exc)
            return False

    def delete_prefix(
        self,
        temp_asset_prefix: Optional[str],
        checkpoint_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        prefix_path = _resolve_safe_local_path(str(temp_asset_prefix or "").strip()) if temp_asset_prefix else None
        if prefix_path is not None and prefix_path.exists():
            if prefix_path.is_dir():
                removed_files = sum(1 for entry in prefix_path.rglob("*") if entry.is_file())
                shutil.rmtree(prefix_path, ignore_errors=True)
                return removed_files
            if prefix_path.is_file():
                prefix_path.unlink(missing_ok=True)
                self._prune_empty_ancestors(prefix_path.parent)
                return 1

        removed_files = 0
        for asset_ref in dict(extract_cached_segment_paths(checkpoint_json)).values():
            asset_path = _resolve_safe_local_path(asset_ref)
            if asset_path is None or not asset_path.is_file():
                continue
            asset_path.unlink(missing_ok=True)
            self._prune_empty_ancestors(asset_path.parent)
            removed_files += 1
        return removed_files

    def _prune_empty_ancestors(self, start_path: Path) -> None:
        current = start_path.resolve(strict=False)
        root = _LOCAL_TEMP_ROOT_ABS.resolve(strict=False)
        while _is_relative_to(current, root) and current != root:
            try:
                next(current.iterdir())
                break
            except StopIteration:
                current.rmdir()
                current = current.parent
            except OSError as exc:
                logger.debug("清理临时片段空目录失败，停止向上剪枝: path=%s error=%s", current, exc)
                break


class DashScopeOssTempSegmentStorageBackend:
    def build_prefix(self, *, run_id: str, chapter_id: int) -> str:
        return f"oss://{_build_oss_prefix_key(run_id=run_id, chapter_id=chapter_id)}"

    def save_audio_map(
        self,
        *,
        run_id: str,
        chapter_id: int,
        audio_map: Dict[int, bytes],
        extension: str,
    ) -> Dict[str, Any]:
        prefix_key = _build_oss_prefix_key(run_id=run_id, chapter_id=chapter_id)
        prefix_ref = f"oss://{prefix_key}"
        cached_audio_paths: Dict[int, str] = {}
        segments: Dict[str, Dict[str, Any]] = {}

        for index, audio_bytes in _iter_normalized_audio_items(audio_map):
            filename = _build_segment_filename(index, audio_bytes, extension)
            object_key = f"{prefix_key}/{filename}"
            asset_ref = f"oss://{object_key}"
            if not self.asset_exists(asset_ref):
                self._upload_audio(object_key=object_key, filename=filename, audio_bytes=audio_bytes, extension=extension)
            cached_audio_paths[index] = asset_ref
            segments[str(index)] = _build_segment_payload(
                index=index,
                asset_ref=asset_ref,
                extension=extension,
                audio_bytes=audio_bytes,
            )

        return {
            "storage_driver": _DRIVER_DASHSCOPE_OSS,
            "temp_asset_prefix": prefix_ref,
            "output_format": extension,
            "segment_count": len(cached_audio_paths),
            "cached_audio_paths": cached_audio_paths,
            "segments": segments,
        }

    def load_bytes(self, asset_ref: str) -> Optional[bytes]:
        public_url = _resolve_oss_public_url(asset_ref)
        if not public_url:
            return None
        try:
            response = httpx.get(public_url, timeout=30.0)
        except httpx.RequestError:
            return None
        if response.status_code != 200:
            return None
        return bytes(response.content or b"")

    def asset_exists(self, asset_ref: str) -> bool:
        public_url = _resolve_oss_public_url(asset_ref)
        if not public_url:
            return False
        try:
            response = httpx.head(public_url, timeout=15.0)
        except httpx.RequestError:
            return False
        if 200 <= response.status_code < 400:
            return True
        if response.status_code == 405:
            try:
                probe_response = httpx.get(
                    public_url,
                    headers={"Range": "bytes=0-0"},
                    timeout=15.0,
                )
            except httpx.RequestError:
                return False
            return 200 <= probe_response.status_code < 400
        return False

    def delete_prefix(
        self,
        temp_asset_prefix: Optional[str],
        checkpoint_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        removed_files = 0
        for asset_ref in _iter_matching_oss_asset_refs(temp_asset_prefix, checkpoint_json):
            object_key = _extract_oss_key(asset_ref)
            if not object_key:
                continue

            delete_request = _build_oss_delete_headers(object_key=object_key)
            if not delete_request:
                continue

            host, headers = delete_request
            delete_url = f"https://{host}/{quote(object_key, safe='/')}"
            try:
                response = httpx.delete(
                    delete_url,
                    headers=headers,
                    timeout=20.0,
                )
            except httpx.RequestError:
                continue

            if response.status_code in {200, 204}:
                removed_files += 1
        return removed_files

    def _upload_audio(
        self,
        *,
        object_key: str,
        filename: str,
        audio_bytes: bytes,
        extension: str,
    ) -> None:
        policy_model = str(
            os.getenv("AUDIOBOOK_TEMP_SEGMENT_OSS_POLICY_MODEL") or _DEFAULT_OSS_POLICY_MODEL
        ).strip() or _DEFAULT_OSS_POLICY_MODEL
        policy = _get_dashscope_upload_policy(policy_model)
        required_fields = (
            "upload_host",
            "oss_access_key_id",
            "signature",
            "policy",
            "x_oss_object_acl",
            "x_oss_forbid_overwrite",
        )
        missing_fields = [field for field in required_fields if policy.get(field) in (None, "")]
        if missing_fields:
            raise TempSegmentStoreError(f"DashScope OSS 上传凭证缺少字段: {', '.join(missing_fields)}")

        form_data = {
            "OSSAccessKeyId": str(policy["oss_access_key_id"]),
            "Signature": str(policy["signature"]),
            "policy": str(policy["policy"]),
            "x-oss-object-acl": str(policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": str(policy["x_oss_forbid_overwrite"]),
            "key": object_key,
            "success_action_status": "200",
        }
        if policy.get("security_token"):
            form_data["x-oss-security-token"] = str(policy["security_token"])

        files = {
            "file": (
                filename,
                audio_bytes,
                _guess_content_type(extension),
            )
        }

        try:
            response = httpx.post(
                str(policy["upload_host"]),
                data=form_data,
                files=files,
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise TempSegmentStoreError(f"上传 temp segment 到 DashScope OSS 失败: {exc}") from exc

        if response.status_code != 200:
            detail = (response.text or "").strip()
            raise TempSegmentStoreError(
                f"上传 temp segment 到 DashScope OSS 失败: {response.status_code} {detail}".strip()
            )


_LOCAL_FS_BACKEND = LocalFSTempSegmentStorageBackend()
_DASHSCOPE_OSS_BACKEND = DashScopeOssTempSegmentStorageBackend()


def _resolve_active_save_backend() -> TempSegmentStorageBackend:
    if _resolve_active_driver_name() == _DRIVER_DASHSCOPE_OSS:
        return _DASHSCOPE_OSS_BACKEND
    return _LOCAL_FS_BACKEND


def _resolve_backend_for_asset_ref(asset_ref: Optional[str]) -> TempSegmentStorageBackend:
    raw = str(asset_ref or "").strip().lower()
    parsed = urlparse(raw)
    if raw.startswith("oss://") or parsed.scheme in {"http", "https"}:
        return _DASHSCOPE_OSS_BACKEND
    return _LOCAL_FS_BACKEND


def build_temp_segment_prefix(*, run_id: str, chapter_id: int) -> str:
    return _resolve_active_save_backend().build_prefix(run_id=run_id, chapter_id=chapter_id)


def save_segment_audio_map(
    *,
    run_id: str,
    chapter_id: int,
    audio_map: Dict[Any, Any],
    format: Optional[str] = None,
) -> Dict[str, Any]:
    extension = normalize_audio_extension(format)
    normalized_map = {index: audio_bytes for index, audio_bytes in _iter_normalized_audio_items(audio_map)}
    return _resolve_active_save_backend().save_audio_map(
        run_id=run_id,
        chapter_id=chapter_id,
        audio_map=normalized_map,
        extension=extension,
    )


def save_segment_audio_batch(
    *,
    run_id: str,
    chapter_id: int,
    audio_list: List[Any],
    format: Optional[str] = None,
) -> Dict[str, Any]:
    audio_map = {
        index: audio_bytes
        for index, audio_bytes in enumerate(list(audio_list or []))
        if _normalize_audio_bytes(audio_bytes)
    }
    return save_segment_audio_map(
        run_id=run_id,
        chapter_id=chapter_id,
        audio_map=audio_map,
        format=format,
    )


def extract_cached_segment_paths(checkpoint_data: Optional[Dict[str, Any]]) -> Dict[int, str]:
    checkpoint = dict(checkpoint_data or {})
    merged: Dict[int, str] = {}

    cached_audio_paths = checkpoint.get("cached_audio_paths") or {}
    if isinstance(cached_audio_paths, dict):
        for raw_index, raw_path in cached_audio_paths.items():
            index = _normalize_segment_index(raw_index)
            path_value = str(raw_path or "").strip()
            if index is None or not path_value:
                continue
            merged[index] = path_value

    segments = checkpoint.get("segments") or {}
    if isinstance(segments, dict):
        for raw_index, segment_payload in segments.items():
            if not isinstance(segment_payload, dict):
                continue
            index = _normalize_segment_index(segment_payload.get("index", raw_index))
            path_value = str(segment_payload.get("temp_object_key") or "").strip()
            if index is None or not path_value or index in merged:
                continue
            merged[index] = path_value

    return dict(sorted(merged.items(), key=lambda item: item[0]))


def _extract_segment_integrity_metadata(
    checkpoint_data: Optional[Dict[str, Any]],
    *,
    index: int,
    asset_ref: str,
) -> Dict[str, Any]:
    checkpoint = dict(checkpoint_data or {})
    segments = checkpoint.get("segments") or {}
    if not isinstance(segments, dict):
        return {}

    segment_payload = segments.get(str(index))
    if not isinstance(segment_payload, dict):
        segment_payload = None
        for raw_index, candidate in segments.items():
            if not isinstance(candidate, dict):
                continue
            candidate_index = _normalize_segment_index(candidate.get("index", raw_index))
            if candidate_index == index:
                segment_payload = candidate
                break

    if not isinstance(segment_payload, dict):
        return {}

    payload_ref = str(segment_payload.get("temp_object_key") or "").strip()
    if payload_ref and payload_ref != str(asset_ref or "").strip():
        return {}

    metadata: Dict[str, Any] = {}
    raw_file_size = segment_payload.get("file_size")
    try:
        file_size = int(raw_file_size)
    except (TypeError, ValueError, OverflowError):
        file_size = None
    if file_size is not None and file_size >= 0:
        metadata["file_size"] = file_size

    content_sha1 = str(segment_payload.get("content_sha1") or "").strip().lower()
    if re.fullmatch(r"[a-f0-9]{40}", content_sha1):
        metadata["content_sha1"] = content_sha1

    return metadata


def _segment_audio_matches_integrity_metadata(
    audio_bytes: bytes,
    metadata: Optional[Dict[str, Any]],
) -> bool:
    if not metadata:
        return True

    expected_file_size = metadata.get("file_size")
    if isinstance(expected_file_size, int) and len(audio_bytes) != expected_file_size:
        return False

    expected_sha1 = str(metadata.get("content_sha1") or "").strip().lower()
    if expected_sha1 and hashlib.sha1(audio_bytes).hexdigest() != expected_sha1:
        return False

    return True


def build_segment_asset_ref(
    *,
    run_id: str,
    chapter_id: int,
    segment_index: int,
    content_sha1: str,
    extension: str,
) -> str:
    """按存储驱动重建确定性片段资产 ref（供服务端签发 token 后还原，不接受客户端路径）。"""
    digest = str(content_sha1 or "").strip().lower()[:12]
    ext = normalize_audio_extension(extension)
    filename = f"{_SEGMENT_FILE_STEM}_{int(segment_index):05d}_{digest}.{ext}"
    if _resolve_active_driver_name() == _DRIVER_DASHSCOPE_OSS:
        prefix_key = _build_oss_prefix_key(run_id=run_id, chapter_id=chapter_id)
        return f"oss://{prefix_key}/{filename}"
    return (_build_local_prefix_path(run_id=run_id, chapter_id=chapter_id) / filename).as_posix()


def load_cached_segment_audio(
    checkpoint_data: Optional[Dict[str, Any]],
    *,
    max_segment_count: Optional[int] = None,
) -> Dict[int, bytes]:
    loaded_audio: Dict[int, bytes] = {}
    for index, asset_ref in extract_cached_segment_paths(checkpoint_data).items():
        if max_segment_count is not None and index >= int(max_segment_count):
            continue
        backend = _resolve_backend_for_asset_ref(asset_ref)
        audio_bytes = backend.load_bytes(asset_ref)
        if not audio_bytes:
            continue
        integrity_metadata = _extract_segment_integrity_metadata(
            checkpoint_data,
            index=index,
            asset_ref=asset_ref,
        )
        if not _segment_audio_matches_integrity_metadata(audio_bytes, integrity_metadata):
            continue
        loaded_audio[index] = audio_bytes
    return loaded_audio


def temp_segment_asset_exists(asset_ref: Optional[str]) -> bool:
    raw = str(asset_ref or "").strip()
    if not raw:
        return False
    backend = _resolve_backend_for_asset_ref(raw)
    return backend.asset_exists(raw)


def delete_temp_segment_prefix(
    temp_asset_prefix: Optional[str],
    checkpoint_json: Optional[Dict[str, Any]] = None,
) -> int:
    if temp_asset_prefix:
        backend = _resolve_backend_for_asset_ref(temp_asset_prefix)
        return int(max(backend.delete_prefix(temp_asset_prefix, checkpoint_json=checkpoint_json), 0))

    extracted_paths = extract_cached_segment_paths(checkpoint_json)
    if not extracted_paths:
        return 0

    grouped_paths: Dict[str, List[str]] = {}
    for asset_ref in extracted_paths.values():
        backend_key = "object" if _resolve_backend_for_asset_ref(asset_ref) is _DASHSCOPE_OSS_BACKEND else "local"
        grouped_paths.setdefault(backend_key, []).append(asset_ref)

    removed_files = 0
    if grouped_paths.get("local"):
        removed_files += int(
            max(
                _LOCAL_FS_BACKEND.delete_prefix(
                    None,
                    checkpoint_json={
                        "cached_audio_paths": {
                            str(index): path_value for index, path_value in extracted_paths.items()
                            if _resolve_backend_for_asset_ref(path_value) is _LOCAL_FS_BACKEND
                        }
                    },
                ),
                0,
            )
        )
    if grouped_paths.get("object"):
        removed_files += int(max(_DASHSCOPE_OSS_BACKEND.delete_prefix(None, checkpoint_json=checkpoint_json), 0))
    return removed_files


def inspect_temp_segment_cleanup_flags(
    temp_asset_prefix: Optional[str],
    checkpoint_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """探测 temp segment 清理场景的 best-effort 元数据。

    - ``oss_delete_credentials_missing``：是否存在 OSS 资产但缺少删除凭证。
    - ``oss_candidate_count``：checkpoint 中命中 OSS 前缀的资产条数。
    - ``best_effort``：是否存在无法 verify 的删除路径（凭证缺失即为 True）。
    """

    normalized_prefix = str(temp_asset_prefix or "").strip()
    has_oss_target = normalized_prefix.startswith("oss://")
    oss_refs: List[str] = []
    if has_oss_target or not normalized_prefix:
        oss_refs = list(_iter_matching_oss_asset_refs(normalized_prefix or None, checkpoint_json))
        if oss_refs:
            has_oss_target = True

    credentials_missing = False
    if has_oss_target:
        credentials_missing = _resolve_oss_delete_credentials() is None

    return {
        "oss_delete_credentials_missing": bool(credentials_missing),
        "oss_candidate_count": len(oss_refs),
        "best_effort": bool(credentials_missing and (oss_refs or has_oss_target)),
    }


__all__ = [
    "build_temp_segment_prefix",
    "delete_temp_segment_prefix",
    "inspect_temp_segment_cleanup_flags",
    "extract_cached_segment_paths",
    "load_cached_segment_audio",
    "normalize_audio_extension",
    "save_segment_audio_batch",
    "save_segment_audio_map",
    "temp_segment_asset_exists",
]
