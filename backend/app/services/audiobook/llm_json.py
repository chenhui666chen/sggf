from __future__ import annotations

import json
import re
from typing import Any


class LLMJsonParseError(ValueError):
    pass


def parse_llm_json_object(text: str) -> dict[str, Any]:
    data = parse_llm_json(text)
    if not isinstance(data, dict):
        raise LLMJsonParseError(f"Expected JSON object, got {type(data).__name__}")
    return data


def parse_llm_json_array(text: str) -> list[Any]:
    data = parse_llm_json(text)
    if not isinstance(data, list):
        if isinstance(data, dict):
            extracted = _extract_array_from_object(data)
            if extracted is not None:
                return extracted
        raise LLMJsonParseError(f"Expected JSON array, got {type(data).__name__}")
    return data


def parse_llm_json(text: str) -> Any:
    cleaned = clean_llm_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        salvaged = salvage_truncated_json_array(cleaned)
        if salvaged is not None:
            try:
                return json.loads(salvaged)
            except json.JSONDecodeError:
                pass
        raise LLMJsonParseError(str(exc)) from exc


def clean_llm_json_text(text: str) -> str:
    value = str(text or "").strip()
    value = _strip_thinking_tags(value)
    value = _extract_fenced_json(value)
    value = _extract_likely_json(value)
    value = _strip_json_comments(value)
    value = re.sub(r",\s*([}\]])", r"\1", value)
    return value.strip()


def salvage_truncated_json_array(text: str) -> str | None:
    value = str(text or "").strip()
    first_bracket = value.find("[")
    last_brace = value.rfind("}")
    if first_bracket == -1 or last_brace == -1 or last_brace <= first_bracket:
        return None

    salvaged = value[first_bracket:last_brace + 1].rstrip()
    if salvaged.endswith(","):
        salvaged = salvaged[:-1].rstrip()
    return salvaged + "]"


def _extract_fenced_json(text: str) -> str:
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _strip_thinking_tags(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"<think\b[^>]*>.*?</think>",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    value = re.sub(r"^.*?</think>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"</?think\b[^>]*>", "", value, flags=re.IGNORECASE)
    return value.strip()


def _extract_likely_json(text: str) -> str:
    value = text.strip()
    if value.startswith("{") or value.startswith("["):
        return value

    starts = [idx for idx in (value.find("{"), value.find("[")) if idx != -1]
    if not starts:
        return value

    start = min(starts)
    end = max(value.rfind("}"), value.rfind("]"))
    if end > start:
        return value[start:end + 1].strip()
    return value[start:].strip()


def _strip_json_comments(text: str) -> str:
    value = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    value = re.sub(r"(^|[^:])//.*?$", r"\1", value, flags=re.MULTILINE)
    return value


def _extract_array_from_object(data: dict[str, Any]) -> list[Any] | None:
    for key in ("segments", "script_segments", "items", "data", "result", "records"):
        value = data.get(key)
        if isinstance(value, list):
            return value

    if len(data) == 1:
        only_value = next(iter(data.values()))
        if isinstance(only_value, list):
            return only_value

    return None
