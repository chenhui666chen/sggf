"""
手动添加 deleted_at 列到 audiobook 相关表
"""
import sqlite3
from pathlib import Path

# 数据库路径
db_path = Path(__file__).parent / "novel_app.db"

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # 检查 audiobook_projects 表是否有 deleted_at 列
    cursor.execute("PRAGMA table_info(audiobook_projects)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'deleted_at' not in columns:
        print("为 audiobook_projects 表添加 deleted_at 列...")
        cursor.execute("""
            ALTER TABLE audiobook_projects 
            ADD COLUMN deleted_at DATETIME
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_audiobook_projects_deleted_at 
            ON audiobook_projects(deleted_at)
        """)
        print("✓ audiobook_projects 表的 deleted_at 列添加成功")
    else:
        print("✓ audiobook_projects 表已存在 deleted_at 列")
    
    # 检查 chapter_audios 表是否有 deleted_at 列
    cursor.execute("PRAGMA table_info(chapter_audios)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'deleted_at' not in columns:
        print("为 chapter_audios 表添加 deleted_at 列...")
        cursor.execute("""
            ALTER TABLE chapter_audios 
            ADD COLUMN deleted_at DATETIME
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_chapter_audios_deleted_at 
            ON chapter_audios(deleted_at)
        """)
        print("✓ chapter_audios 表的 deleted_at 列添加成功")
    else:
        print("✓ chapter_audios 表已存在 deleted_at 列")
    
    # 提交更改
    conn.commit()
    print("\n✅ 数据库更新完成！")
    
    # 验证更改
    print("\n验证表结构：")
    cursor.execute("PRAGMA table_info(audiobook_projects)")
    print("audiobook_projects 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")
    
    cursor.execute("PRAGMA table_info(chapter_audios)")
    print("\nchapter_audios 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")

except Exception as e:
    print(f"❌ 错误：{e}")
    conn.rollback()
finally:
    conn.close()
