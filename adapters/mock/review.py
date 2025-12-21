from __future__ import annotations

from typing import Any, Dict, List


class MockReviewAdapter:
    """返回固定的通过结果，便于流水线先跑通。"""

    def check(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        return {"pass": True, "issues": []}  # type: List[Dict[str, Any]]
