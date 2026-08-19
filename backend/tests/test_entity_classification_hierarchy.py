"""实体提取分类与层级归位修复的测试

覆盖：
- LLM 语义归类优先于静态字典（减少候选积压）
- 提取项的 path/depth/node_type 规范化（修复 "/{name}"、depth=0 占位符）
- subcategory 归位到集合内既有的分类节点
- 提取 prompt 注入项目实际体系与分类节点
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
from app.models.project import Project
from app.models.setting import SettingCollection, SettingItem
from app.models.user import User
from app.services.entity_extraction import (
    EntityExtractionService,
    build_project_category_hints,
)


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
        tables=[User.__table__, Project.__table__, SettingCollection.__table__, SettingItem.__table__],
    )
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def project(db_session):
    user = User(username="cls_user", email="cls@example.com", password_hash="h", is_active=True)
    db_session.add(user)
    db_session.flush()
    proj = Project(user_id=user.id, display_no=1, title="分类层级项目", audio_config="{}", status="draft")
    db_session.add(proj)
    db_session.commit()
    return proj


@pytest.fixture()
def collections(db_session, project):
    """功法体系（含分类节点）+ AI机器人体系（字典外类别）"""
    db = db_session
    tech_col = SettingCollection(project_id=project.id, name="功法体系", category="technique_system", order=0, max_depth=4)
    ai_col = SettingCollection(project_id=project.id, name="AI机器人体系", category="ai_robot_system", order=1)
    db.add_all([tech_col, ai_col])
    db.flush()
    # 功法体系下既有分类节点（非叶子）
    db.add(SettingItem(
        collection_id=tech_col.id, name="剑道功法", content="剑类功法分类",
        depth=1, node_type="category", is_leaf=False, path="功法体系/剑道功法",
    ))
    db.commit()
    return {"tech": tech_col, "ai": ai_col}


# ==================== LLM 语义归类优先 ====================

def test_llm_category_key_beats_dictionary(db_session, project, collections, monkeypatch) -> None:
    """LLM 输出 category key（字典外类别 ai_robot_system）+ 字典外 type → 直接进正式集合"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    result = EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "玄甲七型",
            "type": "机甲",  # 字典内无"机甲"
            "content": "主角驾驶的第三代人形机甲，搭载聚变核心与神经链接系统，近战主武器为高频震动刀。",
            "confidence": 0.85,
            "category": "ai_robot_system",  # LLM 语义归类
        }],
    )

    assert result["saved_to_formal"] == 1
    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.collection_id == collections["ai"].id, SettingItem.name == "玄甲七型")
        .first()
    )
    assert item is not None


def test_llm_category_name_matches(db_session, project, collections, monkeypatch) -> None:
    """LLM 输出体系中文名（功法体系）也能匹配"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    result = EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "流云剑法",
            "type": "剑法",
            "content": "以快打快的上乘剑法，讲究身剑合一，共九式。",
            "confidence": 0.8,
            "category": "功法体系",  # 用名称而非 key
        }],
    )

    assert result["saved_to_formal"] == 1
    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.collection_id == collections["tech"].id, SettingItem.name == "流云剑法")
        .first()
    )
    assert item is not None


def test_invalid_llm_category_falls_back_to_dictionary(db_session, project, collections, monkeypatch) -> None:
    """LLM category 无效时回退字典链（保持既有行为）"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    result = EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "回春散",
            "type": "丹药",  # 字典可归类
            "content": "基础疗伤药散，外敷可止血生肌，江湖常见。",
            "confidence": 0.8,
            "category": "不存在的体系",
        }],
    )

    assert result["saved_to_formal"] == 1
    # 丹药体系被自动创建（字典回退 + 自动建集合）
    pill_col = (
        db_session.query(SettingCollection)
        .filter(SettingCollection.project_id == project.id, SettingCollection.category == "pill_system")
        .first()
    )
    assert pill_col is not None


