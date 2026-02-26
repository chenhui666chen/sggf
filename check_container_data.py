"""
检查PostgreSQL容器中的数据
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")

print("=" * 80)
print("检查PostgreSQL容器中的数据")
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
    
    print(f"\n数据库连接信息:")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Database: {database}")
    print(f"  User: {user}")
    
    try:
        # 连接PostgreSQL
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # 查询所有表
        print(f"\n{'='*80}")
        print("数据库中的所有表:")
        print(f"{'='*80}")
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        
        tables = cursor.fetchall()
        
        if tables:
            for i, (table_name,) in enumerate(tables, 1):
                print(f"  {i}. {table_name}")
        else:
            print("  ❌ 没有找到任何表")
        
        # 查询关键表的数据量
        print(f"\n{'='*80}")
        print("关键表的数据量:")
        print(f"{'='*80}")
        
        key_tables = [
            "users",
            "projects",
            "chapters",
            "project_settings",
            "memories",
            "characters",
            "audiobook_projects",
            "audiobook_tasks"
        ]
        
        print(f"\n{'表名':<30} {'记录数':<15}")
        print("-" * 80)
        
        for table_name in key_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"{table_name:<30} {count:<15}")
            except Exception as e:
                print(f"{table_name:<30} 错误: {str(e)[:30]}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ 数据库连接失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

else:
    print(f"\n❌ 不支持的数据库URL格式: {database_url}")
    sys.exit(1)

print(f"\n{'='*80}")
print("检查完成")
print(f"{'='*80}")
