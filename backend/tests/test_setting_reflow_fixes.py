"""设定回流链路系统性修复的测试

覆盖审计发现的问题：
- P0-1：实体提取直写正式集合时同步向量库
- P0-2：提取完成后的设定回流统一入口（auto_merge 时机修正）
- P1-1：设定摘要总量预算控制
- P2-1：自动合并置信度加权（AI置信度 + 规则分）
- P3-1：usage_count 增量式维护（DreamWeaver 计数不被覆盖）
"""
from __future__ import annotations

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
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.character import Character
from app.models.graph import KnowledgeGraphEdge
from app.models.project import Chapter, Project
from app.models.setting import SettingCollection, SettingItem
from app.models.user import User
from app.services.auto_tracking import AutoTrackingService
from app.services.entity_extraction import EntityExtractionService
from app.services.setting_auto_merge import SettingAutoMergeService
from app.services.setting_templates_pkg._utils import build_project_settings_summary


@pytest.fixture()
def db_session():
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
            Chapter.__table__,
            Character.__table__,
            KnowledgeGraphEdge.__table__,
            SettingCollection.__table__,
            SettingItem.__table__,
        ],
    )
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def project(db_session):
    user = User(username="reflow_user", email="reflow@example.com", password_hash="h", is_active=True)
    db_session.add(user)
    db_session.flush()
    proj = Project(user_id=user.id, display_no=1, title="回流修复项目", audio_config="{}", status="draft")
    db_session.add(proj)
    db_session.commit()
    return proj


# ==================== P0-1：实体提取向量同步 ====================

def test_entity_extraction_formal_write_syncs_vector(db_session, project, monkeypatch) -> None:
    """直写正式集合的设定项应同步向量库（RAG 可见）"""
    calls: list[dict] = []
    import app.services.vector_sync as vector_sync_module

    monkeypatch.setattr(
        vector_sync_module,
        "upsert_setting_to_vector_db",
        lambda **kwargs: calls.append(kwargs),
    )

    result = EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [
            {
                "name": "玄天剑诀",
                "type": "功法",
                "content": "主角主修剑法，剑气可伤敌于百步之外",
                "confidence": 0.9,
            }
        ],
    )

    assert result["saved_to_formal"] == 1
    formal_calls = [c for c in calls if c.get("setting_name") == "玄天剑诀"]
    assert formal_calls, f"正式集合写入后应调用向量同步，实际调用: {calls}"
    assert formal_calls[0]["project_id"] == project.id


def test_entity_extraction_formal_update_syncs_vector(db_session, project, monkeypatch) -> None:
    """更新既有正式项内容时应重新同步向量"""
    db = db_session
    tech_col = SettingCollection(project_id=project.id, name="功法体系", category="technique_system", order=0)
    db.add(tech_col)
    db.flush()
    existing = SettingItem(
        collection_id=tech_col.id, name="玄天剑诀", content="短描述",
        depth=1, is_leaf=True, path="功法体系/玄天剑诀",
    )
    db.add(existing)
    db.commit()

    calls: list[dict] = []
    import app.services.vector_sync as vector_sync_module

    monkeypatch.setattr(
        vector_sync_module,
        "upsert_setting_to_vector_db",
        lambda **kwargs: calls.append(kwargs),
    )

    result = EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [
            {
                "name": "玄天剑诀",
                "type": "功法",
                "content": "一段比短描述长得多的新内容，包含更详细的剑法描述与限制条件",
                "confidence": 0.9,
            }
        ],
    )

    assert result["saved_to_formal"] == 1
    assert any(c.get("setting_name") == "玄天剑诀" for c in calls)


# ==================== P0-2：提取后统一回流入口 ====================

