"""场景驱动设定召回服务测试

验证：场景识别、焦点人物设定召回（功法/境界/法宝/关联设定）、
时间一致性过滤（未习得功法不注入）、场景类别过滤。
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
from app.models.character import Character, CharacterTechnique
from app.models.project import Project
from app.models.setting import SettingCollection, SettingItem
from app.models.user import User
from app.services.scene_setting_retriever import (
    build_scene_setting_pack,
    detect_scenes,
    extract_planned_settings,
)
from app.services.setting_templates_pkg._utils import build_settings_catalog_text


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
            SettingCollection.__table__,
            SettingItem.__table__,
            Character.__table__,
            CharacterTechnique.__table__,
        ],
    )
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def seeded(db_session):
    """构造：林逸（炼气三层，2门功法，1把剑）+ 王猛（炼气二层，未习得功法）"""
    db = db_session
    user = User(username="scene_user", email="scene@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(user_id=user.id, display_no=1, title="场景测试项目", audio_config="{}", status="draft")
    db.add(project)
    db.flush()

    tech_col = SettingCollection(project_id=project.id, name="功法体系", category="technique_system", order=0)
    weapon_col = SettingCollection(project_id=project.id, name="武器与法宝体系", category="weapon_system", order=1)
    realm_col = SettingCollection(project_id=project.id, name="修仙境界体系", category="cultivation_realm_system", order=2)
    map_col = SettingCollection(project_id=project.id, name="地图体系", category="map_system", order=3)
    db.add_all([tech_col, weapon_col, realm_col, map_col])
    db.flush()

    sword_art = SettingItem(
        collection_id=tech_col.id, name="青元剑诀", content="剑气三尺，每次施展消耗一半灵力",
        depth=1, is_leaf=True, path="功法体系/青元剑诀",
    )
    body_art = SettingItem(
        collection_id=tech_col.id, name="磐岩劲", content="防御型体术，可硬接同阶一击",
        depth=1, is_leaf=True, path="功法体系/磐岩劲",
    )
    future_art = SettingItem(
        collection_id=tech_col.id, name="御空术", content="第50章才学会的飞行术",
        depth=1, is_leaf=True, path="功法体系/御空术",
    )
    sword = SettingItem(
        collection_id=weapon_col.id, name="青锋剑", content="凡级上品，可蓄力一击",
        depth=1, is_leaf=True, path="武器与法宝体系/青锋剑",
    )
    realm = SettingItem(
        collection_id=realm_col.id, name="炼气三层", content="灵力可外放三尺",
        depth=1, is_leaf=True, path="修仙境界体系/炼气三层",
    )
    location = SettingItem(
        collection_id=map_col.id, name="青云山", content="宗门所在山脉",
        depth=1, is_leaf=True, path="地图体系/青云山",
    )
    saber = SettingItem(
        collection_id=weapon_col.id, name="黑铁刀", content="凡级中品，厚重耐砍",
        depth=1, is_leaf=True, path="武器与法宝体系/黑铁刀",
    )
    db.add_all([sword_art, body_art, future_art, sword, realm, location, saber])
    db.flush()

    lin = Character(project_id=project.id, name="林逸", current_realm_item_id=realm.id)
    wang = Character(project_id=project.id, name="王猛")
    db.add_all([lin, wang])
    db.flush()

    sword_prof = CharacterTechnique(
        character_id=lin.id, technique_item_id=sword_art.id, proficiency="精通",
        notes="每日限用三次",
    )
    body_prof = CharacterTechnique(
        character_id=lin.id, technique_item_id=body_art.id, proficiency="入门",
    )
    future_prof = CharacterTechnique(
        character_id=lin.id, technique_item_id=future_art.id,
        learned_at_chapter=50,
    )
    db.add_all([sword_prof, body_prof, future_prof])

    # 青锋剑通过 related_characters 关联林逸；黑铁刀关联王猛
    sword.related_characters = json.dumps([lin.id])
    saber.related_characters = json.dumps([wang.id])
    db.commit()

    return {
        "project_id": project.id,
        "lin_id": lin.id,
        "wang_id": wang.id,
        "sword_art_id": sword_art.id,
        "sword_id": sword.id,
        "realm_id": realm.id,
        "location_id": location.id,
        "future_art_id": future_art.id,
    }


# ==================== 场景识别 ====================

def test_detect_scenes_combat() -> None:
    assert detect_scenes("两人在山门外交手，林逸拔剑激战") == ["combat"]


def test_detect_scenes_multiple() -> None:
    scenes = detect_scenes("主角在秘境探险时与守关傀儡激战")
    assert "combat" in scenes
    assert "exploration" in scenes


def test_detect_scenes_no_match() -> None:
    assert detect_scenes("林逸回到住处，回忆白日对话") == []


def test_detect_scenes_empty_text() -> None:
    assert detect_scenes("") == []
    assert detect_scenes(None) == []


# ==================== 设定包构建 ====================

def test_pack_includes_technique_with_proficiency(db_session, seeded) -> None:
    pack = build_scene_setting_pack(
        db_session,
        seeded["project_id"],
        ["林逸"],
        scene_types=["combat"],
        current_chapter_number=30,
    )
    assert "青元剑诀" in pack.text
    assert "精通" in pack.text
    assert "每日限用三次" in pack.text
    assert seeded["sword_art_id"] in pack.setting_ids


def test_pack_filters_not_yet_learned_technique(db_session, seeded) -> None:
    """learned_at_chapter=50 的功法在第30章不可用"""
    pack = build_scene_setting_pack(
        db_session,
        seeded["project_id"],
        ["林逸"],
        scene_types=["combat"],
        current_chapter_number=30,
    )
    assert "御空术" not in pack.text
    assert seeded["future_art_id"] not in pack.setting_ids


def test_pack_includes_current_realm(db_session, seeded) -> None:
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], ["林逸"], scene_types=["combat"],
    )
    assert "炼气三层" in pack.text


def test_pack_includes_related_weapon(db_session, seeded) -> None:
    """related_characters 关联的武器应注入"""
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], ["林逸"], scene_types=["combat"],
    )
    assert "青锋剑" in pack.text
    assert seeded["sword_id"] in pack.setting_ids


def test_pack_excludes_off_scene_category(db_session, seeded) -> None:
    """combat 场景不应注入 map_system 类别"""
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], ["林逸"], scene_types=["combat"],
    )
    assert "青云山" not in pack.text


def test_pack_excludes_unrelated_character(db_session, seeded) -> None:
    """王猛没有任何设定关联，其段落不应出现功法"""
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], ["王猛"], scene_types=["combat"],
    )
    assert "青元剑诀" not in pack.text


def test_pack_empty_without_scenes(db_session, seeded) -> None:
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], ["林逸"], source_text="回忆日常",
    )
    assert pack.text == ""
    assert pack.setting_ids == set()


def test_pack_empty_without_focus_characters(db_session, seeded) -> None:
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], [], scene_types=["combat"],
    )
    assert pack.text == ""


def test_pack_from_source_text_auto_detects_scene(db_session, seeded) -> None:
    """source_text 含打斗词时自动识别场景"""
    pack = build_scene_setting_pack(
        db_session,
        seeded["project_id"],
        ["林逸"],
        source_text="本章细纲：林逸与王猛交手",
    )
    assert "青元剑诀" in pack.text


def test_pack_respects_character_order_and_limit(db_session, seeded) -> None:
    """按传入顺序输出人物段落"""
    pack = build_scene_setting_pack(
        db_session, seeded["project_id"], ["王猛", "林逸"], scene_types=["combat"],
    )
    assert pack.text.index("王猛") < pack.text.index("林逸")


# ==================== 集成：build_typed_rag_context ====================

def test_rag_context_prepends_scene_pack(db_session, seeded) -> None:
    """带焦点人物时，场景设定包应前置注入 rag_world_context"""
    from app.services.workflow_context_builder import WorkflowContextBuilder

    builder = WorkflowContextBuilder(db_session)
    bundle = builder.build_typed_rag_context(
        seeded["project_id"],
        "林逸与王猛交手，拔剑激战",
        current_chapter_number=30,
        focus_character_names=["林逸", "王猛"],
    )
    assert "【本章场景设定包·战斗】" in bundle.rag_world_context
    assert "青元剑诀" in bundle.rag_world_context
    # 场景包应位于世界设定上下文的开头
    assert bundle.rag_world_context.index("【本章场景设定包·战斗】") == 0


def test_rag_context_without_focus_characters_keeps_scene_pack_empty(db_session, seeded) -> None:
    """无焦点人物时不注入场景包（保持原有行为）"""
    from app.services.workflow_context_builder import WorkflowContextBuilder

    builder = WorkflowContextBuilder(db_session)
    bundle = builder.build_typed_rag_context(
        seeded["project_id"],
        "林逸与王猛交手，拔剑激战",
        current_chapter_number=30,
    )
    assert "【本章场景设定包" not in bundle.rag_world_context


# ==================== 设定清单（规划输入） ====================

def test_settings_catalog_groups_by_category_names_only(db_session, seeded) -> None:
    """按类别分组、只列名称不列内容"""
    catalog = build_settings_catalog_text(seeded["project_id"], db_session)
    assert "功法体系" in catalog
    assert "青元剑诀" in catalog
    # 内容不应出现在清单中（token 高效）
    assert "剑气三尺" not in catalog
    # 分组格式：类别行 + 名称
    assert "武器与法宝体系" in catalog
    assert "青锋剑" in catalog


def test_settings_catalog_excludes_candidate(db_session, seeded) -> None:
    """候选集合不进清单"""
    db = db_session
    cand_col = SettingCollection(
        project_id=seeded["project_id"], name="候选集合", category="candidate", order=99,
    )
    db.add(cand_col)
    db.flush()
    db.add(SettingItem(
        collection_id=cand_col.id, name="待定新设定", content="候选内容",
        depth=1, is_leaf=True, path="候选集合/待定新设定",
    ))
    db.commit()

    catalog = build_settings_catalog_text(seeded["project_id"], db)
    assert "待定新设定" not in catalog


def test_settings_catalog_empty_project(db_session, seeded) -> None:
    """无设定集合返回空字符串"""
    assert build_settings_catalog_text(seeded["project_id"] + 999, db_session) == ""


# ==================== 规划点名设定提取（正文消费） ====================

def test_extract_planned_settings_matches_names_in_plan(db_session, seeded) -> None:
    """规划文本中提到的设定名命中，未提到的不命中"""
    items = extract_planned_settings(
        db_session,
        seeded["project_id"],
        "## 8. 设定调用\n- 功法：青元剑诀（林逸主攻手段）\n- 武器：青锋剑\n- 地点：另有一处新场景",
    )
    names = {item.name for item in items}
    assert "青元剑诀" in names
    assert "青锋剑" in names
    assert "磐岩劲" not in names


def test_extract_planned_settings_returns_full_content(db_session, seeded) -> None:
    """命中的设定项带完整内容供正文注入"""
    items = extract_planned_settings(
        db_session, seeded["project_id"], "本章林逸施展青元剑诀",
    )
    matched = next(item for item in items if item.name == "青元剑诀")
    assert "剑气三尺" in matched.content


def test_extract_planned_settings_no_matches(db_session, seeded) -> None:
    """规划未提到任何已有设定时返回空"""
    assert extract_planned_settings(
        db_session, seeded["project_id"], "本章全是新场景新设定",
    ) == []


# ==================== 集成：规划点名设定注入 RAG ====================

def test_rag_context_injects_planned_settings(db_session, seeded) -> None:
    """chapter_plan 点名的设定应注入 rag_world_context 详情"""
    from app.services.workflow_context_builder import WorkflowContextBuilder

    builder = WorkflowContextBuilder(db_session)
    bundle = builder.build_typed_rag_context(
        seeded["project_id"],
        "林逸与王猛交手",
        current_chapter_number=30,
        chapter_plan="## 8. 设定调用\n- 功法：青元剑诀\n- 武器：青锋剑",
    )
    assert "【规划指定设定】" in bundle.rag_world_context
    assert "剑气三尺" in bundle.rag_world_context  # 设定详情已注入


def test_rag_context_planned_settings_dedupe_with_scene_pack(db_session, seeded) -> None:
    """场景包已注入的设定不重复注入规划指定块"""
    from app.services.workflow_context_builder import WorkflowContextBuilder

    builder = WorkflowContextBuilder(db_session)
    bundle = builder.build_typed_rag_context(
        seeded["project_id"],
        "林逸与王猛交手",
        current_chapter_number=30,
        focus_character_names=["林逸"],
        chapter_plan="本章林逸施展青元剑诀和磐岩劲",
    )
    # 场景包注入了林逸的功法（含青元剑诀、磐岩劲）
    assert bundle.rag_world_context.count("青元剑诀") >= 1
    # 磐岩劲在场景包中，不应再出现在规划指定块
    assert "【规划指定设定】" not in bundle.rag_world_context or (
        "磐岩劲" not in bundle.rag_world_context.split("【规划指定设定】")[-1]
    )


# ==================== 集成：章节规划提示词 ====================

def test_chapter_plan_prompt_includes_settings_catalog(db_session, seeded) -> None:
    """设定清单注入后，规划 prompt 应包含清单区块和"设定调用"输出要求"""
    from app.api.v1.workflow.routes_chapter import _build_chapter_plan_user_prompt

    catalog = build_settings_catalog_text(seeded["project_id"], db_session)
    prompt = _build_chapter_plan_user_prompt(
        next_chapter_number=31,
        concept="测试概念",
        current_chapter_outline="",
        current_volume_context="",
        core_character_anchor_context="",
        focus_character_relationship_context="",
        planning_character_context="",
        epic_framework_context="",
        optimized_context_text="",
        structured_memory_text="",
        previous_chapters_summary="",
        recent_chapter_assets_summary="",
        previous_ending="",
        settings_catalog=catalog,
    )
    assert "【项目设定清单】" in prompt
    assert "青元剑诀" in prompt
    assert "## 8. 设定调用" in prompt


def test_chapter_plan_prompt_without_catalog_has_no_settings_section() -> None:
    """无设定清单时，prompt 不含设定区块（保持原有输出结构）"""
    from app.api.v1.workflow.routes_chapter import _build_chapter_plan_user_prompt

    prompt = _build_chapter_plan_user_prompt(
        next_chapter_number=1,
        concept="",
        current_chapter_outline="",
        current_volume_context="",
        core_character_anchor_context="",
        focus_character_relationship_context="",
        planning_character_context="",
        epic_framework_context="",
        optimized_context_text="",
        structured_memory_text="",
        previous_chapters_summary="",
        recent_chapter_assets_summary="",
        previous_ending="",
    )
    assert "【项目设定清单】" not in prompt
    assert "## 8. 设定调用" not in prompt
    assert "## 7. 伏笔事项" in prompt
