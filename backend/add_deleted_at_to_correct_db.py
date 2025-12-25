"""
在正确的数据库中添加缺失的 deleted_at 列
"""
import sqlite3
from pathlib import Path

# 数据库路径 - 项目根目录下的 novel_app.db（后端实际使用的数据库）
db_path = Path(__file__).parent.parent / "novel_app.db"

print(f"数据库路径：{db_path}")
print(f"数据库文件存在：{db_path.exists()}")

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # 检查 audiobook_projects 表的现有列
    print("\n📋 检查 audiobook_projects 表结构...")
    cursor.execute("PRAGMA table_info(audiobook_projects)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"现有列：{columns}")
    
    # 检查是否缺少 deleted_at 列
    if 'deleted_at' not in columns:
        print("\n➕ 添加 deleted_at 列到 audiobook_projects 表...")
        cursor.execute("ALTER TABLE audiobook_projects ADD COLUMN deleted_at DATETIME")
        print("✓ deleted_at 列添加成功")
    else:
        print("✓ deleted_at 列已存在")
    
    # 创建索引（如果不存在）
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_audiobook_projects_deleted_at 
            ON audiobook_projects(deleted_at)
        """)
        print("✓ 索引创建成功")
    except Exception as e:
        print(f"索引创建警告：{e}")
    
    # 检查 chapter_audios 表的现有列
    print("\n📋 检查 chapter_audios 表结构...")
    cursor.execute("PRAGMA table_info(chapter_audios)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"现有列：{columns}")
    
    # 检查是否缺少 deleted_at 列
    if 'deleted_at' not in columns:
        print("\n➕ 添加 deleted_at 列到 chapter_audios 表...")
        cursor.execute("ALTER TABLE chapter_audios ADD COLUMN deleted_at DATETIME")
        print("✓ deleted_at 列添加成功")
    else:
        print("✓ deleted_at 列已存在")
    
    # 创建索引（如果不存在）
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_chapter_audios_deleted_at 
            ON chapter_audios(deleted_at)
        """)
        print("✓ 索引创建成功")
    except Exception as e:
        print(f"索引创建警告：{e}")
    
    # 提交更改
    conn.commit()
    print("\n✅ 数据库更新完成！")
    
    # 验证表结构
    print("\n📋 验证表结构：")
    
    cursor.execute("PRAGMA table_info(audiobook_projects)")
    print("\naudiobook_projects 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")
    
    cursor.execute("PRAGMA table_info(chapter_audios)")
    print("\nchapter_audios 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")

except Exception as e:
    print(f"❌ 错误：{e}")
    import traceback
    traceback.print_exc()
    conn.rollback()
finally:
    conn.close()
