from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from schemas.unified_model_spec import LLMResult


@pytest.mark.asyncio
async def test_unified_llm_client_normalizes_aliases() -> None:
    from core.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()

    with patch(
        "core.model_hub.model_hub.call",
        new=AsyncMock(
            return_value=LLMResult(
                success=True,
                model_id="deepseek-reasoner",
                content="ok",
            )
        ),
    ) as mocked_call:
        content = await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            task_type="content_draft",
            model="deepseek-r1",
        )

    assert content == "ok"
    assert mocked_call.await_args.kwargs["task_type"] == "chapter"
    assert mocked_call.await_args.kwargs["model"] == "deepseek-reasoner"


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

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        """
{
  "version": 1,
  "entries": {
    "failed-model": {
      "verification_status": "failed",
      "last_verified_at": "2026-03-21T00:00:00+00:00"
    },
    "healthy-model": {
      "verification_status": "verified",
      "last_verified_at": "2026-03-21T00:00:00+00:00"
    }
  }
}
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
