"""
检查未迁移表的具体问题
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
print("检查未迁移表的具体问题")
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
            "setting_items",
            "characters",
            "dreamweaver_assets",
            "dreamweaver_projects"
        ]
        
        for table_name in tables_to_check:
            print(f"\n{'='*80}")
            print(f"表: {table_name}")
            print(f"{'='*80}")
            
            # 获取SQLite表结构
            sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
            sqlite_columns = [row[1] for row in sqlite_cursor.fetchall()]
            print(f"\nSQLite列: {sqlite_columns}")
            
            # 获取PostgreSQL表结构
            postgres_cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position;
            """, (table_name,))
            postgres_columns = [row[0] for row in postgres_cursor.fetchall()]
            print(f"PostgreSQL列: {postgres_columns}")
            
            # 找出差异
            sqlite_only = set(sqlite_columns) - set(postgres_columns)
            postgres_only = set(postgres_columns) - set(sqlite_columns)
            common = set(sqlite_columns) & set(postgres_columns)
            
            if sqlite_only:
                print(f"\nSQLite独有列: {sqlite_only}")
            if postgres_only:
                print(f"PostgreSQL独有列: {postgres_only}")
            
            print(f"\n共有列: {len(common)} 个")
            
            # 尝试插入一条数据看看错误
            sqlite_cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
            row = sqlite_cursor.fetchone()
            
            if row:
                print(f"\n尝试迁移第一条数据...")
                row_dict = dict(zip(sqlite_columns, row))
                
                # 只使用共有的列
                row_data = [row_dict[col] for col in sorted(common)]
                
                columns_str = ", ".join(sorted(common))
                placeholders = ", ".join(["%s"] * len(common))
                
                insert_sql = f"""
                    INSERT INTO {table_name} ({columns_str})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """
                
                try:
                    postgres_cursor.execute(insert_sql, row_data)
                    print(f"✅ 成功插入第一条数据")
                except Exception as e:
                    print(f"❌ 插入失败: {e}")
        
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
