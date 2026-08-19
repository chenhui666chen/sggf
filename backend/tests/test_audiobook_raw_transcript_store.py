"""RawTranscriptStore 存储层单元测试。

覆盖（§12.2 原始转写数据治理六项约束）：
- 加密 at-rest：磁盘不含明文正文；
- project 级隔离：delete_project 只删对应项目文件；
- chapter 级隔离：delete_chapter 只删对应章节文件；
- 生命周期级联清理：项目/章节删除后 URI 不可解析；
- 幂等存储：相同内容返回相同 URI；
- 空密钥失败关闭。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[2]
for _path in (ROOT_DIR, PROJECT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.raw_transcript_store import (  # noqa: E402
    EncryptionKeyError,
    RawTranscriptStore,
)


_TEST_KEY = "test-secret-32-chars!!test-secret-!!"


def _store(
    tmp_path: Path, *, key: str = _TEST_KEY, **kw: Any
) -> RawTranscriptStore:
    return RawTranscriptStore(str(tmp_path / "transcripts"), encryption_key=key, **kw)


class TestConstruction:
    def test_empty_key_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(EncryptionKeyError):
            _store(tmp_path, key="")

    def test_short_key_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(EncryptionKeyError):
            _store(tmp_path, key="short")

    def test_creates_storage_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "x"
        assert not d.exists()
        RawTranscriptStore(str(d), encryption_key=_TEST_KEY)
        assert d.is_dir()


class TestStoreAndResolve:
    def test_store_and_resolve(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        uri_t, uri_tl = store.store(
            project_id="proj-a",
            chapter_id="ch-1",
            raw_transcript="hello world",
            raw_timeline='[{"start": 0, "end": 1000, "text": "hello"}]',
            filtered_provider_metadata={"provider": "seed"},
        )
        assert uri_t.startswith("raw-transcript://store/proj-a/ch-1/")
        assert uri_t == uri_tl  # same file, same URI

        result = store.resolve(uri_t)
        assert result is not None
        text, timeline, meta = result
        assert text == "hello world"
        assert timeline == store.resolve(uri_tl)[1]
        assert meta == {"provider": "seed"}

    def test_store_idempotent(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        uri1, _ = store.store("p", "c", "same text", "[]", {})
        uri2, _ = store.store("p", "c", "same text", "[]", {})
        assert uri1 == uri2

    def test_different_content_different_uri(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        uri1, _ = store.store("p", "c", "text A", "[]", {})
        uri2, _ = store.store("p", "c", "text B", "[]", {})
        assert uri1 != uri2

    def test_resolve_nonexistent_uri_returns_none(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.resolve("raw-transcript://store/nonexistent/p/xxx") is None

    def test_resolve_invalid_format_returns_none(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.resolve("") is None
        assert store.resolve("not-a-uri") is None
        assert store.resolve("raw-transcript://bad") is None


class TestEncryptionAtRest:
    def test_encrypted_at_rest(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        transcript = "sensitive content with secrets"
        store.store("proj-sec", "ch-1", transcript, "[]", {})

        for enc_file in tmp_path.rglob("*.enc"):
            raw = enc_file.read_bytes()
            assert b"sensitive" not in raw
            assert b"secrets" not in raw

    def test_decrypted_on_read(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        text = "top secret transcript"
        uri, _ = store.store("p", "c", text, "[]", {})
        resolved = store.resolve(uri)
        assert resolved is not None
        assert resolved[0] == text


class TestProjectIsolation:
    def test_different_projects_isolated(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        u1, _ = store.store("proj-A", "c1", "text A", "[]", {})
        u2, _ = store.store("proj-B", "c1", "text B", "[]", {})
        assert store.resolve(u1) is not None
        assert store.resolve(u2) is not None

        deleted = store.delete_project("proj-A")
        assert deleted >= 1
        assert store.resolve(u1) is None
        assert store.resolve(u2) is not None  # proj-B remains

    def test_list_project_returns_only_project_uris(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        u1, _ = store.store("proj-X", "c1", "a", "[]", {})
        u2, _ = store.store("proj-X", "c2", "b", "[]", {})
        store.store("proj-Y", "c1", "c", "[]", {})

        uris = store.list_project("proj-X")
        assert u1 in uris
        assert u2 in uris
        assert len(uris) == 2


class TestChapterIsolation:
    def test_delete_chapter_only_removes_one_chapter(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        u1, _ = store.store("proj", "ch-A", "text ch-A", "[]", {})
        u2, _ = store.store("proj", "ch-B", "text ch-B", "[]", {})

        deleted = store.delete_chapter("proj", "ch-A")
        assert deleted >= 1
        assert store.resolve(u1) is None
        assert store.resolve(u2) is not None

    def test_delete_chapter_twice_is_idempotent(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.store("proj", "ch", "x", "[]", {})
        assert store.delete_chapter("proj", "ch") >= 1
        assert store.delete_chapter("proj", "ch") == 0

    def test_delete_chapter_nonexistent_returns_zero(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.delete_chapter("nonexistent", "ch") == 0


class TestDeleteProject:
    def test_delete_project_removes_all_artifacts(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        uris = []
        for ch in ("ch1", "ch2", "ch3"):
            u, _ = store.store("proj-del", ch, f"text {ch}", "[]", {})
            uris.append(u)

        deleted = store.delete_project("proj-del")
        assert deleted == 3
        for u in uris:
            assert store.resolve(u) is None

    def test_delete_project_does_not_affect_other_projects(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        keep_uri, _ = store.store("keep-proj", "ch", "keep", "[]", {})
        store.store("delete-proj", "ch", "delete", "[]", {})

        store.delete_project("delete-proj")
        assert store.resolve(keep_uri) is not None


class TestListProject:
    def test_list_empty_project_returns_empty(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.list_project("empty-proj") == []

    def test_list_after_delete_chapter(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.store("proj", "ch1", "a", "[]", {})
        u2, _ = store.store("proj", "ch2", "b", "[]", {})
        store.delete_chapter("proj", "ch1")
        uris = store.list_project("proj")
        assert list(uris) == [u2]