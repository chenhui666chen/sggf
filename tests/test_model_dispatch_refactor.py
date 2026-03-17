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
