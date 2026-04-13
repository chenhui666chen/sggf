import json
import os
import sys

import pytest


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

for path in (ROOT_DIR, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


from app.models.book_parser import BookAnalysis, BookChapter, BookSource
from app.models.character import Character
from app.models.project import Project
from app.models.setting import SettingCollection, SettingItem
from app.services.agents.chapter_summarizer import ChapterSummarizer
from app.services.book_parser.project_bridge import ProjectBridge
from app.services.setting_templates import build_project_settings_summary


def _make_bare_summarizer() -> ChapterSummarizer:
    return object.__new__(ChapterSummarizer)


def test_get_or_generate_summary_uses_cached_summary_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    summarizer = _make_bare_summarizer()

    monkeypatch.setattr(
        summarizer,
        "load_summary_from_db",
        lambda chapter_id: {"core_summary": "缓存摘要", "key_events": ["旧事件"]},
    )

    def _unexpected_generate(**kwargs):
        raise AssertionError("命中缓存时不应重新生成摘要")

    monkeypatch.setattr(summarizer, "generate_chapter_summary", _unexpected_generate)
    monkeypatch.setattr(summarizer, "save_summary_to_db", lambda chapter_id, summary: True)

    result = ChapterSummarizer.get_or_generate_summary(
        summarizer,
        chapter_id=1,
        chapter_number=1,
        chapter_title="第一章",
        chapter_content="章节正文",
    )

    assert result["core_summary"] == "缓存摘要"
    assert result["key_events"] == ["旧事件"]


def test_get_or_generate_summary_can_force_regenerate(monkeypatch: pytest.MonkeyPatch) -> None:
    summarizer = _make_bare_summarizer()
    generated_summary = {
        "core_summary": "新摘要",
        "key_characters": ["林舟"],
        "key_events": ["发现线索"],
        "key_locations": ["青石城"],
        "plot_advancement": "主线推进",
        "hooks": ["黑匣子异动"],
    }
    save_calls = []

    monkeypatch.setattr(
        summarizer,
        "load_summary_from_db",
        lambda chapter_id: {"core_summary": "旧摘要"},
    )
    monkeypatch.setattr(summarizer, "generate_chapter_summary", lambda **kwargs: generated_summary)
    monkeypatch.setattr(
        summarizer,
        "save_summary_to_db",
        lambda chapter_id, summary: save_calls.append((chapter_id, summary)) or True,
    )

    result = ChapterSummarizer.get_or_generate_summary(
        summarizer,
        chapter_id=2,
        chapter_number=2,
        chapter_title="第二章",
        chapter_content="更新后的章节正文",
        force_regenerate=True,
    )

    assert result == generated_summary
    assert save_calls == [(2, generated_summary)]


class _FakeQuery:
    def __init__(self, items):
        self._items = list(items)

    def filter(self, *args, **kwargs):
        filtered = list(self._items)
        for condition in args:
            left_key = getattr(getattr(condition, "left", None), "key", None)
            operator = getattr(condition, "operator", None)
            right = getattr(condition, "right", None)
            right_value = getattr(right, "effective_value", getattr(right, "value", None))
            operator_name = getattr(operator, "__name__", "")

            if not left_key or not operator_name:
                continue

            if operator_name == "eq":
                filtered = [
                    item for item in filtered
                    if getattr(item, left_key, None) == right_value
                ]
            elif operator_name == "in_op":
                expected = set(right_value or [])
                filtered = [
                    item for item in filtered
                    if getattr(item, left_key, None) in expected
                ]
            elif operator_name == "ge":
                filtered = [
                    item for item in filtered
                    if getattr(item, left_key, None) is not None and getattr(item, left_key) >= right_value
                ]
            elif operator_name == "le":
                filtered = [
                    item for item in filtered
                    if getattr(item, left_key, None) is not None and getattr(item, left_key) <= right_value
                ]

        return _FakeQuery(filtered)

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None

    def count(self):
        return len(self._items)


class _FakeDB:
    def __init__(self, book_chapters):
        self.book_chapters = list(book_chapters)
        self.added = []
        self._next_collection_id = 1
        self._next_setting_item_id = 1
        self._next_character_id = 1

    def query(self, model):
        if model is BookChapter:
            return _FakeQuery(self.book_chapters)
        if model is Character:
            return _FakeQuery([item for item in self.added if isinstance(item, Character)])
        if model is SettingCollection:
            return _FakeQuery([item for item in self.added if isinstance(item, SettingCollection)])
        if model is SettingItem:
            return _FakeQuery([item for item in self.added if isinstance(item, SettingItem)])
        return _FakeQuery([])

    def add(self, item):
        self.added.append(item)

    def flush(self):
        for item in self.added:
            if isinstance(item, SettingCollection) and getattr(item, "id", None) is None:
                item.id = self._next_collection_id
                self._next_collection_id += 1
            if isinstance(item, SettingItem) and getattr(item, "id", None) is None:
                item.id = self._next_setting_item_id
                self._next_setting_item_id += 1
            if isinstance(item, Character) and getattr(item, "id", None) is None:
                item.id = self._next_character_id
                self._next_character_id += 1


def test_import_chapters_carries_summary_and_outline_assets() -> None:
    book_chapter = BookChapter(
        book_id=1,
        chapter_number=12,
        title="迷雾重重",
        content="章节正文",
        word_count=1234,
        chapter_type="normal",
        volume_number=2,
        volume_title="风起青石",
        summary="本章摘要",
        key_events=json.dumps(["发现密道", "取得旧卷"], ensure_ascii=False),
        appearing_characters=json.dumps(["林舟", "顾晚"], ensure_ascii=False),
        outline_data=json.dumps(
            {
                "scene_goal": "潜入书库查卷",
                "conflict_arc": {"type": "追捕", "result": "险逃"},
                "ending_hook": {"type": "reveal", "content": "密道尽头传来异响"},
            },
            ensure_ascii=False,
        ),
    )
    fake_db = _FakeDB([book_chapter])
    bridge = ProjectBridge(fake_db)
    project = Project(id=99, user_id=1, title="拆书导入项目")

    bridge._import_chapters(project, book_id=1)

    assert len(fake_db.added) == 1
    imported_chapter = fake_db.added[0]
    imported_summary_data = json.loads(imported_chapter.summary_data)

    assert imported_chapter.summary == "本章摘要"
    assert imported_summary_data["source"] == "book_parser"
    assert imported_summary_data["core_summary"] == "本章摘要"
    assert imported_summary_data["original_chapter_number"] == 12
    assert imported_summary_data["original_title"] == "迷雾重重"
    assert imported_summary_data["original_volume_number"] == 2
    assert imported_summary_data["original_volume_title"] == "风起青石"
    assert imported_summary_data["scene_goal"] == "潜入书库查卷"
    assert imported_summary_data["conflict_arc"]["result"] == "险逃"
    assert imported_summary_data["key_events"] == ["发现密道", "取得旧卷"]
    assert imported_summary_data["appearing_characters"] == ["林舟", "顾晚"]
    assert imported_summary_data["audio_adaptation_hint"]["voice_cast"] == ["林舟", "顾晚"]
    assert imported_summary_data["audio_adaptation_hint"]["ending_hook"] == "reveal / 密道尽头传来异响"
    assert imported_summary_data["drama_adaptation_hint"]["scene_objective"] == "潜入书库查卷"
    assert imported_summary_data["drama_adaptation_hint"]["visual_hooks"]
    assert project.word_count == 1234


def test_build_import_structured_memory_payload_from_book_parser_assets() -> None:
    book = BookSource(id=1, user_id=1, title="青石谜城", genre="悬疑奇幻")
    book_chapter = BookChapter(
        book_id=1,
        chapter_number=12,
        title="迷雾重重",
        content="章节正文",
        word_count=1234,
        summary="林舟和顾晚发现书库密道，并听见深处异响。",
        outline_data=json.dumps(
            {
                "foreshadowing": ["黑匣子的来历仍未解释"],
                "ending_hook": {"content": "密道深处传来脚步声"},
            },
            ensure_ascii=False,
        ),
    )
    fake_db = _FakeDB([book_chapter])
    bridge = ProjectBridge(fake_db)
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "main_plot": "林舟调查青石城旧案，并逐步逼近黑匣子的真相。",
                    "plot_arcs": [
                        {
                            "name": "旧案追查",
                            "description": "主角沿着残卷与密道不断逼近真相。",
                            "chapters": [1, 20],
                            "type": "发展",
                        }
                    ],
                    "turning_points": [
                        {"chapter": 12, "event": "发现密道", "significance": "案件进入隐藏线"}
                    ],
                    "conflicts": [
                        {"description": "黑匣子归属仍存争夺", "status": "进行中"}
                    ],
                },
                ensure_ascii=False,
            ),
        ),
        "characters": BookAnalysis(
            book_id=1,
            analysis_type="characters",
            content=json.dumps(
                {
                    "characters": [
                        {
                            "name": "林舟",
                            "role_position": "主角",
                            "story_stance": "主角方",
                            "faction": "青石调查司",
                            "description": "执着追查旧案的调查者",
                        },
                        {
                            "name": "顾晚",
                            "role_position": "盟友",
                            "story_stance": "主角方",
                            "relationship_to_main": "林舟的重要盟友",
                        },
                    ],
                    "character_relationships": [
                        {
                            "character1": "林舟",
                            "character2": "顾晚",
                            "relationship": "盟友",
                            "description": "共同追查旧案",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ),
        "worldview": BookAnalysis(
            book_id=1,
            analysis_type="worldview",
            content=json.dumps(
                {
                    "world_type": "悬疑奇幻",
                    "time_period": "架空近代",
                    "power_systems": [
                        {
                            "name": "秘印术",
                            "description": "通过秘印追踪残留痕迹",
                            "levels": ["初印", "刻印", "显纹"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ),
        "concepts": BookAnalysis(
            book_id=1,
            analysis_type="concepts",
            content=json.dumps(
                {
                    "terms": [
                        {"term": "黑匣子", "definition": "旧案关键遗物，牵动多方争夺"}
                    ]
                },
                ensure_ascii=False,
            ),
        ),
    }

    payload = bridge._build_import_structured_memory_payload(analysis_map, book)

    assert payload is not None
    assert payload["metadata"]["source"] == "book_parser_import"
    assert payload["metadata"]["book_id"] == 1
    assert "【结构化记忆】" in payload["memory_text"]
    assert any("主线" in item for item in payload["structured_memory"]["global_story_arcs"])
    assert any("林舟" in item for item in payload["structured_memory"]["character_states"])
    assert any("顾晚" in item for item in payload["structured_memory"]["relationship_edges"])
    assert any("黑匣子" in item for item in payload["structured_memory"]["pending_foreshadowings"])
    assert any("秘印术" in item for item in payload["structured_memory"]["world_rules_hard_constraints"])
def test_build_concept_text_includes_style_guide() -> None:
    bridge = ProjectBridge(_FakeDB([]))
    book = BookSource(id=1, user_id=1, title="Misty City", genre="mystery fantasy")
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "main_plot": "A detective traces an old case through a sealed archive beneath the city.",
                    "conflicts": [{"description": "Truth and power collide around the same clue."}],
                },
                ensure_ascii=False,
            ),
        ),
        "style": BookAnalysis(
            book_id=1,
            analysis_type="style",
            content=json.dumps(
                {
                    "narrative_perspective": "third-person limited",
                    "narrative_style": "withheld information and tightly controlled reveals",
                    "tone": "cool restrained",
                    "pacing": "measured setup with sharp acceleration at key turns",
                    "language_features": {
                        "vocabulary_level": "literary but restrained",
                        "sentence_style": "short sentences with occasional pressure-building long lines",
                        "rhetoric": ["ellipsis", "contrast"],
                        "dialogue_style": "brief dialogue with subtext",
                    },
                    "description_style": {
                        "scene_description": "cold light and enclosed space dominate the atmosphere",
                        "psychological_description": "interiority is projected through action details",
                    },
                    "strengths": ["strong atmosphere control"],
                    "unique_features": ["clues often emerge as environmental details"],
                    "genre_conventions": "progressive suspense revelation",
                },
                ensure_ascii=False,
            ),
        ),
    }

    concept_text = bridge._build_concept_text(analysis_map, book)

    assert "\u5199\u4f5c\u98ce\u683c\u53c2\u8003" in concept_text
    assert "third-person limited" in concept_text
    assert "cool restrained" in concept_text
    assert "ellipsis" in concept_text
    assert "short sentences" in concept_text


def test_load_analysis_content_skips_parse_error_results() -> None:
    bridge = ProjectBridge(_FakeDB([]))
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
            extra_data=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
        )
    }

    assert bridge._load_analysis_content(analysis_map, "plot") == {}


def legacy_test_build_plot_outline_text_recovers_from_raw_response_preview() -> None:
    bridge = ProjectBridge(_FakeDB([]))
    recovered_payload = {
        "main_plot": "林舟沿着密道线索追查黑匣子的真正归属。",
        "plot_arcs": [
            {
                "name": "密道追查",
                "description": "主角从残卷与旧案之间找到隐藏入口。",
                "chapters": [1, 18],
                "type": "发展",
            }
        ],
        "turning_points": [
            {
                "chapter": 9,
                "event": "发现密道入口",
                "significance": "故事由明线调查转入暗线真相",
            }
        ],
    }
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
            extra_data=json.dumps(
                {
                    "parse_error": True,
                    "raw_response_preview": json.dumps(recovered_payload, ensure_ascii=False),
                },
                ensure_ascii=False,
            ),
        )
    }

    outline_text = bridge._build_plot_outline_text(analysis_map, 1)

    assert "1. 故事概述" in outline_text
    assert "林舟沿着密道线索追查黑匣子的真正归属。" in outline_text
    assert "密道追查" in outline_text
    assert "第9章" in outline_text


