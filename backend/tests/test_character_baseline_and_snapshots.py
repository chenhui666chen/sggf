"""人物基线字段持久化与章节级动态状态快照（P2）单元测试。

背景：人物防扁平化改造第二阶段——
- characters 表新增基线列（personality/worldview/motivation/limitation/growth_direction），
  由 sync_parsed_characters_to_db 按非空优先策略同步；
- 新建 character_state_snapshots 表保存章节级动态状态，
  同角色同章节唯一、重复保存幂等，且绝不写回基线列。

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
from app.models.character import Character, CharacterStateSnapshot
from app.models.project import Project
from app.models.user import User
from app.services.character_parser import parse_and_sync_characters
from app.services.character_state_snapshot import (
    get_character_state_snapshots,
    save_character_state_snapshot,
)


CHAR_CARD_TEMPLATE = """### 【姓名】：{name}
【年龄/性别】：28/男
【故事立场】：主角方
【角色定位】：主角
【所属势力】：天玑阁
【性格特点】：{personality}
【世界观/价值观立场】：{worldview}
【核心动机】：{motivation}
【弱点/缺陷】：{limitation}
【成长方向】：{growth}
【关键关系】：无
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
        tables=[
            User.__table__,
            Project.__table__,
            Character.__table__,
            CharacterStateSnapshot.__table__,
        ],
    )
    return session_factory()


