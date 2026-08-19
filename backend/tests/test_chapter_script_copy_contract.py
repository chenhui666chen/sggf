"""复制合同持久化测试（GUIDE §2.1，验收 25）。

覆盖：
- 复制后 source_script_hash 与源一致、provenance 齐全、script_status 保持 approved
- 幂等：重复复制（同源）跳过不覆盖
- 源/目标缺失拒绝
"""

import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudio,
)
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook.chapter_script_copy_service import (  # noqa: E402
    copy_approved_script,
)

_TABLES = [
    User.__table__,
    Project.__table__,
    Chapter.__table__,
    AudiobookProject.__table__,
    ChapterAudio.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=_TABLES)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _seed_two_batches(db, tag: str):
    """创建源批次（含已审批剧本）与目标批次（同一章节）。"""
    user = User(username=f"user_{tag}", email=f"{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"proj_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()

    source_batch = AudiobookProject(project_id=project.id, engine_mode="legacy_stems")
    db.add(source_batch)
    db.flush()
    source_audio = ChapterAudio(
        audiobook_project_id=source_batch.id,
        chapter_id=chapter.id,
        script_json=json.dumps(
            [{"index": 0, "text": "第一段"}, {"index": 1, "text": "第二段"}],
            ensure_ascii=False,
        ),
        script_review_json=json.dumps({"verdict": "approved"}),
        script_review_version="rv-1",
        script_status="approved",
    )
    db.add(source_audio)
    db.flush()

    target_batch = AudiobookProject(project_id=project.id, engine_mode="seed_scene")
    db.add(target_batch)
    db.flush()
    target_audio = ChapterAudio(
        audiobook_project_id=target_batch.id,
        chapter_id=chapter.id,
        script_status="pending",
    )
    db.add(target_audio)
    db.flush()
    db.commit()
    return {
        "source_audio": source_audio.id,
        "source_batch": source_batch.id,
        "target_audio": target_audio.id,
        "target_batch": target_batch.id,
        "chapter": chapter.id,
    }


def test_copy_approved_script_persists_source_contract(db_factory):
    """复制后：hash 与源一致 + provenance 齐全 + script_status 保持 approved。"""
    db = db_factory()
    scope = _seed_two_batches(db, "copy1")

    result = copy_approved_script(
        db,
        source_audiobook_project_id=scope["source_batch"],
        source_chapter_audio_id=scope["source_audio"],
        target_audiobook_project_id=scope["target_batch"],
        target_chapter_id=scope["chapter"],
    )
    assert result["copied"] is True
    assert result["reason"] == "copied"
    assert result["source_script_hash"]

    target = db.query(ChapterAudio).filter(ChapterAudio.id == scope["target_audio"]).first()
    source = db.query(ChapterAudio).filter(ChapterAudio.id == scope["source_audio"]).first()

    # 复制合同：hash 与源一致
    assert target.source_script_hash == result["source_script_hash"]
    assert target.script_json == source.script_json
    # provenance 齐全
    assert target.source_audiobook_project_id == scope["source_batch"]
    assert target.source_chapter_audio_id == scope["source_audio"]
    assert target.source_script_review_version == "rv-1"
    provenance = target.source_provenance_json
    assert provenance["source_chapter_audio_id"] == scope["source_audio"]
    assert provenance["copy_contract_version"] == 1
    # 复制后保持 approved（可无阻碍执行 audio_from_scripts）
    assert target.script_status == "approved"
    db.close()


def test_copy_approved_script_idempotent(db_factory):
    """幂等：重复复制（同源）跳过不覆盖。"""
    db = db_factory()
    scope = _seed_two_batches(db, "copy2")

    first = copy_approved_script(
        db,
        source_audiobook_project_id=scope["source_batch"],
        source_chapter_audio_id=scope["source_audio"],
        target_audiobook_project_id=scope["target_batch"],
        target_chapter_id=scope["chapter"],
    )
    second = copy_approved_script(
        db,
        source_audiobook_project_id=scope["source_batch"],
        source_chapter_audio_id=scope["source_audio"],
        target_audiobook_project_id=scope["target_batch"],
        target_chapter_id=scope["chapter"],
    )
    assert first["copied"] is True
    assert second["copied"] is False
    assert second["reason"] == "already_copied"
    db.close()


def test_copy_rejects_missing_source_or_target(db_factory):
    """源/目标缺失拒绝。"""
    db = db_factory()
    scope = _seed_two_batches(db, "copy3")

    missing_source = copy_approved_script(
        db,
        source_audiobook_project_id=scope["source_batch"],
        source_chapter_audio_id=999999,
        target_audiobook_project_id=scope["target_batch"],
        target_chapter_id=scope["chapter"],
    )
    assert missing_source["copied"] is False
    assert missing_source["reason"] == "source_chapter_audio_not_found"

    missing_target = copy_approved_script(
        db,
        source_audiobook_project_id=scope["source_batch"],
        source_chapter_audio_id=scope["source_audio"],
        target_audiobook_project_id=scope["target_batch"],
        target_chapter_id=999999,
    )
    assert missing_target["copied"] is False
    assert missing_target["reason"] == "target_chapter_audio_not_found"
    db.close()
