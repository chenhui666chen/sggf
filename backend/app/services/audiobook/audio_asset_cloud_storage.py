from __future__ import annotations

import logging
import mimetypes
import os
from email.utils import formatdate
import base64
import hashlib
import hmac
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import httpx

from app.services.audiobook.cosyvoice_clone_client import (
    COSYVOICE_V35_PLUS_MODEL_ID,
    _build_public_oss_url,
    _get_dashscope_upload_policy,
)


logger = logging.getLogger(__name__)

_DRIVER_LOCAL_FS = "local_fs"
_DRIVER_DASHSCOPE_OSS = "dashscope_oss"
_DRIVER_ALIYUN_OSS = "aliyun_oss"
_DEFAULT_OSS_PREFIX = "shared/audio_library"


def _normalize_driver(value: str | None = None) -> str:
    raw = str(value if value is not None else os.getenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER") or "")
    normalized = raw.strip().lower()
    if normalized == _DRIVER_DASHSCOPE_OSS:
        return _DRIVER_DASHSCOPE_OSS
    if normalized == _DRIVER_ALIYUN_OSS:
        return _DRIVER_ALIYUN_OSS
    return _DRIVER_LOCAL_FS


def get_audio_library_storage_driver() -> str:
    return _normalize_driver()


def is_audio_library_cloud_storage_enabled() -> bool:
    return get_audio_library_storage_driver() in {_DRIVER_DASHSCOPE_OSS, _DRIVER_ALIYUN_OSS}


def _normalize_relative_path(value: str | Path) -> str:
    raw = str(value or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("audio library asset relative_path is invalid")
    return "/".join(parts)


def _normalize_library_type(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("\\", "/").strip("/")
    if normalized in {"sfx", "sound_effect", "sound_effects"}:
        return "sfx"
    if normalized in {"music", "bgm"}:
        return "music"
    raise ValueError("library_type must be sfx or music")


def _build_local_cache_metadata(*, relative_path: str) -> Dict[str, Any]:
    return {
        "storage_mode": "local_cache",
        "storage_driver": _DRIVER_LOCAL_FS,
        "local_cache_path": relative_path,
        "asset_scope": "shared_library",
    }


def _guess_content_type(local_path: Path) -> str:
    guessed, _ = mimetypes.guess_type(local_path.name)
    return guessed or "application/octet-stream"


def _build_object_key(*, library_type: str, relative_path: str) -> str:
    prefix = str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX") or _DEFAULT_OSS_PREFIX)
    prefix = prefix.strip().strip("/")
    if not prefix:
        prefix = _DEFAULT_OSS_PREFIX
    return f"{prefix}/{library_type}/{relative_path}"


def _normalize_public_host(value: str) -> str:
    host = str(value or "").strip()
    if not host:
        return ""
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"
    return host.rstrip("/")


def _normalize_object_key(value: str) -> str:
    return str(value or "").strip().lstrip("/")


def _extract_object_key_from_cloud_uri(cloud_uri: str) -> str:
    raw = str(cloud_uri or "").strip()
    if raw.startswith("oss://"):
        return _normalize_object_key(raw[len("oss://") :])
    return ""


def build_audio_library_public_url(
    *,
    cloud_uri: str = "",
    object_key: str = "",
    fallback_url: str = "",
    upload_host: str = "",
    storage_driver: str = "",
) -> str:
    configured_host = _normalize_public_host(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST") or "")
    normalized_object_key = _normalize_object_key(object_key)
    if not normalized_object_key:
        normalized_object_key = _extract_object_key_from_cloud_uri(cloud_uri)

    normalized_storage_driver = str(storage_driver or "").strip().lower()
    can_use_configured_host = normalized_storage_driver in {"", _DRIVER_ALIYUN_OSS}
    if configured_host and normalized_object_key and can_use_configured_host:
        return f"{configured_host}/{quote(normalized_object_key, safe='/')}"

    fallback = str(fallback_url or "").strip()
    if fallback.startswith(("http://", "https://")):
        return fallback

    if normalized_object_key and upload_host:
        return _build_public_oss_url(upload_host, normalized_object_key)

    return ""


def _build_public_url(upload_host: str, object_key: str) -> str:
    return build_audio_library_public_url(upload_host=upload_host, object_key=object_key)


def _normalize_oss_endpoint(value: str) -> str:
    endpoint = str(value or "").strip()
    if endpoint.startswith("http://"):
        endpoint = endpoint[len("http://") :]
    elif endpoint.startswith("https://"):
        endpoint = endpoint[len("https://") :]
    return endpoint.strip("/")


def _build_aliyun_oss_object_url(*, bucket: str, endpoint: str, object_key: str) -> str:
    normalized_endpoint = _normalize_oss_endpoint(endpoint)
    if not bucket or not normalized_endpoint:
        raise ValueError("Aliyun OSS bucket and endpoint are required")
    return f"https://{bucket}.{normalized_endpoint}/{quote(object_key, safe='/')}"


def _build_aliyun_oss_authorization(
    *,
    method: str,
    bucket: str,
    object_key: str,
    content_type: str,
    date_header: str,
    access_key_id: str,
    access_key_secret: str,
    oss_headers: Dict[str, str] | None = None,
    canonicalized_resource_suffix: str = "",
) -> str:
    canonicalized_oss_headers = ""
    for key, value in sorted((oss_headers or {}).items(), key=lambda item: item[0].lower()):
        normalized_key = str(key).strip().lower()
        if not normalized_key.startswith("x-oss-"):
            continue
        canonicalized_oss_headers += f"{normalized_key}:{str(value).strip()}\n"
    canonicalized_resource = f"/{bucket}/{object_key}{canonicalized_resource_suffix}"
    string_to_sign = (
        f"{method}\n"
        f"\n"
        f"{content_type}\n"
        f"{date_header}\n"
        f"{canonicalized_oss_headers}{canonicalized_resource}"
    )
    digest = hmac.new(
        access_key_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return f"OSS {access_key_id}:{signature}"


def _normalize_aliyun_oss_query_items(query_items: list[tuple[str, str]] | None) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for key, value in query_items or []:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized_value = str(value or "")
        normalized.append((normalized_key, normalized_value))
    normalized.sort(key=lambda item: item[0])
    return normalized


def _build_aliyun_oss_request_url(
    *,
    bucket: str,
    endpoint: str,
    object_key: str = "",
    query_items: list[tuple[str, str]] | None = None,
) -> str:
    url = _build_aliyun_oss_object_url(bucket=bucket, endpoint=endpoint, object_key=object_key)
    normalized_query_items = _normalize_aliyun_oss_query_items(query_items)
    if not normalized_query_items:
        return url
    return f"{url}?{urlencode(normalized_query_items, quote_via=quote, safe='')}"


def _build_aliyun_oss_canonicalized_resource(
    *,
    bucket: str,
    object_key: str = "",
    query_items: list[tuple[str, str]] | None = None,
) -> str:
    resource = f"/{bucket}/{_normalize_object_key(object_key)}"
    normalized_query_items = _normalize_aliyun_oss_query_items(query_items)
    if not normalized_query_items:
        return resource
    query_parts = []
    for key, value in normalized_query_items:
        query_parts.append(f"{key}={value}" if value != "" else key)
    return f"{resource}?{'&'.join(query_parts)}"


def _build_aliyun_oss_request_headers(
    *,
    method: str,
    bucket: str,
    object_key: str = "",
    content_type: str = "",
    query_items: list[tuple[str, str]] | None = None,
    oss_headers: Dict[str, str] | None = None,
) -> Dict[str, str]:
    date_header = formatdate(usegmt=True)
    normalized_oss_headers = {str(key): str(value) for key, value in (oss_headers or {}).items()}
    headers = {
        "Date": date_header,
    }
    if content_type:
        headers["Content-Type"] = content_type
    for key, value in normalized_oss_headers.items():
        if value:
            headers[key] = value

    headers["Authorization"] = _build_aliyun_oss_authorization(
        method=method,
        bucket=bucket,
        object_key=object_key,
        content_type=content_type,
        date_header=date_header,
        access_key_id=str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID") or "").strip(),
        access_key_secret=str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET") or "").strip(),
        oss_headers=normalized_oss_headers,
        canonicalized_resource_suffix=(
            f"?{'&'.join(f'{key}={value}' if value != '' else key for key, value in _normalize_aliyun_oss_query_items(query_items))}"
            if query_items
            else ""
        ),
    )
    return headers


def _xml_child_text(node: ET.Element, child_name: str) -> str:
    for child in list(node):
        if child.tag.endswith(f"}}{child_name}") or child.tag == child_name:
            return str(child.text or "").strip()
    return ""


def _parse_aliyun_oss_list_objects_xml(xml_text: str) -> Dict[str, Any]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    common_prefixes: list[str] = []

    for child in list(root):
        tag = child.tag.split("}", 1)[-1]
        if tag == "Contents":
            item = {
                "key": _xml_child_text(child, "Key"),
                "last_modified": _xml_child_text(child, "LastModified"),
                "etag": _xml_child_text(child, "ETag"),
                "size": int(_xml_child_text(child, "Size") or 0),
                "storage_class": _xml_child_text(child, "StorageClass"),
            }
            if item["key"]:
                items.append(item)
        elif tag == "CommonPrefixes":
            prefix = _xml_child_text(child, "Prefix")
            if prefix:
                common_prefixes.append(prefix)

    return {
        "bucket": _xml_child_text(root, "Name"),
        "prefix": _xml_child_text(root, "Prefix"),
        "delimiter": _xml_child_text(root, "Delimiter"),
        "max_keys": int(_xml_child_text(root, "MaxKeys") or 0),
        "is_truncated": _xml_child_text(root, "IsTruncated").lower() == "true",
        "next_continuation_token": _xml_child_text(root, "NextContinuationToken"),
        "key_count": int(_xml_child_text(root, "KeyCount") or 0),
        "items": items,
        "common_prefixes": common_prefixes,
    }


def list_audio_library_objects(
    *,
    prefix: str = "",
    max_keys: int = 100,
    continuation_token: str = "",
    delimiter: str = "",
    start_after: str = "",
) -> Dict[str, Any]:
    config = _get_aliyun_oss_required_config()
    query_items: list[tuple[str, str]] = [("list-type", "2"), ("max-keys", str(int(max_keys) if max_keys else 100))]
    normalized_prefix = str(prefix or "").strip()
    if normalized_prefix:
        query_items.append(("prefix", normalized_prefix))
    normalized_continuation_token = str(continuation_token or "").strip()
    if normalized_continuation_token:
        query_items.append(("continuation-token", normalized_continuation_token))
    normalized_delimiter = str(delimiter or "").strip()
    if normalized_delimiter:
        query_items.append(("delimiter", normalized_delimiter))
    normalized_start_after = str(start_after or "").strip()
    if normalized_start_after:
        query_items.append(("start-after", normalized_start_after))

    headers = _build_aliyun_oss_request_headers(
        method="GET",
        bucket=config["bucket"],
        query_items=query_items,
        oss_headers={"x-oss-security-token": config["security_token"]} if config["security_token"] else {},
    )
    url = _build_aliyun_oss_request_url(
        bucket=config["bucket"],
        endpoint=config["endpoint"],
        query_items=query_items,
    )

    response = httpx.get(url, headers=headers, timeout=60.0)
    if response.status_code != 200:
        detail = (response.text or "").strip()
        raise RuntimeError(f"Aliyun OSS list objects failed: {response.status_code} {detail}".strip())

    try:
        parsed = _parse_aliyun_oss_list_objects_xml(response.text or "")
    except ET.ParseError as exc:
        raise RuntimeError(f"Aliyun OSS list objects response parse failed: {exc}") from exc

    parsed.update(
        {
            "request_url": url,
            "status_code": response.status_code,
            "query": {key: value for key, value in query_items if value != ""},
        }
    )
    return parsed


def head_audio_library_object(*, object_key: str) -> Dict[str, Any]:
    config = _get_aliyun_oss_required_config()
    normalized_object_key = _normalize_object_key(object_key)
    if not normalized_object_key:
        raise ValueError("object_key is required")

    headers = _build_aliyun_oss_request_headers(
        method="HEAD",
        bucket=config["bucket"],
        object_key=normalized_object_key,
        oss_headers={"x-oss-security-token": config["security_token"]} if config["security_token"] else {},
    )
    url = _build_aliyun_oss_request_url(
        bucket=config["bucket"],
        endpoint=config["endpoint"],
        object_key=normalized_object_key,
    )
    response = httpx.head(url, headers=headers, timeout=30.0)
    if response.status_code == 404:
        return {
            "object_key": normalized_object_key,
            "exists": False,
            "status_code": response.status_code,
            "request_url": url,
        }
    if not 200 <= response.status_code < 300:
        detail = (response.text or "").strip()
        raise RuntimeError(f"Aliyun OSS head object failed: {response.status_code} {detail}".strip())

    response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    content_length = response_headers.get("content-length", "").strip()
    return {
        "object_key": normalized_object_key,
        "exists": True,
        "status_code": response.status_code,
        "request_url": url,
        "content_length": int(content_length) if content_length.isdigit() else None,
        "content_type": response_headers.get("content-type", ""),
        "etag": response_headers.get("etag", ""),
        "last_modified": response_headers.get("last-modified", ""),
        "storage_class": response_headers.get("x-oss-storage-class", ""),
        "object_type": response_headers.get("x-oss-object-type", ""),
    }


def delete_audio_library_object(*, object_key: str) -> Dict[str, Any]:
    config = _get_aliyun_oss_required_config()
    normalized_object_key = _normalize_object_key(object_key)
    if not normalized_object_key:
        raise ValueError("object_key is required")

    headers = _build_aliyun_oss_request_headers(
        method="DELETE",
        bucket=config["bucket"],
        object_key=normalized_object_key,
        oss_headers={"x-oss-security-token": config["security_token"]} if config["security_token"] else {},
    )
    url = _build_aliyun_oss_request_url(
        bucket=config["bucket"],
        endpoint=config["endpoint"],
        object_key=normalized_object_key,
    )
    response = httpx.delete(url, headers=headers, timeout=30.0)
    if response.status_code in {200, 204}:
        return {
            "object_key": normalized_object_key,
            "deleted": True,
            "status_code": response.status_code,
            "request_url": url,
        }
    if response.status_code == 404:
        return {
            "object_key": normalized_object_key,
            "deleted": False,
            "exists": False,
            "status_code": response.status_code,
            "request_url": url,
        }
    detail = (response.text or "").strip()
    raise RuntimeError(f"Aliyun OSS delete object failed: {response.status_code} {detail}".strip())


def _get_aliyun_oss_required_config() -> Dict[str, str]:
    values = {
        "bucket": str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET") or "").strip(),
        "endpoint": _normalize_oss_endpoint(str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT") or "")),
        "access_key_id": str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID") or "").strip(),
        "access_key_secret": str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET") or "").strip(),
        "security_token": str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_SECURITY_TOKEN") or "").strip(),
    }
    missing = [
        name
        for name in ("bucket", "endpoint", "access_key_id", "access_key_secret")
        if not values[name]
    ]
    if missing:
        raise RuntimeError(f"Aliyun OSS audio library config missing: {', '.join(missing)}")
    return values


def _upload_to_aliyun_oss(*, local_path: Path, object_key: str) -> str:
    config = _get_aliyun_oss_required_config()
    content_type = _guess_content_type(local_path)
    date_header = formatdate(usegmt=True)
    oss_headers: Dict[str, str] = {}
    if config["security_token"]:
        oss_headers["x-oss-security-token"] = config["security_token"]

    headers = {
        "Date": date_header,
        "Content-Type": content_type,
        **oss_headers,
    }
    headers["Authorization"] = _build_aliyun_oss_authorization(
        method="PUT",
        bucket=config["bucket"],
        object_key=object_key,
        content_type=content_type,
        date_header=date_header,
        access_key_id=config["access_key_id"],
        access_key_secret=config["access_key_secret"],
        oss_headers=oss_headers,
    )
    url = _build_aliyun_oss_object_url(
        bucket=config["bucket"],
        endpoint=config["endpoint"],
        object_key=object_key,
    )

    with local_path.open("rb") as file_obj:
        response = httpx.put(
            url,
            content=file_obj,
            headers=headers,
            timeout=60.0,
        )

    if response.status_code not in {200, 201}:
        detail = (response.text or "").strip()
        raise RuntimeError(f"Aliyun OSS upload failed: {response.status_code} {detail}".strip())

    return build_audio_library_public_url(
        cloud_uri=f"oss://{object_key}",
        object_key=object_key,
        fallback_url=url,
        storage_driver=_DRIVER_ALIYUN_OSS,
    )


def _upload_to_dashscope_oss(*, local_path: Path, object_key: str) -> str:
    policy_model = str(
        os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_POLICY_MODEL") or COSYVOICE_V35_PLUS_MODEL_ID
    ).strip() or COSYVOICE_V35_PLUS_MODEL_ID
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
        raise RuntimeError(f"DashScope OSS upload policy missing fields: {', '.join(missing_fields)}")

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

    with local_path.open("rb") as file_obj:
        response = httpx.post(
            str(policy["upload_host"]),
            data=form_data,
            files={"file": (local_path.name, file_obj, _guess_content_type(local_path))},
            timeout=60.0,
        )

    if response.status_code != 200:
        detail = (response.text or "").strip()
        raise RuntimeError(f"DashScope OSS upload failed: {response.status_code} {detail}".strip())

    return build_audio_library_public_url(
        cloud_uri=f"oss://{object_key}",
        object_key=object_key,
        upload_host=str(policy["upload_host"]),
        storage_driver=_DRIVER_DASHSCOPE_OSS,
    )


def upload_audio_library_asset(
    *,
    local_path: Path | str,
    relative_path: str,
    library_type: str,
) -> Dict[str, Any]:
    """Upload a shared audio-library asset when cloud storage is configured.

    The local file remains the backend cache used by quality checks and mixing.
    The returned metadata is designed to be merged directly into music/SFX index
    records. If cloud storage is disabled, the function returns explicit local
    cache metadata and does not touch the network.
    """

    normalized_relative_path = _normalize_relative_path(relative_path)
    normalized_library_type = _normalize_library_type(library_type)
    resolved_local_path = Path(local_path)

    storage_driver = _normalize_driver()
    if storage_driver not in {_DRIVER_DASHSCOPE_OSS, _DRIVER_ALIYUN_OSS}:
        return _build_local_cache_metadata(relative_path=normalized_relative_path)

    if not resolved_local_path.exists() or not resolved_local_path.is_file():
        logger.warning("音频素材云上传跳过，本地缓存文件不存在: %s", resolved_local_path)
        return _build_local_cache_metadata(relative_path=normalized_relative_path)

    object_key = _build_object_key(
        library_type=normalized_library_type,
        relative_path=normalized_relative_path,
    )

    try:
        if storage_driver == _DRIVER_ALIYUN_OSS:
            public_url = _upload_to_aliyun_oss(local_path=resolved_local_path, object_key=object_key)
        else:
            public_url = _upload_to_dashscope_oss(local_path=resolved_local_path, object_key=object_key)
    except Exception as exc:
        logger.warning("音频素材云上传失败，保留本地缓存: %s", exc)
        return _build_local_cache_metadata(relative_path=normalized_relative_path)

    return {
        "storage_mode": "durable_cloud",
        "storage_driver": storage_driver,
        "cloud_uri": f"oss://{object_key}",
        "public_url": public_url,
        "object_key": object_key,
        "local_cache_path": normalized_relative_path,
        "asset_scope": "shared_library",
    }


__all__ = [
    "build_audio_library_public_url",
    "delete_audio_library_object",
    "head_audio_library_object",
    "get_audio_library_storage_driver",
    "is_audio_library_cloud_storage_enabled",
    "list_audio_library_objects",
    "upload_audio_library_asset",
]
