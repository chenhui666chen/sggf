from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


class MockImageAdapter:
    """生成占位图片文件，携带最小元数据。"""

    def gen_frame(self, frame_spec: Dict[str, Any], out_path: str) -> Dict[str, Any]:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 占位：实际渲染前先写入简单标记
        path.write_bytes(b"MOCK_IMAGE")
        return {
            "path": str(path),
            "ratio": frame_spec.get("ratio", "16:9"),
            "spec": frame_spec,
        }
