"""
添加快照和置信度字段到 setting_items 表的迁移脚本
"""
import sqlite3
import os

# 数据库路径
db_path = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

def migrate():
    """执行数据库迁移"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(setting_items)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # 添加 snapshots 字段
        if "snapshots" not in columns:
            cursor.execute("""
                ALTER TABLE setting_items 
                ADD COLUMN snapshots TEXT
            """)
            print("✓ 已添加 snapshots 字段")
        else:
            print("✓ snapshots 字段已存在")
        
        # 添加 confidence_score 字段
        if "confidence_score" not in columns:
            cursor.execute("""
                ALTER TABLE setting_items 
                ADD COLUMN confidence_score REAL
            """)
            print("✓ 已添加 confidence_score 字段")
        else:
            print("✓ confidence_score 字段已存在")
        
        conn.commit()
        print("\n✅ 数据库迁移完成")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