def test_llm_category_candidate_excluded(db_session, project, collections, monkeypatch) -> None:
    """LLM 输出 candidate 不可作为归类目标"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    db = db_session
    cand_col = SettingCollection(project_id=project.id, name="设定候选", category="candidate", order=999)
    db.add(cand_col)
    db.commit()

    result = EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "神秘之物",
            "type": "未知类型XYZ",
            "content": "描述不明所以的神秘之物，无法判断其类别归属的详细说明文字。",
            "confidence": 0.5,
            "category": "candidate",
        }],
    )

    # 不允许 LLM 把项指定进候选集合；无字典归类 → 走候选兜底逻辑（结果一致但非 category 直达）
    assert result["saved_to_formal"] == 0
    assert result["saved_to_candidate"] == 1


# ==================== 层级归位 ====================

def test_new_item_has_canonical_path_and_depth(db_session, project, collections, monkeypatch) -> None:
    """无 subcategory：path=集合名/名称、depth=1、node_type=detail、is_leaf=True（修复占位符）"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "磐石诀",
            "type": "功法",
            "content": "土系防御功法，修炼后肌肤如岩石般坚硬。",
            "confidence": 0.8,
        }],
    )

    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.name == "磐石诀")
        .first()
    )
    assert item.path == "功法体系/磐石诀"
    assert item.depth == 1
    assert item.node_type == "detail"
    assert item.is_leaf is True


def test_item_places_under_existing_subcategory(db_session, project, collections, monkeypatch) -> None:
    """subcategory 命中既有分类节点（非叶子）→ 挂到其下，depth=2"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "九天玄诀",
            "type": "功法",
            "content": "传说级剑道功法，剑气可裂山，修炼门槛极高。",
            "confidence": 0.9,
            "category": "technique_system",
            "subcategory": "剑道功法",
        }],
    )

    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.name == "九天玄诀")
        .first()
    )
    assert item.path == "功法体系/剑道功法/九天玄诀"
    assert item.depth == 2
    assert item.is_leaf is True


def test_item_ignores_nonexistent_subcategory(db_session, project, collections, monkeypatch) -> None:
    """subcategory 无同名节点 → 回落体系根（不凭空造分类）"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "游龙身法",
            "type": "功法",
            "content": "轻灵身法，施展时如游龙戏水。",
            "confidence": 0.8,
            "subcategory": "幻觉分类",
        }],
    )

    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.name == "游龙身法")
        .first()
    )
    assert item.path == "功法体系/游龙身法"
    assert item.depth == 1


def test_item_ignores_subcategory_pointing_to_leaf(db_session, project, collections, monkeypatch) -> None:
    """subcategory 指向叶子节点（不能挂子项）→ 回落体系根"""
    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "_sync_formal_item_vector", lambda *a, **kw: None)

    db = db_session
    db.add(SettingItem(
        collection_id=collections["tech"].id, name="已有功法",
        content="叶子功法", depth=1, node_type="detail", is_leaf=True,
        path="功法体系/已有功法",
    ))
    db.commit()

    EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "新功法",
            "type": "功法",
            "content": "新提取的功法描述内容足够详细以通过校验。",
            "confidence": 0.8,
            "subcategory": "已有功法",  # 指向叶子
        }],
    )

    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.name == "新功法")
        .first()
    )
    assert item.path == "功法体系/新功法"
    assert item.depth == 1


def test_candidate_item_path_also_canonical(db_session, project, collections) -> None:
    """候选集合内的新项 path 也规范化（不再 "/{name}"）"""
    db = db_session
    cand_col = SettingCollection(project_id=project.id, name="设定候选", category="candidate", order=999)
    db.add(cand_col)
    db.commit()

    EntityExtractionService.classify_and_save_entities(
        db_session,
        project.id,
        [{
            "name": "谜之物",
            "type": "未知类型ABC",
            "content": "无法归类的神秘之物的详细描述内容，长度超过基本要求。",
            "confidence": 0.5,
        }],
    )

    item = (
        db_session.query(SettingItem)
        .filter(SettingItem.name == "谜之物")
        .first()
    )
    assert item.path == "设定候选/谜之物"
    assert item.depth == 1


# ==================== 项目体系 hints 构建 ====================

