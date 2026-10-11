"""章节编号安全测试（阶段 B WP2）。

背景：`routes_chapter.py` 此前用 `len(existing_chapters) + 1` 计算下一章编号，
软删除、编号缺口或手工删章时不等于 `MAX(chapter_number) + 1`，会导致章节号重复、
RAG 覆盖错误、人物快照选错。指南 §5.3 要求：编号用 `MAX + 1`，并增加
`(project_id, chapter_number)` 唯一约束（软删除行不参与约束）。

本测试锁定两点：
1. `resolve_chapter_number` 的 MAX+1 语义（含缺口、软删除、空项目）；
2. `Chapter` 的部分唯一索引 `uq_chapters_project_number_active`（仅约束 deleted_at IS NULL）。
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.project import Chapter
from app.services.chapter_creation import (
    ChapterNumberConflictError,
    create_project_chapter,
    resolve_chapter_number,
)
from app.utils.datetime_utils import utc_now

PROJECT_ID = 1


def _load_migration():
    """按路径加载迁移模块（alembic versions 非包，不能直接 import）。"""
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "add_chapter_project_number_unique_index.py"
    )
    spec = importlib.util.spec_from_file_location("_chapter_number_unique_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chapters_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE chapters ("
                "id INTEGER PRIMARY KEY, project_id INTEGER, "
                "chapter_number INTEGER, deleted_at TIMESTAMP NULL)"
            )
        )
    return engine


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Chapter.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _add_chapter(db, number, *, deleted=False, project_id=PROJECT_ID, content="正文内容"):
    chapter = Chapter(
        project_id=project_id,
        chapter_number=number,
        title=f"第{number}章",
        content=content,
        deleted_at=utc_now() if deleted else None,
    )
    db.add(chapter)
    db.commit()
    return chapter


# --- resolve_chapter_number：MAX+1 语义 ---


def test_next_number_uses_max_plus_one_not_count_with_gap():
    """编号缺口时取 MAX+1，而非 len+1（1,2,5 → 6，不是 4）。"""
    db = _db()
    for number in (1, 2, 5):
        _add_chapter(db, number)

    assert resolve_chapter_number(db, PROJECT_ID) == 6


def test_next_number_never_reuses_soft_deleted_number():
    """软删除最高章后，编号仍单调递增（不复用已删号，避免 RAG/快照覆盖错误）。"""
    db = _db()
    _add_chapter(db, 1)
    _add_chapter(db, 2)
    _add_chapter(db, 3, deleted=True)

    # MAX 覆盖全部行（含软删除）→ 3 + 1 = 4
    assert resolve_chapter_number(db, PROJECT_ID) == 4


def test_next_number_empty_project_returns_one():
    db = _db()
    assert resolve_chapter_number(db, PROJECT_ID) == 1


def test_next_number_scoped_per_project():
    db = _db()
    _add_chapter(db, 1, project_id=1)
    _add_chapter(db, 2, project_id=1)
    _add_chapter(db, 7, project_id=2)

    assert resolve_chapter_number(db, 1) == 3
    assert resolve_chapter_number(db, 2) == 8


# --- 部分唯一索引：仅约束 deleted_at IS NULL 的活跃行 ---


def test_unique_index_blocks_duplicate_active_number():
    """同一项目下两条活跃（未软删）章节不得共用 chapter_number。"""
    db = _db()
    _add_chapter(db, 1)

    with pytest.raises(IntegrityError):
        _add_chapter(db, 1)


def test_unique_index_allows_reuse_after_soft_delete():
    """软删除后同号可再次作为活跃章存在（部分索引只覆盖 deleted_at IS NULL）。"""
    db = _db()
    _add_chapter(db, 1)
    # 软删除既有第 1 章
    chapter = db.query(Chapter).filter(Chapter.chapter_number == 1).one()
    chapter.deleted_at = utc_now()
    db.commit()

    # 再插入一条活跃第 1 章不应冲突
    _add_chapter(db, 1)
    active = (
        db.query(Chapter)
        .filter(Chapter.chapter_number == 1, Chapter.deleted_at.is_(None))
        .count()
    )
    assert active == 1


def test_unique_index_scoped_per_project_allows_same_number():
    """不同项目的相同 chapter_number 不冲突。"""
    db = _db()
    _add_chapter(db, 1, project_id=1)
    _add_chapter(db, 1, project_id=2)

    assert db.query(Chapter).filter(Chapter.chapter_number == 1).count() == 2


# --- 迁移自检：建索引前拒绝存量活跃重复 ---


def test_migration_selfcheck_raises_on_active_duplicates():
    """存量有未软删除的重复 (project_id, chapter_number) 时，迁移必须 raise，不静默建索引。"""
    migration = _load_migration()
    engine = _chapters_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO chapters (project_id, chapter_number, deleted_at) VALUES (1, 1, NULL)")
        )
        conn.execute(
            text("INSERT INTO chapters (project_id, chapter_number, deleted_at) VALUES (1, 1, NULL)")
        )
    with engine.connect() as conn:
        with pytest.raises(RuntimeError, match="重复"):
            migration._assert_no_active_duplicates(conn)


def test_migration_selfcheck_passes_when_duplicates_are_soft_deleted():
    """重复号中至多一条活跃（其余软删除）时，自检通过。"""
    migration = _load_migration()
    engine = _chapters_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO chapters (project_id, chapter_number, deleted_at) "
                "VALUES (1, 1, '2026-01-01 00:00:00')"
            )
        )
        conn.execute(
            text("INSERT INTO chapters (project_id, chapter_number, deleted_at) VALUES (1, 1, NULL)")
        )
    with engine.connect() as conn:
        migration._assert_no_active_duplicates(conn)  # 不应抛出


# --- create_project_chapter：并发编号冲突回滚重试 + 显式重复编号冲突 ---


@pytest.fixture
def quiet_post_save(monkeypatch):
    """隔离编号/重试逻辑：屏蔽实体追踪与保存后后台任务（避免触碰外部服务/异步任务）。"""
    monkeypatch.setattr(
        "app.services.chapter_creation._track_new_chapter_entities", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "app.services.chapter_creation._start_chapter_post_save", lambda *a, **k: None
    )


def test_create_project_chapter_retries_on_auto_number_conflict(quiet_post_save, monkeypatch):
    """自动编号并发：首次撞唯一约束时回滚重读 MAX 重试一次，最终成功且不重号。

    模拟并发 loser：首次 resolve 返回已被占用的编号，触发 IntegrityError；
    重试时重读真实 MAX+1，得到未占用的编号。
    """
    db = _db()
    _add_chapter(db, 5)  # 既有活跃第 5 章

    real_resolve = resolve_chapter_number
    calls = {"n": 0}

    def fake_resolve(session, pid, requested=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return 5  # 并发 loser：首次拿到已被占用的编号
        return real_resolve(session, pid, requested)

    monkeypatch.setattr(
        "app.services.chapter_creation.resolve_chapter_number", fake_resolve
    )

    chapter = create_project_chapter(db, PROJECT_ID, content="新章正文")

    assert chapter.chapter_number == 6  # 重试后用真实 MAX+1
    assert calls["n"] == 2
    active_numbers = sorted(
        c.chapter_number
        for c in db.query(Chapter).filter(Chapter.deleted_at.is_(None)).all()
    )
    assert active_numbers == [5, 6]


def test_create_project_chapter_raises_conflict_on_duplicate_explicit_number(quiet_post_save):
    """显式指定与既有活跃章重复的编号：抛领域冲突异常（API 层映射 409），不静默改号。"""
    db = _db()
    _add_chapter(db, 3)

    with pytest.raises(ChapterNumberConflictError):
        create_project_chapter(db, PROJECT_ID, content="重复章", chapter_number=3)


def test_public_create_endpoints_map_conflict_to_409():
    """两个公共创建入口须捕获 ChapterNumberConflictError 并返回 409（不传播为 500）。"""
    backend = Path(__file__).resolve().parents[1]
    chapters_src = (backend / "app" / "api" / "v1" / "chapters.py").read_text(encoding="utf-8")
    projects_src = (backend / "app" / "api" / "v1" / "projects.py").read_text(encoding="utf-8")
    for src in (chapters_src, projects_src):
        assert "ChapterNumberConflictError" in src
        assert "HTTP_409_CONFLICT" in src
