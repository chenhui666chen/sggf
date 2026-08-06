"""片段候选音频的服务端签发 token。

候选音频不再以客户端可篡改的路径流转，而是由服务端签发不可伪造的
candidate_id（HMAC-SHA256 签名），绑定章节音频记录、片段索引、存储前缀、
内容签名、预览类型、基础/有效片段指纹、合成指纹、扩展名与过期时间。apply/试听接口仅接受
candidate_id，由服务端重建受控 asset ref 并校验内容签名与指纹，
杜绝跨资产读取、SSRF 与“文本 A 的音频被写成文本 B”的跨片段错绑。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.audiobook.segment_synthesis_contract import (
    CANDIDATE_CONTRACT_REVISION,
)

logger = logging.getLogger(__name__)

CANDIDATE_TOKEN_TTL_SECONDS = 24 * 3600
_FALLBACK_SECRET = "audiobook-segment-candidate-dev-secret"


def _candidate_secret() -> bytes:
    secret = str(
        getattr(settings, "AUDIOBOOK_CANDIDATE_SECRET", "")
        or getattr(settings, "JWT_SECRET", "")
        or _FALLBACK_SECRET
    ).strip()
    return (secret or _FALLBACK_SECRET).encode("utf-8")


def _sign_payload(payload_b64: str) -> str:
    return hmac.new(
        _candidate_secret(), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:43]


def issue_segment_candidate_token(
    *,
    chapter_audio_id: int,
    chapter_id: int,
    segment_index: int,
    run_id: str,
    content_sha1: str,
    extension: str,
    preview_type: str = "",
    segment_fingerprint: str = "",
    effective_segment_fingerprint: str = "",
    synthesis_fingerprint: str = "",
    ttl_seconds: int = CANDIDATE_TOKEN_TTL_SECONDS,
) -> str:
    """签发候选 token，绑定归属、内容签名、预览类型和三类合成指纹。"""
    payload: Dict[str, Any] = {
        "cai": int(chapter_audio_id),
        "chi": int(chapter_id),
        "si": int(segment_index),
        "run": str(run_id or ""),
        "sha1": str(content_sha1 or "").strip().lower(),
        "ext": str(extension or "mp3").strip().lower(),
        "pt": str(preview_type or "").strip().lower(),
        "fp": str(segment_fingerprint or "").strip(),
        "efp": str(effective_segment_fingerprint or "").strip(),
        "sfp": str(synthesis_fingerprint or "").strip(),
        "rev": CANDIDATE_CONTRACT_REVISION,
        "exp": int(time.time()) + int(ttl_seconds),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{payload_b64}.{_sign_payload(payload_b64)}"


def verify_segment_candidate_token(
    token: Optional[str],
    *,
    chapter_audio_id: int,
    segment_index: int,
) -> Optional[Dict[str, Any]]:
    """校验 token 合法性与归属绑定，返回 payload；非法/过期/不匹配时返回 None。"""
    raw = str(token or "").strip()
    if not raw or "." not in raw:
        return None
    payload_b64, signature = raw.rsplit(".", 1)
    expected = _sign_payload(payload_b64)
    if not hmac.compare_digest(expected, signature):
        logger.warning("片段候选 token 签名校验失败")
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except (ValueError, TypeError) as exc:
        logger.warning("片段候选 token 解析失败: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("rev") or "").strip() != CANDIDATE_CONTRACT_REVISION:
        logger.info(
            "片段候选 token 合同版本已失效: got=%s expected=%s",
            payload.get("rev"),
            CANDIDATE_CONTRACT_REVISION,
        )
        return None
    try:
        expired = int(payload.get("exp") or 0) < int(time.time())
    except (TypeError, ValueError):
        return None
    if expired:
        logger.info("片段候选 token 已过期")
        return None
    try:
        bound_chapter_audio = int(payload.get("cai"))
        bound_segment = int(payload.get("si"))
    except (TypeError, ValueError):
        return None
    if bound_chapter_audio != int(chapter_audio_id) or bound_segment != int(segment_index):
        logger.warning(
            "片段候选 token 归属不匹配: expect=(%s,%s) got=(%s,%s)",
            chapter_audio_id, segment_index, bound_chapter_audio, bound_segment,
        )
        return None
    return payload


__all__ = [
    "CANDIDATE_TOKEN_TTL_SECONDS",
    "issue_segment_candidate_token",
    "verify_segment_candidate_token",
]