def test_build_project_category_hints(db_session, project, collections) -> None:
    """hints 含正式体系 key/name 和 depth=1 分类节点，排除候选"""
    db = db_session
    cand_col = SettingCollection(project_id=project.id, name="设定候选", category="candidate", order=999)
    db.add(cand_col)
    db.commit()

    hints = build_project_category_hints(db_session, project.id)

    keys = {h["key"] for h in hints}
    assert "technique_system" in keys
    assert "ai_robot_system" in keys
    assert "candidate" not in keys

    tech_hint = next(h for h in hints if h["key"] == "technique_system")
    assert tech_hint["name"] == "功法体系"
    assert "剑道功法" in tech_hint["top_nodes"]


def test_build_project_category_hints_excludes_leaf_nodes(db_session, project, collections) -> None:
    """分类节点只收非叶子；叶子功法不进 top_nodes"""
    db = db_session
    db.add(SettingItem(
        collection_id=collections["tech"].id, name="普通功法",
        content="叶子", depth=1, node_type="detail", is_leaf=True,
        path="功法体系/普通功法",
    ))
    db.commit()

    hints = build_project_category_hints(db_session, project.id)
    tech_hint = next(h for h in hints if h["key"] == "technique_system")
    assert "剑道功法" in tech_hint["top_nodes"]
    assert "普通功法" not in tech_hint["top_nodes"]


# ==================== 提取 prompt 注入项目体系 ====================

def test_unified_prompt_contains_project_categories(monkeypatch) -> None:
    """统一提取 prompt 含项目体系 key/名称与分类节点，实体 schema 含 category/subcategory 字段"""
    import asyncio

    from app.services.unified_extraction import UnifiedExtractionService

    captured: dict = {}

    class FakeResp:
        content = json.dumps({"entities": [], "locations": [], "relations": [], "character_relations": []})

    class FakeLLM:
        async def ainvoke(self, prompt):
            captured["prompt"] = prompt
            return FakeResp()

    import app.services.unified_extraction as ue_module
    monkeypatch.setattr(ue_module, "create_model_llm", lambda **kw: FakeLLM())

    asyncio.run(UnifiedExtractionService.extract_all_from_chapter(
        chapter_title="第一章",
        chapter_content="章节内容" * 50,
        project_id=1,
        project_categories=[
            {"key": "technique_system", "name": "功法体系", "top_nodes": ["剑道功法", "拳掌武学"]},
        ],
    ))

    prompt = captured["prompt"]
    assert "technique_system" in prompt
    assert "功法体系" in prompt
    assert "剑道功法" in prompt
    assert '"category"' in prompt
    assert '"subcategory"' in prompt


def test_standalone_prompt_contains_project_categories(monkeypatch) -> None:
    """独立实体提取 prompt 同样注入项目体系与 category/subcategory 字段"""
    import asyncio

    from app.services.entity_extraction import EntityExtractionService

    captured: dict = {}

    class FakeResp:
        content = "[]"

    class FakeLLM:
        async def ainvoke(self, prompt):
            captured["prompt"] = prompt
            return FakeResp()

    import app.services.entity_extraction as ee_module
    monkeypatch.setattr(ee_module, "get_task_llm", lambda *a, **kw: FakeLLM())

    asyncio.run(EntityExtractionService.extract_entities_from_chapter(
        chapter_title="第一章",
        chapter_content="章节内容" * 50,
        project_id=1,
        project_categories=[
            {"key": "ai_robot_system", "name": "AI机器人体系", "top_nodes": []},
        ],
    ))

    prompt = captured["prompt"]
    assert "ai_robot_system" in prompt
    assert "AI机器人体系" in prompt
    assert '"category"' in prompt
    assert '"subcategory"' in prompt


def test_validate_entities_preserves_category_fields() -> None:
    """统一提取的验证保留 category/subcategory 字段"""
    from app.services.unified_extraction import UnifiedExtractionService

    entities = UnifiedExtractionService._validate_entities([
        {"name": "甲", "type": "功法", "content": "描述", "category": "technique_system", "subcategory": "剑道功法"},
        {"name": "乙", "type": "功法", "content": "描述"},  # 无 category 字段
    ])
    assert entities[0]["category"] == "technique_system"
    assert entities[0]["subcategory"] == "剑道功法"
    assert entities[1].get("category") is None