def test_post_extraction_setting_flow_merges_candidates(db_session, project, monkeypatch) -> None:
    """提取完成后的设定回流：高置信候选合并进正式集合并同步向量"""
    from app.services.chapter_post_save import run_post_extraction_setting_flow

    db = db_session
    tech_col = SettingCollection(project_id=project.id, name="功法体系", category="technique_system", order=0)
    cand_col = SettingCollection(project_id=project.id, name="设定候选", category="candidate", order=999)
    db.add_all([tech_col, cand_col])
    db.flush()
    cand = SettingItem(
        collection_id=cand_col.id, name="赤焰掌",
        content="类型：功法\n\n赤焰掌为火系掌法，出掌时掌心凝聚赤色火焰，连续使用会灼伤自身经脉，属于伤敌伤己的搏命功法。",
        tags=json.dumps(["候选", "自动抽取"], ensure_ascii=False),
        confidence_score=0.9,
        depth=1, is_leaf=True, path="设定候选/赤焰掌",
    )
    db.add(cand)
    db.commit()

    upserts: list[dict] = []
    import app.services.vector_sync as vector_sync_module
    monkeypatch.setattr(vector_sync_module, "upsert_setting_to_vector_db", lambda **kw: upserts.append(kw))
    monkeypatch.setattr(vector_sync_module, "delete_setting_from_vector_db", lambda *a, **kw: None)

    result = run_post_extraction_setting_flow(
        db,
        project_id=project.id,
        chapter_plan="本章主角修习赤焰掌",
        chapter_content="主角开始修习赤焰掌，掌心泛起火焰。",
        notify=False,
    )

    assert result["merged_count"] == 1
    # 候选已被合并删除
    remaining_candidates = db.query(SettingItem).filter(SettingItem.collection_id == cand_col.id).all()
    assert len(remaining_candidates) == 0
    # 正式集合出现该项且向量已同步
    formal = db.query(SettingItem).filter(SettingItem.collection_id == tech_col.id, SettingItem.name == "赤焰掌").first()
    assert formal is not None
    assert any(c.get("setting_name") == "赤焰掌" for c in upserts)
    assert result["conflict_summary"] is not None


# ==================== P1-1：摘要预算控制 ====================

def test_settings_summary_limits_items_per_collection(db_session, project) -> None:
    """每个集合最多列出 max_items_per_collection 条，超出截断"""
    db = db_session
    col = SettingCollection(project_id=project.id, name="功法体系", category="technique_system", order=0)
    db.add(col)
    db.flush()
    for i in range(20):
        db.add(SettingItem(
            collection_id=col.id, name=f"功法{i}号",
            content=f"第{i}号功法的详细描述内容",
            depth=1, is_leaf=True, path=f"功法体系/功法{i}号",
        ))
    db.commit()

    summary = build_project_settings_summary(project.id, db)
    # 20 条只保留前 12 条（默认 max_items_per_collection=12）
    assert "功法0号" in summary
    assert "功法11号" in summary
    assert "功法12号" not in summary
    assert "功法19号" not in summary


def test_settings_summary_total_length_cap(db_session, project) -> None:
    """摘要总长度不超过 max_total_length"""
    db = db_session
    for col_idx in range(5):
        col = SettingCollection(
            project_id=project.id, name=f"体系{col_idx}", category=f"cat_{col_idx}", order=col_idx,
        )
        db.add(col)
        db.flush()
        for i in range(10):
            db.add(SettingItem(
                collection_id=col.id, name=f"设定{col_idx}_{i}",
                content="很长的设定内容" * 30,
                depth=1, is_leaf=True, path=f"体系{col_idx}/设定{col_idx}_{i}",
            ))
    db.commit()

    summary = build_project_settings_summary(project.id, db)
    assert 0 < len(summary) <= 2400 + 10  # 截断允许尾缀误差


# ==================== P2-1：置信度加权 ====================

def test_calculate_confidence_combines_ai_and_rule() -> None:
    """AI置信度与规则分加权：AI低置信会拉低总分"""
    rule_high_args = dict(
        item_name="赤焰掌",
        item_content="类型：功法\n\n" + "赤焰掌为火系掌法描述。" * 10,
        chapter_plan="主角修习赤焰掌",
        chapter_content="主角修习赤焰掌。",
    )
    score_no_ai = SettingAutoMergeService.calculate_confidence(**rule_high_args)
    score_high_ai = SettingAutoMergeService.calculate_confidence(**rule_high_args, ai_confidence=0.95)
    score_low_ai = SettingAutoMergeService.calculate_confidence(**rule_high_args, ai_confidence=0.2)

    # 无 AI 置信度时保持纯规则分（向后兼容）
    assert score_no_ai == pytest.approx(score_no_ai)
    assert 0 <= score_low_ai <= score_no_ai <= 1.0
    # AI 高置信不应显著降低纯规则高分
    assert score_high_ai >= 0.8
    # AI 低置信应拉低到阈值下，防止误合并
    assert score_low_ai < 0.8


