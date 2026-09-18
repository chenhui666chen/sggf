"""迭代过程落库测试。

背景：迭代优化的中间稿与每轮复评报告只存在于内存和日志里，章节一旦保存，
"第1轮改成什么样、为什么被丢弃、终稿评审说了什么"就再也查不到，复盘只能重跑工作流。
本章稿版本写入 chapter_revisions（前端版本历史已消费该表），评审报告写入 reviews。
"""

import re

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.project import ChapterRevision
from app.models.review import Review
from app.services.workflow_revision_store import record_iteration_history


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ChapterRevision.__table__.create(engine)
    Review.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _rounds():
    return [
        {
            "round": 1,
            "content": "第一轮修订稿" * 20,
            "review": "综合评分：7.5/10分\n\n## 剩余关键问题\n1. 巡捕房搜掠段信息倾倒",
            "score": 7.5,
            "failure_codes": ["PACE_DRAG"],
            "adopted": True,
        },
        {
            "round": 2,
            "content": "第二轮修订稿" * 20,
            "review": "综合评分：8.6/10分\n\n## 剩余关键问题\n无",
            "score": 8.6,
            "failure_codes": [],
            "adopted": True,
        },
    ]


def test_records_initial_draft_and_every_round_revision():
    db = _db()

    record_iteration_history(
        db,
        chapter_id=101,
        initial_content="初稿正文" * 20,
        initial_review="综合评分：6.2/10分",
        initial_score=6.2,
        rounds=_rounds(),
        final_review="【终稿编辑评审】综合评分：8.6/10分",
        final_score=8.6,
    )

    revisions = db.query(ChapterRevision).order_by(ChapterRevision.id).all()
    assert [revision.content for revision in revisions] == [
        "初稿正文" * 20,
        "第一轮修订稿" * 20,
        "第二轮修订稿" * 20,
    ]
    assert revisions[0].revision_note.startswith("迭代初稿")
    assert "评分6.2/10" in revisions[0].revision_note
    assert revisions[1].revision_note.startswith("迭代第1轮")
    assert "PACE_DRAG" in revisions[1].revision_note
    assert "无剩余失败码" in revisions[2].revision_note
    assert revisions[1].word_count == len(re.sub(r"\s", "", "第一轮修订稿" * 20))


def test_review_rows_keep_full_report_and_stage_tag():
    db = _db()

    record_iteration_history(
        db,
        chapter_id=101,
        initial_content="初稿正文" * 20,
        initial_review="综合评分：6.2/10分",
        initial_score=6.2,
        rounds=_rounds(),
        final_review="终稿仍偏长，建议压缩结尾",
        final_score=8.6,
    )

    reviews = db.query(Review).order_by(Review.id).all()
    assert len(reviews) == 4
    assert "综合评分：7.5/10分" in reviews[1].feedback
    assert reviews[0].feedback.startswith("【初评】")
    assert reviews[1].feedback.startswith("【迭代第1轮复评】")
    assert reviews[3].feedback.startswith("【终稿评审】")
    # overall_score 列为整数，四舍五入保留可排序的分值
    assert [review.overall_score for review in reviews] == [6, 8, 9, 9]
    # 未解决问题单独可检索，不必再解析整篇报告
    assert "巡捕房搜掠段信息倾倒" in reviews[1].suggestions


def test_rejected_round_revision_is_marked_not_adopted():
    db = _db()
    rounds = [_rounds()[0]]
    rounds[0]["adopted"] = False

    record_iteration_history(
        db,
        chapter_id=101,
        initial_content="初稿正文" * 20,
        initial_review="综合评分：7.9/10分",
        initial_score=7.9,
        rounds=rounds,
    )

    note = db.query(ChapterRevision).order_by(ChapterRevision.id).all()[1].revision_note
    assert "本轮未采用" in note


def test_blank_round_contributes_neither_revision_nor_review():
    db = _db()

    record_iteration_history(
        db,
        chapter_id=101,
        initial_content="初稿正文" * 20,
        rounds=[
            {"round": 1, "content": "   ", "review": "综合评分：9.2/10分", "score": 9.2,
             "failure_codes": [], "adopted": False},
        ],
    )

    assert db.query(ChapterRevision).count() == 1
    assert db.query(Review).count() == 0


def test_duplicate_final_review_not_recorded_twice():
    db = _db()

    record_iteration_history(
        db,
        chapter_id=101,
        initial_content="初稿正文" * 20,
        initial_review="综合评分：9.1/10分",
        initial_score=9.1,
        rounds=[],
        # 跳过迭代的场景：终稿评审就是初评，不得重复落库
        final_review="综合评分：9.1/10分",
        final_score=9.1,
    )

    reviews = db.query(Review).order_by(Review.id).all()
    assert len(reviews) == 1
    assert reviews[0].feedback.startswith("【初评】")


def test_store_failure_does_not_raise():
    class _BrokenSession:
        def add(self, *_args):
            raise RuntimeError("表不存在")

        def commit(self):
            raise RuntimeError("表不存在")

        def rollback(self):
            raise RuntimeError("连接已断开")

    stats = record_iteration_history(
        _BrokenSession(),
        chapter_id=1,
        initial_content="初稿",
        initial_review="评审",
        rounds=[],
    )

    assert stats == {"revisions": 0, "reviews": 0}
