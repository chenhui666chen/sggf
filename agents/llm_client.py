from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import requests


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def pick_model(*, primary_env: str, fallback_env: str, default: str = "qwen-plus") -> str:
    raw = os.getenv(primary_env, "").strip()
    if raw:
        return raw

    raw2 = os.getenv(fallback_env, "").strip()
    if raw2:
        return raw2

    # 兼容历史：若使用方把 DEEPSEEK_MODEL 指向 qwen-*，则复用该值。
    raw3 = os.getenv("DEEPSEEK_MODEL", "").strip()
    if raw3.startswith("qwen"):
        return raw3

    return default


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        return None

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            pass

    # 兼容模型输出带解释文字；扫描并抽取第一个“括号平衡”的 JSON 对象。
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_str:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : idx + 1]
                    try:
                        obj = json.loads(candidate)
                        return obj if isinstance(obj, dict) else None
                    except Exception:  # noqa: BLE001
                        break
        start = text.find("{", start + 1)

    return None


def chat_completions(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    timeout_s: int,
    temperature: float = 0.2,
) -> str:
    base = (base_url or "").rstrip("/")
    # 兼容两种配置习惯：
    # - base_url=".../v1"      -> /chat/completions
    # - base_url="... (无/v1)" -> /v1/chat/completions
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
    }
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=max(10, int(timeout_s)),
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:  # noqa: BLE001
        detail: str = ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict) and err:
                    code = err.get("code")
                    message = err.get("message")
                    detail = f"{code}: {message}" if code or message else json.dumps(err, ensure_ascii=False)
                else:
                    detail = json.dumps(data, ensure_ascii=False)
            else:
                detail = json.dumps(data, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            detail = (resp.text or "").strip()
        detail = re.sub(r"\s+", " ", detail).strip()
        if len(detail) > 240:
            detail = detail[:240] + "…"
        raise RuntimeError(f"LLM request failed (HTTP {resp.status_code}): {detail}") from exc
    data = resp.json()
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice0 = choices[0] if isinstance(choices[0], dict) else None
            message = choice0.get("message") if isinstance(choice0, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content
    raise RuntimeError("invalid LLM response: missing choices[0].message.content")
