# -*- coding: utf-8 -*-
"""内部视频质量评价客户端；不参与用户交付状态机。"""
from __future__ import annotations

import base64
import math
from typing import Any

from .adapters.base import UrllibTransport
from .assets.safe_fetch import fetch_bytes
from .vision_contract import VISION_DEFAULT_CRITERIA, VISION_MAX_TOKENS, build_vision_review_prompt, parse_vision_review_content

QUALITY_MODEL = "qwen3.8-omni-flash"
QUALITY_MAX_TOKENS = VISION_MAX_TOKENS
QUALITY_CRITERIA = tuple(VISION_DEFAULT_CRITERIA["video"])


def build_prompt() -> str:
    return build_vision_review_prompt(asset_kind="video", analysis_type="quality",
                                     criteria=list(QUALITY_CRITERIA))


def _content_text(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("quality response has no content") from exc
    if not isinstance(content, str):
        raise ValueError("quality response content is not text")
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("quality response is not JSON")
    return content[start:end + 1]


def validate_review(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("quality response is not an object")
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("quality response scores is invalid")
    normalized = {}
    for name in QUALITY_CRITERIA:
        item = scores.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"quality score missing: {name}")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) \
                or not math.isfinite(score) or not 0 <= score <= 10:
            raise ValueError(f"quality score out of range: {name}")
        comment = item.get("comment", "")
        if not isinstance(comment, str) or not comment.strip() or len(comment) > 1000:
            raise ValueError(f"quality comment is invalid: {name}")
        normalized[name] = {"score": float(score), "comment": comment}
    return {"scores": normalized}


class VideoQualityClient:
    def __init__(self, *, api_key: str, base_url: str = "https://dashscope.aliyuncs.com/compatible-mode",
                 model: str = QUALITY_MODEL, timeout: int = 45, transport=None, fetcher=None):
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self._timeout = timeout
        self._http = transport or UrllibTransport()
        self._fetcher = fetcher or fetch_bytes

    def evaluate(self, source_url: str) -> dict[str, Any]:
        media = self._fetcher(source_url, timeout=self._timeout, max_bytes=64 * 1024 * 1024)
        encoded = base64.b64encode(media.body).decode("ascii")
        mime = media.content_type if media.content_type.startswith("video/") else "video/mp4"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{encoded}"}},
                {"type": "text", "text": build_prompt()},
            ]}],
            "max_tokens": QUALITY_MAX_TOKENS,
            "reasoning_effort": "none",
        }
        status, response = self._http.request(
            "POST", self._url,
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
            body=payload, timeout=self._timeout)
        if status != 200:
            raise RuntimeError(f"quality model HTTP {status}")
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("quality response choices is invalid")
        if choices[0].get("finish_reason") not in (None, "stop"):
            raise ValueError("quality model did not finish normally")
        parsed = parse_vision_review_content(_content_text(response))
        return validate_review(parsed)


def review_score(result: dict[str, Any]) -> tuple[float, bool]:
    scores = [item["score"] for item in result["scores"].values()]
    score = sum(scores) / len(scores)
    return score, score >= 6.0
