"""
创建 project_settings 表
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
print("创建 project_settings 表")
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
        
        # 创建 project_settings 表
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS project_settings (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            concept TEXT,
            world_setting TEXT,
            characters TEXT,
            plot_outline TEXT,
            chapter_draft TEXT,
            review_report TEXT,
            final_version TEXT,
            stage_one_status VARCHAR(20) DEFAULT 'pending',
            stage_two_status VARCHAR(20) DEFAULT 'pending',
            stage_three_status VARCHAR(20) DEFAULT 'pending',
            stage_four_status VARCHAR(20) DEFAULT 'pending',
            stage_five_status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS ix_project_settings_project_id ON project_settings(project_id);
        """
        
        print(f"\n{'='*60}")
        print("创建表...")
        print(f"{'='*60}")
        
        cursor.execute(create_table_sql)
        
        print("✅ project_settings 表创建成功")
        
        # 验证表是否创建成功
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'project_settings'
            );
        """)
        
        exists = cursor.fetchone()[0]
        
        if exists:
            print("✅ 表已成功创建并验证")
            
            # 显示表结构
            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'project_settings'
                ORDER BY ordinal_position;
            """)
            
            columns = cursor.fetchall()
            
            print(f"\n表结构:")
            for col_name, data_type, is_nullable, col_default in columns:
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                default = f" DEFAULT {col_default}" if col_default else ""
                print(f"  {col_name}: {data_type} {nullable}{default}")
        else:
            print("❌ 表创建失败")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ 创建表失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

else:
    print(f"\n❌ 不支持的数据库URL格式: {database_url}")
    sys.exit(1)

print(f"\n{'='*60}")
print("操作完成")
print(f"{'='*60}")
