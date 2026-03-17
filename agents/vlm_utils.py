from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def mime_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def file_to_data_url(path: Path) -> str:
    mime = mime_from_path(path)
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def try_parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def vlm_chat_json(
    *,
    vlm_adapter: Any,
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 400,
) -> Optional[Dict[str, Any]]:
    if vlm_adapter is None:
        return None

    try:
        if isinstance(vlm_adapter, str):
            from adapters.adapter_helpers import chat_messages

            result = chat_messages(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                model_id=vlm_adapter,
            )
            if not getattr(result, "success", False):
                result = chat_messages(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model_id=vlm_adapter,
                )
        else:
            if not hasattr(vlm_adapter, "chat"):
                return None
            result = vlm_adapter.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            if not getattr(result, "success", False):
                result = vlm_adapter.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
        if not getattr(result, "success", False):
            return None
        content = ""
        if isinstance(result.data, dict) and isinstance(result.data.get("content"), str):
            content = result.data["content"]
        return try_parse_json_object(content)
    except Exception:  # noqa: BLE001
        return None


def clamp_prompt_text(text: str, limit: int = 900) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip()


def clamp_text_list(
    items: Any,
    *,
    max_items: int = 8,
    max_chars: int = 120,
) -> List[str]:
    if not isinstance(items, list):
        return []
    max_items = max(0, int(max_items))
    max_chars = max(0, int(max_chars))
    out: List[str] = []
    for item in items:
        if not isinstance(item, (str, int, float)):
            continue
        text = str(item).strip()
        if not text:
            continue
        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        if text in out:
            continue
        out.append(text)
        if max_items and len(out) >= max_items:
            break
    return out
