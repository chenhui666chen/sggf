#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库文本编码门禁：拦截非 UTF-8 字节、U+FFFD 替换符与二次转码乱码签名。

只读检查，不修改任何文件。文件清单取自 `git ls-files`，因此 `.tmp/` 等
被忽略的临时产物不会进入扫描范围；扩展名白名单避免把二进制资源当文本读。

用法：
    python scripts/check_text_encoding.py
    python scripts/check_text_encoding.py --paths backend/app shared
    python scripts/check_text_encoding.py --verbose
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 只扫描确定是文本的扩展名；png/xlsx/docx 之类的二进制文件交给别的检查。
TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".md",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".txt",
        ".ts",
        ".tsx",
        ".js",
        ".cjs",
        ".mjs",
        ".jsx",
        ".css",
        ".html",
        ".mako",
        ".sh",
        ".bat",
        ".ps1",
        ".conf",
        ".ini",
        ".http",
        ".env",
        ".example",
        ".sql",
    }
)

REPLACEMENT_CHAR = "\ufffd"

# UTF-8 替换符在 GBK 环境下再被解码一次的固定产物，出现即证明发生过二次转码。
MOJIBAKE_SIGNATURES = ("锟斤拷",)

KIND_INVALID_UTF8 = "invalid_utf8"
KIND_REPLACEMENT_CHAR = "replacement_char"
KIND_MOJIBAKE_SIGNATURE = "mojibake_signature"


@dataclass(frozen=True)
class EncodingIssue:
    path: str
    kind: str
    line: int
    detail: str


def is_text_file(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in TEXT_EXTENSIONS


def iter_tracked_text_files(
    paths: Sequence[str] = (),
    root: Path = PROJECT_ROOT,
) -> List[str]:
    """列出 git 跟踪的文本文件（仓库相对路径）。"""
    cmd = ["git", "ls-files", "-z"]
    if paths:
        cmd += ["--", *paths]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    names = [item.decode("utf-8") for item in proc.stdout.split(b"\x00") if item]
    return [name for name in names if is_text_file(name)]


def line_of_byte_offset(raw: bytes, offset: int) -> int:
    return raw[:offset].count(b"\n") + 1


def scan_bytes(rel_path: str, raw: bytes) -> List[EncodingIssue]:
    """在单个文件的字节流上判定编码问题。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [
            EncodingIssue(
                path=rel_path,
                kind=KIND_INVALID_UTF8,
                line=line_of_byte_offset(raw, exc.start),
                detail=f"byte offset {exc.start}: {exc.reason}",
            )
        ]

    issues: List[EncodingIssue] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if REPLACEMENT_CHAR in line:
            issues.append(
                EncodingIssue(
                    path=rel_path,
                    kind=KIND_REPLACEMENT_CHAR,
                    line=line_no,
                    detail=f"count={line.count(REPLACEMENT_CHAR)}",
                )
            )
        for signature in MOJIBAKE_SIGNATURES:
            if signature in line:
                issues.append(
                    EncodingIssue(
                        path=rel_path,
                        kind=KIND_MOJIBAKE_SIGNATURE,
                        line=line_no,
                        detail=f"signature={signature!r}",
                    )
                )
    return issues


def scan_files(
    rel_paths: Iterable[str],
    root: Path = PROJECT_ROOT,
) -> List[EncodingIssue]:
    issues: List[EncodingIssue] = []
    for rel in rel_paths:
        target = root / rel
        if not target.is_file():
            continue
        issues.extend(scan_bytes(rel, target.read_bytes()))
    return issues


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查仓库文本文件的编码完整性")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="限定 git pathspec 范围，默认扫描全部跟踪文件",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="逐条打印问题详情（默认只打印文件与行号）",
    )
    args = parser.parse_args(argv)

    files = iter_tracked_text_files(args.paths)
    issues = scan_files(files)

    print(f"扫描文本文件 {len(files)} 个，发现问题 {len(issues)} 处")
    if not issues:
        return 0

    by_kind: dict[str, int] = {}
    for issue in issues:
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind}: {count}")

    for issue in issues:
        if args.verbose:
            print(f"{issue.path}:{issue.line}: {issue.kind} ({issue.detail})")
        else:
            print(f"{issue.path}:{issue.line}: {issue.kind}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
