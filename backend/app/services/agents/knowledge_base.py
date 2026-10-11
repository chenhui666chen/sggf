"""
Knowledge Base Management - Store and retrieve novel settings using vector database.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from importlib_resources import files
from langchain_core.documents import Document

from app.services.character_runtime_context import build_character_runtime_metadata

from .aliyun_embeddings import AliyunEmbeddings
from .config import Config

# Disable proxy variables to keep vector and embedding requests predictable in local runs.
for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    if proxy_var in os.environ:
        del os.environ[proxy_var]

try:
    from langchain_chroma import Chroma  # Preferred modern Chroma integration.

    CHROMA_SRC = "langchain_chroma"
except ImportError:
    try:
        from langchain_community.vectorstores import Chroma  # Compatibility fallback for older installs.

        CHROMA_SRC = "langchain_community.vectorstores"
    except ImportError:
        from langchain.vectorstores import Chroma  # Legacy fallback for very old LangChain releases.

        CHROMA_SRC = "langchain.vectorstores"

logger = logging.getLogger(__name__)


_MIGRATION_FILENAME_PATTERN = re.compile(r"(?P<version>\d+)-.+\.sqlite\.sql$")


class _FallbackTextSplitter:
    """Minimal overlap splitter used only when LangChain's optional parsers cannot import."""

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = max(1, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size - 1))

    def split_text(self, text: str) -> List[str]:
        normalized = str(text or "")
        if not normalized:
            return []
        step = self.chunk_size - self.chunk_overlap
        return [
            normalized[start:start + self.chunk_size]
            for start in range(0, len(normalized), step)
            if normalized[start:start + self.chunk_size]
        ]


def _create_text_splitter() -> Any:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        return RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
    except (ImportError, OSError) as exc:
        logger.warning(
            "LangChain text splitter unavailable, using built-in overlap splitter: %s",
            exc,
        )
        return _FallbackTextSplitter(chunk_size=1000, chunk_overlap=200)


def _derive_supported_migration_versions_from_files() -> Dict[str, int]:
    """Legacy fallback: guess the runtime's migration ceiling from packaged .sql files.

    NOTE: this under-reports newer chromadb releases (e.g. 1.3.4 ships the 10th sysdb
    migration outside migrations/sysdb, so file listing caps at 9 while a fresh
    self-created store already records sysdb=10). Never trust it over a runtime probe.
    """
    versions: Dict[str, int] = {}
    try:
        root = files("chromadb.migrations")
    except Exception as exc:
        logger.debug("无法读取 chromadb 内置 migrations 目录: %s", exc)
        return versions

    for dir_name in ("sysdb", "metadb", "embeddings_queue"):
        try:
            migration_dir = root / dir_name
            max_version = 0
            for entry in migration_dir.iterdir():
                match = _MIGRATION_FILENAME_PATTERN.match(entry.name)
                if match:
                    max_version = max(max_version, int(match.group("version")))
            if max_version > 0:
                versions[dir_name] = max_version
        except Exception as exc:
            logger.debug("读取 chromadb migrations/%s 失败: %s", dir_name, exc)
    return versions