def legacy_test_build_plot_outline_text_falls_back_to_chapter_summaries_when_plot_parse_error() -> None:
    fake_db = _FakeDB(
        [
            BookChapter(
                book_id=1,
                chapter_number=1,
                title="雨夜入城",
                summary="林舟抵达青石城，决定重查旧案。",
            ),
            BookChapter(
                book_id=1,
                chapter_number=6,
                title="暗线浮现",
                summary="顾晚带来密道地图，调查从明线转入暗线。",
            ),
            BookChapter(
                book_id=1,
                chapter_number=12,
                title="真相逼近",
                summary="黑匣子归属浮出水面，众人被迫提前决战。",
            ),
        ]
    )
    bridge = ProjectBridge(fake_db)
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
            extra_data=json.dumps(
                {
                    "parse_error": True,
                    "raw_response_preview": '{"main_plot":"截断在这里"',
                },
                ensure_ascii=False,
            ),
        )
    }

    outline_text = bridge._build_plot_outline_text(analysis_map, 1)

    assert "1. 故事概述" in outline_text
    assert "林舟抵达青石城" in outline_text
    assert "黑匣子归属浮出水面" in outline_text
    assert "2. 情节发展" in outline_text
    assert "5. 结局规划" in outline_text


def test_build_world_setting_text_skips_parse_error_worldview() -> None:
    bridge = ProjectBridge(_FakeDB([]))
    analysis_map = {
        "worldview": BookAnalysis(
            book_id=1,
            analysis_type="worldview",
            content=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
            extra_data=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
        )
    }

    assert bridge._build_world_setting_text(analysis_map) == ""


