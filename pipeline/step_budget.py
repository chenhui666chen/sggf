from __future__ import annotations

import os
from typing import Callable


def _env_int(name: str, default: int, *, getenv: Callable[[str], str | None]) -> int:
    raw = getenv(name)
    if raw is None:
        return int(default)
    text = str(raw).strip()
    if not text:
        return int(default)
    try:
        return int(text)
    except Exception:  # noqa: BLE001
        return int(default)


def _env_flag(name: str, default: bool, *, getenv: Callable[[str], str | None]) -> bool:
    raw = getenv(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip()
    if not text:
        return bool(default)
    return text.lower() not in {"0", "false", "no", "off"}


def estimate_pipeline_max_steps(
    *,
    required_roles_count: int,
    manual_mode: bool,
    asset_parallelism: int,
    base_steps: int,
    cap_steps: int,
) -> int:
    base = max(20, int(base_steps))
    cap = max(base, int(cap_steps))
    if int(required_roles_count) <= 0 or bool(manual_mode):
        return min(base, cap)

    parallelism = max(1, int(asset_parallelism))
    asset_steps = (int(required_roles_count) + parallelism - 1) // parallelism
    estimated = max(base, int(asset_steps) + 30)
    return min(estimated, cap)


def estimate_pipeline_max_steps_from_env(
    *,
    required_roles_count: int,
    manual_mode_override: bool | None = None,
    getenv: Callable[[str], str | None] = os.getenv,
) -> int:
    base_steps = _env_int("DREAMWEAVER_PIPELINE_MAX_STEPS_BASE", 50, getenv=getenv)
    cap_steps = _env_int("DREAMWEAVER_PIPELINE_MAX_STEPS_CAP", 500, getenv=getenv)
    if manual_mode_override is None:
        manual_mode = _env_flag("DREAMWEAVER_LIBRARY_MANUAL", True, getenv=getenv)
    else:
        manual_mode = bool(manual_mode_override)
    asset_parallelism = _env_int("DREAMWEAVER_ASSET_LIBRARY_PARALLELISM", 1, getenv=getenv)
    return estimate_pipeline_max_steps(
        required_roles_count=int(required_roles_count),
        manual_mode=bool(manual_mode),
        asset_parallelism=int(asset_parallelism),
        base_steps=int(base_steps),
        cap_steps=int(cap_steps),
    )