def _probe_runtime_migration_versions() -> Optional[Dict[str, int]]:
    """Ask the installed chromadb runtime which migration versions it applies itself.

    Creates a throwaway PersistentClient in a temp dir and reads its migrations table.
    Returns None when probing is unavailable (caller falls back to file derivation).
    """
    try:
        import chromadb
        from chromadb.config import Settings

        probe_dir = tempfile.mkdtemp(prefix="chroma_version_probe_")
        try:
            chromadb.PersistentClient(
                path=probe_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            versions = _read_db_migration_versions(Path(probe_dir) / "chroma.sqlite3")
        finally:
            try:
                shutil.rmtree(probe_dir, ignore_errors=True)
            except Exception:
                pass
        return versions or None
    except Exception as exc:
        logger.debug("chromadb 运行时迁移版本自导探测失败: %s", exc)
        return None


_RUNTIME_MIGRATION_VERSIONS: Optional[Dict[str, int]] = None


def _load_supported_migration_versions(*, use_cache: bool = True) -> Dict[str, int]:
    """Migration versions the current chromadb runtime actually supports (cached).

    The runtime self-probe is authoritative: comparing a database against the
    packaged .sql file list produced false "incompatible" verdicts on stores the
    runtime itself had just created, trapping every startup in the fallback /
    cleanroom loop.
    """
    global _RUNTIME_MIGRATION_VERSIONS
    if not use_cache:
        return _probe_runtime_migration_versions() or _derive_supported_migration_versions_from_files()
    if _RUNTIME_MIGRATION_VERSIONS is None:
        probed = _probe_runtime_migration_versions()
        _RUNTIME_MIGRATION_VERSIONS = probed or _derive_supported_migration_versions_from_files()
    return _RUNTIME_MIGRATION_VERSIONS


def _read_db_migration_versions(chroma_sqlite_path: Path) -> Dict[str, int]:
    if not chroma_sqlite_path.exists():
        return {}

    conn = sqlite3.connect(chroma_sqlite_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT count(*)
            FROM sqlite_master
            WHERE type='table' AND name='migrations'
            """
        )
        if int(cur.fetchone()[0] or 0) == 0:
            return {}

        cur.execute(
            """
            SELECT dir, MAX(version)
            FROM migrations
            GROUP BY dir
            """
        )
        return {str(row[0]): int(row[1]) for row in cur.fetchall() if row and row[0] is not None}
    finally:
        conn.close()


def _detect_incompatible_persist_directory(
    persist_directory: str,
    *,
    supported_versions: Optional[Dict[str, int]] = None,
) -> Optional[str]:
    chroma_sqlite_path = Path(persist_directory) / "chroma.sqlite3"
    if not chroma_sqlite_path.exists():
        return None

    expected_versions = supported_versions or _load_supported_migration_versions()
    if not expected_versions:
        return None

    try:
        db_versions = _read_db_migration_versions(chroma_sqlite_path)
    except Exception as exc:
        return f"无法读取 migrations 元数据: {exc}"

    incompatible_parts: List[str] = []
    for dir_name, db_version in sorted(db_versions.items()):
        expected_version = expected_versions.get(dir_name)
        if expected_version is None:
            incompatible_parts.append(f"{dir_name}=db:{db_version},src:missing")
        elif db_version > expected_version:
            incompatible_parts.append(f"{dir_name}=db:{db_version}>src:{expected_version}")

    if incompatible_parts:
        return "migrations 版本高于当前 chromadb 运行时，" + "；".join(incompatible_parts)
    return None


def _build_cleanroom_persist_directory(persist_directory: str) -> str:
    """Build a fresh persist dir that current chromadb can initialize.
    Reusing a previous *_cleanroom is unsafe: once opened by a newer runtime
    it may already be sysdb=10 and will panic the older runtime again.
    """
    from datetime import datetime
    base_path = Path(persist_directory)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(base_path.parent / f"{base_path.name}_cleanroom_{stamp}")


class NovelKnowledgeBase:
    """Novel knowledge base - manage world settings, characters, plots, and chapters."""

    def __init__(self, persist_directory: Optional[str] = None):
        self.persist_directory = persist_directory or Config.CHROMA_PERSIST_DIRECTORY
        self.active_persist_directory: Optional[str] = None
        self.vectorstore_mode = "uninitialized"
        self.embeddings = AliyunEmbeddings(
            api_key=(
                os.getenv("EMBEDDING_API_KEY")
                or os.getenv("DASHSCOPE_API_KEY")
                or Config.EMBEDDING_API_KEY
                or Config.DASHSCOPE_API_KEY
            ),
            api_base=Config.EMBEDDING_API_BASE or Config.DASHSCOPE_API_BASE,
            model=Config.EMBEDDING_MODEL or "text-embedding-v4",
        )

        try:
            import chromadb
            from chromadb.config import Settings

            supported_versions = _load_supported_migration_versions()
            primary_skip_reason = _detect_incompatible_persist_directory(
                self.persist_directory,
                supported_versions=supported_versions,
            )
            if primary_skip_reason:
                raise RuntimeError(
                    f"Primary persistent Chroma directory is incompatible: {primary_skip_reason}"
                )

            self.vectorstore = self._create_persistent_vectorstore(
                chromadb=chromadb,
                settings_cls=Settings,
                persist_directory=self.persist_directory,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise

            logger.warning("Primary persistent Chroma initialization failed: %s", exc)
            fallback_directory = self._build_fallback_persist_directory(self.persist_directory)
            try:
                import chromadb
                from chromadb.config import Settings

                fallback_skip_reason = _detect_incompatible_persist_directory(
                    fallback_directory,
                    supported_versions=_load_supported_migration_versions(),
                )
                if fallback_skip_reason:
                    cleanroom_directory = _build_cleanroom_persist_directory(fallback_directory)
                    logger.warning(
                        "Fallback persistent Chroma directory is incompatible, switching to a fresh cleanroom directory %s: %s. Existing chapter vectors in the primary store cannot be read by this chromadb runtime.",
                        cleanroom_directory,
                        fallback_skip_reason,
                    )
                    fallback_directory = cleanroom_directory

                self.vectorstore = self._create_persistent_vectorstore(
                    chromadb=chromadb,
                    settings_cls=Settings,
                    persist_directory=fallback_directory,
                )
                logger.warning(
                    "Using fallback persistent Chroma directory after primary failure: %s",
                    fallback_directory,
                )
            except BaseException as fallback_exc:
                if isinstance(fallback_exc, (KeyboardInterrupt, SystemExit)):
                    raise

                logger.warning(
                    "Fallback persistent Chroma initialization failed, falling back to in-memory store: %s",
                    fallback_exc,
                )
                self.vectorstore = Chroma(
                    embedding_function=self.embeddings,
                    collection_name="novel_knowledge",
                )
                self.vectorstore_mode = "in_memory"
                self.active_persist_directory = None
                logger.warning("Using in-memory Chroma fallback from: %s", CHROMA_SRC)

        self.text_splitter = _create_text_splitter()

    def _create_persistent_vectorstore(self, chromadb, settings_cls, persist_directory: str):
        chroma_client = chromadb.PersistentClient(
            path=persist_directory,
            settings=settings_cls(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )

        vectorstore = Chroma(
            client=chroma_client,
            embedding_function=self.embeddings,
            collection_name="novel_knowledge",
        )
        self.vectorstore_mode = "persistent"
        self.active_persist_directory = persist_directory
        logger.info("Using persistent Chroma from %s via: %s", persist_directory, CHROMA_SRC)
        return vectorstore

    @staticmethod
    def _build_fallback_persist_directory(persist_directory: str) -> str:
        base_path = Path(persist_directory)
        fallback_name = f"{base_path.name}_runtime_fallback"
        return str(base_path.parent / fallback_name)

    @staticmethod
    def _build_metadata(metadata: Optional[Dict[str, Any]], **defaults: Any) -> Dict[str, Any]:
        resolved = dict(metadata or {})
        for key, value in defaults.items():
            resolved[key] = value
        return resolved

    def _add_text_documents(self, content: str, metadata: Dict[str, Any], log_label: str) -> int:
        chunks = self.text_splitter.split_text(content)
        if not chunks:
            logger.debug("Skip empty vector document: %s", log_label)
            return 0

        documents = [Document(page_content=chunk, metadata=metadata) for chunk in chunks]
        self.vectorstore.add_documents(documents)
        logger.debug("Added %s vector chunks for %s", len(documents), log_label)
        return len(documents)

    def _similarity_search(
        self,
        query: str,
        *,
        k: int,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        if filter_dict is not None:
            try:
                return self.vectorstore.similarity_search(query, k=k, filter=filter_dict)
            except Exception as exc:
                # 带过滤检索失败时禁止回退到无过滤检索：
                # 无过滤会跨项目返回数据，造成不同项目的设定/人物串扰
                logger.warning(
                    "Vector similarity search with filter failed, returning empty result "
                    "(unfiltered fallback disabled to avoid cross-project leakage): %s",
                    exc,
                )
                return []

        try:
            return self.vectorstore.similarity_search(query, k=k)
        except Exception as exc:
            logger.warning("Vector similarity search failed: %s", exc)
            return []

    def _similarity_search_with_score(
        self,
        query: str,
        *,
        k: int,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[tuple[Document, float]]:
        if filter_dict is not None:
            try:
                return self.vectorstore.similarity_search_with_score(query, k=k, filter=filter_dict)
            except Exception as exc:
                # 同上：带过滤检索失败禁止无过滤回退，防止跨项目数据泄漏
                logger.warning(
                    "Vector similarity search with score and filter failed, returning empty result "
                    "(unfiltered fallback disabled to avoid cross-project leakage): %s",
                    exc,
                )
                return []

        try:
            return self.vectorstore.similarity_search_with_score(query, k=k)
        except Exception as exc:
            logger.warning("Vector similarity search with score failed: %s", exc)
            return []

    def add_world_setting(self, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add world setting."""
        try:
            meta = self._build_metadata(metadata, type="world_setting", title=title)
            self._add_text_documents(content, meta, f"world_setting:{title}")
        except Exception as exc:
            logger.warning("Error adding world setting to vector store: %s", exc)

    def add_character(self, name: str, profile: str, metadata: Optional[Dict[str, Any]] = None):
        """Add character profile."""
        try:
            meta = self._build_metadata(metadata, type="character", name=name)
            runtime_meta = build_character_runtime_metadata(name, profile)
            for key, value in runtime_meta.items():
                if value and not meta.get(key):
                    meta[key] = value
            self._add_text_documents(profile, meta, f"character:{name}")
        except Exception as exc:
            logger.warning("Error adding character profile to vector store: %s", exc)

    def add_chapter(self, chapter_num: int, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add written chapter."""
        try:
            meta = self._build_metadata(
                metadata,
                type="chapter",
                chapter_num=str(chapter_num),
                chapter_number=str(chapter_num),
                title=title,
            )
            self._add_text_documents(content, meta, f"chapter:{chapter_num}:{title}")
        except Exception as exc:
            logger.warning("Error adding chapter to vector store: %s", exc)

    def add_plot_outline(self, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add plot outline without downgrading its semantic type to chapter."""
        try:
            meta = self._build_metadata(metadata, type="plot_outline", title=title)
            self._add_text_documents(content, meta, f"plot_outline:{title}")
        except Exception as exc:
            logger.warning("Error adding plot outline to vector store: %s", exc)

    def search(
        self,
        query: str,
        k: int = 5,
        filter_type: Optional[str] = None,
        project_id: Optional[int] = None,
    ) -> List[Document]:
        """Search related knowledge."""
        conditions: List[Dict[str, Any]] = []
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        if filter_type:
            conditions.append({"type": filter_type})

        filter_dict: Optional[Dict[str, Any]]
        if not conditions:
            filter_dict = None
        elif len(conditions) == 1:
            filter_dict = conditions[0]
        else:
            filter_dict = {"$and": conditions}

        return self._similarity_search(query, k=k, filter_dict=filter_dict)

    def search_enhanced(
        self,
        query: str,
        k: int = 10,
        project_id: Optional[int] = None,
        filter_types: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        chapter_range: Optional[tuple] = None,
        character_names: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Run enhanced knowledge search with structured filters."""
        conditions: List[Dict[str, Any]] = []
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})

        if filter_types:
            if len(filter_types) == 1:
                conditions.append({"type": filter_types[0]})
            else:
                conditions.append({"$or": [{"type": item} for item in filter_types]})

        if categories:
            if len(categories) == 1:
                conditions.append({"category": categories[0]})
            else:
                conditions.append({"$or": [{"category": item} for item in categories]})

        filter_dict: Optional[Dict[str, Any]]
        if not conditions:
            filter_dict = None
        elif len(conditions) == 1:
            filter_dict = conditions[0]
        else:
            filter_dict = {"$and": conditions}

        search_k = k * 3
        results_with_scores = self._similarity_search_with_score(
            query,
            k=search_k,
            filter_dict=filter_dict,
        )

        filtered_results: List[Dict[str, Any]] = []
        for doc, score in results_with_scores:
            similarity_score = max(0, 1 - score / 2)
            if similarity_score < min_score:
                continue

            metadata = doc.metadata or {}

            if chapter_range:
                chapter_num = metadata.get("chapter_num")
                if chapter_num is not None:
                    try:
                        normalized_chapter_num = int(chapter_num)
                    except (TypeError, ValueError):
                        normalized_chapter_num = None
                    if normalized_chapter_num is not None and not (
                        chapter_range[0] <= normalized_chapter_num <= chapter_range[1]
                    ):
                        continue

            if character_names:
                content = doc.page_content.lower()
                if not any(name.lower() in content for name in character_names):
                    continue

            if tags:
                doc_tags = metadata.get("tags", [])
                if isinstance(doc_tags, str):
                    doc_tags = [item.strip() for item in doc_tags.split(",") if item.strip()]
                if not any(tag in doc_tags for tag in tags):
                    continue

            filtered_results.append(
                {
                    "content": doc.page_content,
                    "metadata": metadata,
                    "score": round(similarity_score, 4),
                    "type": metadata.get("type", "unknown"),
                }
            )

        filtered_results.sort(key=lambda item: item["score"], reverse=True)
        return filtered_results[:k]

    def search_by_characters(
        self,
        character_names: List[str],
        project_id: int,
        k: int = 10,
        include_chapters: bool = True,
        include_settings: bool = True,
    ) -> List[Dict[str, Any]]:
        """Search knowledge related to a group of characters."""
        filter_types: List[str] = []
        if include_chapters:
            filter_types.append("chapter")
        if include_settings:
            filter_types.extend(["character", "world_setting", "plot_outline"])

        return self.search_enhanced(
            query=" ".join(character_names),
            k=k,
            project_id=project_id,
            filter_types=filter_types if filter_types else None,
            character_names=character_names,
        )

    def search_recent_chapters(
        self,
        query: str,
        project_id: int,
        last_n_chapters: int = 5,
        k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search the most recent chapters for related knowledge."""
        try:
            collection = self.vectorstore._collection
            results = collection.get(
                where={
                    "$and": [
                        {"type": "chapter"},
                        {"project_id": str(project_id)},
                    ]
                }
            )

            if not results or not results["metadatas"]:
                return []

            max_chapter = 0
            for meta in results["metadatas"]:
                chapter_num = meta.get("chapter_num")
                if chapter_num is None:
                    continue
                try:
                    max_chapter = max(max_chapter, int(chapter_num))
                except (TypeError, ValueError):
                    continue

            if max_chapter <= 0:
                return []

            start_chapter = max(1, max_chapter - last_n_chapters + 1)
            return self.search_enhanced(
                query=query,
                k=k,
                project_id=project_id,
                filter_types=["chapter"],
                chapter_range=(start_chapter, max_chapter),
            )
        except Exception as exc:
            logger.debug("Error in search_recent_chapters: %s", exc)
            return []

    def get_character_info(self, character_name: str, project_id: Optional[int] = None) -> List[Document]:
        """Get all information for a specific character."""
        conditions = [
            {"type": "character"},
            {"name": character_name},
        ]
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})

        return self._similarity_search(
            character_name,
            k=10,
            filter_dict={"$and": conditions},
        )

    def get_chapter_summary(self, chapter_num: int, project_id: Optional[int] = None) -> List[Document]:
        """Get content for a specific chapter."""
        conditions = [
            {"type": "chapter"},
            {"chapter_num": str(chapter_num)},
        ]
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})

        return self._similarity_search(
            f"Chapter {chapter_num}",
            k=10,
            filter_dict={"$and": conditions},
        )

    def delete_chapter(self, chapter_number: int, project_id: Optional[int] = None) -> int:
        """Delete chapter from vector database."""
        try:
            collection = self.vectorstore._collection
            where_filter: Dict[str, Any]
            if project_id is not None:
                where_filter = {
                    "$and": [
                        {"type": "chapter"},
                        {"project_id": str(project_id)},
                    ]
                }
            else:
                where_filter = {"type": "chapter"}

            results = collection.get(where=where_filter)
            if not results or not results["ids"]:
                logger.debug("No chapter documents found in vector database")
                return 0

            ids_to_delete: List[str] = []
            for doc_id, metadata in zip(results["ids"], results["metadatas"]):
                if not metadata:
                    continue

                title = str(metadata.get("title", ""))
                stored_chapter_num = metadata.get("chapter_num")
                stored_chapter_number = metadata.get("chapter_number")
                if (
                    stored_chapter_num == chapter_number
                    or stored_chapter_num == str(chapter_number)
                    or stored_chapter_number == chapter_number
                    or stored_chapter_number == str(chapter_number)
                    or f"第{chapter_number}章" in title
                    or f"Chapter {chapter_number}" in title
                ):
                    ids_to_delete.append(doc_id)

            if not ids_to_delete:
                logger.debug("No documents found for chapter %s", chapter_number)
                return 0

            collection.delete(ids=ids_to_delete)
            logger.debug("Deleted %s documents for chapter %s", len(ids_to_delete), chapter_number)
            return len(ids_to_delete)
        except Exception as exc:
            logger.debug("Error deleting chapter from vector database: %s", exc)
            return 0

    def delete_project(self, project_id: int) -> int:
        """Delete all vector data for a project."""
        try:
            collection = self.vectorstore._collection
            results = collection.get(where={"project_id": str(project_id)})
            if not results or not results["ids"]:
                logger.debug("No documents found for project %s", project_id)
                return 0

            deleted_count = len(results["ids"])
            collection.delete(ids=results["ids"])
            logger.debug("Deleted %s documents for project %s", deleted_count, project_id)
            return deleted_count
        except Exception as exc:
            logger.debug("Error deleting project from vector database: %s", exc)
            return 0

    def clear_database(self):
        """Clear knowledge base (use with caution)."""
        self.vectorstore.delete_collection()
        logger.debug("Knowledge base cleared")

    def load_from_markdown(self, file_path: str, doc_type: str, metadata: Optional[Dict[str, Any]] = None):
        """Load data from Markdown file to knowledge base."""
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                content = handle.read()

            meta = dict(metadata or {})

            if doc_type == "world_setting":
                title = f"World setting loaded from {file_path}"
                self.add_world_setting(title, content, meta)
                logger.debug("Loaded world setting from %s", file_path)
            elif doc_type == "character":
                name = f"Character loaded from {file_path}"
                self.add_character(name, content, meta)
                logger.debug("Loaded character profile from %s", file_path)
            elif doc_type == "plot":
                self.add_plot_outline(f"Plot outline loaded from {file_path}", content, meta)
                logger.debug("Loaded plot outline from %s", file_path)
            else:
                logger.debug("Unknown document type: %s", doc_type)
                return False

            return True
        except FileNotFoundError:
            logger.debug("File not found: %s", file_path)
            return False
        except Exception as exc:
            logger.debug("Error loading file: %s", exc)
            return False

    def load_from_directory(self, directory: str, metadata: Optional[Dict[str, Any]] = None):
        """Load all Markdown files from directory."""
        try:
            files_loaded = 0

            world_file = os.path.join(directory, "world_setting.md")
            if os.path.exists(world_file) and self.load_from_markdown(world_file, "world_setting", metadata):
                files_loaded += 1

            char_file = os.path.join(directory, "character_profiles.md")
            if os.path.exists(char_file) and self.load_from_markdown(char_file, "character", metadata):
                files_loaded += 1

            plot_file = os.path.join(directory, "plot_outline.md")
            if os.path.exists(plot_file) and self.load_from_markdown(plot_file, "plot", metadata):
                files_loaded += 1

            logger.debug("Loaded %s files from directory", files_loaded)
            return files_loaded > 0
        except Exception as exc:
            logger.debug("Error loading directory: %s", exc)
            return False
