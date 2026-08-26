"""章节人物状态提取 → 快照落库 → 下一章注入闭环测试。

背景：人物防扁平化改造收尾——补齐文档数据流的最后两环：
- 写入端：章节保存后用 LLM 提取人物动态状态，经快照服务幂等落库
  （chapter_number 列支持按章节号排序与恢复）；
- 读取端：生成第 N 章时读取第 N-1 章及更早的最新快照，
  以【人物当前状态】注入人物运行态上下文。

纯 sqlite 内存库 + mock LLM，离线确定性。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
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
from app.services import character_state_extractor as extractor_module
from app.services.character_state_extractor import (
    CharacterStateExtractionService,
    run_character_state_extraction_flow,
)
from app.services.character_state_snapshot import (
    build_character_state_context_from_snapshots,
    get_latest_character_states_before_chapter,
    merge_character_state_context,
    save_character_state_snapshot,
)


VALID_LLM_JSON = """[
  {
    "name": "林昭",
    "current_motivation": "拿到第二枚假印",
    "current_belief": "偏殿里有人见过假印",
    "emotional_state": "克制中的决意",
    "relationship_state": {"苏晚晴": "初步互信"},
    "known_information": "黑市密账存在",
    "state_changes": [{"field": "motivation", "from": "先取信苏晚晴", "to": "拿到第二枚假印"}],
    "evidence": "林昭收起密账：“下一步，找第二枚。”"
  },
  {
    "name": "路人甲",
    "current_motivation": "看热闹",
    "current_belief": "",
    "emotional_state": "",
    "relationship_state": {},
    "known_information": "",
    "state_changes": [],
    "evidence": ""
  }
]"""


class FakeLLM:
    def __init__(self, content: str):
        self.content_text = content

    async def ainvoke(self, prompt):
        class _Resp:
            def __init__(self, content):
                self.content = content

        return _Resp(self.content_text)


def _patch_llm(monkeypatch, content: str):
    def _fake_create_model_llm(*, model, temperature=0.7, **kwargs):
        return FakeLLM(content)

    monkeypatch.setattr(extractor_module, "create_model_llm", _fake_create_model_llm)


# ==================== A. 提取器 ====================

def test_extract_states_parses_and_filters_llm_json(monkeypatch):
    _patch_llm(monkeypatch, f"```json\n{VALID_LLM_JSON}\n```")

    states = asyncio.run(
        CharacterStateExtractionService.extract_character_states_from_chapter(
            chapter_title="灯下问局",
            chapter_content="林昭收起密账。",
            project_id=9,
            character_names=["林昭", "苏晚晴"],
            model="deepseek-v4-pro",
        )
    )

    # 路人甲不在角色名单内，被过滤
    assert [s["name"] for s in states] == ["林昭"]
    assert states[0]["current_motivation"] == "拿到第二枚假印"
    assert states[0]["relationship_state"] == {"苏晚晴": "初步互信"}
    assert "第二枚" in states[0]["evidence"]


def test_extract_states_invalid_json_returns_empty(monkeypatch):
    _patch_llm(monkeypatch, "模型输出异常内容，不是 JSON")

    states = asyncio.run(
        CharacterStateExtractionService.extract_character_states_from_chapter(
            chapter_title="t",
            chapter_content="c",
            project_id=9,
            character_names=["林昭"],
            model="deepseek-v4-pro",
        )
    )

    assert states == []


def test_extract_states_skips_when_no_characters():
    states = asyncio.run(
        CharacterStateExtractionService.extract_character_states_from_chapter(
            chapter_title="t",
            chapter_content="c",
            project_id=9,
            character_names=[],
            model="deepseek-v4-pro",
        )
    )

    assert states == []


# ==================== B. 提取落库流程 ====================

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


def _seed_project_and_character(db):
    user = User(username="extract_user", email="extract@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    project = Project(title="状态提取项目", description="", user_id=user.id, display_no=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    char = Character(project_id=project.id, name="林昭", motivation="夺回家族传承")
    db.add(char)
    db.commit()
    db.refresh(char)
    return project.id, char.id


def test_extraction_flow_saves_snapshots(monkeypatch):
    db = build_session()
    project_id, character_id = _seed_project_and_character(db)
    _patch_llm(monkeypatch, VALID_LLM_JSON)
    try:
        result = asyncio.run(
            run_character_state_extraction_flow(
                db,
                project_id=project_id,
                chapter_id=17,
                chapter_number=17,
                chapter_title="灯下问局",
                chapter_content="林昭收起密账。",
                model="deepseek-v4-pro",
            )
        )

        assert result["extracted"] == 1
        assert result["saved"] == 1

        snapshot = (
            db.query(CharacterStateSnapshot)
            .filter(CharacterStateSnapshot.character_id == character_id)
            .one()
        )
        assert snapshot.chapter_number == 17
        assert snapshot.current_motivation == "拿到第二枚假印"
        assert "初步互信" in (snapshot.relationship_state_json or "")
        assert "第二枚" in (snapshot.evidence_text or "")

        # 重复执行同章提取：幂等覆盖，不产生重复快照
        asyncio.run(
            run_character_state_extraction_flow(
                db,
                project_id=project_id,
                chapter_id=17,
                chapter_number=17,
                chapter_title="灯下问局",
                chapter_content="（重生成后的章节内容）",
                model="deepseek-v4-pro",
            )
        )
        count = (
            db.query(CharacterStateSnapshot)
            .filter(CharacterStateSnapshot.character_id == character_id)
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_extraction_flow_never_raises_on_llm_failure(monkeypatch):
    db = build_session()
    project_id, _ = _seed_project_and_character(db)

    def _boom(*, model, temperature=0.7, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(extractor_module, "create_model_llm", _boom)
    try:
        result = asyncio.run(
            run_character_state_extraction_flow(
                db,
                project_id=project_id,
                chapter_id=17,
                chapter_number=17,
                chapter_title="t",
                chapter_content="c",
                model="deepseek-v4-pro",
            )
        )
        assert result["saved"] == 0
    finally:
        db.close()


# ==================== C. 读取端：最新状态与上下文构建 ====================

def _seed_snapshots(db, project_id, character_id):
    save_character_state_snapshot(
        db,
        project_id=project_id,
        character_id=character_id,
        chapter_id=15,
        chapter_number=15,
        current_motivation="潜入偏殿",
    )
    save_character_state_snapshot(
        db,
        project_id=project_id,
        character_id=character_id,
        chapter_id=16,
        chapter_number=16,
        current_motivation="先取信苏晚晴",
        current_belief="偏殿有内应",
    )
    # 第17章（当前生成章）的快照不应注入
    save_character_state_snapshot(
        db,
        project_id=project_id,
        character_id=character_id,
        chapter_id=17,
        chapter_number=17,
        current_motivation="当前章快照不应出现",
    )


def test_get_latest_states_before_chapter():
    db = build_session()
    project_id, character_id = _seed_project_and_character(db)
    _seed_snapshots(db, project_id, character_id)
    try:
        latest = get_latest_character_states_before_chapter(db, project_id, before_chapter_number=17)

        assert character_id in latest
        assert latest[character_id].current_motivation == "先取信苏晚晴"
        assert latest[character_id].chapter_number == 16
    finally:
        db.close()


def test_build_character_state_context_formats_latest_states():
    db = build_session()
    project_id, character_id = _seed_project_and_character(db)
    _seed_snapshots(db, project_id, character_id)
    try:
        context = build_character_state_context_from_snapshots(
            db,
            project_id=project_id,
            before_chapter_number=17,
        )

        assert "【人物当前状态】" in context
        assert "林昭" in context
        assert "先取信苏晚晴" in context
        assert "当前章快照不应出现" not in context
        assert "潜入偏殿" not in context  # 只取最新一条
    finally:
        db.close()


def test_build_character_state_context_empty_without_snapshots():
    db = build_session()
    project_id, _ = _seed_project_and_character(db)
    try:
        context = build_character_state_context_from_snapshots(
            db,
            project_id=project_id,
            before_chapter_number=17,
        )
        assert context == ""
    finally:
        db.close()


def test_merge_character_state_context_combines_sections():
    merged = merge_character_state_context(
        "【人物当前状态】\n- 林昭：先取信苏晚晴",
        "【角色名单摘要】\n1. 林昭（主角）",
    )

    assert "【人物当前状态】" in merged
    assert "【角色名单摘要】" in merged
    # 状态在前（动态优先），基线在后（稳定约束补充）
    assert merged.index("【人物当前状态】") < merged.index("【角色名单摘要】")

    # 状态为空时原样返回运行态上下文
    assert merge_character_state_context("", "runtime") == "runtime"
