from __future__ import annotations

def run(ctx: Any) -> dict:
    from pathlib import Path
    from typing import Any, Dict, List

    issues: List[Dict[str, Any]] = []

    merged_video = ctx.payload.get("merged_video")
    if not isinstance(merged_video, str) or not merged_video:
        issues.append({"category": "output", "message": "merged_video missing"})
    else:
        merged_path = Path(merged_video)
        if not merged_path.exists():
            issues.append({"category": "output", "message": "merged_video file missing", "path": merged_video})
        else:
            try:
                if merged_path.stat().st_size < 1024:
                    issues.append({"category": "output", "message": "merged_video too small", "path": merged_video})
            except Exception as exc:  # noqa: BLE001
                issues.append({"category": "output", "message": f"merged_video stat failed: {exc}"})

    result = {"pass": len(issues) == 0, "issues": issues}
    ctx.payload["audit"] = result
    return result
