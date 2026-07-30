from __future__ import annotations

import io
from pathlib import Path
import sys
import zipfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from app.services.book_parser.chapter_splitter import ChapterSplitter
from app.services.book_parser.file_parser import FileParser


def _require_beautiful_soup():
    try:
        from bs4 import BeautifulSoup
    except (ImportError, OSError) as exc:
        pytest.skip(f"BeautifulSoup is unavailable: {exc}")
    return BeautifulSoup


class _FakeEpubItem:
    def __init__(
        self,
        item_id: str,
        item_type: str = "document",
        *,
        name: str | None = None,
        content: str = "",
        properties: list[str] | None = None,
        media_type: str = "",
    ) -> None:
        self._item_id = item_id
        self._item_type = item_type
        self._name = name or item_id
        self._content = content
        self.properties = properties or []
        self.media_type = media_type

    def get_id(self) -> str:
        return self._item_id

    def get_type(self) -> str:
        return self._item_type

    def get_name(self) -> str:
        return self._name

    def get_content(self) -> bytes:
        return self._content.encode("utf-8")


class _FakeEpubBook:
    def __init__(self) -> None:
        self.spine = [("chapter-2", "yes"), ("nav", "no"), ("chapter-1", "yes")]
        self._items = [
            _FakeEpubItem("chapter-1"),
            _FakeEpubItem("nav"),
            _FakeEpubItem("chapter-2"),
            _FakeEpubItem("appendix"),
        ]

    def get_items(self):
        return list(self._items)


class _FakeTocLink:
    def __init__(self, href: str, title: str) -> None:
        self.href = href
        self.title = title


class _FakeNavEpubBook:
    def __init__(self) -> None:
        self.spine = [("chapter-doc", "yes")]
        self._items = [
            _FakeEpubItem(
                "nav",
                name="OEBPS/nav.xhtml",
                properties=["nav"],
                media_type="application/xhtml+xml",
                content="""
                <html><body>
                  <nav epub:type="toc">
                    <ol>
                      <li><a href="chapter.xhtml#c1">第一章 星河</a></li>
                      <li><a href="chapter.xhtml#c2">第二章 归航</a></li>
                    </ol>
                  </nav>
                </body></html>
                """,
            ),
            _FakeEpubItem(
                "chapter-doc",
                name="OEBPS/chapter.xhtml",
                content="""
                <html><body>
                  <section id="c1"><h1>第一章 星河</h1><p>甲段。</p></section>
                  <section id="c2"><h1>第二章 归航</h1><p>乙段。</p></section>
                </body></html>
                """,
            ),
        ]

    def get_items(self):
        return list(self._items)


def test_ordered_epub_documents_uses_spine_then_falls_back_to_manifest_order():
    ordered = FileParser._ordered_epub_documents(_FakeEpubBook(), "document")

    assert [item.get_id() for item in ordered] == ["chapter-2", "chapter-1", "appendix"]


def test_ordered_epub_documents_includes_html_items_with_unknown_type():
    class Book:
        spine = [("chapter-1", "yes"), ("chapter-2", "yes"), ("nav", "no")]

        def get_items(self):
            return [
                _FakeEpubItem("nav", "unknown", name="OEBPS/nav.xhtml", properties=["nav"], media_type="text/html"),
                _FakeEpubItem("toc", "unknown", name="OEBPS/toc.xhtml", media_type="application/xhtml+xml"),
                _FakeEpubItem("chapter-1", "unknown", name="OEBPS/chapter-1.xhtml", media_type="text/html"),
                _FakeEpubItem("chapter-2", "document", name="OEBPS/chapter-2.xhtml"),
            ]

    ordered = FileParser._ordered_epub_documents(Book(), "document")

    assert [item.get_id() for item in ordered] == ["chapter-1", "chapter-2"]


def test_epub_toc_title_fallback_matches_spine_item_href_and_basename():
    class Book:
        def get_toc(self):
            return [
                _FakeTocLink("Text/chapter-001.xhtml#start", "第一章 星门"),
                (_FakeTocLink("chapter-002.xhtml", "第二章 归航"), []),
            ]

    titles = FileParser._epub_toc_titles_by_href(Book())

    assert FileParser._epub_toc_title_for_item(
        _FakeEpubItem("id-1", name="Text/chapter-001.xhtml"),
        titles,
    ) == "第一章 星门"
    assert FileParser._epub_toc_title_for_item(
        _FakeEpubItem("id-2", name="OEBPS/chapter-002.xhtml"),
        titles,
    ) == "第二章 归航"


