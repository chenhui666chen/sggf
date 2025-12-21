from __future__ import annotations

from typing import Any, List

from adapters.mock.llm import MockLLMAdapter


def run(ctx: Any) -> None:
    llm = MockLLMAdapter()
    ctx.payload["storyboard"] = [
        {
            "scene_id": "S1",
            "shot_id": f"S1-{i}",
            "desc": llm.generate("shot", None)["text"],
            "duration_s": 3.0,
            "head_frame": {"prompt": "head", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
            "tail_frame": {"prompt": "tail", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
        }
        for i in range(1, 3)
    ]  # type: List[dict]
