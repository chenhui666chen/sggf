"""
检查具体未迁移的数据
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import sqlite3
import psycopg2

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")
sqlite_db_path = Path(__file__).parent / "novel_app.db"

print("=" * 80)
print("检查具体未迁移的数据")
print("=" * 80)

# 解析PostgreSQL数据库URL
if database_url.startswith("postgresql://"):
    db_url = database_url.replace("postgresql://", "")
    parts = db_url.split("@")
    credentials = parts[0].split(":")
    host_db = parts[1].split("/")
    
    user = credentials[0]
    password = credentials[1]
    host_port = host_db[0].split(":")
    host = host_port[0]
    port = int(host_port[1]) if len(host_port) > 1 else 5432
    database = host_db[1]
    
    try:
        # 连接SQLite
        sqlite_conn = sqlite3.connect(str(sqlite_db_path))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        
        # 连接PostgreSQL
        postgres_conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        postgres_conn.autocommit = True
        postgres_cursor = postgres_conn.cursor()
        
        # 检查的表
        tables_to_check = [
            "audiobook_projects",
            "audiobook_tasks",
            "chapter_audios",
            "dreamweaver_episodes",
            "dreamweaver_shots",
            "knowledge_graph_edges",
            "setting_collections",
            "setting_items"
        ]
        
        for table_name in tables_to_check:
            print(f"\n{'='*80}")
            print(f"表: {table_name}")
            print(f"{'='*80}")
            
            # 获取SQLite数据
            sqlite_cursor.execute(f"SELECT * FROM {table_name}")
            sqlite_rows = sqlite_cursor.fetchall()
            
            # 获取PostgreSQL数据
            postgres_cursor.execute(f"SELECT * FROM {table_name}")
            postgres_rows = postgres_cursor.fetchall()
            
            print(f"\nSQLite记录数: {len(sqlite_rows)}")
            print(f"PostgreSQL记录数: {len(postgres_rows)}")
            
            if len(sqlite_rows) == 0:
                print("  ℹ️  SQLite无数据")
                continue
            
            # 获取列名
            sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
            sqlite_columns = [row[1] for row in sqlite_cursor.fetchall()]
            
            # 显示前3条SQLite数据
            print(f"\nSQLite前3条数据:")
            for i, row in enumerate(sqlite_rows[:3], 1):
                row_dict = dict(zip(sqlite_columns, row))
                print(f"\n  记录 {i}:")
                for key, value in row_dict.items():
                    if value is not None:
                        print(f"    {key}: {value}")
        
        sqlite_cursor.close()
        sqlite_conn.close()
        postgres_cursor.close()
        postgres_conn.close()
        
    except Exception as e:
        print(f"\n❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

else:
    print(f"\n❌ 不支持的数据库URL格式: {database_url}")
    sys.exit(1)

print(f"\n{'='*80}")
print("检查完成")
print(f"{'='*80}")