def test_infer_epub_title_from_item_identifier_is_conservative():
    assert FileParser._infer_epub_title_from_identifier("Text/chapter_001.xhtml") == "Chapter 001"
    assert FileParser._infer_epub_title_from_identifier("OEBPS/part-iv.html") == "Part Iv"
    assert FileParser._infer_epub_title_from_identifier("OEBPS/body.xhtml") is None


def test_extract_epub_document_text_removes_footnote_links_and_normalizes_quotes():
    BeautifulSoup = _require_beautiful_soup()
    html = """
    <html>
      <body>
        <nav>目录噪声</nav>
        <h1>“第一章”</h1>
        <p>他说：<a href="#fn1">1</a>‘开始吧’。</p>
        <p><a href="chapter2.html">下一章</a></p>
        <script>ignore()</script>
      </body>
    </html>
    """

    text = FileParser._extract_epub_document_text(html, BeautifulSoup)

    assert '"第一章"' in text
    assert "他说：'开始吧'。" in text
    assert "下一章" in text
    assert "目录噪声" not in text
    assert "ignore" not in text


def test_extract_epub_document_text_removes_sup_and_footnote_blocks():
    BeautifulSoup = _require_beautiful_soup()
    html = """
    <html>
      <body>
        <h1>第一章</h1>
        <p>正文开始<sup id="fnref1"><a epub:type="noteref" href="#fn1">[1]</a></sup>继续。</p>
        <aside epub:type="footnote" id="fn1"><p>这里是脚注内容。</p></aside>
        <section class="endnotes"><p>尾注内容。</p></section>
        <p>尾声。</p>
      </body>
    </html>
    """

    text = FileParser._extract_epub_document_text(html, BeautifulSoup)

    assert "正文开始继续。" in text
    assert "尾声。" in text
    assert "[1]" not in text
    assert "这里是脚注内容" not in text
    assert "尾注内容" not in text


def test_extract_epub_document_text_preserves_structural_audio_blocks():
    BeautifulSoup = _require_beautiful_soup()
    html = """
    <html>
      <body>
        <p>第一行<br/>第二行。</p>
        <hr/>
        <blockquote>信上写着：别回头。</blockquote>
        <figure><figcaption>图1 星图。</figcaption></figure>
        <ul><li>待办一</li><li>待办二</li></ul>
        <div class="poem">群星落下。</div>
      </body>
    </html>
    """

    text = FileParser._extract_epub_document_text(html, BeautifulSoup)

    assert text.splitlines() == [
        "第一行 [pause:0.5s] 第二行。",
        "[pause:1.5s]",
        "信上写着：别回头。",
        "图1 星图。",
        "待办一",
        "待办二",
        "群星落下。",
    ]


def test_extract_epub_document_text_removes_inline_notes_at_chapter_end():
    BeautifulSoup = _require_beautiful_soup()
    html = """
    <html>
      <body>
        <p>她推开门。</p>
        <p>星光落进屋里。</p>
        <p>Notes</p>
        <p>1. This edition note should not be narrated.</p>
        <p>2. Another endnote.</p>
      </body>
    </html>
    """

    text = FileParser._extract_epub_document_text(html, BeautifulSoup)

    assert text.splitlines() == ["她推开门。", "星光落进屋里。"]


def test_strip_epub_inline_note_blocks_keeps_numbered_body_lists():
    blocks = [
        "第一段。",
        "1. 第一条线索。",
        "2. 第二条线索。",
        "3. 第三条线索。",
        "她终于明白了。",
    ]

    assert FileParser._strip_epub_inline_note_blocks(blocks) == blocks


def test_extract_epub_document_title_reads_headings_and_chapter_classes():
    BeautifulSoup = _require_beautiful_soup()

    assert (
        FileParser._extract_epub_document_title(
            "<html><body><h2>第二章 归航</h2><p>正文。</p></body></html>",
            BeautifulSoup,
        )
        == "第二章 归航"
    )
    assert (
        FileParser._extract_epub_document_title(
            "<html><body><div class='chapter-title'>Chapter 3: Home</div><p>Body.</p></body></html>",
            BeautifulSoup,
        )
        == "Chapter 3: Home"
    )


