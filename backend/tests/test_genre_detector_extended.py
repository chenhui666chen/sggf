from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.prompt_evolution.genre_detector import GenreDetector


def test_detector_supports_science_fiction_history_and_wuxia():
    detector = GenreDetector()
    assert detector.detect("星舰驶离火星殖民地，人工智能开始计算量子跃迁。" * 4) == "科幻"
    assert detector.detect("皇帝下诏，丞相率百官入朝，史官记下这个年号。" * 4) == "历史"
    assert detector.detect("侠客踏入江湖，门派弟子拔剑，使出祖传剑法。" * 4) == "武侠"
