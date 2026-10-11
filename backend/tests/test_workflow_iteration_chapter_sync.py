"""阶段级迭代终稿覆盖当前最新一章。

背景：评审报告弹窗「保存并继续」触发的是阶段级 iteration，历史实现只把结果写进
`project_settings.final_version`，`chapters` 表里的章节正文始终停留在上一版，用户
看到「改完了但没覆盖」。本模块验证迭代终稿会原地覆盖当前最新一章，并在覆盖前把
旧正文留档到 `chapter_revisions`，保证可回溯。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.project import Chapter, ChapterRevision
from app.api.v1.workflow.helpers import (
    apply_iteration_result_to_latest_chapter,
    resolve_current_chapter_number,
)


@pytest.fixture(autouse=True)
def _block_background_post_save(monkeypatch):
    """默认拦掉后台后处理线程，避免单测真的去连库跑实体提取。"""
    import app.services.chapter_post_save as chapter_post_save_module

    monkeypatch.setattr(
        chapter_post_save_module,
        "start_chapter_post_save_task",
        lambda **kwargs: None,
    )


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Chapter.__table__.create(engine)
    ChapterRevision.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _seed_chapter(db, *, number: int, content: str, project_id: int = 145) -> Chapter:
    chapter = Chapter(
        project_id=project_id,
        chapter_number=number,
        title=f"第{number}章",
        content=content,
        status="draft",
        word_count=len(content),
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def test_overwrites_latest_chapter_and_archives_previous_content():
    db = _db()
    _seed_chapter(db, number=1, content="第一章旧正文")
    latest = _seed_chapter(db, number=2, content="第二章旧正文")

    result = apply_iteration_result_to_latest_chapter(
        db, project_id=145, content="第二章迭代终稿", revision_note="迭代终稿覆盖"
    )

    assert result["chapter_id"] == latest.id
    assert result["chapter_number"] == 2
    assert result["updated"] is True

    db.refresh(latest)
    assert latest.content == "第二章迭代终稿"
    assert latest.word_count == len("第二章迭代终稿")

    archived = db.query(ChapterRevision).filter(ChapterRevision.chapter_id == latest.id).all()
    assert [item.content for item in archived] == ["第二章旧正文"]
    assert archived[0].revision_note == "迭代终稿覆盖"

    first_chapter = db.query(Chapter).filter(Chapter.chapter_number == 1).one()
    assert first_chapter.content == "第一章旧正文"


def test_resolve_current_chapter_number_returns_latest_chapter():
    db = _db()
    _seed_chapter(db, number=1, content="第一章")
    _seed_chapter(db, number=3, content="第三章")

    assert resolve_current_chapter_number(db, 145) == 3


def test_resolve_current_chapter_number_defaults_to_first_chapter():
    assert resolve_current_chapter_number(_db(), 145) == 1


def test_resolve_current_chapter_number_ignores_other_projects():
    db = _db()
    _seed_chapter(db, number=5, content="别的项目", project_id=999)

    assert resolve_current_chapter_number(db, 145) == 1


def test_no_chapter_means_nothing_to_overwrite():
    db = _db()

    assert apply_iteration_result_to_latest_chapter(db, project_id=145, content="迭代终稿") is None
    assert db.query(ChapterRevision).count() == 0


def test_blank_iteration_result_keeps_chapter_untouched():
    db = _db()
    chapter = _seed_chapter(db, number=1, content="原有正文")

    assert apply_iteration_result_to_latest_chapter(db, project_id=145, content="   ") is None

    db.refresh(chapter)
    assert chapter.content == "原有正文"
    assert db.query(ChapterRevision).count() == 0


def test_identical_content_does_not_create_duplicate_revision():
    db = _db()
    chapter = _seed_chapter(db, number=1, content="同一份正文")

    result = apply_iteration_result_to_latest_chapter(db, project_id=145, content="同一份正文")

    assert result["updated"] is False
    assert db.query(ChapterRevision).count() == 0
    db.refresh(chapter)
    assert chapter.content == "同一份正文"


def test_soft_deleted_chapter_is_not_overwritten():
    import datetime

    db = _db()
    chapter = _seed_chapter(db, number=1, content="已删除章节正文")
    chapter.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()

    assert apply_iteration_result_to_latest_chapter(db, project_id=145, content="迭代终稿") is None

    db.refresh(chapter)
    assert chapter.content == "已删除章节正文"


def test_overwrite_triggers_post_save_refresh(monkeypatch):
    import app.services.chapter_post_save as chapter_post_save_module

    started = []
    monkeypatch.setattr(
        chapter_post_save_module,
        "start_chapter_post_save_task",
        lambda **kwargs: started.append(kwargs),
    )

    db = _db()
    _seed_chapter(db, number=3, content="第三章旧正文")

    apply_iteration_result_to_latest_chapter(db, project_id=145, content="第三章迭代终稿")

    assert len(started) == 1
    assert started[0]["chapter_number"] == 3
    assert started[0]["chapter_content"] == "第三章迭代终稿"
    assert started[0]["project_id"] == 145
