"""查看数据库所有表"""
import sqlite3
import sys

# 设置输出编码为UTF-8
sys.stdout.reconfigure(encoding='utf-8')

db_path = "c:/Users/cuigu/novel_writing_agent/backend/novel_app.db"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 获取所有表名
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print("\n" + "="*80)
    print("📊 数据库表列表")
    print("="*80 + "\n")
    
    for table in tables:
        table_name = table[0]
        print(f"📁 {table_name}")
        
        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        for col in columns:
            col_id, col_name, col_type, not_null, default, pk = col
            print(f"   - {col_name} ({col_type})")
        print()
    
    conn.close()
    
except Exception as e:
    print(f"\n❌ 错误: {e}\n")
    import traceback
    traceback.print_exc()
