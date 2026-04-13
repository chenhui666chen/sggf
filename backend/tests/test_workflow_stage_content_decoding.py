import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.services import workflow_context_builder as builder_module


def test_decode_storage_text_unwraps_json_string() -> None:
    wrapped = "\"### 【姓名】：凌无痕\\n【角色定位】：主角\""

    result = builder_module._decode_storage_text(wrapped, pretty_json=True)

    assert result == "### 【姓名】：凌无痕\n【角色定位】：主角"


def test_decode_storage_text_keeps_plain_markdown_quotes() -> None:
    plain_markdown = "\"quoted heading\"\n\n## 正文"

    result = builder_module._decode_storage_text(plain_markdown, pretty_json=True)

    assert result == plain_markdown