def test_epub_spine_fallback_uses_document_title_marker_when_nav_is_missing():
    BeautifulSoup = _require_beautiful_soup()
    html = """
    <html><body>
      <div class="chapter-title">第三章 微光</div>
      <p>她听见远处的钟声。</p>
    </body></html>
    """
    text = FileParser._extract_epub_document_text(html, BeautifulSoup)
    title = FileParser._extract_epub_document_title(html, BeautifulSoup)
    formatted = FileParser._format_epub_chapter_marker(title, text)

    result = ChapterSplitter().split(formatted)

    assert result.chapters[0].title == "第三章 微光"
    assert result.chapters[0].content == "她听见远处的钟声。"


def test_filter_epub_non_narrative_parts_trims_boundary_matter():
    parts, skipped = FileParser._filter_epub_non_narrative_parts([
        ("Copyright", "Copyright 2024. All rights reserved. ISBN 978-0-123456-78-9."),
        ("第一章 星光", "她推开门。" * 80),
        ("第二章 归航", "船回来了。" * 80),
        ("Index", "Alpha, 1, 5\nBeta, 2, 8\nGamma, 3, 12\nDelta, 4, 20\nEcho, 5, 25\nFoxtrot, 6, 30"),
    ])

    assert [title for title, _ in parts] == ["第一章 星光", "第二章 归航"]
    assert skipped == [
        {"index": 0, "title": "Copyright", "reason": "title"},
        {"index": 3, "title": "Index", "reason": "title"},
    ]


def test_filter_epub_non_narrative_parts_keeps_middle_notes_and_chapters():
    parts, skipped = FileParser._filter_epub_non_narrative_parts([
        ("第一章", "故事开始。" * 80),
        ("Notes", "这是一段在正文中出现的角色笔记。" * 80),
        ("第二章", "故事继续。" * 80),
    ])

    assert [title for title, _ in parts] == ["第一章", "Notes", "第二章"]
    assert skipped == []


def test_parse_pdf_uses_pypdf_dependency_and_preserves_metadata():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": "星河样章", "/Author": "测试作者"})
    pdf_buffer = io.BytesIO()
    writer.write(pdf_buffer)

    parsed = FileParser().parse(pdf_buffer.getvalue(), "sample.pdf")

    assert parsed.success is True
    assert parsed.title == "星河样章"
    assert parsed.author == "测试作者"
    assert parsed.metadata["pages"] == 1


def test_extract_pdf_outline_entries_flattens_and_dedupes_pages():
    class Destination:
        def __init__(self, title: str, page_index: int) -> None:
            self.title = title
            self.page_index = page_index

    class Reader:
        outline = [
            Destination("封面", 0),
            [Destination("第一章 星光", 1), Destination("第一章 重复", 1)],
            Destination("第二章 归航", 3),
        ]

        def get_destination_page_number(self, item):
            return item.page_index

    entries = FileParser._extract_pdf_outline_entries(Reader())

    assert entries == [
        {"title": "封面", "page_index": 0},
        {"title": "第一章 星光", "page_index": 1},
        {"title": "第二章 归航", "page_index": 3},
    ]


def test_format_pdf_text_with_outline_adds_chapter_markers():
    text = FileParser._format_pdf_text_with_outline(
        [
            "版权页。",
            "第一章 星光\n她推开门。",
            "雨声落下。",
            "第二章 归航\n船回来了。",
        ],
        [
            {"title": "第一章 星光", "page_index": 1},
            {"title": "第二章 归航", "page_index": 3},
        ],
    )

    result = ChapterSplitter().split(text)

    assert [chapter.title for chapter in result.chapters] == ["导言", "第一章 星光", "第二章 归航"]
    assert result.chapters[0].content == "版权页。"
    assert result.chapters[1].content == "她推开门。\n\n雨声落下。"
    assert result.chapters[2].content == "船回来了。"


def test_strip_pdf_repeated_boundary_lines_removes_headers_footers_and_page_numbers():
    pages, removed_count = FileParser._strip_pdf_repeated_boundary_lines([
        "星河手记\n第一章正文第一段。\n1",
        "星河手记\n第一章正文第二段。\n2",
        "星河手记\n第一章正文第三段。\n3",
    ])

    assert pages == [
        "第一章正文第一段。",
        "第一章正文第二段。",
        "第一章正文第三段。",
    ]
    assert removed_count == 6


def test_format_pdf_markdown_chapter_markers_uses_repeated_heading_level():
    text, marker_count = FileParser._format_pdf_markdown_chapter_markers(
        "\n".join([
            "# 星河手记",
            "封面文案。",
            "",
            "## 第一章 星光",
            "她推开门。",
            "",
            "## 第二章 归航",
            "船回来了。",
        ])
    )

    result = ChapterSplitter().split(text)

    assert marker_count == 2
    assert "<<CHAPTER_MARKER:星河手记>>" not in text
    assert [chapter.title for chapter in result.chapters] == ["第一章 星光", "第二章 归航"]
    assert [chapter.content for chapter in result.chapters] == ["她推开门。", "船回来了。"]


