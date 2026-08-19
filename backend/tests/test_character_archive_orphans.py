"""epic 框架重建人物卡归档（防复发）单元测试。

背景：epic 框架重建时，旧框架的人物卡若不被新框架引用将永久残留累积
（项目 102 实测 21→58 张）。修复引入 source/archived_at 两列：
- 扩展管线同步时标记 source='expansion' 并解除历史归档；
- epic 重建后归档 source='expansion' 且不在新名单中的卡片；
- 手动创建/历史卡片（source 为 NULL）永不被归档。

纯 sqlite 内存库，离线确定性。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.character import Character
from app.models.project import Project
from app.models.user import User
from app.services.character_parser import (
    archive_orphan_expansion_characters,
    parse_and_sync_characters,
)


CHAR_CARD_TEMPLATE = """### 【姓名】：{name}
【年龄/性别】：28/男
【故事立场】：主角方
【角色定位】：{position}
【所属势力】：天玑阁
【外貌锚点】：测试外貌
【性格锚点】：测试性格
【背景/当前处境】：测试背景
【核心动机】：测试动机
【能力与限制】：测试能力 / 限制：测试限制
【关键关系】：无
【主线绑定】：剧情职责：{duty} / 关联线索：无
---"""


def build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Project.__table__, Character.__table__],
    )
    return session_factory()


def seed_project(db):
    user = User(username="archive_user", email="archive@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    project = Project(title="归档测试项目", description="", user_id=user.id, display_no=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.id


def get_char(db, project_id, name):
    return (
        db.query(Character)
        .filter(Character.project_id == project_id, Character.name == name)
        .first()
    )


def test_sync_marks_source_and_returns_normalized_names():
    db = build_session()
    project_id = seed_project(db)
    try:
        text = CHAR_CARD_TEMPLATE.format(name="林昭", position="主角", duty="推进主线")
        result = parse_and_sync_characters(project_id, text, db)

        assert result["parsed"] == 1
        assert result["normalized_names"] == ["林昭"]

        char = get_char(db, project_id, "林昭")
        assert char is not None
        assert char.source == "expansion"
        assert char.archived_at is None
    finally:
        db.close()


def test_rebuild_archives_only_expansion_orphans():
    db = build_session()
    project_id = seed_project(db)
    try:
        # 第一轮 epic：三个扩展管线人物
        old_text = "\n\n".join(
            CHAR_CARD_TEMPLATE.format(name=name, position="配角", duty="旧框架职责")
            for name in ("林昭", "柳如烟", "陈玄机")
        )
        first = parse_and_sync_characters(project_id, old_text, db)
        assert first["created"] == 3

        # 手动创建的人物卡（source 为 NULL）
        manual = Character(project_id=project_id, name="路人甲", source=None)
        db.add(manual)
        db.commit()

        # 第二轮 epic 重建：新框架只保留林昭，新增萧铁衣
        new_text = "\n\n".join(
            CHAR_CARD_TEMPLATE.format(name=name, position="配角", duty="新框架职责")
            for name in ("林昭", "萧铁衣")
        )
        second = parse_and_sync_characters(project_id, new_text, db)
        assert second["created"] == 1
        assert second["updated"] == 1

        archive = archive_orphan_expansion_characters(
            project_id=project_id,
            keep_normalized_names=second["normalized_names"],
            db_session=db,
        )

        # 柳如烟/陈玄机（旧框架扩展卡）被归档；林昭/萧铁衣在册；路人甲（手动）不受影响
        assert sorted(archive["names"]) == ["柳如烟", "陈玄机"]
        assert get_char(db, project_id, "柳如烟").archived_at is not None
        assert get_char(db, project_id, "陈玄机").archived_at is not None
        assert get_char(db, project_id, "林昭").archived_at is None
        assert get_char(db, project_id, "萧铁衣").archived_at is None
        assert get_char(db, project_id, "路人甲").archived_at is None
    finally:
        db.close()


def test_re_reference_unarchives_and_idempotent():
    db = build_session()
    project_id = seed_project(db)
    try:
        text = CHAR_CARD_TEMPLATE.format(name="林昭", position="主角", duty="推进主线")
        parse_and_sync_characters(project_id, text, db)

        # 第三轮重建不再包含林昭 → 归档
        other_text = CHAR_CARD_TEMPLATE.format(name="新主角", position="主角", duty="新主线")
        third = parse_and_sync_characters(project_id, other_text, db)
        archive = archive_orphan_expansion_characters(
            project_id=project_id,
            keep_normalized_names=third["normalized_names"],
            db_session=db,
        )
        assert archive["names"] == ["林昭"]
        assert get_char(db, project_id, "林昭").archived_at is not None

        # 重复归档幂等（已归档卡片不重复处理）
        archive_again = archive_orphan_expansion_characters(
            project_id=project_id,
            keep_normalized_names=third["normalized_names"],
            db_session=db,
        )
        assert archive_again["archived"] == 0

        # 第四轮重新引用林昭 → 同步时解除归档
        fourth = parse_and_sync_characters(project_id, text, db)
        assert fourth["updated"] == 1
        char = get_char(db, project_id, "林昭")
        assert char.archived_at is None
        assert char.source == "expansion"
    finally:
        db.close()


def test_empty_keep_list_with_no_expansion_cards_is_safe():
    """keep 名单为空且无扩展卡时不误伤手动卡片。"""
    db = build_session()
    project_id = seed_project(db)
    try:
        db.add(Character(project_id=project_id, name="手动角色", source=None))
        db.commit()

        archive = archive_orphan_expansion_characters(
            project_id=project_id,
            keep_normalized_names=[],
            db_session=db,
        )
        assert archive["archived"] == 0
        assert get_char(db, project_id, "手动角色").archived_at is None
    finally:
        db.close()
