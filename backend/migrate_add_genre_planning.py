"""
添加题材与篇幅规划字段到 projects 表的迁移脚本
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
        cursor.execute("PRAGMA table_info(projects)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # 添加 sub_genre 字段
        if "sub_genre" not in columns:
            cursor.execute("""
                ALTER TABLE projects 
                ADD COLUMN sub_genre VARCHAR(100)
            """)
            print("✓ 已添加 sub_genre 字段")
        else:
            print("✓ sub_genre 字段已存在")
        
        # 添加 planned_length_type 字段
        if "planned_length_type" not in columns:
            cursor.execute("""
                ALTER TABLE projects 
                ADD COLUMN planned_length_type VARCHAR(20)
            """)
            print("✓ 已添加 planned_length_type 字段")
        else:
            print("✓ planned_length_type 字段已存在")
        
        # 添加 planned_chapters_min 字段
        if "planned_chapters_min" not in columns:
            cursor.execute("""
                ALTER TABLE projects 
                ADD COLUMN planned_chapters_min INTEGER
            """)
            print("✓ 已添加 planned_chapters_min 字段")
        else:
            print("✓ planned_chapters_min 字段已存在")
        
        # 添加 planned_chapters_max 字段
        if "planned_chapters_max" not in columns:
            cursor.execute("""
                ALTER TABLE projects 
                ADD COLUMN planned_chapters_max INTEGER
            """)
            print("✓ 已添加 planned_chapters_max 字段")
        else:
            print("✓ planned_chapters_max 字段已存在")
        
        # 添加 user_outline_plan 字段
        if "user_outline_plan" not in columns:
            cursor.execute("""
                ALTER TABLE projects 
                ADD COLUMN user_outline_plan TEXT
            """)
            print("✓ 已添加 user_outline_plan 字段")
        else:
            print("✓ user_outline_plan 字段已存在")
        
        conn.commit()
        print("\n✅ 数据库迁移完成 - 题材与篇幅规划字段已添加到 projects 表")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
