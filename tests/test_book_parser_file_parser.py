import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest


epub = pytest.importorskip("ebooklib.epub")


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

for path in (ROOT_DIR, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def _load_file_parser_module():
    module_path = Path(ROOT_DIR) / "backend" / "app" / "services" / "book_parser" / "file_parser.py"
    spec = importlib.util.spec_from_file_location("book_file_parser", module_path)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_file_parser_parses_utf8_txt() -> None:
    module = _load_file_parser_module()
    parser = module.FileParser()

    result = parser.parse("Chapter 1\nPlain text body.".encode("utf-8"), "sample.txt")

    assert result.success is True
    assert result.format == module.FileFormat.TXT
    assert result.metadata["encoding"] == "utf-8"
    assert "Plain text body." in result.text


def test_file_parser_parses_epub_documents() -> None:
    module = _load_file_parser_module()
    parser = module.FileParser()

    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test EPUB")
    book.set_language("en")
    book.add_author("Test Author")

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter1.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>EPUB body text.</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            epub.write_epub(str(temp_path), book)

        result = parser.parse(temp_path.read_bytes(), "sample.epub")
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()

    assert result.success is True
    assert result.format == module.FileFormat.EPUB
    assert result.title == "Test EPUB"
    assert result.author == "Test Author"
    assert "EPUB body text." in result.text
