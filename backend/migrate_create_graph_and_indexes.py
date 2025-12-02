"""
创建知识图谱关系表与索引；为层级查询添加索引。
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")


def table_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cursor.fetchone() is not None


def index_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,))
    return cursor.fetchone() is not None


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 创建知识图谱关系表
        if not table_exists(cursor, "knowledge_graph_edges"):
            cursor.execute(
                """
                CREATE TABLE knowledge_graph_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_item_id INTEGER NOT NULL,
                    target_item_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL,
                    auto_extracted INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(source_item_id) REFERENCES setting_items(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_item_id) REFERENCES setting_items(id) ON DELETE CASCADE
                )
                """
            )
            print("✓ 已创建 knowledge_graph_edges 表")
        else:
            print("✓ knowledge_graph_edges 表已存在")

        # 索引：关系查询
        if not index_exists(cursor, "idx_kge_source"):
            cursor.execute("CREATE INDEX idx_kge_source ON knowledge_graph_edges(source_item_id)")
            print("✓ 创建索引 idx_kge_source")
        if not index_exists(cursor, "idx_kge_target"):
            cursor.execute("CREATE INDEX idx_kge_target ON knowledge_graph_edges(target_item_id)")
            print("✓ 创建索引 idx_kge_target")
        if not index_exists(cursor, "idx_kge_reltype"):
            cursor.execute("CREATE INDEX idx_kge_reltype ON knowledge_graph_edges(relation_type)")
            print("✓ 创建索引 idx_kge_reltype")

        # 为层级查询添加索引
        if not index_exists(cursor, "idx_setting_items_path"):
            cursor.execute("CREATE INDEX idx_setting_items_path ON setting_items(path)")
            print("✓ 创建索引 idx_setting_items_path")
        if not index_exists(cursor, "idx_setting_items_depth"):
            cursor.execute("CREATE INDEX idx_setting_items_depth ON setting_items(depth)")
            print("✓ 创建索引 idx_setting_items_depth")

        conn.commit()
        print("\n✅ 图谱表与索引迁移完成")
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