def test_import_settings_adds_style_collection_to_summary_chain() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=7, user_id=1, title="Imported Project")
    analysis_map = {
        "style": BookAnalysis(
            book_id=1,
            analysis_type="style",
            confidence=0.91,
            content=json.dumps(
                {
                    "narrative_perspective": "third-person limited",
                    "tone": "bleak minimalism",
                    "pacing": "slow burn then sharp release",
                    "language_features": {
                        "vocabulary_level": "restrained everyday diction",
                        "dialogue_style": "short exchanges that push hidden tension",
                    },
                    "description_style": "direct action beats with cold scene details",
                    "strengths": ["stable pacing control", "details pay off later"],
                    "unique_features": ["chapter endings often rely on information gaps"],
                },
                ensure_ascii=False,
            ),
        )
    }

    bridge._import_settings(project, analysis_map)

    style_collections = [
        item for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "style"
    ]
    style_items = [item for item in fake_db.added if isinstance(item, SettingItem)]
    settings_summary = build_project_settings_summary(project.id, fake_db)

    assert len(style_collections) == 1
    assert style_collections[0].name == "\u5199\u4f5c\u98ce\u683c\u53c2\u8003"
    assert any(
        item.name == "\u53d9\u4e8b\u89c6\u89d2" and "third-person limited" in (item.content or "")
        for item in style_items
    )
    assert any(
        item.name == "\u6574\u4f53\u57fa\u8c03" and "bleak minimalism" in (item.content or "")
        for item in style_items
    )
    assert "\u5199\u4f5c\u98ce\u683c\u53c2\u8003" in settings_summary
    assert "\u53d9\u4e8b\u89c6\u89d2" in settings_summary
    assert "third-person limited" in settings_summary


