"""
Knowledge Base Management - Store and retrieve novel settings using vector database
"""
from typing import List, Dict, Any, Optional
try:
    from langchain_chroma import Chroma  # 优先使用新包，避免弃用警告
    CHROMA_SRC = "langchain_chroma"
except ImportError:
    try:
        from langchain_community.vectorstores import Chroma  # 回退兼容
        CHROMA_SRC = "langchain_community.vectorstores"
    except ImportError:
        from langchain.vectorstores import Chroma  # 最后一层回退
        CHROMA_SRC = "langchain.vectorstores"
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from .config import Config
import os
import requests
import numpy as np


class AliyunEmbeddings(Embeddings):
    """阿里云百炼 Embeddings 适配器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "text-embedding-v4"
    ):
        """
        初始化阿里云百炼 Embeddings
        
        Args:
            api_key: 阿里云百炼 API Key
            api_base: API 基础 URL
            model: 使用的模型名称，默认为 text-embedding-v4
        """
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or Config.DEEPSEEK_API_KEY
        self.api_base = api_base
        self.model = model
        
        if not self.api_key:
            raise ValueError("Aliyun API key is required. Please set DASHSCOPE_API_KEY in .env file")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """为文档列表生成 embeddings"""
        embeddings = []
        for text in texts:
            embedding = self._get_embedding(text)
            embeddings.append(embedding)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """为查询文本生成 embedding"""
        return self._get_embedding(text)

    def _get_embedding(self, text: str) -> List[float]:
        """
        调用阿里云百炼 API 获取文本 embedding
        
        Args:
            text: 输入文本
            
        Returns:
            文本的 embedding 向量
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model,
                "input": text,
                "dimensions": 2048  # 指定使用2048维向量
            }

            response = requests.post(
                f"{self.api_base}/embeddings",
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0]["embedding"]
                else:
                    print(f"Warning: Aliyun Embedding API returned empty data: {result}")
            else:
                print(f"Warning: Aliyun Embedding API call failed with status {response.status_code}: {response.text}")
                
        except Exception as e:
            print(f"Warning: Error getting embedding from Aliyun: {e}")
            
        # Fallback to deterministic random vector
        print(f"Using fallback vector for text: {text[:50]}...")
        np.random.seed(hash(text) % 2**32)
        return np.random.randn(2048).tolist()  # text-embedding-v4 默认维度是2048


