"""
Knowledge Base Management - Store and retrieve novel settings using vector database
"""
from typing import List, Dict, Any, Optional
from pathlib import Path
import os
import logging

# Disable proxy variables to keep vector and embedding requests predictable in local runs.
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
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
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from .config import Config
import os
import requests
import numpy as np

logger = logging.getLogger(__name__)


class AliyunEmbeddings(Embeddings):
    """Aliyun embedding adapter."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "text-embedding-v4"
    ):
        """
        Initialize the Aliyun embedding adapter.
        
        Args:
            api_key: DashScope API key.
            api_base: Base URL for the embedding API.
            model: Embedding model name, defaults to text-embedding-v4.
        """
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or Config.DEEPSEEK_API_KEY
        self.api_base = api_base
        self.model = model
        
        if not self.api_key:
            raise ValueError("Aliyun API key is required. Please set DASHSCOPE_API_KEY in .env file")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of documents."""
        embeddings = []
        for text in texts:
            embedding = self._get_embedding(text)
            embeddings.append(embedding)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        return self._get_embedding(text)

    def _get_embedding(self, text: str) -> List[float]:
        """
        Request one embedding vector from the remote API.
        
        Args:
            text: Input text to embed.
            
        Returns:
            A single embedding vector.
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model,
                "input": text,
                "dimensions": 2048  # text-embedding-v4 currently returns 2048 dimensions.
            }

            response = requests.post(
                f"{self.api_base}/embeddings",
                headers=headers,
                json=data,
                timeout=30,
                proxies={'http': None, 'https': None}  # Force direct requests and ignore host proxy settings.
            )

            if response.status_code == 200:
                result = response.json()
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0]["embedding"]
                else:
                    logger.debug(f"Warning: Aliyun Embedding API returned empty data: {result}")
            else:
                logger.debug(f"Warning: Aliyun Embedding API call failed with status {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.debug(f"Warning: Error getting embedding from Aliyun: {e}")
            
        # Fallback to deterministic random vector
        logger.debug(f"Using fallback vector for text: {text[:50]}...")
        np.random.seed(hash(text) % 2**32)
        return np.random.randn(2048).tolist()  # Fallback vector with the expected 2048 dimensions.


class NovelKnowledgeBase:
    """Novel Knowledge Base - Manage world settings, characters, plots, etc."""

    def __init__(self, persist_directory: Optional[str] = None):
        """Initialize knowledge base"""
        self.persist_directory = persist_directory or Config.CHROMA_PERSIST_DIRECTORY
        self.active_persist_directory: Optional[str] = None
        self.vectorstore_mode = "uninitialized"
        self.embeddings = AliyunEmbeddings(
            api_key=os.getenv("DASHSCOPE_API_KEY") or Config.EMBEDDING_API_KEY,
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="text-embedding-v4"
        )

        # Try the persistent Chroma client first, then fall back to older bindings if needed.
        try:
            import chromadb
            from chromadb.config import Settings

            self.vectorstore = self._create_persistent_vectorstore(
                chromadb=chromadb,
                settings_cls=Settings,
                persist_directory=self.persist_directory,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise

            logger.warning(
                "Primary persistent Chroma initialization failed: %s",
                exc,
            )
            fallback_directory = self._build_fallback_persist_directory(self.persist_directory)
            try:
                import chromadb
                from chromadb.config import Settings

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
                    collection_name="novel_knowledge"
                )
                self.vectorstore_mode = "in_memory"
                self.active_persist_directory = None
                logger.warning("Using in-memory Chroma fallback from: %s", CHROMA_SRC)

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )

    def _create_persistent_vectorstore(self, chromadb, settings_cls, persist_directory: str):
        chroma_client = chromadb.PersistentClient(
            path=persist_directory,
            settings=settings_cls(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        vectorstore = Chroma(
            client=chroma_client,
            embedding_function=self.embeddings,
            collection_name="novel_knowledge"
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
    
    def add_world_setting(self, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add world setting"""
        try:
            meta = metadata or {}
            meta.update({"type": "world_setting", "title": title})

            chunks = self.text_splitter.split_text(content)
            if not chunks:
                logger.debug(f"Warning: World setting is empty: {title}")
                return

            documents = [Document(page_content=chunk, metadata=meta) for chunk in chunks]

            if documents:
                self.vectorstore.add_documents(documents)
                # Note: Chroma 0.4.x+ auto-persists, no need to call persist()
                logger.debug(f"Added world setting: {title}")
            else:
                logger.debug(f"Warning: Cannot create documents: {title}")
        except Exception as e:
            logger.debug(f"Warning: Error adding world setting: {e}")
    
    def add_character(self, name: str, profile: str, metadata: Optional[Dict[str, Any]] = None):
        """Add character profile"""
        try:
            meta = metadata or {}
            meta.update({"type": "character", "name": name})

            chunks = self.text_splitter.split_text(profile)
            if not chunks:
                logger.debug(f"Warning: Character profile is empty: {name}")
                return

            documents = [Document(page_content=chunk, metadata=meta) for chunk in chunks]

            if documents:
                self.vectorstore.add_documents(documents)
                # Note: Chroma 0.4.x+ auto-persists, no need to call persist()
                logger.debug(f"Added character profile: {name}")
            else:
                logger.debug(f"Warning: Cannot create documents: {name}")
        except Exception as e:
            logger.debug(f"Warning: Error adding character profile: {e}")
    
    def add_chapter(self, chapter_num: int, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add written chapter"""
        try:
            meta = metadata or {}
            meta.update({"type": "chapter", "chapter_num": chapter_num, "title": title})

            chunks = self.text_splitter.split_text(content)
            if not chunks:
                logger.debug(f"Warning: Chapter content is empty: Chapter {chapter_num} - {title}")
                return

            documents = [Document(page_content=chunk, metadata=meta) for chunk in chunks]

            if documents:
                self.vectorstore.add_documents(documents)
                # Note: Chroma 0.4.x+ auto-persists, no need to call persist()
                logger.debug(f"Added chapter: Chapter {chapter_num} - {title}")
            else:
                logger.debug(f"Warning: Cannot create documents: Chapter {chapter_num} - {title}")
        except Exception as e:
            logger.debug(f"Warning: Error adding chapter: {e}")
    
    def search(
        self, 
        query: str, 
        k: int = 5, 
        filter_type: Optional[str] = None,
        project_id: Optional[int] = None
    ) -> List[Document]:
        """Search related knowledge.
        
        Args:
            query: Search query text.
            k: Maximum number of documents to return.
            filter_type: Optional knowledge type filter, such as world_setting or character.
            project_id: Optional project scope.
        
        Returns:
            List[Document]: Matching documents.
        """
        # Build metadata filters for Chroma when project or type scoping is requested.
        filter_dict = None
        
        # Collect filter conditions.
        conditions = []
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        if filter_type:
            conditions.append({"type": filter_type})
        
        # Chroma expects a single filter object when only one condition is present.
        if len(conditions) == 0:
            filter_dict = None
        elif len(conditions) == 1:
            # Single-condition filter.
            filter_dict = conditions[0]
        else:
            # Multiple conditions are combined with $and.
            filter_dict = {"$and": conditions}
        
        # Execute the search.
        try:
            if filter_dict is None:
                # Unfiltered similarity search.
                results = self.vectorstore.similarity_search(query, k=k)
            else:
                # Filtered similarity search.
                results = self.vectorstore.similarity_search(query, k=k, filter=filter_dict)
        except Exception as e:
            # Some Chroma backends reject complex filters; fall back to unfiltered search.
            logger.debug(f"Warning: Chroma filter error: {e}, falling back to unfiltered search")
            results = self.vectorstore.similarity_search(query, k=k)
        
        return results
    
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
        """Run enhanced knowledge search with structured filters.
        
        Args:
            query: Search query text.
            k: Maximum number of results to keep after post-filtering.
            project_id: Optional project scope.
            filter_types: Optional list of knowledge types.
            categories: Optional list of category values.
            chapter_range: Optional inclusive chapter range as (start, end).
            character_names: Optional character names used for result filtering.
            tags: Optional metadata tags.
            min_score: Minimum normalized similarity score between 0 and 1.
        
        Returns:
            List[Dict]: Result items containing content, metadata, and score.
        """
        # Collect structured filter conditions for vector search.
        conditions = []
        
        # Restrict to the requested project when provided.
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        
        # Type filters are combined with $or when multiple values are provided.
        if filter_types and len(filter_types) > 0:
            if len(filter_types) == 1:
                conditions.append({"type": filter_types[0]})
            else:
                type_conditions = [{"type": t} for t in filter_types]
                conditions.append({"$or": type_conditions})
        
        # Category filters are combined with $or when multiple values are provided.
        if categories and len(categories) > 0:
            if len(categories) == 1:
                conditions.append({"category": categories[0]})
            else:
                cat_conditions = [{"category": c} for c in categories]
                conditions.append({"$or": cat_conditions})
        
        # Build the final Chroma filter payload.
        filter_dict = None
        if len(conditions) == 0:
            filter_dict = None
        elif len(conditions) == 1:
            filter_dict = conditions[0]
        else:
            filter_dict = {"$and": conditions}
        
        # Retrieve extra candidates first so local post-filtering still has room to trim.
        search_k = k * 3  # Search a wider window before applying local filters.
        
        try:
            if filter_dict is None:
                results_with_scores = self.vectorstore.similarity_search_with_score(query, k=search_k)
            else:
                results_with_scores = self.vectorstore.similarity_search_with_score(
                    query, k=search_k, filter=filter_dict
                )
        except Exception as e:
            logger.debug(f"Warning: Enhanced search filter error: {e}, falling back to basic search")
            results_with_scores = self.vectorstore.similarity_search_with_score(query, k=search_k)
        
        # Apply score and metadata filtering in Python.
        filtered_results = []
        
        for doc, score in results_with_scores:
            # Chroma distance is smaller when two vectors are more similar.
            # Convert the distance into a simple 0-1 similarity score for UI use.
            similarity_score = max(0, 1 - score / 2)  # Normalize distance to a comparable similarity score.
            
            # Drop low-confidence results early.
            if similarity_score < min_score:
                continue
            
            metadata = doc.metadata or {}
            
            # Apply chapter range filtering when requested.
            if chapter_range:
                chapter_num = metadata.get('chapter_num')
                if chapter_num is not None:
                    try:
                        ch_num = int(chapter_num)
                        if not (chapter_range[0] <= ch_num <= chapter_range[1]):
                            continue
                    except (ValueError, TypeError):
                        pass
            
            # Apply character-name filtering against result metadata.
            if character_names:
                content = doc.page_content.lower()
                found_any = False
                for name in character_names:
                    if name.lower() in content:
                        found_any = True
                        break
                if not found_any:
                    continue
            
            # Apply tag filtering.
            if tags:
                doc_tags = metadata.get('tags', [])
                if isinstance(doc_tags, str):
                    doc_tags = [t.strip() for t in doc_tags.split(',')]
                if not any(tag in doc_tags for tag in tags):
                    continue
            
            # Collect the normalized result payload.
            filtered_results.append({
                'content': doc.page_content,
                'metadata': metadata,
                'score': round(similarity_score, 4),
                'type': metadata.get('type', 'unknown'),
            })
        
        # Keep only the top-k results after all filters are applied.
        filtered_results.sort(key=lambda x: x['score'], reverse=True)
        return filtered_results[:k]
    
    def search_by_characters(
        self,
        character_names: List[str],
        project_id: int,
        k: int = 10,
        include_chapters: bool = True,
        include_settings: bool = True,
    ) -> List[Dict[str, Any]]:
        """Search knowledge related to a group of characters.
        
        Args:
            character_names: Character names to search for.
            project_id: Project identifier.
            k: Maximum number of results.
            include_chapters: Whether to search chapter content.
            include_settings: Whether to search character and world-setting entries.
        
        Returns:
            Search results filtered by the requested character names.
        """
        filter_types = []
        if include_chapters:
            filter_types.append('chapter')
        if include_settings:
            filter_types.extend(['character', 'world_setting'])
        
        # Reuse the character names as the primary search query.
        query = ' '.join(character_names)
        
        return self.search_enhanced(
            query=query,
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
        """Search the most recent chapters for related knowledge.
        
        Args:
            query: Search query text.
            project_id: Project identifier.
            last_n_chapters: Number of recent chapters to include.
            k: Maximum number of results.
        
        Returns:
            Matching chapter documents.
        """
        # Query chapter metadata directly to discover the latest chapter number.
        try:
            collection = self.vectorstore._collection
            results = collection.get(
                where={
                    "$and": [
                        {"type": "chapter"},
                        {"project_id": str(project_id)}
                    ]
                }
            )
            
            if not results or not results['metadatas']:
                return []
            
            # Find the highest stored chapter number.
            max_chapter = 0
            for meta in results['metadatas']:
                ch_num = meta.get('chapter_num')
                if ch_num:
                    try:
                        max_chapter = max(max_chapter, int(ch_num))
                    except (ValueError, TypeError):
                        pass
            
            if max_chapter == 0:
                return []
            
            # Limit the search to the requested recent chapter window.
            start_chapter = max(1, max_chapter - last_n_chapters + 1)
            
            return self.search_enhanced(
                query=query,
                k=k,
                project_id=project_id,
                filter_types=['chapter'],
                chapter_range=(start_chapter, max_chapter),
            )
        except Exception as e:
            logger.debug(f"Error in search_recent_chapters: {e}")
            return []
    
    def get_character_info(self, character_name: str, project_id: Optional[int] = None) -> List[Document]:
        """Get all information for a specific character
        
        Args:
            character_name: Character name to search for.
            project_id: Optional project scope.
        """
        # Build filters for character records.
        conditions = [
            {"type": "character"},
            {"name": character_name}
        ]
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        
        # Chroma requires $and when combining type and name filters.
        filter_dict = {"$and": conditions}
        
        try:
            return self.vectorstore.similarity_search(
                character_name, k=10, filter=filter_dict
            )
        except Exception as e:
            logger.debug(f"Warning: Chroma filter error in get_character_info: {e}, falling back to unfiltered search")
            return self.vectorstore.similarity_search(character_name, k=10)
    
    def get_chapter_summary(self, chapter_num: int, project_id: Optional[int] = None) -> List[Document]:
        """Get content for a specific chapter
        
        Args:
            chapter_num: Chapter number to search for.
            project_id: Optional project scope.
        """
        # Build filters for chapter records.
        conditions = [
            {"type": "chapter"},
            {"chapter_num": str(chapter_num)}
        ]
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        
        # Chroma requires $and when combining chapter and project filters.
        filter_dict = {"$and": conditions}
        
        try:
            return self.vectorstore.similarity_search(
                f"Chapter {chapter_num}", k=10, filter=filter_dict
            )
        except Exception as e:
            logger.debug(f"Warning: Chroma filter error in get_chapter_summary: {e}, falling back to unfiltered search")
            return self.vectorstore.similarity_search(f"Chapter {chapter_num}", k=10)
    
    def delete_chapter(self, chapter_number: int, project_id: Optional[int] = None) -> int:
        """Delete chapter from vector database

        Args:
            chapter_number: Chapter number to delete.
            project_id: Optional project scope used to narrow the deletion.

        Returns:
            int: Number of deleted documents.
        """
        try:
            collection = self.vectorstore._collection

            # Build the metadata filter used to read candidate chapter documents.
            if project_id is not None:
                # Project-scoped delete uses a combined $and filter.
                where_filter = {
                    "$and": [
                        {"type": "chapter"},
                        {"project_id": str(project_id)}
                    ]
                }
            else:
                # Global delete only filters by chapter type.
                where_filter = {"type": "chapter"}

            # Load candidate chapter documents first, then delete by id.
            results = collection.get(where=where_filter)

            if not results or not results['ids']:
                logger.debug(f"No chapter documents found in vector database")
                return 0

            # Match the stored chapter number or a recognizable chapter title.
            ids_to_delete = []
            for doc_id, metadata in zip(results['ids'], results['metadatas']):
                if metadata and (
                    metadata.get('chapter_number') == chapter_number or
                    metadata.get('chapter_number') == str(chapter_number) or
                    f"第{chapter_number}章" in str(metadata.get("title", "")) or
                    f"Chapter {chapter_number}" in str(metadata.get("title", ""))
                ):
                    ids_to_delete.append(doc_id)

            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                logger.debug(f"Deleted {len(ids_to_delete)} documents for chapter {chapter_number}")
                return len(ids_to_delete)
            else:
                logger.debug(f"No documents found for chapter {chapter_number}")
                return 0

        except Exception as e:
            logger.debug(f"Error deleting chapter from vector database: {e}")
            return 0

    def delete_project(self, project_id: int) -> int:
        """Delete all vector data for a project

        Args:
            project_id: Project identifier.

        Returns:
            int: Number of deleted documents.
        """
        try:
            collection = self.vectorstore._collection

            # Load all project-scoped documents, then delete them by id.
            results = collection.get(
                where={"project_id": str(project_id)}
            )

            if results and results['ids']:
                deleted_count = len(results['ids'])
                collection.delete(ids=results['ids'])
                logger.debug(f"Deleted {deleted_count} documents for project {project_id}")
                return deleted_count
            else:
                logger.debug(f"No documents found for project {project_id}")
                return 0

        except Exception as e:
            logger.debug(f"Error deleting project from vector database: {e}")
            return 0

    def clear_database(self):
        """Clear knowledge base (use with caution)"""
        self.vectorstore.delete_collection()
        logger.debug("Knowledge base cleared")

    def load_from_markdown(self, file_path: str, doc_type: str, metadata: Optional[Dict[str, Any]] = None):
        """Load data from Markdown file to knowledge base"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            meta = metadata or {}

            if doc_type == "world_setting":
                title = f"World setting loaded from {file_path}"
                self.add_world_setting(title, content, meta)
                logger.debug(f"Loaded world setting from {file_path}")

            elif doc_type == "character":
                name = f"Character loaded from {file_path}"
                self.add_character(name, content, meta)
                logger.debug(f"Loaded character profile from {file_path}")

            elif doc_type == "plot":
                self.add_chapter(0, f"Plot outline loaded from {file_path}", content, meta)
                logger.debug(f"Loaded plot outline from {file_path}")

            else:
                logger.debug(f"Unknown document type: {doc_type}")
                return False

            return True

        except FileNotFoundError:
            logger.debug(f"File not found: {file_path}")
            return False
        except Exception as e:
            logger.debug(f"Error loading file: {str(e)}")
            return False

    def load_from_directory(self, directory: str, metadata: Optional[Dict[str, Any]] = None):
        """Load all Markdown files from directory"""
        import os

        try:
            files_loaded = 0

            world_file = os.path.join(directory, "world_setting.md")
            if os.path.exists(world_file):
                if self.load_from_markdown(world_file, "world_setting", metadata):
                    files_loaded += 1

            char_file = os.path.join(directory, "character_profiles.md")
            if os.path.exists(char_file):
                if self.load_from_markdown(char_file, "character", metadata):
                    files_loaded += 1

            plot_file = os.path.join(directory, "plot_outline.md")
            if os.path.exists(plot_file):
                if self.load_from_markdown(plot_file, "plot", metadata):
                    files_loaded += 1

            logger.debug(f"Loaded {files_loaded} files from directory")
            return files_loaded > 0

        except Exception as e:
            logger.debug(f"Error loading directory: {str(e)}")
            return False
