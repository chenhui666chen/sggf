# -*- coding: utf-8 -*-
"""文本编码门禁脚本的检测器与仓库级防回归检查。"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_text_encoding import (
    KIND_INVALID_UTF8,
    KIND_MOJIBAKE_SIGNATURE,
    KIND_REPLACEMENT_CHAR,
    is_text_file,
    iter_tracked_text_files,
    line_of_byte_offset,
    scan_bytes,
    scan_files,
)


def test_clean_utf8_has_no_issue():
    raw = "第一行\n天下事有大相反者\n".encode("utf-8")
    assert scan_bytes("a.md", raw) == []


def test_gbk_bytes_are_reported_as_invalid_utf8():
    lines = ["ok", "中文表演要求", "tail"]
    raw = "\n".join(lines).encode("gbk")
    issues = scan_bytes("broken.py", raw)
    assert [i.kind for i in issues] == [KIND_INVALID_UTF8]
    assert issues[0].line == 2


def test_replacement_char_is_reported_with_line_number():
    raw = "第一行\n\ufffd\ufffd 丢了两个汉字\n".encode("utf-8")
    issues = scan_bytes("damaged.md", raw)
    assert [(i.kind, i.line) for i in issues] == [(KIND_REPLACEMENT_CHAR, 2)]
    assert issues[0].detail == "count=2"


def test_double_decoded_signature_is_reported():
    raw = "旁白\n锟斤拷烫烫烫\n".encode("utf-8")
    issues = scan_bytes("damaged.md", raw)
    assert [i.kind for i in issues] == [KIND_MOJIBAKE_SIGNATURE]
    assert issues[0].line == 2


def test_line_of_byte_offset_counts_preceding_newlines():
    raw = b"a\nb\n\xc3\xa7d"
    assert line_of_byte_offset(raw, 4) == 3


def test_binary_extensions_are_out_of_scope():
    assert not is_text_file("scripts/test_fixtures/test_image.png")
    assert not is_text_file("docs/report.xlsx")
    assert is_text_file("shared/seed_tts_2_0_voices.json")
    assert is_text_file("dev-kill.PS1")


def test_scan_files_skips_missing_entries(tmp_path: Path):
    (tmp_path / "ok.md").write_bytes("正常中文\n".encode("utf-8"))
    issues = scan_files(["ok.md", "gone.md"], root=tmp_path)
    assert issues == []


def test_tracked_listing_only_returns_text_files():
    files = iter_tracked_text_files(["scripts"])
    assert files
    assert all(is_text_file(item) for item in files)


@pytest.mark.parametrize(
    "pathspec",
    ["backend/app", "frontend/src", "shared", "docs", "config", "scripts", "tests"],
)
def test_source_directories_are_encoding_clean(pathspec: str):
    files = iter_tracked_text_files([pathspec])
    assert files, f"{pathspec} 下没有扫到文本文件，pathspec 可能写错"
    issues = scan_files(files)
    assert issues == []
