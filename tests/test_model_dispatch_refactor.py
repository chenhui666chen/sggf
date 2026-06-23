from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from schemas.unified_model_spec import LLMResult


@pytest.mark.asyncio
async def test_unified_llm_client_routes_official_deepseek_v4_model() -> None:
    from core.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()

    with patch(
        "core.model_hub.model_hub.call",
        new=AsyncMock(
            return_value=LLMResult(
                success=True,
                model_id="deepseek-v4-pro",
                content="ok",
            )
        ),
    ) as mocked_call:
        content = await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            task_type="content_draft",
            model="deepseek-v4-pro",
        )

    assert content == "ok"
    assert mocked_call.await_args.kwargs["task_type"] == "chapter"
    assert mocked_call.await_args.kwargs["model"] == "deepseek-v4-pro"


def test_agents_llm_client_forwards_timeout_to_chat() -> None:
    from agents.llm_client import chat_completions

    captured: dict[str, object] = {}

    class _FakeClient:
        async def chat(self, **kwargs: object) -> str:
            captured.update(kwargs)
            return "ok"

    with patch("agents.llm_client.get_llm_client", return_value=_FakeClient()):
        content = chat_completions(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="qwen3.5-plus",
            messages=[{"role": "user", "content": "hello"}],
            timeout_s=321,
        )

    assert content == "ok"
    assert captured["timeout"] == 321


def test_agents_llm_client_forwards_timeout_to_chat_stream() -> None:
    from agents.llm_client import chat_completions

    captured: dict[str, object] = {}
    streamed_chunks: list[str] = []

    class _FakeClient:
        async def chat_stream(self, **kwargs: object) -> str:
            captured.update(kwargs)
            on_chunk = kwargs.get("on_chunk")
            assert callable(on_chunk)
            await on_chunk("chunk")  # type: ignore[misc]
            return "stream-ok"

    def _on_chunk(text: str, idx: int) -> None:
        streamed_chunks.append(f"{idx}:{text}")

    with patch("agents.llm_client.get_llm_client", return_value=_FakeClient()):
        content = chat_completions(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="qwen3.5-plus",
            messages=[{"role": "user", "content": "hello"}],
            timeout_s=654,
            on_chunk=_on_chunk,
        )

    assert content == "stream-ok"
    assert captured["timeout"] == 654
    assert streamed_chunks == ["0:chunk"]


def test_agents_llm_client_resolves_deepseek_v4_to_official_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.llm_client import resolve_llm_runtime_config

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_BASE", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    config = resolve_llm_runtime_config("deepseek-v4-pro")

    assert config.api_key == "deepseek-key"
    assert config.base_url == "https://api.deepseek.com"
    assert config.api_key_env == "DEEPSEEK_API_KEY"
    assert config.base_url_env == "DEEPSEEK_API_BASE"


def test_agents_llm_client_keeps_qwen_on_dashscope(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.llm_client import resolve_llm_runtime_config

    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    config = resolve_llm_runtime_config("qwen-plus")

    assert config.api_key == "dashscope-key"
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.api_key_env == "DASHSCOPE_API_KEY"
    assert config.base_url_env == "DASHSCOPE_API_BASE"


def test_deepseek_v4_pro_uses_thinking_mode_without_temperature() -> None:
    from core.llm_adapters import DeepSeekV4ProAdapter
    from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        provider="deepseek",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.deepseek.com"),
        default_params={
            "request_model": "deepseek-v4-pro",
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        },
    )
    adapter = DeepSeekV4ProAdapter.__new__(DeepSeekV4ProAdapter)
    adapter.spec = spec

    params = adapter._build_completion_params(
        messages=[{"role": "user", "content": "review"}],
        temperature=0.7,
        max_tokens=2048,
        extra_kwargs={},
    )

    assert "temperature" not in params
    assert params["extra_body"]["thinking"] == {"type": "enabled"}
    assert params["reasoning_effort"] == "high"


