from app.services import vector_sync


class _FakeCollection:
    def __init__(self):
        self.deleted_ids = []
        self.queries = []

    def get(self, where):
        self.queries.append(where)
        return {"ids": ["old-plot-doc"], "metadatas": []}

    def delete(self, ids):
        self.deleted_ids.extend(ids)


class _FakeVectorstore:
    def __init__(self):
        self._collection = _FakeCollection()


class _FakeKnowledgeBase:
    def __init__(self):
        self.vectorstore = _FakeVectorstore()
        self.added_plot_outlines = []
        self.added_chapters = []

    def add_plot_outline(self, name, content, metadata):
        self.added_plot_outlines.append((name, content, metadata))

    def add_chapter(self, chapter_num, name, content, metadata):
        self.added_chapters.append((chapter_num, name, content, metadata))

    def add_world_setting(self, name, content, metadata):
        raise AssertionError("unexpected add_world_setting")

    def add_character(self, name, content, metadata):
        raise AssertionError("unexpected add_character")


def test_sync_to_vector_db_uses_plot_outline_writer_and_deletes_old_project_docs(monkeypatch):
    kb = _FakeKnowledgeBase()
    monkeypatch.setattr(vector_sync, "get_vector_kb", lambda: kb)

    vector_sync.sync_to_vector_db(
        "plot",
        "project_15_plot_outline",
        "第17章：进入遗迹",
        {"project_id": "15"},
    )

    assert kb.vectorstore._collection.deleted_ids == ["old-plot-doc"]
    assert len(kb.added_plot_outlines) == 1
    assert kb.added_plot_outlines[0][2]["project_id"] == "15"
    assert kb.added_chapters == []
