"""
全面检查SQLite和PostgreSQL数据库的迁移情况
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import sqlite3
import psycopg2
from collections import defaultdict

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")
sqlite_db_path = Path(__file__).parent / "novel_app.db"

print("=" * 80)
print("SQLite vs PostgreSQL 数据库迁移全面检查")
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
    print(f"  SQLite: {sqlite_db_path}")
    print(f"  PostgreSQL: {host}:{port}/{database}")
    
    try:
        # 连接SQLite
        print(f"\n{'='*80}")
        print("连接SQLite数据库...")
        print(f"{'='*80}")
        
        if not sqlite_db_path.exists():
            print(f"❌ SQLite数据库文件不存在: {sqlite_db_path}")
            sys.exit(1)
        
        sqlite_conn = sqlite3.connect(str(sqlite_db_path))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        
        # 获取SQLite所有表
        sqlite_cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
        """)
        sqlite_tables = [row[0] for row in sqlite_cursor.fetchall()]
        
        print(f"✅ SQLite连接成功，找到 {len(sqlite_tables)} 个表")
        
        # 连接PostgreSQL
        print(f"\n{'='*80}")
        print("连接PostgreSQL数据库...")
        print(f"{'='*80}")
        
        postgres_conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        postgres_conn.autocommit = True
        postgres_cursor = postgres_conn.cursor()
        
        # 获取PostgreSQL所有表
        postgres_cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        postgres_tables = [row[0] for row in postgres_cursor.fetchall()]
        
        print(f"✅ PostgreSQL连接成功，找到 {len(postgres_tables)} 个表")
        
        # 对比表
        print(f"\n{'='*80}")
        print("表对比")
        print(f"{'='*80}")
        
        sqlite_only = set(sqlite_tables) - set(postgres_tables)
        postgres_only = set(postgres_tables) - set(sqlite_tables)
        common_tables = set(sqlite_tables) & set(postgres_tables)
        
        print(f"\nSQLite独有表 ({len(sqlite_only)} 个):")
        if sqlite_only:
            for table in sorted(sqlite_only):
                print(f"  ❌ {table}")
        else:
            print("  无")
        
        print(f"\nPostgreSQL独有表 ({len(postgres_only)} 个):")
        if postgres_only:
            for table in sorted(postgres_only):
                print(f"  ➕ {table}")
        else:
            print("  无")
        
        print(f"\n共有表 ({len(common_tables)} 个):")
        for table in sorted(common_tables):
            print(f"  ✓ {table}")
        
        # 检查每个表的数据量
        print(f"\n{'='*80}")
        print("数据量对比")
        print(f"{'='*80}")
        
        print(f"\n{'表名':<30} {'SQLite记录数':<15} {'PostgreSQL记录数':<20} {'状态':<15}")
        print("-" * 80)
        
        migration_issues = []
        
        for table in sorted(common_tables):
            # SQLite记录数
            try:
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                sqlite_count = sqlite_cursor.fetchone()[0]
            except Exception as e:
                sqlite_count = f"错误: {str(e)[:20]}"
            
            # PostgreSQL记录数
            try:
                postgres_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                postgres_count = postgres_cursor.fetchone()[0]
            except Exception as e:
                postgres_count = f"错误: {str(e)[:20]}"
            
            # 判断状态
            if isinstance(sqlite_count, int) and isinstance(postgres_count, int):
                if sqlite_count == postgres_count:
                    status = "✅ 完整"
                elif postgres_count == 0:
                    status = "❌ 未迁移"
                    migration_issues.append((table, sqlite_count, 0))
                elif postgres_count < sqlite_count:
                    status = f"⚠️ 不完整 ({postgres_count}/{sqlite_count})"
                    migration_issues.append((table, sqlite_count, postgres_count))
                else:
                    status = f"➕ 超出 ({postgres_count}/{sqlite_count})"
            else:
                status = "❌ 错误"
            
            print(f"{table:<30} {str(sqlite_count):<15} {str(postgres_count):<20} {status:<15}")
        
        # 检查SQLite独有表的数据
        if sqlite_only:
            print(f"\n{'='*80}")
            print("SQLite独有表的数据量")
            print(f"{'='*80}")
            
            for table in sorted(sqlite_only):
                try:
                    sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = sqlite_cursor.fetchone()[0]
                    print(f"  {table}: {count} 条记录")
                    migration_issues.append((table, count, 0))
                except Exception as e:
                    print(f"  {table}: 错误 - {e}")
        
        # 检查表结构差异
        print(f"\n{'='*80}")
        print("表结构对比（共有表）")
        print(f"{'='*80}")
        
        for table in sorted(common_tables):
            print(f"\n表: {table}")
            print("-" * 80)
            
            # SQLite列
            try:
                sqlite_cursor.execute(f"PRAGMA table_info({table})")
                sqlite_columns = {row[1]: row[2] for row in sqlite_cursor.fetchall()}
            except Exception as e:
                sqlite_columns = {}
                print(f"  ❌ SQLite列查询失败: {e}")
            
            # PostgreSQL列
            try:
                postgres_cursor.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position;
                """, (table,))
                postgres_columns = {row[0]: row[1] for row in postgres_cursor.fetchall()}
            except Exception as e:
                postgres_columns = {}
                print(f"  ❌ PostgreSQL列查询失败: {e}")
            
            # 对比列
            sqlite_only_cols = set(sqlite_columns.keys()) - set(postgres_columns.keys())
            postgres_only_cols = set(postgres_columns.keys()) - set(sqlite_columns.keys())
            common_cols = set(sqlite_columns.keys()) & set(postgres_columns.keys())
            
            if sqlite_only_cols:
                print(f"  SQLite独有列: {', '.join(sorted(sqlite_only_cols))}")
            if postgres_only_cols:
                print(f"  PostgreSQL独有列: {', '.join(sorted(postgres_only_cols))}")
            
            if not sqlite_only_cols and not postgres_only_cols:
                print(f"  ✅ 列结构一致 ({len(common_cols)} 个列)")
        
        # 总结
        print(f"\n{'='*80}")
        print("迁移总结")
        print(f"{'='*80}")
        
        print(f"\nSQLite表总数: {len(sqlite_tables)}")
        print(f"PostgreSQL表总数: {len(postgres_tables)}")
        print(f"共有表数: {len(common_tables)}")
        print(f"SQLite独有表数: {len(sqlite_only)}")
        print(f"PostgreSQL独有表数: {len(postgres_only)}")
        
        if migration_issues:
            print(f"\n❌ 发现 {len(migration_issues)} 个迁移问题:")
            print(f"{'='*80}")
            print(f"{'表名':<30} {'SQLite记录数':<15} {'PostgreSQL记录数':<20}")
            print("-" * 80)
            
            for table, sqlite_count, postgres_count in migration_issues:
                print(f"{table:<30} {sqlite_count:<15} {postgres_count:<20}")
        else:
            print(f"\n✅ 所有数据迁移完整！")
        
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
