from __future__ import annotations

import random
from typing import Any, Dict, Optional


class MockLLMAdapter:
    """返回可预测的占位结果，接口形态与真实 LLM 保持一致。"""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def generate(self, prompt: str, schema: Optional[dict] = None) -> Dict[str, Any]:
        variant = self.rng.choice(
            [
                "mock response",
                "mock alt response",
                "mock structured response",
            ]
        )
        return {
            "text": f"[mock llm] {variant}",
            "meta": {
                "prompt_len": len(prompt),
                "schema_provided": schema is not None,
            },
        }
