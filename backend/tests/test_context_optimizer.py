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

from app.services.agents.context_optimizer import ContextOptimizer, get_context_optimizer


def test_context_optimizer_initializes_without_name_error() -> None:
    optimizer = ContextOptimizer(current_chapter=2, stage="content_creation")

    assert optimizer.current_chapter == 2
    assert optimizer.stage == "content_creation"
    assert optimizer.selected_model
    assert optimizer.target_tokens > 0


def test_get_context_optimizer_returns_configured_instance() -> None:
    optimizer = get_context_optimizer(current_chapter=12, stage="chapter_planning")

    assert isinstance(optimizer, ContextOptimizer)
    assert optimizer.current_chapter == 12
    assert optimizer.stage == "chapter_planning"
