"""
检查PostgreSQL数据库中的表结构
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")

print("=" * 60)
print("PostgreSQL数据库表检查")
print("=" * 60)

# 解析数据库URL
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
        # 连接数据库
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
        print(f"\n{'='*60}")
        print("数据库中的所有表:")
        print(f"{'='*60}")
        
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
        
        # 检查 project_settings 表是否存在
        print(f"\n{'='*60}")
        print("检查 project_settings 表:")
        print(f"{'='*60}")
        
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'project_settings'
            );
        """)
        
        exists = cursor.fetchone()[0]
        
        if exists:
            print("  ✅ project_settings 表存在")
            
            # 查询表结构
            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'project_settings'
                ORDER BY ordinal_position;
            """)
            
            columns = cursor.fetchall()
            
            print(f"\n  表结构:")
            for col_name, data_type, is_nullable, col_default in columns:
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                default = f" DEFAULT {col_default}" if col_default else ""
                print(f"    {col_name}: {data_type} {nullable}{default}")
            
            # 查询表中的数据
            cursor.execute("SELECT COUNT(*) FROM project_settings;")
            count = cursor.fetchone()[0]
            print(f"\n  表中的记录数: {count}")
            
        else:
            print("  ❌ project_settings 表不存在")
            print("\n  💡 需要创建 project_settings 表")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ 数据库连接失败: {e}")
        sys.exit(1)

else:
    print(f"\n❌ 不支持的数据库URL格式: {database_url}")
    sys.exit(1)

print(f"\n{'='*60}")
print("检查完成")
print(f"{'='*60}")