def test_import_settings_projects_worldview_assets_into_standard_collections() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=9, user_id=1, title="Imported Project")
    analysis_map = {
        "worldview": BookAnalysis(
            book_id=1,
            analysis_type="worldview",
            confidence=0.93,
            content=json.dumps(
                {
                    "world_type": "mystery fantasy",
                    "locations": [
                        {
                            "name": "青石城",
                            "type": "城市",
                            "description": "旧案调查的主舞台",
                            "importance": "high",
                        },
                        {
                            "name": "藏书楼",
                            "type": "建筑",
                            "description": "保管旧案卷宗的档案馆",
                        },
                    ],
                    "factions": [
                        {
                            "name": "青石调查局",
                            "type": "组织",
                            "description": "负责追查旧案与维持秩序",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
    }

    bridge._import_settings(project, analysis_map)

    collections = [item for item in fake_db.added if isinstance(item, SettingCollection)]
    categories = {collection.category for collection in collections}

    assert {"worldview", "map_system", "organization_force_system"} <= categories

    map_collection = next(collection for collection in collections if collection.category == "map_system")
    force_collection = next(
        collection for collection in collections if collection.category == "organization_force_system"
    )
    map_items = [
        item for item in fake_db.added
        if isinstance(item, SettingItem) and item.collection_id == map_collection.id
    ]
    force_items = [
        item for item in fake_db.added
        if isinstance(item, SettingItem) and item.collection_id == force_collection.id
    ]

    assert map_collection.name == "地图体系"
    assert map_collection.max_depth == 4
    assert map_collection.hierarchy_config
    assert any(
        item.name == "青石城"
        and "类型: 城市" in (item.content or "")
        and "重要性: high" in (item.content or "")
        and item.path == "地图体系/青石城"
        and item.node_type == "detail"
        and item.is_leaf is True
        for item in map_items
    )
    assert any(
        item.name == "藏书楼"
        and "档案馆" in (item.content or "")
        for item in map_items
    )
    assert force_collection.name == "组织势力体系"
    assert force_collection.hierarchy_config
    assert any(
        item.name == "青石调查局"
        and "类型: 组织" in (item.content or "")
        and "维持秩序" in (item.content or "")
        and item.path == "组织势力体系/青石调查局"
        for item in force_items
    )


def test_import_characters_normalizes_mentions_and_backfills_missing_cards() -> None:
    book_chapters = [
        BookChapter(
            book_id=1,
            chapter_number=1,
            title="Chapter 1",
            appearing_characters=json.dumps(
                ["\u6797\u6f88\uff08\u961f\u957f\uff09", "\u987e\u665a"],
                ensure_ascii=False,
            ),
        ),
        BookChapter(
            book_id=1,
            chapter_number=2,
            title="Chapter 2",
            appearing_characters=json.dumps(
                ["\u6797\u6f88", "\u6c88\u781a"],
                ensure_ascii=False,
            ),
        ),
    ]
    fake_db = _FakeDB(book_chapters)
    bridge = ProjectBridge(fake_db)
    project = Project(id=11, user_id=1, title="Imported Project")
    analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "\u6797\u6f88",
                        "aliases": ["\u961f\u957f"],
                        "role_position": "\u4e3b\u89d2",
                        "story_stance": "\u4e3b\u89d2\u65b9",
                        "faction": "\u9752\u77f3\u8c03\u67e5\u5c40",
                        "description": "\u6267\u7740\u8ffd\u67e5\u65e7\u6848\u7684\u8c03\u67e5\u8005",
                        "personality_anchor": ["\u51b7\u9759", "\u654f\u9510"],
                        "ability_outline": ["\u75d5\u8ff9\u63a8\u6f14"],
                        "first_appearance_chapter": 1,
                        "importance_level": "\u6838\u5fc3\u89d2\u8272",
                    },
                    {
                        "name": "\u987e\u665a",
                        "role_position": "\u76df\u53cb",
                        "story_stance": "\u4e3b\u89d2\u65b9",
                        "relationship_to_main": "\u6797\u6f88\u7684\u91cd\u8981\u76df\u53cb",
                        "description": "\u5171\u540c\u8ffd\u67e5\u7684\u6863\u6848\u7ba1\u7406\u5458",
                    },
                ],
                "character_relationships": [
                    {
                        "character1": "\u6797\u6f88",
                        "character2": "\u987e\u665a",
                        "relationship": "\u76df\u53cb",
                        "description": "\u5171\u540c\u8ffd\u67e5\u65e7\u6848",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, analysis)

    characters = [item for item in fake_db.added if isinstance(item, Character)]
    character_names = {character.name for character in characters}

    assert len(characters) == 3
    assert character_names == {"\u6797\u6f88", "\u987e\u665a", "\u6c88\u781a"}

    lin_che = next(character for character in characters if character.name == "\u6797\u6f88")
    gu_wan = next(character for character in characters if character.name == "\u987e\u665a")
    shen_yan = next(character for character in characters if character.name == "\u6c88\u781a")

    assert lin_che.appearance_status == "\u5df2\u51fa\u573a"
    assert lin_che.first_appearance_chapter == 1
    assert lin_che.faction == "\u9752\u77f3\u8c03\u67e5\u5c40"
    assert lin_che.role == "\u4e3b\u89d2\u65b9"
    assert lin_che.role_position == "\u4e3b\u89d2"
    assert "\u961f\u957f" in (lin_che.profile or "")
    assert "\u51b7\u9759" in (lin_che.profile or "")
    assert "\u75d5\u8ff9\u63a8\u6f14" in (lin_che.profile or "")
    assert "\u3010\u89d2\u8272\u5b9a\u4f4d\u3011\uff1a\u4e3b\u89d2" in (lin_che.profile or "")
    assert any(
        relation.get("target") == "\u987e\u665a" and relation.get("type") == "\u76df\u53cb"
        for relation in json.loads(lin_che.relations or "[]")
    )

    assert gu_wan.appearance_status == "\u5df2\u51fa\u573a"
    assert gu_wan.first_appearance_chapter == 1
    assert gu_wan.role == "\u4e3b\u89d2\u65b9"
    assert gu_wan.role_position == "\u76df\u53cb"
    assert "\u91cd\u8981\u76df\u53cb" in (gu_wan.summary or "") or "\u91cd\u8981\u76df\u53cb" in (gu_wan.profile or "")

    assert shen_yan.appearance_status == "\u5df2\u51fa\u573a"
    assert shen_yan.first_appearance_chapter == 2
    assert shen_yan.importance_level == "\u6b21\u8981\u89d2\u8272"
    assert shen_yan.role in {None, ""}
    assert shen_yan.role_position == "\u529f\u80fd\u89d2\u8272"
    assert "\u62c6\u4e66" in (shen_yan.summary or "")


def test_import_characters_accept_new_semantic_character_alias_fields() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=52, user_id=1, title="Alias Import")
    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "faction": "青石调查局",
                        "appearance_anchor": "眉眼冷厉，习惯先观察后开口",
                        "personality_anchor": ["冷静", "执拗"],
                        "background_status": "停职调查员，仍暗中追查旧案",
                        "motivation": "查明黑匣子真相并洗清旧案污名",
                        "ability_outline": "痕迹推演与现场复盘",
                        "limitation": "过度冒险，难以及时止损",
                        "mainline_role": "负责追查旧案并撬开主线缺口",
                        "mainline_clues": "掌握黑匣子与旧档案两条关键线索",
                        "growth_direction": "从独胆追查转向主动协作",
                    }
                ],
                "character_relationships": [],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, characters_analysis)

    character = next(item for item in fake_db.added if isinstance(item, Character) and item.name == "林澈")

    assert character.summary == "负责追查旧案并撬开主线缺口"
    assert "【外貌锚点】：眉眼冷厉，习惯先观察后开口" in (character.profile or "")
    assert "【性格锚点】：性格：冷静、执拗" in (character.profile or "")
    assert "【背景/当前处境】：停职调查员，仍暗中追查旧案" in (character.profile or "")
    assert "【能力与限制】：能力：痕迹推演与现场复盘" in (character.profile or "")
    assert "限制：过度冒险，难以及时止损" in (character.profile or "")
    assert "【主线绑定】：剧情职责：负责追查旧案并撬开主线缺口" in (character.profile or "")
    assert "关联线索：掌握黑匣子与旧档案两条关键线索" in (character.profile or "")
    assert "【成长方向】：从独胆追查转向主动协作" in (character.profile or "")