def test_deepseek_v4_flash_disables_thinking_mode_by_default() -> None:
    from core.llm_adapters import DeepSeekV4FlashAdapter
    from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="deepseek-v4-flash",
        name="DeepSeek V4 Flash",
        provider="deepseek",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.deepseek.com"),
        default_params={
            "request_model": "deepseek-v4-flash",
            "thinking": {"type": "disabled"},
        },
    )
    adapter = DeepSeekV4FlashAdapter.__new__(DeepSeekV4FlashAdapter)
    adapter.spec = spec

    params = adapter._build_completion_params(
        messages=[{"role": "user", "content": "rewrite"}],
        temperature=0.7,
        max_tokens=512,
        extra_kwargs={},
    )

    assert params["temperature"] == 0.7
    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_deepseek_thinking_mode_is_disabled_for_stream_tools_and_json() -> None:
    from core.llm_adapters import DeepSeekV4ProAdapter
    from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        provider="deepseek",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.deepseek.com"),
        default_params={
            "request_model": "deepseek-v4-pro",
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        },
    )
    adapter = DeepSeekV4ProAdapter.__new__(DeepSeekV4ProAdapter)
    adapter.spec = spec

    params = adapter._build_completion_params(
        messages=[{"role": "user", "content": "extract"}],
        temperature=0.1,
        max_tokens=512,
        extra_kwargs={
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "noop", "parameters": {}}}],
            "response_format": {"type": "json_object"},
        },
    )

    assert params["extra_body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in params


@pytest.mark.asyncio
async def test_deepseek_reasoning_content_is_kept_out_of_business_content() -> None:
    from core.llm_adapters import DeepSeekV4ProAdapter
    from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        provider="deepseek",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.deepseek.com"),
        default_params={
            "request_model": "deepseek-v4-pro",
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        },
    )

    class _FakeCompletions:
        async def create(self, **_: object) -> object:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="final answer",
                            reasoning_content="private reasoning",
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            )

    adapter = DeepSeekV4ProAdapter.__new__(DeepSeekV4ProAdapter)
    adapter.spec = spec
    adapter._initialized = True
    adapter._get_client_for_current_context = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )

    result = await adapter.generate(
        messages=[{"role": "user", "content": "review"}],
        max_tokens=128,
    )

    assert result.success is True
    assert result.content == "final answer"
    assert result.metadata["reasoning_content_len"] == len("private reasoning")
    assert result.metadata["has_reasoning_content"] is True


def test_langchain_bridge_routes_through_model_hub() -> None:
    from core.langchain_bridge import create_task_llm

    llm = create_task_llm(task_type="content_draft")

    with patch(
        "core.model_hub.model_hub.call",
        new=AsyncMock(
            return_value=LLMResult(
                success=True,
                model_id="qwen3-max",
                content="bridge-ok",
            )
        ),
    ) as mocked_call:
        response = llm.invoke([HumanMessage(content="test")])

    assert response.content == "bridge-ok"
    assert mocked_call.await_args.kwargs["task_type"] == "chapter"


def test_create_model_llm_resolves_catalog_guarded_model_at_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from core.langchain_bridge import create_model_llm
    from core.model_runtime import get_model_base_url
    from core.model_hub import model_hub
    from core.unified_registry import UnifiedModelRegistry
    from schemas.unified_model_spec import UnifiedModelSpec, ModelType, APIConfig, RoutingConfig

    recent_verified_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        f"""
{{
  "version": 1,
  "entries": {{
    "failed-model": {{
      "verification_status": "failed",
      "last_verified_at": "{recent_verified_at}"
    }},
    "healthy-model": {{
      "verification_status": "verified",
      "last_verified_at": "{recent_verified_at}"
    }}
  }}
}}
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    registry = UnifiedModelRegistry()
    registry.clear()
    model_hub.registry = registry
    registry.register(
        UnifiedModelSpec(
            id="failed-model",
            name="Failed Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://failed.example/v1"),
            routing=RoutingConfig(task_types=["chapter"], fallback_models=["healthy-model"]),
        )
    )
    registry.register(
        UnifiedModelSpec(
            id="healthy-model",
            name="Healthy Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://healthy.example/v1"),
            routing=RoutingConfig(task_types=["chapter"]),
        )
    )

    llm = create_model_llm("failed-model")

    assert llm.model_name == "healthy-model"
    assert llm.openai_api_base == "https://healthy.example/v1"
    assert get_model_base_url("failed-model") == "https://healthy.example/v1"


def test_no_legacy_llm_imports_in_runtime_code() -> None:
    project_root = Path(__file__).parent.parent
    targets = [
        project_root / "backend/app",
        project_root / "core",
        project_root / "agents",
    ]
    forbidden_patterns = [
        r"from app\.services\.llm_client import",
        r"from app\.services\.model_optimizer import",
        r"from app\.services\.agents\.llm_singleton import",
        r"from \.llm_singleton import",
        r"from \.\.llm_client import",
        r"from \.\.model_optimizer import",
        r"from langchain_openai import ChatOpenAI",
        r"from langchain_community\.chat_models import ChatOpenAI",
        r"\bChatOpenAI\(",
    ]

    offenders: list[str] = []
    for target in targets:
        for path in target.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in forbidden_patterns:
                if re.search(pattern, text):
                    offenders.append(f"{path}: {pattern}")

    assert offenders == []


def test_no_deprecated_deepseek_model_ids_in_runtime_code() -> None:
    project_root = Path(__file__).parent.parent
    targets = [
        project_root / "backend/app",
        project_root / "core",
        project_root / "agents",
        project_root / "config/llm_models.yaml",
        project_root / "config/model_catalog_profiles.yaml",
    ]
    deprecated_model_ids = ("deepseek-" + "chat", "deepseek-" + "reasoner")

    offenders: list[str] = []
    for target in targets:
        paths = [target] if target.is_file() else list(target.rglob("*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for model_id in deprecated_model_ids:
                if model_id in text:
                    offenders.append(f"{path}: {model_id}")

    assert offenders == []
