import sys
import types

from app.services.agents import knowledge_base as knowledge_base_module


class _FakeEmbeddings:
    def __init__(self, *args, **kwargs):
        pass


class _FakeSettings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakePersistentClient:
    def __init__(self, path, settings):
        self.path = path
        self.settings = settings


class _FakeChroma:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _FakeSplitter:
    def split_text(self, text):
        return [text]


class _FakeVectorstoreForAdd:
    def __init__(self):
        self.added_documents = []

    def add_documents(self, documents):
        self.added_documents.extend(documents)


def _install_fake_chromadb(monkeypatch, persistent_client_cls):
    fake_chromadb = types.ModuleType("chromadb")
    fake_chromadb.PersistentClient = persistent_client_cls
    fake_config = types.ModuleType("chromadb.config")
    fake_config.Settings = _FakeSettings
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    monkeypatch.setitem(sys.modules, "chromadb.config", fake_config)


def test_knowledge_base_falls_back_to_alternate_persistent_directory(monkeypatch):
    class _PrimaryFailsClient(_FakePersistentClient):
        def __init__(self, path, settings):
            if path == "primary_dir":
                raise RuntimeError("primary broken")
            super().__init__(path, settings)

    _install_fake_chromadb(monkeypatch, _PrimaryFailsClient)
    monkeypatch.setattr(knowledge_base_module, "AliyunEmbeddings", _FakeEmbeddings)
    monkeypatch.setattr(knowledge_base_module, "Chroma", _FakeChroma)

    kb = knowledge_base_module.NovelKnowledgeBase(persist_directory="primary_dir")

    assert kb.vectorstore_mode == "persistent"
    assert kb.active_persist_directory == "primary_dir_runtime_fallback"
    assert kb.vectorstore.kwargs["client"].path == "primary_dir_runtime_fallback"
    assert kb.vectorstore.kwargs["collection_name"] == "novel_knowledge"


def test_knowledge_base_falls_back_to_in_memory_after_all_persistent_attempts_fail(monkeypatch):
    class _AlwaysFailClient(_FakePersistentClient):
        def __init__(self, path, settings):
            raise RuntimeError(f"broken: {path}")

    _install_fake_chromadb(monkeypatch, _AlwaysFailClient)
    monkeypatch.setattr(knowledge_base_module, "AliyunEmbeddings", _FakeEmbeddings)
    monkeypatch.setattr(knowledge_base_module, "Chroma", _FakeChroma)

    kb = knowledge_base_module.NovelKnowledgeBase(persist_directory="primary_dir")

    assert kb.vectorstore_mode == "in_memory"
    assert kb.active_persist_directory is None
    assert "client" not in kb.vectorstore.kwargs
    assert kb.vectorstore.kwargs["collection_name"] == "novel_knowledge"


def test_add_plot_outline_preserves_plot_outline_type():
    kb = object.__new__(knowledge_base_module.NovelKnowledgeBase)
    kb.text_splitter = _FakeSplitter()
    kb.vectorstore = _FakeVectorstoreForAdd()

    kb.add_plot_outline(
        "project_15_plot_outline",
        "第17章：进入遗迹",
        {"project_id": "15", "type": "chapter"},
    )

    assert len(kb.vectorstore.added_documents) == 1
    assert kb.vectorstore.added_documents[0].metadata["type"] == "plot_outline"
    assert kb.vectorstore.added_documents[0].metadata["project_id"] == "15"