def test_build_characters_text_outputs_story_stance_and_role_position() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "description": "负责追查旧案的调查员",
                    },
                    {
                        "name": "顾晚",
                        "role_position": "盟友",
                        "story_stance": "主角方",
                        "relationship_to_main": "林澈的重要盟友",
                        "description": "协助查卷的档案管理员",
                    },
                ],
                "character_relationships": [],
            },
            ensure_ascii=False,
        ),
    )

    text = bridge._build_characters_text({"characters": characters_analysis})

    assert "【故事立场】：主角方" in text
    assert "【角色定位】：主角" in text
    assert "【角色定位】：盟友" in text
    assert "## 支持角色" in text


def test_imported_characters_link_to_projected_standard_collections() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=12, user_id=1, title="Imported Project")
    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "faction": "青石调查局",
                        "description": "负责追查旧案的调查员",
                        "background_status": "常驻青石城藏书楼，负责保管旧案卷宗",
                    }
                ],
                "character_relationships": [],
            },
            ensure_ascii=False,
        ),
    )
    worldview_analysis = BookAnalysis(
        book_id=1,
        analysis_type="worldview",
        confidence=0.9,
        content=json.dumps(
            {
                "locations": [
                    {"name": "青石城", "type": "城市", "description": "旧案发生地"},
                    {"name": "藏书楼", "type": "建筑", "description": "保管卷宗的书库"},
                ],
                "factions": [
                    {"name": "青石调查局", "type": "组织", "description": "负责旧案调查"}
                ],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, characters_analysis)
    bridge._import_settings(project, {"worldview": worldview_analysis})
    result = bridge._link_imported_characters_to_settings(
        project_id=project.id,
        analysis_map={"worldview": worldview_analysis},
    )

    character = next(item for item in fake_db.added if isinstance(item, Character) and item.name == "林澈")
    force_collection = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "organization_force_system"
    )
    map_collection = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "map_system"
    )
    force_item = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingItem)
        and item.collection_id == force_collection.id
        and item.name == "青石调查局"
    )
    city_item = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingItem)
        and item.collection_id == map_collection.id
        and item.name == "青石城"
    )
    archive_item = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingItem)
        and item.collection_id == map_collection.id
        and item.name == "藏书楼"
    )

    assert result["factions"] == 1
    assert result["locations"] == 2
    assert character.faction_item_id == force_item.id
    assert set(json.loads(character.related_locations_json or "[]")) == {city_item.id, archive_item.id}
    assert json.loads(force_item.related_characters or "[]") == [character.id]
    assert json.loads(city_item.related_characters or "[]") == [character.id]
    assert json.loads(archive_item.related_characters or "[]") == [character.id]


