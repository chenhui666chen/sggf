"""Helpers for generation paths that must not be rerouted to another model."""

from __future__ import annotations

from typing import Optional

from core.model_resolution import normalize_model_id, normalize_task_type
from core.model_runtime import resolve_model_for_task


class ExactModelRequiredError(RuntimeError):
    """Raised when the model catalog reroutes an explicitly locked model."""


def require_exact_model(model: Optional[str], task_type: Optional[str] = None) -> Optional[str]:
    """Validate and return an explicit model without allowing catalog fallback."""
    explicit_model = normalize_model_id(model)
    if not explicit_model:
        return None
    resolved_model = resolve_model_for_task(normalize_task_type(task_type), explicit_model) or explicit_model
    if resolved_model != explicit_model:
        raise ExactModelRequiredError(
            f"Locked model {explicit_model} was rerouted to {resolved_model}"
        )
    return explicit_model
