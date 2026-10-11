"""有界章节运行时窗口测试（阶段 B WP1）。

背景：`routes_chapter.py` 此前用一条无 LIMIT、无范围过滤、含 `content` 的全量查询读取
项目所有章节，再在 Python 侧构造 `previous_chapters_payload`（每章含全文）与
`"\n\n".join(summaries)` 全量历史摘要中间串，导致运行时内存/payload 随章节数 O(N) 膨胀
（阶段 A 实测 1000 章 payload 8.47 MB）。指南 §5.3/§5.4 要求：列裁剪 + 范围过滤 + LIMIT，
上一章全文独立有界读取，禁止拼接全量历史摘要中间串。

本测试锁定 `load_chapter_runtime_window` 的有界性与 `build_bounded_summary_navigation` 的上限，
并以源码接线断言保证 worker 入口已切换到有界窗口、不再保留全量查询与 `len()+1` 编号。
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.workflow.helpers import (
    CHAPTER_NAV_WINDOW,
    CHAPTER_RECENT_FULL_CAP,
    ChapterRuntimeWindow,
    build_bounded_summary_navigation,
    load_chapter_runtime_window,
)
from app.models.project import Chapter

ROUTES_CHAPTER = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "api"
    / "v1"
    / "workflow"
    / "routes_chapter.py"
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Chapter.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _seed(db, project_id, numbers, *, deleted=False, content_fn=None):
    for number in numbers:
        content = content_fn(number) if content_fn else f"第{number}章正文"
        db.add(
            Chapter(
                project_id=project_id,
                chapter_number=number,
                title=f"第{number}章",
                content=content,
            )
        )
    db.commit()


def _seed_soft_deleted(db, project_id, numbers):
    from app.utils.datetime_utils import utc_now

    for number in numbers:
        db.add(
            Chapter(
                project_id=project_id,
                chapter_number=number,
                title=f"第{number}章",
                content=f"第{number}章正文",
                deleted_at=utc_now(),
            )
        )
    db.commit()


# --- 有界读取 ---


def test_window_bounds_reads_for_thousand_chapters():
    """1000 章项目：窗口行数与 DB 读取行数有固定上限，不随章节数线性增长。"""
    db = _db()
    _seed(db, 1, range(1, 1001))

    window = load_chapter_runtime_window(db, 1)

    assert isinstance(window, ChapterRuntimeWindow)
    assert len(window.chapters) <= CHAPTER_NAV_WINDOW
    assert window.db_rows_read <= CHAPTER_NAV_WINDOW + CHAPTER_RECENT_FULL_CAP
    assert window.has_active_chapters is True
    assert window.max_active_chapter_number == 1000
    assert window.next_chapter_number == 1001


def test_content_only_populated_for_recent_window():
    """只有最近 RECENT_FULL_CAP 章携带 content，更早的导航行 content 为空。"""
    db = _db()
    _seed(db, 1, range(1, 101), content_fn=lambda n: f"CONTENT-{n}-" + "x" * 200)

    window = load_chapter_runtime_window(db, 1)

    with_content = [row for row in window.chapters if row[3]]
    assert len(with_content) <= CHAPTER_RECENT_FULL_CAP
    # 携带 content 的必须是编号最大的近期章
    numbers_with_content = sorted(row[1] for row in with_content)
    assert numbers_with_content == list(range(101 - len(with_content), 101))
    # 窗口内最早的导航行不含全文
    assert window.chapters[0][3] == ""


def test_previous_full_text_from_most_recent_chapter():
    """上一章全文/结尾来自编号最大的活跃章，且结尾截断到 500 字符。"""
    db = _db()
    _seed(db, 1, [1, 2, 3], content_fn=lambda n: chr(64 + n) * 600)

    window = load_chapter_runtime_window(db, 1)

    assert window.previous_chapter_content == "C" * 600
    assert window.previous_ending == "C" * 500


def test_empty_project_window():
    db = _db()

    window = load_chapter_runtime_window(db, 1)

    assert window.has_active_chapters is False
    assert window.chapters == []
    assert window.previous_ending == ""
    assert window.previous_chapter_content == ""
    assert window.next_chapter_number == 1


def test_soft_deleted_excluded_from_window_but_counts_for_numbering():
    """软删除章不进入窗口，但编号 MAX 覆盖全部行（不复用已删号）。"""
    db = _db()
    _seed(db, 1, [1, 2])
    _seed_soft_deleted(db, 1, [3])

    window = load_chapter_runtime_window(db, 1)

    assert [row[1] for row in window.chapters] == [1, 2]
    assert window.max_active_chapter_number == 2
    assert window.next_chapter_number == 4


def test_window_scoped_per_project():
    db = _db()
    _seed(db, 1, [1, 2, 3])
    _seed(db, 2, [1, 2])

    window = load_chapter_runtime_window(db, 2)

    assert [row[1] for row in window.chapters] == [1, 2]
    assert window.next_chapter_number == 3


# --- has_chapter_history：区分“无活跃章节”与“从未有章节历史”（修复 WP2 软删语义）---


def test_all_soft_deleted_has_history_but_no_active_chapters():
    """全部章节软删除：无活跃章节但仍有章节历史，编号为 MAX+1（不回到 1）。

    该场景下路由不得按“第1章初始化”重置（否则重置文案与实际生成编号矛盾）。
    """
    db = _db()
    _seed_soft_deleted(db, 1, [1, 2, 3])

    window = load_chapter_runtime_window(db, 1)

    assert window.has_active_chapters is False
    assert window.has_chapter_history is True
    assert window.chapters == []
    assert window.next_chapter_number == 4


def test_empty_project_has_no_chapter_history():
    """从未存在任何章节：既无活跃章节也无历史，下一章为第 1 章（可按第1章初始化）。"""
    db = _db()

    window = load_chapter_runtime_window(db, 1)

    assert window.has_active_chapters is False
    assert window.has_chapter_history is False
    assert window.next_chapter_number == 1


def test_active_project_has_chapter_history():
    db = _db()
    _seed(db, 1, [1, 2])

    window = load_chapter_runtime_window(db, 1)

    assert window.has_active_chapters is True
    assert window.has_chapter_history is True


# --- 有界摘要导航串 ---


def test_bounded_summary_navigation_caps_length_and_keeps_recent():
    """导航串受固定字符上限约束，超限时保留最近章节、裁掉最早章节。"""
    summaries = [f"第{n}章:" + "梗" * 500 for n in range(1, 101)]

    result = build_bounded_summary_navigation(summaries, max_chars=3000)

    assert len(result) <= 3000
    # 最近一章（第100章）必须保留
    assert "第100章" in result
    # 最早章节被裁掉
    assert "第1章:" not in result


def test_bounded_summary_navigation_joins_all_when_under_cap():
    summaries = ["第1章:甲", "第2章:乙"]

    result = build_bounded_summary_navigation(summaries, max_chars=3000)

    assert result == "第1章:甲\n\n第2章:乙"


# --- 源码接线断言 ---


def test_worker_uses_bounded_window_and_drops_full_scan():
    source = ROUTES_CHAPTER.read_text(encoding="utf-8")

    # 已切换到有界窗口 loader
    assert "load_chapter_runtime_window(" in source
    # 不再用 len(existing_chapters) + 1 计算编号
    assert "len(existing_chapters) + 1" not in source
    # 不再保留无 LIMIT 的全量 content 查询（旧查询特征：SELECT 同时含 content 且 ORDER BY chapter_number ASC 无 LIMIT）
    assert "SELECT id, chapter_number, title, content, summary" not in source
    # 重置判据用 has_chapter_history（含软删历史），不再用 not existing_chapters（仅活跃）
    assert "has_chapter_history" in source
    assert "if not existing_chapters:" not in source