def test_auto_merge_uses_stored_ai_confidence(db_session, project, monkeypatch) -> None:
    """合并时使用候选项存储的 AI 置信度参与加权"""
    db = db_session
    tech_col = SettingCollection(project_id=project.id, name="功法体系", category="technique_system", order=0)
    cand_col = SettingCollection(project_id=project.id, name="设定候选", category="candidate", order=999)
    db.add_all([tech_col, cand_col])
    db.flush()
    # 规则分会很高（格式+双文本+长度），但 AI 置信度极低 → 不应合并
    cand = SettingItem(
        collection_id=cand_col.id, name="幻影步",
        content="类型：功法\n\n" + "幻影步为身法描述。" * 10,
        tags=json.dumps(["候选"], ensure_ascii=False),
        confidence_score=0.15,
        depth=1, is_leaf=True, path="设定候选/幻影步",
    )
    db.add(cand)
    db.commit()

    import app.services.vector_sync as vector_sync_module
    monkeypatch.setattr(vector_sync_module, "upsert_setting_to_vector_db", lambda **kw: None)
    monkeypatch.setattr(vector_sync_module, "delete_setting_from_vector_db", lambda *a, **kw: None)

    result = SettingAutoMergeService.auto_merge_high_confidence_items(
        db=db,
        project_id=project.id,
        candidate_collection_id=cand_col.id,
        chapter_plan="主角施展幻影步",
        chapter_content="主角施展幻影步穿越敌阵。",
    )

    assert result["merged_count"] == 0
    remaining = db.query(SettingItem).filter(SettingItem.collection_id == cand_col.id).all()
    assert len(remaining) == 1  # 候选保留


# ==================== P3-1：usage_count 增量式维护 ====================

def test_usage_count_incremental_on_add(db_session, project) -> None:
    """新增章节引用时 usage_count 增量 +1，不覆盖 DreamWeaver 等外部计数"""
    db = db_session
    col = SettingCollection(project_id=project.id, name="道具体系", category="weapon_system", order=0)
    db.add(col)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title="第一章", content="")
    db.add(chapter)
    db.flush()
    # 模拟 DreamWeaver 已置 usage_count=3（referenced_chapters 为空）
    item = SettingItem(
        collection_id=col.id, name="玄铁重剑", content="重剑无锋",
        usage_count=3, referenced_chapters="[]",
        depth=1, is_leaf=True, path="道具体系/玄铁重剑",
    )
    db.add(item)
    db.commit()

    AutoTrackingService.update_setting_references_smart(
        chapter_id=chapter.id,
        old_content="",
        new_content="主角提着【玄铁重剑】走入山门。",
        project_id=project.id,
        db=db,
    )

    db.refresh(item)
    assert json.loads(item.referenced_chapters) == [chapter.id]
    # 3（DreamWeaver）+ 1（本章引用）= 4，而不是被 len() 覆盖为 1
    assert item.usage_count == 4


def test_usage_count_decrement_on_removal(db_session, project) -> None:
    """移除章节引用时 usage_count 减 1（不为负），保留外部计数"""
    db = db_session
    col = SettingCollection(project_id=project.id, name="道具体系", category="weapon_system", order=0)
    db.add(col)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title="第一章", content="")
    db.add(chapter)
    db.flush()
    item = SettingItem(
        collection_id=col.id, name="玄铁重剑", content="重剑无锋",
        usage_count=5, referenced_chapters=json.dumps([chapter.id]),
        depth=1, is_leaf=True, path="道具体系/玄铁重剑",
    )
    db.add(item)
    db.commit()

    AutoTrackingService.update_setting_references_smart(
        chapter_id=chapter.id,
        old_content="主角提着【玄铁重剑】走入山门。",
        new_content="主角空手走入山门。",
        project_id=project.id,
        db=db,
    )

    db.refresh(item)
    assert json.loads(item.referenced_chapters) == []
    # 5 - 1 = 4，而不是被 len() 覆盖为 0
    assert item.usage_count == 4
