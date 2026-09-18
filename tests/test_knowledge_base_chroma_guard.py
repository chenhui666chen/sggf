import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.app.services.agents import knowledge_base as kb_module


def _write_migrations_db(
    persist_directory: Path,
    *,
    versions: dict[str, int],
) -> Path:
    persist_directory.mkdir(parents=True, exist_ok=True)
    db_path = persist_directory / "chroma.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE migrations (
                dir TEXT NOT NULL,
                version INTEGER NOT NULL,
                filename TEXT NOT NULL,
                sql TEXT NOT NULL,
                hash TEXT NOT NULL,
                PRIMARY KEY (dir, version)
            )
            """
        )
        for dir_name, version in versions.items():
            cur.execute(
                """
                INSERT INTO migrations (dir, version, filename, sql, hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    dir_name,
                    version,
                    f"{version:05d}-dummy.sqlite.sql",
                    "-- test migration",
                    "dummy-hash",
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_detect_incompatible_persist_directory_flags_higher_db_migration_version(tmp_path):
    persist_directory = tmp_path / "chroma_db"
    _write_migrations_db(
        persist_directory,
        versions={"sysdb": 10, "metadb": 5, "embeddings_queue": 2},
    )

    reason = kb_module._detect_incompatible_persist_directory(
        str(persist_directory),
        supported_versions={"sysdb": 9, "metadb": 5, "embeddings_queue": 2},
    )

    assert reason is not None
    assert "sysdb=db:10>src:9" in reason


def test_supported_versions_prefer_runtime_self_migration_probe_over_file_derivation(
    monkeypatch,
):
    # 回归：chromadb 1.3.4 自产新库 sysdb=10，但包内 migrations/sysdb 文件清单最大只到 9，
    # 按文件清单猜运行上限会把自产库误判为 incompatible，导致每次启动都 fallback/cleanroom，
    # 向量检索从未真正持久化过。支持上限必须以运行时自导探测结果为准。
    monkeypatch.setattr(
        kb_module,
        "_probe_runtime_migration_versions",
        lambda: {"sysdb": 10, "metadb": 5, "embeddings_queue": 2},
    )
    monkeypatch.setattr(
        kb_module,
        "_derive_supported_migration_versions_from_files",
        lambda: {"sysdb": 9, "metadb": 5, "embeddings_queue": 2},
    )

    assert kb_module._load_supported_migration_versions(use_cache=False)["sysdb"] == 10


def test_supported_versions_fall_back_to_file_derivation_when_probe_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(kb_module, "_probe_runtime_migration_versions", lambda: None)
    monkeypatch.setattr(
        kb_module,
        "_derive_supported_migration_versions_from_files",
        lambda: {"sysdb": 9, "metadb": 5, "embeddings_queue": 2},
    )

    assert kb_module._load_supported_migration_versions(use_cache=False)["sysdb"] == 9


def test_runtime_self_migrated_directory_is_not_flagged(tmp_path):
    # 用当前 venv 的真实 chromadb 运行时在临时目录自建一个库：
    # 它代表“运行时自己写出的最新版本”，预检测必须放行（此前 1.3.4 下被误判 sysdb=10>src:9）。
    import chromadb
    from chromadb.config import Settings

    persist_directory = tmp_path / "chroma_self_migrated"
    chromadb.PersistentClient(
        path=str(persist_directory),
        settings=Settings(anonymized_telemetry=False),
    )

    assert kb_module._detect_incompatible_persist_directory(str(persist_directory)) is None


def test_novel_knowledge_base_skips_incompatible_primary_directory_and_uses_fallback(
    tmp_path,
    monkeypatch,
):
    primary_directory = tmp_path / "chroma_db"
    _write_migrations_db(
        primary_directory,
        versions={"sysdb": 10, "metadb": 5, "embeddings_queue": 2},
    )
    expected_fallback = str(tmp_path / "chroma_db_runtime_fallback")
    used_directories: list[str] = []

    monkeypatch.setattr(kb_module, "AliyunEmbeddings", lambda **kwargs: object())
    monkeypatch.setattr(
        kb_module,
        "_load_supported_migration_versions",
        lambda: {"sysdb": 9, "metadb": 5, "embeddings_queue": 2},
    )

    def _fake_create(self, chromadb, settings_cls, persist_directory):
        used_directories.append(persist_directory)
        self.vectorstore_mode = "persistent"
        self.active_persist_directory = persist_directory
        return object()

    monkeypatch.setattr(
        kb_module.NovelKnowledgeBase,
        "_create_persistent_vectorstore",
        _fake_create,
    )

    knowledge_base = kb_module.NovelKnowledgeBase(persist_directory=str(primary_directory))

    assert used_directories == [expected_fallback]
    assert knowledge_base.active_persist_directory == expected_fallback
    assert knowledge_base.vectorstore_mode == "persistent"