def test_sync_imported_characters_to_character_system_creates_reusable_items() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=13, user_id=1, title="Imported Project")
    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "faction": "青石调查局",
                        "description": "负责追查旧案的调查员",
                        "background_status": "常驻青石城藏书楼，负责保管旧案卷宗",
                    },
                    {
                        "name": "顾晚",
                        "role_position": "盟友",
                        "story_stance": "主角方",
                        "description": "协助查卷的档案管理员",
                        "relationship_to_main": "林澈的重要盟友",
                    },
                ],
                "character_relationships": [
                    {
                        "character1": "林澈",
                        "character2": "顾晚",
                        "relationship": "盟友",
                        "description": "共同追查旧案",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    worldview_analysis = BookAnalysis(
        book_id=1,
        analysis_type="worldview",
        confidence=0.91,
        content=json.dumps(
            {
                "locations": [
                    {"name": "青石城", "type": "城市", "description": "旧案发生地"},
                    {"name": "藏书楼", "type": "建筑", "description": "保管卷宗的书库"},
                ],
                "factions": [
                    {"name": "青石调查局", "type": "组织", "description": "负责旧案调查"}
                ],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, characters_analysis)
    bridge._import_settings(project, {"worldview": worldview_analysis})
    bridge._link_imported_characters_to_settings(
        project_id=project.id,
        analysis_map={"worldview": worldview_analysis},
    )
    result = bridge._sync_imported_characters_to_standard_collection(project.id)

    character_collection = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "character_system"
    )
    character_items = [
        item
        for item in fake_db.added
        if isinstance(item, SettingItem) and item.collection_id == character_collection.id
    ]
    lin_che = next(item for item in character_items if item.name == "林澈")
    gu_wan = next(item for item in character_items if item.name == "顾晚")
    lin_che_relations = json.loads(lin_che.relations or "[]")

    assert result["collection_created"] == 1
    assert result["items_synced"] == 2
    assert character_collection.name == "角色体系"
    assert character_collection.hierarchy_config
    assert lin_che.path == "角色体系/主角/林澈"
    assert lin_che.depth == 3
    assert "所属势力: 青石调查局" in (lin_che.content or "")
    assert "关键地点: 青石城、藏书楼" in (lin_che.content or "")
    assert "人物摘要: 负责追查旧案的调查员" in (lin_che.content or "")
    assert any(relation.get("type") == "faction" and relation.get("target") == "青石调查局" for relation in lin_che_relations)
    assert any(relation.get("type") == "location" and relation.get("target") == "青石城" for relation in lin_che_relations)
    assert any(relation.get("type") == "盟友" and relation.get("target") == "顾晚" for relation in lin_che_relations)
    assert "盟友" in json.loads(gu_wan.tags or "[]")


def test_sync_imported_characters_to_character_system_is_idempotent() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=14, user_id=1, title="Imported Project")
    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "faction": "青石调查局",
                        "description": "负责追查旧案的调查员",
                    }
                ],
                "character_relationships": [],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, characters_analysis)
    first_result = bridge._sync_imported_characters_to_standard_collection(project.id)
    second_result = bridge._sync_imported_characters_to_standard_collection(project.id)

    character_collection = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "character_system"
    )
    character_items = [
        item
        for item in fake_db.added
        if isinstance(item, SettingItem) and item.collection_id == character_collection.id
    ]
    lin_che_items = [item for item in character_items if item.name == "林澈"]

    assert first_result["collection_created"] == 1
    assert second_result["collection_created"] == 0
    assert len(lin_che_items) == 1
    assert json.loads(lin_che_items[0].related_characters or "[]") == [1]


