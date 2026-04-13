import os
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.api.v1 import workflow as workflow_module


class DummySession:
    def __init__(self) -> None:
        self.added = []
        self.committed = False
        self.refreshed = []
        self.rolled_back = False

    def add(self, instance) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.committed = True

    def refresh(self, instance) -> None:
        self.refreshed.append(instance)
        instance.id = 123

    def rollback(self) -> None:
        self.rolled_back = True


class CommitFailingSession(DummySession):
    def commit(self) -> None:
        raise RuntimeError("commit failed")


def test_create_generated_chapter_sets_required_fields() -> None:
    db = DummySession()
    content = "第一章内容\n第二段内容"

    chapter = workflow_module._create_generated_chapter(
        db,
        project_id=2,
        chapter_number=5,
        title="第5章 测试标题",
        content=content,
    )

    assert chapter.id == 123
    assert chapter.status == "draft"
    assert chapter.word_count == len(content)
    assert chapter.project_id == 2
    assert chapter.chapter_number == 5
    assert db.added == [chapter]
    assert db.committed is True
    assert db.refreshed == [chapter]


def test_create_generated_chapter_rolls_back_when_commit_fails() -> None:
    db = CommitFailingSession()

    with pytest.raises(RuntimeError, match="commit failed"):
        workflow_module._create_generated_chapter(
            db,
            project_id=9,
            chapter_number=2,
            title="第2章 石屋·逆流盏",
            content="测试正文",
        )

    assert db.rolled_back is True
    assert db.refreshed == []


def test_extract_iteration_review_score_supports_markdown_review_format() -> None:
    review_text = """
## 网文质量评审报告

**综合评分**：9.2/10分

其余评审内容略。
""".strip()

    score = workflow_module._extract_iteration_review_score(review_text)

    assert score == 9.2


def test_extract_iteration_review_score_returns_zero_when_missing_score() -> None:
    assert workflow_module._extract_iteration_review_score("仅有建议，没有分数") == 0.0