def test_format_pdf_markdown_chapter_markers_ignores_single_document_title():
    text, marker_count = FileParser._format_pdf_markdown_chapter_markers(
        "# 星河手记\n封面文案。\n正文。"
    )

    assert text == ""
    assert marker_count == 0


def test_parse_txt_extracts_header_metadata_and_removes_metadata_lines():
    parsed = FileParser().parse(
        "Title: 耳畔星河\nAuthor: 佚名\n\n# 序幕\n正文开始。".encode("utf-8"),
        "book.txt",
    )

    assert parsed.success is True
    assert parsed.title == "耳畔星河"
    assert parsed.author == "佚名"
    assert parsed.metadata["encoding"] == "utf-8"
    assert "Title:" not in parsed.text
    assert "Author:" not in parsed.text
    assert "# 序幕" in parsed.text
    assert "正文开始。" in parsed.text


def test_parse_txt_markdown_headings_become_explicit_chapter_markers():
    parsed = FileParser().parse(
        "\n".join([
            "Title: 星河手记",
            "",
            "# 星河手记",
            "",
            "## 第一章 星光",
            "甲段。",
            "",
            "## 第二章 归航",
            "乙段。",
        ]).encode("utf-8"),
        "book.txt",
    )

    result = ChapterSplitter().split(parsed.text)

    assert "<<CHAPTER_MARKER:星河手记>>" not in parsed.text
    assert "<<CHAPTER_MARKER:第一章 星光>>" in parsed.text
    assert "<<CHAPTER_MARKER:第二章 归航>>" in parsed.text
    assert [chapter.title for chapter in result.chapters] == ["第一章 星光", "第二章 归航"]
    assert [chapter.content for chapter in result.chapters] == ["甲段。", "乙段。"]


def test_parse_txt_markdown_heading_voice_hints_are_not_read_as_titles():
    parsed = FileParser().parse(
        "\n".join([
            "# 第一章 % female_voice",
            "甲段。",
            "",
            "# 第二章 % male_voice",
            "乙段。",
        ]).encode("utf-8"),
        "book.txt",
    )

    result = ChapterSplitter().split(parsed.text)

    assert [chapter.title for chapter in result.chapters] == ["第一章", "第二章"]
    assert parsed.metadata["chapter_voice_hints"] == [
        {"chapter_index": 1, "title": "第一章", "voice_hint": "female_voice"},
        {"chapter_index": 2, "title": "第二章", "voice_hint": "male_voice"},
    ]


def test_parse_markdown_strips_front_matter_comments_and_chapter_metadata():
    parsed = FileParser().parse(
        "\n".join([
            "---",
            "title: Star Crossing",
            "author: Ada",
            "description: Draft manuscript",
            "---",
            "<!-- editor-only note -->",
            "# Chapter 1",
            "**POV**: Alice",
            "**Timeline**: Day 1",
            "**Location**: Dock",
            "## Scene Goals",
            "- [ ] Find the key",
            "The gate opened.",
            "",
            "# Chapter 2",
            "**Word Count**: 1200",
            "They crossed the river.",
        ]).encode("utf-8"),
        "book.md",
    )

    assert parsed.title == "Star Crossing"
    assert parsed.author == "Ada"
    assert parsed.metadata["description"] == "Draft manuscript"
    assert "editor-only note" not in parsed.text
    assert "POV" not in parsed.text
    assert "Scene Goals" not in parsed.text
    assert "- [ ]" not in parsed.text

    result = ChapterSplitter().split(parsed.text)

    assert [chapter.title for chapter in result.chapters] == ["Chapter 1", "Chapter 2"]
    assert [chapter.content for chapter in result.chapters] == [
        "The gate opened.",
        "They crossed the river.",
    ]


def test_parse_markdown_scene_breaks_become_pause_tags():
    parsed = FileParser().parse(
        "\n".join([
            "# Chapter 1",
            "Before the cut.",
            "* * *",
            "After the cut.",
            "",
            "# Chapter 2",
            "Another scene.",
            "---",
            "Last scene.",
        ]).encode("utf-8"),
        "book.md",
    )

    result = ChapterSplitter().split(parsed.text)

    assert [chapter.content for chapter in result.chapters] == [
        "Before the cut.\n[pause:1.5s]\nAfter the cut.",
        "Another scene.\n[pause:1.5s]\nLast scene.",
    ]


