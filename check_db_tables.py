"""检查数据库表结构"""
import sqlite3

db_path = "c:/Users/cuigu/novel_writing_agent/backend/novel_app.db"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查询所有表
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' 
        ORDER BY name
    """)
    
    tables = cursor.fetchall()
    
    print("\n" + "="*80)
    print("📊 数据库中的所有表")
    print("="*80 + "\n")
    
    for table in tables:
        table_name = table[0]
        print(f"📋 表名: {table_name}")
        
        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        for col in columns:
            col_id, col_name, col_type, not_null, default_val, pk = col
            print(f"   - {col_name} ({col_type}){' [主键]' if pk else ''}")
        
        print()
    
    # 检查project_settings表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='project_settings'
    """)
    
    result = cursor.fetchone()
    
    if not result:
        print("\n❌ project_settings 表不存在！")
        print("需要运行数据库迁移\n")
    else:
        print("\n✅ project_settings 表存在\n")
    
    conn.close()
    
except Exception as e:
    print(f"\n❌ 错误: {e}\n")
    import traceback
    traceback.print_exc()
