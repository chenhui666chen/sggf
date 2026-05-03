from app.services.audiobook.safe_filename import (
    build_safe_filename,
    ensure_unique_filename,
    sanitize_filename_component,
)


def test_sanitize_filename_component_removes_unsafe_chars_and_reserved_names():
    assert sanitize_filename_component('CON<>:"/\\|?*') == "CON_file"
    assert sanitize_filename_component("  第 1 章：重逢 / 风暴  ") == "第_1_章_重逢_风暴"
    assert sanitize_filename_component("", fallback="audiobook") == "audiobook"


def test_build_safe_filename_preserves_utf8_boundary_and_extension():
    filename = build_safe_filename("章节" * 80, ".m4b", fallback="book", max_bytes=96)

    assert filename.endswith(".m4b")
    assert len(filename.encode("utf-8")) <= 96
    assert "_" in filename


def test_build_safe_filename_supports_multi_part_extension():
    filename = build_safe_filename("chapter_12", ".labels.txt", fallback="chapter")

    assert filename == "chapter_12.labels.txt"


def test_ensure_unique_filename_adds_suffix_case_insensitively():
    used = {"chapter.wav"}

    filename = ensure_unique_filename("chapter.wav", used)

    assert filename == "chapter_2.wav"
    assert "chapter_2.wav" in used
