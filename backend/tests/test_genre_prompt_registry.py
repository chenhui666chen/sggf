import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.services.prompts.genre_registry import (
    SUPPORTED_GENRES,
    get_genre_character_fields,
    get_genre_chapter_detail_template,
)
from app.services.prompts.stages.chapter_planning import ChapterPlanningPrompts


def test_genre_character_fields_are_append_only_and_do_not_reintroduce_low_value_legacy_fields() -> None:
    for genre in SUPPORTED_GENRES:
        extra_fields = get_genre_character_fields(genre)
        if not extra_fields.strip():
            continue

        assert "标准人物卡后的追加信息" in extra_fields
        assert "不得替代或改写" in extra_fields

    pure_literature_fields = get_genre_character_fields("纯文学")
    assert "象征意义" not in pure_literature_fields
    assert "价值观立场" not in pure_literature_fields

    romance_fields = get_genre_character_fields("言情")
    assert "外貌魅力值" not in romance_fields


def test_genre_chapter_detail_templates_keep_canonical_outline_schema() -> None:
    required_fields = [
        "场景目标",
        "冲突设计",
        "关键事件",
        "涉及人物",
        "人物推进",
        "情节作用",
        "结尾钩子",
        "爽点类型",
        "伏笔事项",
    ]

    for genre in SUPPORTED_GENRES:
        template = get_genre_chapter_detail_template(genre)
        assert template.strip()
        for field in required_fields:
            assert field in template
        assert "情绪曲线" not in template
        assert "信息落地" not in template


def test_chapter_planning_prompt_uses_current_schema_without_legacy_sections() -> None:
    prompt = ChapterPlanningPrompts.get_user_prompt_template()

    assert "- 场景目标：..." in prompt
    assert "- 冲突设计：..." in prompt
    assert "- 关键事件：" in prompt
    assert "- 人物推进：..." in prompt
    assert "- 情节作用：..." in prompt
    assert "- 结尾钩子：..." in prompt
    assert "## 1. 本章定位" not in prompt
    assert "情绪曲线" not in prompt
    assert "信息落地" not in prompt
