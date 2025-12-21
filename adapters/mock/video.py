from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List


def _build_ffmpeg_placeholder(duration: float, label: str, out_path: str) -> List[str]:
    return [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        f"color=c=0x4b5bef:s=1280x720:d={duration}",
        "-vf",
        f"drawtext=text='{label}':fontcolor=white:fontsize=48:x=(w-tw)/2:y=(h-th)/2",
        out_path,
    ]


class MockVideoAdapter:
    """织梦映心 mock：生成占位 MP4，写入首尾帧元数据。"""

    def gen_clip(self, frames: List[str], duration: float, out_path: str, label: str = "DreamWeave Mock") -> Dict[str, Any]:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = _build_ffmpeg_placeholder(duration, label, str(out))
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 无 ffmpeg 时 fallback：写入占位内容，保持流程可用
            out.write_bytes(b"MOCK_VIDEO")
        return {
            "path": str(out),
            "duration": duration,
            "head": frames[0] if frames else None,
            "tail": frames[-1] if frames else None,
        }
