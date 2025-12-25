"""
检查数据库中的所有表
"""
import sqlite3
from pathlib import Path

# 数据库路径
db_path = Path(__file__).parent / "novel_app.db"

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # 获取所有表名
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    
    print(f"数据库中的表（共 {len(tables)} 个）：\n")
    for table in tables:
        table_name = table[0]
        print(f"📋 {table_name}")
        
        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        for col in columns:
            print(f"   - {col[1]} ({col[2]})")
        print()

except Exception as e:
    print(f"❌ 错误：{e}")
finally:
    conn.close()
