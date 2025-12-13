"""简化查看表结构"""
import sqlite3

db_path = "c:/Users/cuigu/novel_writing_agent/backend/novel_app.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 获取所有表名
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()

print("\n=== Tables ===\n")
for table in tables:
    table_name = table[0]
    print(f"\n[{table_name}]")
    
    # 检查是否包含epic_framework字段
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for col in columns:
        col_name = col[1]
        col_type = col[2]
        if 'epic' in col_name.lower() or 'plot' in col_name.lower():
            print(f"  * {col_name} ({col_type})")

conn.close()
