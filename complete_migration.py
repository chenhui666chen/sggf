"""
完整的数据迁移脚本 - 修复所有迁移问题
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import sqlite3
import psycopg2
from psycopg2 import sql

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")
sqlite_db_path = Path(__file__).parent / "novel_app.db"

print("=" * 80)
print("完整数据迁移 - 修复所有迁移问题")
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
        print(f"\n连接SQLite数据库: {sqlite_db_path}")
        sqlite_conn = sqlite3.connect(str(sqlite_db_path))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        
        # 连接PostgreSQL
        print(f"连接PostgreSQL数据库: {host}:{port}/{database}")
        postgres_conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        postgres_conn.autocommit = True
        postgres_cursor = postgres_conn.cursor()
        
        # ============ 1. 创建SQLite独有表 ============
        print(f"\n{'='*80}")
        print("步骤1: 创建SQLite独有表")
        print(f"{'='*80}")
        
        # chapter_plans表
        print("\n创建 chapter_plans 表...")
        postgres_cursor.execute("""
            CREATE TABLE IF NOT EXISTS chapter_plans (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
                title TEXT,
                content TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✅ chapter_plans 表创建成功")
        
        # generation_history表
        print("\n创建 generation_history 表...")
        postgres_cursor.execute("""
            CREATE TABLE IF NOT EXISTS generation_history (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
                task_type VARCHAR(50),
                prompt TEXT,
                result TEXT,
                model_used VARCHAR(100),
                tokens_used INTEGER,
                duration_ms INTEGER,
                status VARCHAR(20) DEFAULT 'completed',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✅ generation_history 表创建成功")
        
        # knowledge_base表
        print("\n创建 knowledge_base 表...")
        postgres_cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT,
                category VARCHAR(50),
                tags TEXT,
                source_type VARCHAR(50),
                source_url TEXT,
                confidence_score FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✅ knowledge_base 表创建成功")
        
        # review_results表
        print("\n创建 review_results 表...")
        postgres_cursor.execute("""
            CREATE TABLE IF NOT EXISTS review_results (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
                review_type VARCHAR(50),
                content TEXT,
                suggestions TEXT,
                score FLOAT,
                status VARCHAR(20) DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✅ review_results 表创建成功")
        
        # workflow_sessions表
        print("\n创建 workflow_sessions 表...")
        postgres_cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_sessions (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                session_type VARCHAR(50),
                status VARCHAR(20) DEFAULT 'active',
                current_stage VARCHAR(50),
                data TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
        """)
        print("✅ workflow_sessions 表创建成功")
        
        # ============ 2. 修复表结构差异 ============
        print(f"\n{'='*80}")
        print("步骤2: 修复表结构差异")
        print(f"{'='*80}")
        
        # characters表 - 添加缺失的列
        print("\n为 characters 表添加缺失的列...")
        columns_to_add = [
            ("artifacts", "TEXT"),
            ("related_locations", "TEXT"),
            ("techniques", "TEXT")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                postgres_cursor.execute(f"""
                    ALTER TABLE characters 
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type};
                """)
                print(f"  ✅ 添加列: {col_name}")
            except Exception as e:
                print(f"  ⚠️ 添加列 {col_name} 失败: {e}")
        
        # project_settings表 - 添加缺失的列
        print("\n为 project_settings 表添加缺失的列...")
        columns_to_add = [
            ("epic_framework", "TEXT"),
            ("epic_framework_generated_at", "TIMESTAMP"),
            ("epic_volumes_detail", "TEXT")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                postgres_cursor.execute(f"""
                    ALTER TABLE project_settings 
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type};
                """)
                print(f"  ✅ 添加列: {col_name}")
            except Exception as e:
                print(f"  ⚠️ 添加列 {col_name} 失败: {e}")
        
        # ============ 3. 迁移数据 ============
        print(f"\n{'='*80}")
        print("步骤3: 迁移数据")
        print(f"{'='*80}")
        
        # 定义需要迁移的表
        tables_to_migrate = [
            "audiobook_delete_audits",
            "audiobook_projects",
            "audiobook_tasks",
            "chapter_audios",
            "chapters",
            "characters",
            "dreamweaver_assets",
            "dreamweaver_episodes",
            "dreamweaver_projects",
            "dreamweaver_shots",
            "knowledge_graph_edges",
            "memories",
            "project_settings",
            "projects",
            "setting_collections",
            "setting_items",
            "chapter_plans",
            "generation_history",
            "knowledge_base",
            "review_results",
            "workflow_sessions"
        ]
        
        for table_name in tables_to_migrate:
            print(f"\n迁移表: {table_name}")
            
            try:
                # 获取SQLite表结构
                sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
                sqlite_columns = [row[1] for row in sqlite_cursor.fetchall()]
                
                # 获取SQLite数据
                sqlite_cursor.execute(f"SELECT * FROM {table_name}")
                rows = sqlite_cursor.fetchall()
                
                if not rows:
                    print(f"  ℹ️  无数据需要迁移")
                    continue
                
                # 构建插入语句
                columns_str = ", ".join(sqlite_columns)
                placeholders = ", ".join(["%s"] * len(sqlite_columns))
                
                insert_sql = f"""
                    INSERT INTO {table_name} ({columns_str})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """
                
                # 转换数据并插入
                migrated_count = 0
                for row in rows:
                    try:
                        # 转换数据类型
                        row_data = []
                        for i, value in enumerate(row):
                            col_name = sqlite_columns[i]
                            
                            # 处理NULL值
                            if value is None:
                                row_data.append(None)
                            # 处理时间戳
                            elif col_name in ['created_at', 'updated_at', 'started_at', 'completed_at', 
                                            'generated_at', 'deleted_at', 'last_referenced_at']:
                                if value:
                                    row_data.append(value)
                                else:
                                    row_data.append(None)
                            # 处理其他类型
                            else:
                                row_data.append(value)
                        
                        postgres_cursor.execute(insert_sql, row_data)
                        migrated_count += 1
                        
                    except Exception as e:
                        print(f"  ⚠️ 迁移行失败: {e}")
                        continue
                
                print(f"  ✅ 迁移了 {migrated_count} 条记录")
                
            except Exception as e:
                print(f"  ❌ 迁移失败: {e}")
                continue
        
        # ============ 4. 验证迁移结果 ============
        print(f"\n{'='*80}")
        print("步骤4: 验证迁移结果")
        print(f"{'='*80}")
        
        print(f"\n{'表名':<30} {'SQLite记录数':<15} {'PostgreSQL记录数':<20} {'状态':<15}")
        print("-" * 80)
        
        all_tables = set()
        sqlite_cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
        """)
        all_tables.update([row[0] for row in sqlite_cursor.fetchall()])
        
        postgres_cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        all_tables.update([row[0] for row in postgres_cursor.fetchall()])
        
        success_count = 0
        issue_count = 0
        
        for table in sorted(all_tables):
            # SQLite记录数
            try:
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                sqlite_count = sqlite_cursor.fetchone()[0]
            except:
                sqlite_count = 0
            
            # PostgreSQL记录数
            try:
                postgres_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                postgres_count = postgres_cursor.fetchone()[0]
            except:
                postgres_count = 0
            
            # 判断状态
            if sqlite_count == postgres_count:
                status = "✅ 完整"
                success_count += 1
            elif postgres_count == 0 and sqlite_count == 0:
                status = "ℹ️  空表"
            elif postgres_count == 0:
                status = "❌ 未迁移"
                issue_count += 1
            elif postgres_count < sqlite_count:
                status = f"⚠️ 不完整 ({postgres_count}/{sqlite_count})"
                issue_count += 1
            else:
                status = f"➕ 超出 ({postgres_count}/{sqlite_count})"
            
            print(f"{table:<30} {sqlite_count:<15} {postgres_count:<20} {status:<15}")
        
        # 总结
        print(f"\n{'='*80}")
        print("迁移总结")
        print(f"{'='*80}")
        print(f"\n✅ 完整迁移的表: {success_count}")
        print(f"❌ 有问题的表: {issue_count}")
        
        if issue_count == 0:
            print(f"\n🎉 所有数据迁移完成！")
        else:
            print(f"\n⚠️  仍有 {issue_count} 个表需要检查")
        
        sqlite_cursor.close()
        sqlite_conn.close()
        postgres_cursor.close()
        postgres_conn.close()
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

else:
    print(f"\n❌ 不支持的数据库URL格式: {database_url}")
    sys.exit(1)

print(f"\n{'='*80}")
print("迁移完成")
print(f"{'='*80}")