def test_link_imported_characters_to_settings_prefers_system_collections() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=21, user_id=1, title="Imported Project")

    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "faction": "青石调查局",
                        "description": "负责追查旧案的调查员",
                        "background_status": "常驻青石城藏书楼，负责保管旧案卷宗",
                    }
                ],
                "character_relationships": [],
            },
            ensure_ascii=False,
        ),
    )
    worldview_analysis = BookAnalysis(
        book_id=1,
        analysis_type="worldview",
        confidence=0.92,
        content=json.dumps(
            {
                "locations": [
                    {"name": "青石城", "type": "city", "description": "旧案发生地"},
                    {"name": "藏书楼", "type": "building", "description": "保管卷宗的书库"},
                ],
                "factions": [
                    {"name": "青石调查局", "type": "organization", "description": "负责追查旧案"}
                ],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, characters_analysis)
    bridge._create_worldview_collection(project, worldview_analysis, order=0)

    force_collection = SettingCollection(
        project_id=project.id,
        name="组织势力体系",
        category="organization_force_system",
    )
    map_collection = SettingCollection(
        project_id=project.id,
        name="地图体系",
        category="map_system",
    )
    fake_db.add(force_collection)
    fake_db.add(map_collection)
    fake_db.flush()

    force_item = SettingItem(collection_id=force_collection.id, name="青石调查局", content="系统势力项")
    city_item = SettingItem(collection_id=map_collection.id, name="青石城", content="系统地点项")
    archive_item = SettingItem(collection_id=map_collection.id, name="藏书楼", content="系统地点项")
    fake_db.add(force_item)
    fake_db.add(city_item)
    fake_db.add(archive_item)

    result = bridge._link_imported_characters_to_settings(
        project_id=project.id,
        analysis_map={"worldview": worldview_analysis},
    )

    character = next(item for item in fake_db.added if isinstance(item, Character) and item.name == "林澈")
    worldview_collection = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "worldview"
    )
    worldview_force_item = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingItem)
        and item.collection_id == worldview_collection.id
        and item.name == "青石调查局"
    )

    assert result["factions"] == 1
    assert result["locations"] == 2
    assert character.faction_item_id == force_item.id
    assert set(json.loads(character.related_locations_json or "[]")) == {city_item.id, archive_item.id}
    assert json.loads(force_item.related_characters or "[]") == [character.id]
    assert json.loads(city_item.related_characters or "[]") == [character.id]
    assert json.loads(archive_item.related_characters or "[]") == [character.id]
    assert worldview_force_item.related_characters is None


def test_link_imported_characters_to_settings_falls_back_to_worldview_items() -> None:
    fake_db = _FakeDB([])
    bridge = ProjectBridge(fake_db)
    project = Project(id=22, user_id=1, title="Imported Project")

    characters_analysis = BookAnalysis(
        book_id=1,
        analysis_type="characters",
        content=json.dumps(
            {
                "characters": [
                    {
                        "name": "林澈",
                        "role_position": "主角",
                        "story_stance": "主角方",
                        "faction": "青石调查局（外勤组）",
                        "description": "负责追查旧案的调查员",
                        "background_status": "长期驻守青石城（东区），追查失踪案",
                    }
                ],
                "character_relationships": [],
            },
            ensure_ascii=False,
        ),
    )
    worldview_analysis = BookAnalysis(
        book_id=1,
        analysis_type="worldview",
        confidence=0.88,
        content=json.dumps(
            {
                "locations": [
                    {"name": "青石城", "type": "city", "description": "故事主舞台"}
                ],
                "factions": [
                    {"name": "青石调查局", "type": "organization", "description": "负责旧案调查"}
                ],
            },
            ensure_ascii=False,
        ),
    )

    bridge._import_characters(project, characters_analysis)
    bridge._create_worldview_collection(project, worldview_analysis, order=0)

    result = bridge._link_imported_characters_to_settings(
        project_id=project.id,
        analysis_map={"worldview": worldview_analysis},
    )

    character = next(item for item in fake_db.added if isinstance(item, Character) and item.name == "林澈")
    worldview_collection = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingCollection) and item.category == "worldview"
    )
    worldview_force_item = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingItem)
        and item.collection_id == worldview_collection.id
        and item.name == "青石调查局"
    )
    worldview_location_item = next(
        item
        for item in fake_db.added
        if isinstance(item, SettingItem)
        and item.collection_id == worldview_collection.id
        and item.name == "青石城"
    )

    assert result["factions"] == 1
    assert result["locations"] == 1
    assert character.faction_item_id == worldview_force_item.id
    assert set(json.loads(character.related_locations_json or "[]")) == {worldview_location_item.id}
    assert json.loads(worldview_force_item.related_characters or "[]") == [character.id]
    assert json.loads(worldview_location_item.related_characters or "[]") == [character.id]