def test_chapter_splitter_supports_roman_numeral_headings_and_volumes():
    result = ChapterSplitter().split(
        "\n".join([
            "Part II: The Crossing",
            "",
            "Chapter IV: The Door",
            "The door opened.",
            "",
            "V. The Return",
            "They came back.",
        ])
    )

    assert [chapter.title for chapter in result.chapters] == ["The Door", "The Return"]
    assert [chapter.original_number for chapter in result.chapters] == ["IV", "V"]
    assert [chapter.part_number for chapter in result.chapters] == [2, 2]
    assert result.volumes[0].number == 2
    assert result.volumes[0].title == "The Crossing"


def test_chapter_splitter_supports_act_scene_section_headings():
    result = ChapterSplitter().split(
        "\n".join([
            "Act I: Arrival",
            "The curtain rises.",
            "",
            "Scene 2: The Gate",
            "They wait outside.",
            "",
            "Section III: Methods",
            "The record begins.",
            "",
            "第三幕：归来",
            "灯光暗下。",
        ])
    )

    assert [chapter.title for chapter in result.chapters] == [
        "Arrival",
        "The Gate",
        "Methods",
        "归来",
    ]
    assert [chapter.original_number for chapter in result.chapters] == ["I", "2", "III", "三"]


def test_extract_epub_cover_payload_reads_opf_cover_manifest_item():
    epub_bytes = io.BytesIO()
    cover_bytes = b"\xff\xd8cover\xff\xd9"
    with zipfile.ZipFile(epub_bytes, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
              </rootfiles>
            </container>
            """,
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
            <package xmlns="http://www.idpf.org/2007/opf">
              <metadata>
                <meta name="cover" content="cover-image"/>
              </metadata>
              <manifest>
                <item id="cover-image" href="Images/cover.jpg" media-type="image/jpeg"/>
              </manifest>
            </package>
            """,
        )
        archive.writestr("OEBPS/Images/cover.jpg", cover_bytes)

    payload = FileParser._extract_epub_cover_payload(epub_bytes.getvalue())

    assert payload is not None
    assert payload["cover_image_bytes"] == cover_bytes
    assert payload["cover_image_extension"] == ".jpg"
    assert payload["cover_image_media_type"] == "image/jpeg"
    assert payload["cover_image_path"] == "OEBPS/Images/cover.jpg"


def test_extract_epub_navigation_text_parts_slices_html_nav_anchors():
    BeautifulSoup = _require_beautiful_soup()

    parts = FileParser._extract_epub_navigation_text_parts(
        _FakeNavEpubBook(),
        "document",
        BeautifulSoup,
    )

    assert parts == [
        ("第一章 星河", "第一章 星河\n甲段。"),
        ("第二章 归航", "第二章 归航\n乙段。"),
    ]


def test_format_epub_chapter_markers_are_used_by_chapter_splitter():
    text = "\n\n".join([
        FileParser._format_epub_chapter_marker("第一章 星河", "第一章 星河\n甲段。"),
        FileParser._format_epub_chapter_marker("第二章 归航", "第二章 归航\n乙段。"),
    ])

    result = ChapterSplitter().split(text)

    assert [chapter.title for chapter in result.chapters] == ["第一章 星河", "第二章 归航"]
    assert [chapter.content for chapter in result.chapters] == ["甲段。", "乙段。"]


def test_format_epub_chapter_marker_removes_equivalent_heading_prefix():
    formatted = FileParser._format_epub_chapter_marker(
        "Chapter 1: The Return",
        "Chapter 1\nThe ship came home.",
    )

    assert formatted == "<<CHAPTER_MARKER:Chapter 1: The Return>>\nThe ship came home."


def test_format_epub_chapter_marker_keeps_different_opening_line():
    formatted = FileParser._format_epub_chapter_marker(
        "第一章 星河",
        "序幕。\n甲段。",
    )

    assert formatted == "<<CHAPTER_MARKER:第一章 星河>>\n序幕。\n甲段。"


def test_format_epub_chapter_marker_does_not_confuse_chapter_one_and_ten():
    formatted = FileParser._format_epub_chapter_marker(
        "Chapter 10: Later",
        "Chapter 1\nEarlier context.",
    )

    assert formatted == "<<CHAPTER_MARKER:Chapter 10: Later>>\nChapter 1\nEarlier context."
