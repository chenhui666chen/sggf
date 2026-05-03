from __future__ import annotations

from app.services.book_parser.chapter_splitter import ChapterSplitter
from app.services.book_parser.text_cleaner import TextCleaner
from app.services.book_parser.text_metrics import count_readable_units


def test_count_readable_units_counts_multilingual_text():
    assert count_readable_units("你好 world 2026") == 4
    assert count_readable_units("かな тест") == 3


def test_text_cleaner_and_chapter_splitter_use_multilingual_counts():
    clean_result = TextCleaner().clean("Hello world\n你好")
    split_result = ChapterSplitter().split(
        "\n".join([
            "Chapter 1",
            "Hello world",
            "你好",
            "",
            "Chapter 2",
            "Next step",
        ])
    )

    assert clean_result.word_count == 4
    assert [chapter.word_count for chapter in split_result.chapters] == [4, 2]
    assert split_result.total_words == 6


def test_text_cleaner_repairs_english_hyphenated_line_breaks():
    clean_result = TextCleaner().clean("This exam-\nple stays well-formed.\n中文-\n换行不合并。")

    assert "example" in clean_result.text
    assert "exam-" not in clean_result.text
    assert "中文-\n换行" in clean_result.text


def test_text_cleaner_removes_standalone_isbn_metadata_lines():
    clean_result = TextCleaner().clean(
        "ISBN: 978-0-123456-78-9\n\n第一章\n故事开始。\n这句提到 ISBN 但属于正文。"
    )

    assert "978-0-123456-78-9" not in clean_result.text
    assert "第一章" in clean_result.text
    assert "这句提到 ISBN 但属于正文。" in clean_result.text
