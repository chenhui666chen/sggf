from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar

from core.model_resolution import normalize_model_id, normalize_task_type

T = TypeVar("T")

_hub_lock = threading.Lock()
_hub_initialized = False


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
    normalized_model = normalize_model_id(model_id)
    if normalized_model is None:
        return ""

    from core.model_hub import model_hub

    spec = model_hub.registry.get_spec(normalized_model)
    if spec is None:
        return ""

    return spec.api_config.base_url


def resolve_model_for_task(task_type: Optional[str], model: Optional[str]) -> Optional[str]:
    """按统一规则解析最终模型。"""

    ensure_model_hub_initialized()

    normalized_model = normalize_model_id(model)
    if normalized_model is not None:
        return normalized_model

    normalized_task = normalize_task_type(task_type)
    if normalized_task is None:
        return None

    from core.model_hub import model_hub

    spec = model_hub.select_model(normalized_task)
    if spec is None:
        return None

    return spec.id
