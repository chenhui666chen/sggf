from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_normalize_state_text_collapses_whitespace() -> None:
    from pipeline.autoqc_pkg._utils import _normalize_state_text

    assert _normalize_state_text("  door   open\nlight on  ") == "door open light on"


def test_normalize_state_text_extracts_dict_text_fields() -> None:
    from pipeline.autoqc_pkg._utils import _normalize_state_text

    assert _normalize_state_text({"description": "  holding a cup  "}) == "holding a cup"


def test_normalize_state_text_joins_list_values() -> None:
    from pipeline.autoqc_pkg._utils import _normalize_state_text

    assert _normalize_state_text([" standing ", {"text": "  facing left"}]) == "standing facing left"


def test_autoqc_package_imports_with_split_modules() -> None:
    from pipeline import autoqc

    assert callable(autoqc.run)
