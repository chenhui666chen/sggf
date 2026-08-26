"""免费档后置处理模型透传（步骤3）单元测试。

覆盖 post_processing_model 在统一提取、三段回退提取、章节摘要全链路的透传，
以及缺省（None）时保持现有模型选择行为不变。
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for _path in (BACKEND_DIR, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")

from app.services import chapter_post_save as post_save_module
from app.services import entity_extraction as entity_module
from app.services import location_hierarchy_extractor as location_module
from app.services import unified_extraction as unified_module
from app.services.entity_extraction import EntityExtractionService
from app.services.location_hierarchy_extractor import LocationHierarchyExtractor
from app.services.unified_extraction import UnifiedExtractionService
from app.services.exact_model_guard import ExactModelRequiredError
from app.services import exact_model_guard as guard_module

FLASH = "qwen3.7-flash"


class FakeLLM:
    """返回固定 JSON 的假 LLM。"""

    def __init__(self, content: str = "[]"):
        self.content_text = content

    async def ainvoke(self, prompt):
        class _Resp:
            def __init__(self, content):
                self.content = content

        return _Resp(self.content_text)


# ==================== A. 各服务的 model 参数生效 ====================

def test_unified_extraction_uses_explicit_model(monkeypatch):
    captured = {}

    def _fake_create_model_llm(*, model, temperature=0.7, **kwargs):
        captured["model"] = model
        return FakeLLM('{"entities": [], "locations": [], "relations": [], "character_relations": []}')

    monkeypatch.setattr(unified_module, "create_model_llm", _fake_create_model_llm)
    monkeypatch.setenv("UNIFIED_EXTRACTION_MODEL", "deepseek-v4-pro")

    result = asyncio.run(UnifiedExtractionService.extract_all_from_chapter(
        chapter_title="t", chapter_content="c", project_id=1, model=FLASH,
    ))
    assert captured["model"] == FLASH
    assert result["entities"] == []


def test_unified_extraction_default_keeps_env_logic(monkeypatch):
    captured = {}

    def _fake_create_model_llm(*, model, temperature=0.7, **kwargs):
        captured["model"] = model
        return FakeLLM('{"entities": [], "locations": [], "relations": [], "character_relations": []}')

    monkeypatch.setattr(unified_module, "create_model_llm", _fake_create_model_llm)
    monkeypatch.setenv("UNIFIED_EXTRACTION_MODEL", "deepseek-v4-pro")

    asyncio.run(UnifiedExtractionService.extract_all_from_chapter(
        chapter_title="t", chapter_content="c", project_id=1,
    ))
    assert captured["model"] == "deepseek-v4-pro"


def test_locked_post_processing_model_rejects_catalog_reroute(monkeypatch):
    monkeypatch.setattr(
        guard_module,
        "resolve_model_for_task",
        lambda task_type, model: "qwen3.7-plus",
    )

    with pytest.raises(ExactModelRequiredError):
        asyncio.run(UnifiedExtractionService.extract_all_from_chapter(
            chapter_title="t", chapter_content="c", project_id=1, model=FLASH,
        ))


def test_entity_extraction_uses_explicit_model(monkeypatch):
    captured = {}

    def _fake_create_task_llm(task_type=None, *, model=None, **kwargs):
        captured["task_type"] = task_type
        captured["model"] = model
        return FakeLLM("[]")

    def _fake_get_task_llm(task_type=None):
        captured["get_task_llm_called"] = True
        return FakeLLM("[]")

    monkeypatch.setattr(entity_module, "create_task_llm", _fake_create_task_llm)
    monkeypatch.setattr(entity_module, "get_task_llm", _fake_get_task_llm)

    asyncio.run(EntityExtractionService.extract_entities_from_chapter(
        chapter_title="t", chapter_content="c", project_id=1, model=FLASH,
    ))
    assert captured["model"] == FLASH
    assert captured["task_type"] == "entity_extract"
    assert "get_task_llm_called" not in captured


def test_entity_extraction_default_keeps_task_routing(monkeypatch):
    captured = {}

    def _fake_get_task_llm(task_type=None):
        captured["get_task_llm_called"] = True
        return FakeLLM("[]")

    monkeypatch.setattr(entity_module, "get_task_llm", _fake_get_task_llm)

    asyncio.run(EntityExtractionService.extract_entities_from_chapter(
        chapter_title="t", chapter_content="c", project_id=1,
    ))
    assert captured.get("get_task_llm_called") is True


def test_relation_extraction_uses_explicit_model(monkeypatch):
    captured = {}

    def _fake_create_task_llm(task_type=None, *, model=None, **kwargs):
        captured["model"] = model
        return FakeLLM("[]")

    monkeypatch.setattr(entity_module, "create_task_llm", _fake_create_task_llm)

    asyncio.run(EntityExtractionService.extract_relations_from_chapter(
        chapter_title="t", chapter_content="c",
        entities=[{"name": "A"}, {"name": "B"}], model=FLASH,
    ))
    assert captured["model"] == FLASH


def test_location_extraction_uses_explicit_model(monkeypatch):
    captured = {}

    def _fake_create_task_llm(task_type=None, *, model=None, **kwargs):
        captured["model"] = model
        return FakeLLM("[]")

    monkeypatch.setattr(location_module, "create_task_llm", _fake_create_task_llm)

    asyncio.run(LocationHierarchyExtractor.extract_location_hierarchy(
        chapter_title="t", chapter_content="c", model=FLASH,
    ))
    assert captured["model"] == FLASH


# ==================== B. chapter_post_save 全链路透传 ====================

class FakeDB:
    def close(self):
        return


@pytest.fixture
def _quiet_post_save(monkeypatch):
    """屏蔽 chapter_post_save 中的 DB 与广播副作用。"""
    monkeypatch.setattr(post_save_module, "SessionLocal", lambda: FakeDB())

    async def _no_broadcast(**kwargs):
        return True

    monkeypatch.setattr(post_save_module, "_broadcast_project_event", _no_broadcast)


def test_post_save_passes_model_to_unified_and_summary(monkeypatch, _quiet_post_save):
    captured = {}

    async def _fake_unified(*, chapter_title, chapter_content, project_id, model=None, project_categories=None):
        captured["unified_model"] = model
        return {"entities": [], "locations": [], "relations": [], "character_relations": []}

    monkeypatch.setattr(UnifiedExtractionService, "extract_all_from_chapter", _fake_unified)

    from app.services.agents import chapter_summarizer as summarizer_module

    class FakeSummarizer:
        def get_or_generate_summary(self, **kwargs):
            return {}

    def _fake_create_summarizer(knowledge_base=None, memory_manager=None,
                                db_session=None, model: Optional[str] = None):
        captured["summary_model"] = model
        return FakeSummarizer()

    monkeypatch.setattr(summarizer_module, "create_chapter_summarizer", _fake_create_summarizer)

    asyncio.run(post_save_module.process_chapter_post_save(
        chapter_id=1, chapter_title="t", chapter_content="c",
        chapter_number=1, project_id=1, generate_summary=True,
        post_processing_model=FLASH,
    ))
    assert captured["unified_model"] == FLASH
    assert captured["summary_model"] == FLASH


def test_post_save_passes_model_to_fallback_extractors(monkeypatch, _quiet_post_save):
    """统一提取失败 → 三段回退提取同样收到锁定模型（上线门槛：回退路径纳入锁定测试）。"""
    captured = {}

    async def _fail_unified(*, chapter_title, chapter_content, project_id, model=None, project_categories=None):
        raise RuntimeError("simulated unified failure")

    async def _fake_entities(*, chapter_title, chapter_content, project_id, model=None, project_categories=None):
        captured["entities_model"] = model
        return [{"name": "A", "type": "人物", "content": "x"}, {"name": "B", "type": "人物", "content": "y"}]

    async def _fake_locations(*, chapter_title, chapter_content, model=None):
        captured["locations_model"] = model
        return []

    async def _fake_relations(*, chapter_title, chapter_content, entities, model=None):
        captured["relations_model"] = model
        return []

    monkeypatch.setattr(UnifiedExtractionService, "extract_all_from_chapter", _fail_unified)
    monkeypatch.setattr(EntityExtractionService, "extract_entities_from_chapter", _fake_entities)
    monkeypatch.setattr(LocationHierarchyExtractor, "extract_location_hierarchy", _fake_locations)
    monkeypatch.setattr(EntityExtractionService, "extract_relations_from_chapter", _fake_relations)
    monkeypatch.setattr(
        EntityExtractionService, "classify_and_save_entities",
        staticmethod(lambda *, db, project_id, entities: {"saved_to_formal": 0, "saved_to_candidate": 0, "skipped": 0}),
    )

    asyncio.run(post_save_module.process_chapter_post_save(
        chapter_id=1, chapter_title="t", chapter_content="c",
        chapter_number=1, project_id=1, generate_summary=False,
        post_processing_model=FLASH,
    ))
    assert captured["entities_model"] == FLASH
    assert captured["locations_model"] == FLASH
    assert captured["relations_model"] == FLASH


def test_post_save_default_model_is_none(monkeypatch, _quiet_post_save):
    """缺省调用（标准档/手动章节）：透传 None，各服务保持现有行为。"""
    captured = {}

    async def _fake_unified(*, chapter_title, chapter_content, project_id, model=None, project_categories=None):
        captured["unified_model"] = model
        return {"entities": [], "locations": [], "relations": [], "character_relations": []}

    monkeypatch.setattr(UnifiedExtractionService, "extract_all_from_chapter", _fake_unified)

    asyncio.run(post_save_module.process_chapter_post_save(
        chapter_id=1, chapter_title="t", chapter_content="c",
        chapter_number=1, project_id=1, generate_summary=False,
    ))
    assert captured["unified_model"] is None
