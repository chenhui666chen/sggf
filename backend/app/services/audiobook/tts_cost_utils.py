from __future__ import annotations

import re
from typing import Any, Mapping


def parse_tts_cost_yuan(raw_value: Any) -> float | None:
    try:
        return float(
            str(raw_value)
            .replace("¥", "")
            .replace("￥", "")
            .replace("$", "")
            .strip()
        )
    except (TypeError, ValueError):
        return None


def extract_tts_cost_yuan(stats: Mapping[str, Any]) -> float:
    numeric_value = parse_tts_cost_yuan(stats.get("estimated_cost_yuan"))
    if numeric_value is not None:
        return max(numeric_value, 0.0)

    parsed_display_value = parse_tts_cost_yuan(stats.get("estimated_cost"))
    if parsed_display_value is not None:
        return max(parsed_display_value, 0.0)

    match = re.search(r"-?\d+(?:\.\d+)?", str(stats.get("estimated_cost") or ""))
    return max(float(match.group(0)), 0.0) if match else 0.0
