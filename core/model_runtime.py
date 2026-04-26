from __future__ import annotations

import asyncio
import math
import threading
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar

from core.model_resolution import normalize_model_id, normalize_task_type

T = TypeVar("T")

_hub_lock = threading.Lock()
_hub_initialized = False


def _safe_positive_int(value: object) -> Optional[int]:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _safe_positive_float(value: object) -> Optional[float]:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def estimate_model_timeout_seconds(
    model_id: Optional[str],
    requested_max_tokens: Optional[int] = None,
    *,
    minimum_timeout: Optional[int] = None,
) -> Optional[int]:
    """根据模型吞吐与本次输出预算估算更合理的请求超时时间。"""

    normalized_model = normalize_model_id(model_id)
    if normalized_model is None and isinstance(model_id, str):
        normalized_model = model_id.strip() or None
    if not normalized_model:
        return _safe_positive_int(minimum_timeout)

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    spec = model_hub.registry.get_spec(normalized_model)
    minimum_timeout_value = _safe_positive_int(minimum_timeout)
    if spec is None:
        return minimum_timeout_value

    default_timeout = (
        _safe_positive_int(getattr(spec.api_config, "default_timeout", None))
        or minimum_timeout_value
        or 120
    )
    requested_tokens = _safe_positive_int(requested_max_tokens)
    if requested_tokens is None:
        requested_tokens = _safe_positive_int((getattr(spec, "default_params", {}) or {}).get("max_tokens"))
    if requested_tokens is None:
        return max(default_timeout, minimum_timeout_value or 0)

    performance = getattr(spec, "performance", None)
    tokens_per_second = _safe_positive_float(getattr(performance, "tokens_per_second", None))
    if tokens_per_second is None:
        return max(default_timeout, minimum_timeout_value or 0)

    p95_latency_seconds = _safe_positive_float(getattr(performance, "p95_latency_seconds", None)) or 0.0
    avg_latency_seconds = _safe_positive_float(getattr(performance, "avg_latency_seconds", None)) or 0.0
    latency_buffer_seconds = max(15.0, p95_latency_seconds, avg_latency_seconds * 1.5)

    if requested_tokens >= 131072:
        safety_factor = 1.35
    elif requested_tokens >= 65536:
        safety_factor = 1.30
    elif requested_tokens >= 32768:
        safety_factor = 1.25
    else:
        safety_factor = 1.20

    estimated_timeout = int(
        math.ceil((requested_tokens / tokens_per_second) * safety_factor + latency_buffer_seconds)
    )

    return max(default_timeout, estimated_timeout, minimum_timeout_value or 0)


def ensure_model_hub_initialized() -> None:
    """确保 ModelHub 已按项目配置完成初始化。"""

    global _hub_initialized
    if _hub_initialized:
        return

    with _hub_lock:
        if _hub_initialized:
            return

        from core.model_hub import model_hub

        config_path = Path(__file__).resolve().parent.parent / "config" / "llm_models.yaml"
        if config_path.exists():
            model_hub.initialize(str(config_path))
        else:
            model_hub.initialize()

        _hub_initialized = True


def run_async_compat(factory: Callable[[], Awaitable[T]]) -> T:
    """
    在同步上下文中安全执行异步调用。

    当当前线程已经存在事件循环时，切换到新线程执行，避免
    `asyncio.run()` 在运行中的 loop 中报错。
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result_box: dict[str, T] = {}
    error_box: dict[str, BaseException] = {}
    done = threading.Event()

    def runner() -> None:
        try:
            result_box["value"] = asyncio.run(factory())
        except BaseException as exc:  # pragma: no cover - 透传异常
            error_box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    done.wait()

    if "error" in error_box:
        raise error_box["error"]

    return result_box["value"]


def get_model_base_url(model_id: Optional[str]) -> str:
    """读取指定模型的 base_url，供 LangChain 兼容层和旧判断逻辑使用。"""

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    selection = model_hub.resolve_model_request(model=model_id)
    resolved_model_id = selection.get("resolved_model_id")
    if resolved_model_id is None:
        return ""

    spec = model_hub.registry.get_spec(resolved_model_id)
    if spec is None:
        return ""

    return spec.api_config.base_url


def resolve_model_for_task(task_type: Optional[str], model: Optional[str]) -> Optional[str]:
    """按统一规则解析最终模型。"""

    ensure_model_hub_initialized()

    from core.model_hub import model_hub

    selection = model_hub.resolve_model_request(
        task_type=normalize_task_type(task_type),
        model=normalize_model_id(model),
    )
    return selection.get("resolved_model_id")