def seed_project(db):
    user = User(username="baseline_user", email="baseline@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    project = Project(title="基线测试项目", description="", user_id=user.id, display_no=1)
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


def test_sync_creates_character_with_baseline_fields():
    db = build_session()
    project_id = seed_project(db)
    try:
        text = CHAR_CARD_TEMPLATE.format(
            name="林昭",
            personality="冷静缜密，谋定后动",
            worldview="重承诺胜过个人利益",
            motivation="夺回家族传承",
            limitation="不能暴露真名",
            growth="从复仇者走向守护者",
        )
        result = parse_and_sync_characters(project_id, text, db)

        assert result["parsed"] == 1
        char = get_char(db, project_id, "林昭")
        assert char is not None
        assert char.personality == "冷静缜密，谋定后动"
        assert char.worldview == "重承诺胜过个人利益"
        assert char.motivation == "夺回家族传承"
        assert char.limitation == "不能暴露真名"
        assert char.growth_direction == "从复仇者走向守护者"
        # profile 完整档案仍然保留（回退能力不受影响）
        assert char.profile and "性格：冷静缜密，谋定后动" in char.profile
    finally:
        db.close()


def test_sync_updates_baseline_with_non_empty_precedence():
    db = build_session()
    project_id = seed_project(db)
    try:
        first_text = CHAR_CARD_TEMPLATE.format(
            name="林昭",
            personality="冷静缜密",
            worldview="重承诺",
            motivation="夺回家族传承",
            limitation="不能暴露真名",
            growth="走向守护者",
        )
        parse_and_sync_characters(project_id, first_text, db)

        # 第二轮同步：性格/动机更新，弱点/成长方向缺失（旧卡没有这些标签）
        second_text = (
            "### 【姓名】：林昭\n"
            "【故事立场】：主角方\n"
            "【角色定位】：主角\n"
            "【性格特点】：暴烈冲动，以力破局\n"
            "【核心动机】：查明灭门真凶\n"
        )
        parse_and_sync_characters(project_id, second_text, db)

        char = get_char(db, project_id, "林昭")
        # 非空新值覆盖旧值
        assert char.personality == "暴烈冲动，以力破局"
        assert char.motivation == "查明灭门真凶"
        # 空解析不覆盖已有值（非空优先）
        assert char.worldview == "重承诺"
        assert char.limitation == "不能暴露真名"
        assert char.growth_direction == "走向守护者"
    finally:
        db.close()


def test_legacy_character_without_baseline_fields_keeps_profile():
    db = build_session()
    project_id = seed_project(db)
    try:
        # 旧项目角色：只有 profile，没有基线字段
        legacy = Character(
            project_id=project_id,
            name="旧角色",
            profile="【角色定位】旧档案\n【核心动机】旧动机",
        )
        db.add(legacy)
        db.commit()

        # 空字段同步（角色卡无基线标签）：不伪造基线、不破坏 profile 回退
        sync_text = (
            "### 【姓名】：旧角色\n"
            "【故事立场】：中立方\n"
            "【角色定位】：情报商\n"
        )
        parse_and_sync_characters(project_id, sync_text, db)

        char = get_char(db, project_id, "旧角色")
        assert char is not None
        # 基线字段保持 None（回退到 profile），不凭空伪造
        assert char.personality is None
        assert char.worldview is None
        assert char.motivation is None
        assert char.limitation is None
        assert char.growth_direction is None
        # profile 回退能力保留：同步后仍是非空完整档案
        assert char.profile and "情报商" in char.profile
        assert char.role_position == "情报商"
    finally:
        db.close()


def test_save_character_state_snapshot_is_idempotent():
    db = build_session()
    project_id = seed_project(db)
    try:
        char = Character(project_id=project_id, name="林昭", motivation="夺回家族传承")
        db.add(char)
        db.commit()
        db.refresh(char)

        save_character_state_snapshot(
            db,
            project_id=project_id,
            character_id=char.id,
            chapter_id=17,
            current_motivation="先取信苏晚晴",
            current_belief="偏殿里有人见过假印",
            emotional_state="克制中的紧绷",
            relationship_state={"苏晚晴": "合作中试探"},
            known_information="假印不止一枚",
            state_changes=[{"field": "motivation", "from": "夺回家族传承", "to": "先取信苏晚晴"}],
            evidence_text="林昭压低了声音：“先取信她，再谈传承。”",
        )
        save_character_state_snapshot(
            db,
            project_id=project_id,
            character_id=char.id,
            chapter_id=17,
            current_motivation="拿到第二枚假印",
            current_belief="偏殿里有人见过假印",
            emotional_state="决意",
            relationship_state={"苏晚晴": "初步互信"},
            known_information="假印不止一枚；黑市密账存在",
            state_changes=[{"field": "motivation", "from": "先取信苏晚晴", "to": "拿到第二枚假印"}],
            evidence_text="林昭收起密账：“下一步，找第二枚。”",
        )

        snapshots = get_character_state_snapshots(db, project_id, char.id)
        assert len(snapshots) == 1  # 同角色同章节幂等，不生成重复快照
        assert snapshots[0].current_motivation == "拿到第二枚假印"
        assert snapshots[0].chapter_id == 17
    finally:
        db.close()


def test_snapshot_does_not_touch_character_baseline():
    db = build_session()
    project_id = seed_project(db)
    try:
        char = Character(
            project_id=project_id,
            name="林昭",
            motivation="夺回家族传承",
            personality="冷静缜密",
            worldview="重承诺",
        )
        db.add(char)
        db.commit()
        db.refresh(char)

        save_character_state_snapshot(
            db,
            project_id=project_id,
            character_id=char.id,
            chapter_id=18,
            current_motivation="放弃传承换情报",
            current_belief="承诺可以被交易",
            relationship_state={},
        )

        db.refresh(char)
        # 动态状态绝不写回基线
        assert char.motivation == "夺回家族传承"
        assert char.personality == "冷静缜密"
        assert char.worldview == "重承诺"
    finally:
        db.close()


def test_sync_persists_speech_style_to_db():
    db = build_session()
    project_id = seed_project(db)
    try:
        text = (
            "### 【姓名】：林昭\n"
            "【故事立场】：主角方\n"
            "【角色定位】：主角\n"
            "【说话风格】：语气克制，短句为主；自称“在下”；回避：感叹号\n"
        )
        parse_and_sync_characters(project_id, text, db)

        char = get_char(db, project_id, "林昭")
        assert char.speech_style is not None
        assert "在下" in char.speech_style

        # 非空优先：第二次同步缺失说话风格时不覆盖已有值
        parse_and_sync_characters(
            project_id,
            "### 【姓名】：林昭\n【角色定位】：主角\n",
            db,
        )
        char = get_char(db, project_id, "林昭")
        assert char.speech_style is not None
        assert "在下" in char.speech_style
    finally:
        db.close()


def test_snapshots_ordered_by_chapter_for_state_restore():
    db = build_session()
    project_id = seed_project(db)
    try:
        char = Character(project_id=project_id, name="林昭")
        db.add(char)
        db.commit()
        db.refresh(char)

        for chapter_id, motivation in ((17, "先取信苏晚晴"), (18, "拿到第二枚假印"), (19, "直取幕后黑手")):
            save_character_state_snapshot(
                db,
                project_id=project_id,
                character_id=char.id,
                chapter_id=chapter_id,
                current_motivation=motivation,
            )

        snapshots = get_character_state_snapshots(db, project_id, char.id)
        assert [s.chapter_id for s in snapshots] == [17, 18, 19]
        # 恢复第18章状态
        chapter_18 = next(s for s in snapshots if s.chapter_id == 18)
        assert chapter_18.current_motivation == "拿到第二枚假印"
    finally:
        db.close()
