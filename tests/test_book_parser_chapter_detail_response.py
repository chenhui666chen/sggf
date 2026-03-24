import json
import os
import sys


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

for path in (ROOT_DIR, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


from app.api.v1.book_parser import _build_chapter_content_response
from app.models.book_parser import BookChapter


def test_build_chapter_content_response_parses_structured_assets() -> None:
    chapter = BookChapter(
        book_id=1,
        chapter_number=8,
        title="暗潮初现",
        content="章节正文",
        word_count=2048,
        summary="本章摘要",
        key_events=json.dumps(["发现密信", "夜探地窖"], ensure_ascii=False),
        appearing_characters=json.dumps(["林舟", "顾晚"], ensure_ascii=False),
        outline_data=json.dumps(
            {
                "scene_goal": "确认密信来源",
                "ending_hook": {"type": "suspense", "content": "密道深处传来脚步声"},
            },
            ensure_ascii=False,
        ),
    )

    response = _build_chapter_content_response(chapter)

    assert response.chapter_number == 8
    assert response.summary == "本章摘要"
    assert response.key_events == ["发现密信", "夜探地窖"]
    assert response.appearing_characters == ["林舟", "顾晚"]
    assert response.outline_data["scene_goal"] == "确认密信来源"
    assert response.outline_data["ending_hook"]["type"] == "suspense"


def test_build_chapter_content_response_falls_back_when_json_is_invalid() -> None:
    chapter = BookChapter(
        book_id=1,
        chapter_number=9,
        title="迷雾未散",
        content=None,
        word_count=0,
        key_events="{invalid-json",
        appearing_characters=json.dumps({"name": "林舟"}, ensure_ascii=False),
        outline_data=json.dumps(["unexpected-list"], ensure_ascii=False),
    )

    response = _build_chapter_content_response(chapter)

    assert response.content == ""
    assert response.key_events == []
    assert response.appearing_characters == []
    assert response.outline_data == {}