def test_build_plot_outline_text_recovers_from_raw_response_preview() -> None:
    bridge = ProjectBridge(_FakeDB([]))
    recovered_payload = {
        "main_plot": "林舟沿着密道线索追查黑匣子的真正归属。",
        "plot_arcs": [
            {
                "name": "密道追查",
                "description": "主角从残卷与旧案之间找到隐藏入口。",
                "chapters": [1, 18],
                "type": "发展",
            }
        ],
        "turning_points": [
            {
                "chapter": 9,
                "event": "发现密道入口",
                "significance": "故事由明线调查转入暗线真相。",
            }
        ],
    }
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
            extra_data=json.dumps(
                {
                    "parse_error": True,
                    "raw_response_preview": json.dumps(recovered_payload, ensure_ascii=False),
                },
                ensure_ascii=False,
            ),
        )
    }

    outline_text = bridge._build_plot_outline_text(analysis_map, 1)

    assert "故事总纲：" in outline_text
    assert "第9章：" in outline_text
    assert "- 场景目标：" in outline_text
    assert "发现密道入口" in outline_text
    assert "- 情节作用：" in outline_text
    assert "- 关键事件：" in outline_text


def test_build_plot_outline_text_falls_back_to_chapter_summaries_when_plot_parse_error() -> None:
    fake_db = _FakeDB(
        [
            BookChapter(
                book_id=1,
                chapter_number=1,
                title="雨夜入城",
                summary="林舟抵达青石城，决定重查旧案。",
            ),
            BookChapter(
                book_id=1,
                chapter_number=6,
                title="暗线浮现",
                summary="顾晚带来密道地图，调查从明线转入暗线。",
            ),
            BookChapter(
                book_id=1,
                chapter_number=12,
                title="真相逼近",
                summary="黑匣子归属浮出水面，众人被迫提前决战。",
            ),
        ]
    )
    bridge = ProjectBridge(fake_db)
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "parse_error": True,
                    "quality_warning": "LLM 响应未能成功解析为 JSON",
                },
                ensure_ascii=False,
            ),
            extra_data=json.dumps(
                {
                    "parse_error": True,
                    "raw_response_preview": '{"main_plot":"截断在这里',
                },
                ensure_ascii=False,
            ),
        )
    }

    outline_text = bridge._build_plot_outline_text(analysis_map, 1)

    assert "第1章：雨夜入城" in outline_text
    assert "第6章：暗线浮现" in outline_text
    assert "第12章：真相逼近" in outline_text
    assert "- 场景目标：林舟抵达青石城" in outline_text
    assert "- 关键事件：" in outline_text
    assert "故事总纲：" in outline_text


def test_build_plot_outline_text_maps_book_parser_outline_fields_to_standard_schema() -> None:
    fake_db = _FakeDB(
        [
            BookChapter(
                book_id=1,
                chapter_number=3,
                title="潜入书阁",
                summary="林舟与顾晚潜入书阁查卷，险些被巡逻弟子发现。",
                key_events=json.dumps(["潜入书阁查卷", "险逃巡逻追捕"], ensure_ascii=False),
                appearing_characters=json.dumps(["林舟", "顾晚"], ensure_ascii=False),
                outline_data=json.dumps(
                    {
                        "scene_goal": "潜入书阁查卷并确认密道入口",
                        "conflict_arc": {"type": "追捕", "result": "险逃"},
                        "emotion_curve": "谨慎→紧张→喘息未定",
                        "highlight": {
                            "type": "反转",
                            "description": "暗门在旧卷后显现",
                            "intensity": "4星",
                        },
                        "ending_hook": {"type": "悬念", "content": "密道尽头传来脚步声"},
                        "gains": {
                            "character_gains": "取得旧卷",
                            "plot_progress": "确认密道通向旧档库",
                        },
                        "foreshadowing": ["黑匣子的来历未明"],
                    },
                    ensure_ascii=False,
                ),
            )
        ]
    )
    bridge = ProjectBridge(fake_db)
    analysis_map = {
        "plot": BookAnalysis(
            book_id=1,
            analysis_type="plot",
            content=json.dumps(
                {
                    "main_plot": "林舟沿着旧案与密道线索逼近黑匣子的真正归属。",
                },
                ensure_ascii=False,
            ),
        )
    }

    outline_text = bridge._build_plot_outline_text(analysis_map, 1)

    assert "第3章：潜入书阁" in outline_text
    assert "- 场景目标：潜入书阁查卷并确认密道入口" in outline_text
    assert "- 冲突设计：冲突类型：追捕；结果：险逃" in outline_text
    assert "- 关键事件：" in outline_text
    assert "- 爽点类型：反转；内容：暗门在旧卷后显现；强度：4星" in outline_text
    assert "- 涉及人物：林舟、顾晚" in outline_text
    assert "- 人物推进：取得旧卷" in outline_text
    assert "- 情节作用：" in outline_text
    assert "- 结尾钩子：悬念 / 密道尽头传来脚步声" in outline_text
    assert "- 伏笔事项：黑匣子的来历未明" in outline_text