class NovelKnowledgeBase:
    """Novel Knowledge Base - Manage world settings, characters, plots, etc."""

    def __init__(self, persist_directory: Optional[str] = None):
        """Initialize knowledge base"""
        self.persist_directory = persist_directory or Config.CHROMA_PERSIST_DIRECTORY
        self.embeddings = AliyunEmbeddings(
            api_key=os.getenv("DASHSCOPE_API_KEY") or Config.EMBEDDING_API_KEY,
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="text-embedding-v4"
        )

        self.vectorstore = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embeddings,
            collection_name="novel_knowledge"
        )
        print(f"🔧 Using Chroma from: {CHROMA_SRC}")

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
    
    def add_world_setting(self, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add world setting"""
        try:
            meta = metadata or {}
            meta.update({"type": "world_setting", "title": title})

            chunks = self.text_splitter.split_text(content)
            if not chunks:
                print(f"Warning: World setting is empty: {title}")
                return

            documents = [Document(page_content=chunk, metadata=meta) for chunk in chunks]

            if documents:
                self.vectorstore.add_documents(documents)
                # Note: Chroma 0.4.x+ auto-persists, no need to call persist()
                print(f"Added world setting: {title}")
            else:
                print(f"Warning: Cannot create documents: {title}")
        except Exception as e:
            print(f"Warning: Error adding world setting: {e}")
    
    def add_character(self, name: str, profile: str, metadata: Optional[Dict[str, Any]] = None):
        """Add character profile"""
        try:
            meta = metadata or {}
            meta.update({"type": "character", "name": name})

            chunks = self.text_splitter.split_text(profile)
            if not chunks:
                print(f"Warning: Character profile is empty: {name}")
                return

            documents = [Document(page_content=chunk, metadata=meta) for chunk in chunks]

            if documents:
                self.vectorstore.add_documents(documents)
                # Note: Chroma 0.4.x+ auto-persists, no need to call persist()
                print(f"Added character profile: {name}")
            else:
                print(f"Warning: Cannot create documents: {name}")
        except Exception as e:
            print(f"Warning: Error adding character profile: {e}")
    
    def add_chapter(self, chapter_num: int, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add written chapter"""
        try:
            meta = metadata or {}
            meta.update({"type": "chapter", "chapter_num": chapter_num, "title": title})

            chunks = self.text_splitter.split_text(content)
            if not chunks:
                print(f"Warning: Chapter content is empty: Chapter {chapter_num} - {title}")
                return

            documents = [Document(page_content=chunk, metadata=meta) for chunk in chunks]

            if documents:
                self.vectorstore.add_documents(documents)
                # Note: Chroma 0.4.x+ auto-persists, no need to call persist()
                print(f"Added chapter: Chapter {chapter_num} - {title}")
            else:
                print(f"Warning: Cannot create documents: Chapter {chapter_num} - {title}")
        except Exception as e:
            print(f"Warning: Error adding chapter: {e}")
    
    def search(
        self, 
        query: str, 
        k: int = 5, 
        filter_type: Optional[str] = None,
        project_id: Optional[int] = None
    ) -> List[Document]:
        """Search related knowledge
        
        Args:
            query: 搜索查询
            k: 返回结果数量
            filter_type: 类型过滤 (world_setting, character, chapter)
            project_id: 项目ID过滤（强烈推荐，确保项目隔离）
        
        Returns:
            List[Document]: 搜索结果
        """
        # 构建过滤条件（使用正确的 ChromaDB 格式）
        filter_dict = None
        
        # 构建条件列表
        conditions = []
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        if filter_type:
            conditions.append({"type": filter_type})
        
        # 根据条件数量选择格式
        if len(conditions) == 0:
            filter_dict = None
        elif len(conditions) == 1:
            # 单条件：直接使用字典
            filter_dict = conditions[0]
        else:
            # 多条件：使用 $and 操作符
            filter_dict = {"$and": conditions}
        
        # 执行搜索
        try:
            if filter_dict is None:
                # 无过滤条件
                results = self.vectorstore.similarity_search(query, k=k)
            else:
                # 使用过滤条件
                results = self.vectorstore.similarity_search(query, k=k, filter=filter_dict)
        except Exception as e:
            # 如果过滤器格式不正确，尝试不使用过滤器
            print(f"Warning: Chroma filter error: {e}, falling back to unfiltered search")
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
        """增强RAG检索，支持结构化过滤
        
        Args:
            query: 搜索查询文本
            k: 返回结果数量
            project_id: 项目ID（强烈推荐，确保项目隔离）
            filter_types: 类型过滤列表，如 ['chapter', 'character', 'world_setting']
            categories: 设定体系过滤，如 ['cultivation_realm_system', 'technique_system']
            chapter_range: 章节范围 (start, end)，如 (1, 10)
            character_names: 人物名称过滤，搜索与这些人物相关的内容
            tags: 标签过滤
            min_score: 最小相关性分数阈值 (0-1)
        
        Returns:
            List[Dict]: 搜索结果列表，包含 content, metadata, score
        """
        # 构建过滤条件
        conditions = []
        
        # 项目ID过滤
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        
        # 多类型过滤（使用 $or）
        if filter_types and len(filter_types) > 0:
            if len(filter_types) == 1:
                conditions.append({"type": filter_types[0]})
            else:
                type_conditions = [{"type": t} for t in filter_types]
                conditions.append({"$or": type_conditions})
        
        # 设定体系过滤
        if categories and len(categories) > 0:
            if len(categories) == 1:
                conditions.append({"category": categories[0]})
            else:
                cat_conditions = [{"category": c} for c in categories]
                conditions.append({"$or": cat_conditions})
        
        # 构建最终过滤字典
        filter_dict = None
        if len(conditions) == 0:
            filter_dict = None
        elif len(conditions) == 1:
            filter_dict = conditions[0]
        else:
            filter_dict = {"$and": conditions}
        
        # 执行向量搜索（搜索更多结果用于后续过滤）
        search_k = k * 3  # 搜索更多用于过滤
        
        try:
            if filter_dict is None:
                results_with_scores = self.vectorstore.similarity_search_with_score(query, k=search_k)
            else:
                results_with_scores = self.vectorstore.similarity_search_with_score(
                    query, k=search_k, filter=filter_dict
                )
        except Exception as e:
            print(f"Warning: Enhanced search filter error: {e}, falling back to basic search")
            results_with_scores = self.vectorstore.similarity_search_with_score(query, k=search_k)
        
        # 后处理过滤
        filtered_results = []
        
        for doc, score in results_with_scores:
            # 转换分数（ChromaDB返回距离，转为相似度）
            # 距离越小越相似，转为 0-1 分数
            similarity_score = max(0, 1 - score / 2)  # 简单的转换公式
            
            # 最小分数过滤
            if similarity_score < min_score:
                continue
            
            metadata = doc.metadata or {}
            
            # 章节范围过滤
            if chapter_range:
                chapter_num = metadata.get('chapter_num')
                if chapter_num is not None:
                    try:
                        ch_num = int(chapter_num)
                        if not (chapter_range[0] <= ch_num <= chapter_range[1]):
                            continue
                    except (ValueError, TypeError):
                        pass
            
            # 人物名称过滤（检查内容中是否包含人物名）
            if character_names:
                content = doc.page_content.lower()
                found_any = False
                for name in character_names:
                    if name.lower() in content:
                        found_any = True
                        break
                if not found_any:
                    continue
            
            # 标签过滤
            if tags:
                doc_tags = metadata.get('tags', [])
                if isinstance(doc_tags, str):
                    doc_tags = [t.strip() for t in doc_tags.split(',')]
                if not any(tag in doc_tags for tag in tags):
                    continue
            
            # 添加到结果
            filtered_results.append({
                'content': doc.page_content,
                'metadata': metadata,
                'score': round(similarity_score, 4),
                'type': metadata.get('type', 'unknown'),
            })
        
        # 按分数排序并限制数量
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
        """根据人物名称搜索相关内容
        
        Args:
            character_names: 人物名称列表
            project_id: 项目ID
            k: 返回结果数量
            include_chapters: 是否包含章节内容
            include_settings: 是否包含设定内容
        
        Returns:
            与人物相关的内容列表
        """
        filter_types = []
        if include_chapters:
            filter_types.append('chapter')
        if include_settings:
            filter_types.extend(['character', 'world_setting'])
        
        # 用人物名作为查询
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
        """在最近N章中搜索
        
        Args:
            query: 搜索查询
            project_id: 项目ID
            last_n_chapters: 最近几章
            k: 返回结果数量
        
        Returns:
            搜索结果列表
        """
        # 先获取最大章节号
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
            
            # 找出最大章节号
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
            
            # 计算章节范围
            start_chapter = max(1, max_chapter - last_n_chapters + 1)
            
            return self.search_enhanced(
                query=query,
                k=k,
                project_id=project_id,
                filter_types=['chapter'],
                chapter_range=(start_chapter, max_chapter),
            )
        except Exception as e:
            print(f"Error in search_recent_chapters: {e}")
            return []
    
    def get_character_info(self, character_name: str, project_id: Optional[int] = None) -> List[Document]:
        """Get all information for a specific character
        
        Args:
            character_name: 角色名称
            project_id: 项目ID（推荐提供以确保项目隔离）
        """
        # 构建条件列表
        conditions = [
            {"type": "character"},
            {"name": character_name}
        ]
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        
        # 使用 $and 操作符（多条件）
        filter_dict = {"$and": conditions}
        
        try:
            return self.vectorstore.similarity_search(
                character_name, k=10, filter=filter_dict
            )
        except Exception as e:
            print(f"Warning: Chroma filter error in get_character_info: {e}, falling back to unfiltered search")
            return self.vectorstore.similarity_search(character_name, k=10)
    
    def get_chapter_summary(self, chapter_num: int, project_id: Optional[int] = None) -> List[Document]:
        """Get content for a specific chapter
        
        Args:
            chapter_num: 章节编号
            project_id: 项目ID（推荐提供以确保项目隔离）
        """
        # 构建条件列表
        conditions = [
            {"type": "chapter"},
            {"chapter_num": str(chapter_num)}
        ]
        if project_id is not None:
            conditions.append({"project_id": str(project_id)})
        
        # 使用 $and 操作符（多条件）
        filter_dict = {"$and": conditions}
        
        try:
            return self.vectorstore.similarity_search(
                f"Chapter {chapter_num}", k=10, filter=filter_dict
            )
        except Exception as e:
            print(f"Warning: Chroma filter error in get_chapter_summary: {e}, falling back to unfiltered search")
            return self.vectorstore.similarity_search(f"Chapter {chapter_num}", k=10)
    
    def delete_chapter(self, chapter_number: int, project_id: Optional[int] = None) -> int:
        """Delete chapter from vector database

        Args:
            chapter_number: 章节号
            project_id: 项目ID (可选,用于更精确的过滤)

        Returns:
            int: 删除的文档数量
        """
        try:
            collection = self.vectorstore._collection

            # 构建过滤条件（使用 $and 操作符）
            if project_id is not None:
                # 多条件查询，需要使用 $and
                where_filter = {
                    "$and": [
                        {"type": "chapter"},
                        {"project_id": str(project_id)}
                    ]
                }
            else:
                # 单条件查询
                where_filter = {"type": "chapter"}

            # 获取所有章节文档
            results = collection.get(where=where_filter)

            if not results or not results['ids']:
                print(f"No chapter documents found in vector database")
                return 0

            # 筛选出该章节的文档
            ids_to_delete = []
            for doc_id, metadata in zip(results['ids'], results['metadatas']):
                if metadata and (
                    metadata.get('chapter_number') == chapter_number or
                    metadata.get('chapter_number') == str(chapter_number) or
                    f'第{chapter_number}章' in str(metadata.get('title', ''))
                ):
                    ids_to_delete.append(doc_id)

            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                print(f"Deleted {len(ids_to_delete)} documents for chapter {chapter_number}")
                return len(ids_to_delete)
            else:
                print(f"No documents found for chapter {chapter_number}")
                return 0

        except Exception as e:
            print(f"Error deleting chapter from vector database: {e}")
            return 0

    def delete_project(self, project_id: int) -> int:
        """Delete all vector data for a project

        Args:
            project_id: 项目ID

        Returns:
            int: 删除的文档数量
        """
        try:
            collection = self.vectorstore._collection

            # 获取该项目的所有文档
            results = collection.get(
                where={"project_id": str(project_id)}
            )

            if results and results['ids']:
                deleted_count = len(results['ids'])
                collection.delete(ids=results['ids'])
                print(f"Deleted {deleted_count} documents for project {project_id}")
                return deleted_count
            else:
                print(f"No documents found for project {project_id}")
                return 0

        except Exception as e:
            print(f"Error deleting project from vector database: {e}")
            return 0

    def clear_database(self):
        """Clear knowledge base (use with caution)"""
        self.vectorstore.delete_collection()
        print("Knowledge base cleared")

    def load_from_markdown(self, file_path: str, doc_type: str, metadata: Optional[Dict[str, Any]] = None):
        """Load data from Markdown file to knowledge base"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            meta = metadata or {}

            if doc_type == "world_setting":
                title = f"World setting loaded from {file_path}"
                self.add_world_setting(title, content, meta)
                print(f"Loaded world setting from {file_path}")

            elif doc_type == "character":
                name = f"Character loaded from {file_path}"
                self.add_character(name, content, meta)
                print(f"Loaded character profile from {file_path}")

            elif doc_type == "plot":
                self.add_chapter(0, f"Plot outline loaded from {file_path}", content, meta)
                print(f"Loaded plot outline from {file_path}")

            else:
                print(f"Unknown document type: {doc_type}")
                return False

            return True

        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return False
        except Exception as e:
            print(f"Error loading file: {str(e)}")
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

            print(f"Loaded {files_loaded} files from directory")
            return files_loaded > 0

        except Exception as e:
            print(f"Error loading directory: {str(e)}")
            return False