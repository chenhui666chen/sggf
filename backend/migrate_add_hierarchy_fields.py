"""
添加层级与模板字段到 setting_items / setting_collections 表
允许在迁移过程中修改结构（当前数据为调试用途）。
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

COLUMNS_ITEMS = {
    "depth": "INTEGER",
    "node_type": "TEXT",
    "is_leaf": "INTEGER",  # SQLite 无原生 BOOLEAN，使用整型 0/1
    "path": "TEXT",
    "summary": "TEXT",
}

COLUMNS_COLLECTIONS = {
    "max_depth": "INTEGER",
    "hierarchy_config": "TEXT",
}


def column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # setting_items
        for col, typ in COLUMNS_ITEMS.items():
            if not column_exists(cursor, "setting_items", col):
                cursor.execute(f"ALTER TABLE setting_items ADD COLUMN {col} {typ}")
                print(f"✓ setting_items 添加列: {col} {typ}")
            else:
                print(f"✓ setting_items 列已存在: {col}")

        # setting_collections
        for col, typ in COLUMNS_COLLECTIONS.items():
            if not column_exists(cursor, "setting_collections", col):
                cursor.execute(f"ALTER TABLE setting_collections ADD COLUMN {col} {typ}")
                print(f"✓ setting_collections 添加列: {col} {typ}")
            else:
                print(f"✓ setting_collections 列已存在: {col}")

        conn.commit()
        print("\n✅ 层级与模板字段迁移完成")
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
