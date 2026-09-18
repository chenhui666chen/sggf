from __future__ import annotations

import asyncio
import sys
import threading
import types
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


from core.llm_adapters import OpenAICompatibleAdapter
from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec


def _build_spec(default_timeout: int = 30) -> UnifiedModelSpec:
    return UnifiedModelSpec(
        id="loop-safe-model",
        name="Loop Safe Model",
        provider="test",
        model_type=ModelType.LLM,
        api_config=APIConfig(
            api_key_env="TEST_API_KEY",
            base_url="https://api.test.com/v1",
            default_timeout=default_timeout,
        ),
    )


def _install_fake_openai_runtime():
    created_clients: list[FakeAsyncOpenAI] = []

    class FakeTimeout:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            created_clients.append(self)

        def close(self):
            self.closed = True

    fake_openai = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
    fake_httpx = types.SimpleNamespace(AsyncClient=FakeAsyncClient, Timeout=FakeTimeout)
    return created_clients, fake_openai, fake_httpx


def _install_async_close_runtime():
    created_clients: list[FakeAsyncOpenAI] = []
    close_loop_ids: list[int] = []

    class FakeTimeout:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def aclose(self):
            close_loop_ids.append(id(asyncio.get_running_loop()))

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._http_client = kwargs["http_client"]
            created_clients.append(self)

        async def close(self):
            await self._http_client.aclose()

    fake_openai = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
    fake_httpx = types.SimpleNamespace(AsyncClient=FakeAsyncClient, Timeout=FakeTimeout)
    return created_clients, close_loop_ids, fake_openai, fake_httpx


@pytest.mark.asyncio
async def test_openai_adapter_reuses_client_within_same_event_loop() -> None:
    created_clients, fake_openai, fake_httpx = _install_fake_openai_runtime()

    with patch.dict("os.environ", {"TEST_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"openai": fake_openai, "httpx": fake_httpx}):
            adapter = OpenAICompatibleAdapter(_build_spec())

            client_a = adapter._get_client_for_current_context()
            client_b = adapter._get_client_for_current_context()

            assert client_a is client_b
            assert len(created_clients) == 1


def test_openai_adapter_isolates_clients_across_threads_and_loops() -> None:
    created_clients, fake_openai, fake_httpx = _install_fake_openai_runtime()

    with patch.dict("os.environ", {"TEST_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"openai": fake_openai, "httpx": fake_httpx}):
            adapter = OpenAICompatibleAdapter(_build_spec())

            async def get_client():
                return adapter._get_client_for_current_context()

            main_client = asyncio.run(get_client())
            worker_box: dict[str, object] = {}

            def runner() -> None:
                worker_box["client"] = asyncio.run(get_client())

            thread = threading.Thread(target=runner, daemon=True)
            thread.start()
            thread.join()

            worker_client = worker_box["client"]
            assert worker_client is not main_client
            assert len(created_clients) == 3


@pytest.mark.asyncio
async def test_openai_adapter_resets_current_context_client_after_network_failure() -> None:
    created_clients, fake_openai, fake_httpx = _install_fake_openai_runtime()

    with patch.dict("os.environ", {"TEST_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"openai": fake_openai, "httpx": fake_httpx}):
            adapter = OpenAICompatibleAdapter(_build_spec())

            first_client = adapter._get_client_for_current_context()
            adapter._reset_current_context_client("network_error")
            second_client = adapter._get_client_for_current_context()

            assert first_client is not second_client
            assert first_client.closed is True
            assert len(created_clients) == 2


@pytest.mark.asyncio
async def test_openai_adapter_closes_async_client_on_current_loop_when_reset() -> None:
    created_clients, close_loop_ids, fake_openai, fake_httpx = _install_async_close_runtime()

    with patch.dict("os.environ", {"TEST_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"openai": fake_openai, "httpx": fake_httpx}):
            adapter = OpenAICompatibleAdapter(_build_spec())

            adapter._get_client_for_current_context()
            current_loop_id = id(asyncio.get_running_loop())
            adapter._reset_current_context_client("network_error")
            await asyncio.sleep(0)

            assert len(created_clients) == 1
            assert close_loop_ids == [current_loop_id]


def test_openai_adapter_client_timeout_caps_connect_phase() -> None:
    """client 级 timeout 必须是带 connect 上限的结构化对象。

    openai SDK 会把 client 级裸 float timeout 作为 per-request 参数覆盖
    http_client 默认值，导致 TLS 握手挂起时按全量超时（如 300s）而非 30s 失败。
    """
    created_clients, fake_openai, fake_httpx = _install_fake_openai_runtime()

    with patch.dict("os.environ", {"TEST_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"openai": fake_openai, "httpx": fake_httpx}):
            adapter = OpenAICompatibleAdapter(_build_spec(default_timeout=300))
            client = adapter._get_client_for_current_context()

            timeout = client.kwargs["timeout"]
            assert isinstance(timeout, fake_httpx.Timeout)
            assert timeout.args == (300.0,)
            assert timeout.kwargs["connect"] == 30.0
            # 与 http_client 使用同一个结构化配置，两层不再有分歧
            assert timeout is client.kwargs["http_client"].kwargs["timeout"]
