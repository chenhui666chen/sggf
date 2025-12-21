from __future__ import annotations

from pathlib import Path
from typing import Any, List

from adapters.mock.video import MockVideoAdapter


def run_video(ctx: Any) -> None:
    video = MockVideoAdapter()
    run_dir = Path("runs") / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    clips: List[dict] = []
    storyboard = ctx.payload.get("storyboard", [])
    for item in storyboard:
        head = run_dir / f"{item['shot_id']}_head.png"
        tail = run_dir / f"{item['shot_id']}_tail.png"
        out = run_dir / f"{item['shot_id']}.mp4"
        clip = video.gen_clip([str(head), str(tail)], duration=item.get("duration_s", 3.0), out_path=str(out))
        clips.append(clip)
    ctx.payload["video_clips"] = clips
