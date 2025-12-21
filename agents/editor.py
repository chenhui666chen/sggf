from __future__ import annotations

from pathlib import Path
from typing import Any, List


def run(ctx: Any) -> None:
    run_dir = Path("runs") / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    merged = run_dir / "merged.mp4"
    merged.write_bytes(b"MOCK_MERGED_VIDEO")
    ctx.payload["merged_video"] = str(merged)
