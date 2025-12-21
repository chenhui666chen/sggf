from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from adapters.mock.image import MockImageAdapter


def _ensure_run_dir(ctx: Any) -> Path:
    base = Path("runs") / ctx.run_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def run_keyframes(ctx: Any) -> None:
    image = MockImageAdapter()
    run_dir = _ensure_run_dir(ctx)
    frames: List[Dict[str, str]] = []
    for item in ctx.payload.get("storyboard", []):
        head_path = run_dir / f"{item['shot_id']}_head.png"
        tail_path = run_dir / f"{item['shot_id']}_tail.png"
        frames.append(image.gen_frame(item["head_frame"], str(head_path)))
        frames.append(image.gen_frame(item["tail_frame"], str(tail_path)))
    ctx.payload["keyframes"] = frames


def run_midframes(ctx: Any) -> None:
    image = MockImageAdapter()
    run_dir = _ensure_run_dir(ctx)
    mids: List[Dict[str, str]] = []
    for item in ctx.payload.get("storyboard", []):
        mid_path = run_dir / f"{item['shot_id']}_mid.png"
        mids.append(image.gen_frame({"prompt": "mid", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}}, str(mid_path)))
    ctx.payload["midframes"] = mids
