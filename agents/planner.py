from __future__ import annotations

from typing import Any

from adapters.mock.llm import MockLLMAdapter


def run(ctx: Any) -> None:
    llm = MockLLMAdapter()
    ctx.payload["plan"] = llm.generate("plan story", schema=None)
