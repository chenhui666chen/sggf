"""
终极数据迁移脚本 - 处理所有数据类型和外键问题
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import sqlite3
import psycopg2
from psycopg2 import sql
from datetime import datetime

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")
sqlite_db_path = Path(__file__).parent / "novel_app.db"

print("=" * 80)
print("终极数据迁移 - 处理所有数据类型和外键问题")
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
        
        # ============ 1. 清空PostgreSQL表 ============
        print(f"\n{'='*80}")
        print("步骤1: 清空PostgreSQL表")
        print(f"{'='*80}")
        
        truncate_order = [
            "knowledge_graph_edges",
            "setting_items",
            "setting_collections",
            "chapter_revisions",
            "chapters",
            "chapter_audios",
            "audiobook_tasks",
            "audiobook_delete_audits",
            "audiobook_projects",
            "dreamweaver_shots",
            "dreamweaver_episodes",
            "dreamweaver_assets",
            "dreamweaver_projects",
            "character_techniques",
            "characters",
            "memories",
            "project_settings",
            "projects",
            "book_chapters",
            "book_sources",
            "book_analyses",
            "reviews",
            "chapter_plans",
            "generation_history",
            "knowledge_base",
            "review_results",
            "workflow_sessions"
        ]
        
        for table_name in truncate_order:
            try:
                postgres_cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE;")
                print(f"  ✅ 清空表: {table_name}")
            except Exception as e:
                print(f"  ⚠️ 清空表 {table_name} 失败: {e}")
        
        # ============ 2. 迁移数据 ============
        print(f"\n{'='*80}")
        print("步骤2: 迁移数据")
        print(f"{'='*80}")
        
        # 定义迁移顺序
        migrate_order = [
            "users",
            "projects",
            "project_settings",
            "memories",
            "characters",
            "character_techniques",
            "setting_collections",
            "setting_items",
            "chapters",
            "chapter_revisions",
            "chapter_audios",
            "audiobook_projects",
            "audiobook_tasks",
            "audiobook_delete_audits",
            "dreamweaver_projects",
            "dreamweaver_episodes",
            "dreamweaver_shots",
            "dreamweaver_assets",
            "knowledge_graph_edges",
            "book_sources",
            "book_chapters",
            "book_analyses",
            "reviews",
            "chapter_plans",
            "generation_history",
            "knowledge_base",
            "review_results",
            "workflow_sessions"
        ]
        
        for table_name in migrate_order:
            print(f"\n迁移表: {table_name}")
            
            try:
                # 获取SQLite表结构
                sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
                sqlite_columns = [row[1] for row in sqlite_cursor.fetchall()]
                
                # 获取PostgreSQL表结构
                postgres_cursor.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position;
                """, (table_name,))
                postgres_columns_info = {row[0]: row[1] for row in postgres_cursor.fetchall()}
                postgres_columns = list(postgres_columns_info.keys())
                
                # 找出共有的列
                common_columns = set(sqlite_columns) & set(postgres_columns)
                
                if not common_columns:
                    print(f"  ⚠️ 没有共有的列，跳过")
                    continue
                
                # 获取SQLite数据
                sqlite_cursor.execute(f"SELECT * FROM {table_name}")
                rows = sqlite_cursor.fetchall()
                
                if not rows:
                    print(f"  ℹ️  无数据需要迁移")
                    continue
                
                # 构建插入语句
                quoted_columns = [f'"{col}"' if col == "order" else col for col in sorted(common_columns)]
                columns_str = ", ".join(quoted_columns)
                placeholders = ", ".join(["%s"] * len(common_columns))
                
                insert_sql = f"""
                    INSERT INTO {table_name} ({columns_str})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """
                
                # 转换数据并插入
                migrated_count = 0
                for row in rows:
                    try:
                        row_dict = dict(zip(sqlite_columns, row))
                        row_data = []
                        
                        for col in sorted(common_columns):
                            value = row_dict[col]
                            col_type = postgres_columns_info.get(col, "")
                            
                            # 处理NULL值
                            if value is None:
                                row_data.append(None)
                            # 处理布尔类型转换
                            elif "boolean" in col_type.lower() or "bool" in col_type.lower():
                                if isinstance(value, int):
                                    row_data.append(bool(value))
                                else:
                                    row_data.append(value)
                            # 处理日期时间格式
                            elif col in ['created_at', 'updated_at', 'started_at', 'completed_at', 
                                        'generated_at', 'deleted_at', 'last_referenced_at']:
                                if value:
                                    # 尝试解析各种日期格式
                                    try:
                                        if isinstance(value, str):
                                            # 处理ISO格式: 2025-12-15T18:36:01.054349
                                            if 'T' in value:
                                                value = value.replace('T', ' ')
                                                # 移除微秒部分
                                                if '.' in value:
                                                    value = value.split('.')[0]
                                            # 处理标准格式: 2025-12-15 18:36:01
                                            row_data.append(value)
                                        else:
                                            row_data.append(value)
                                    except:
                                        row_data.append(value)
                                else:
                                    row_data.append(None)
                            # 处理其他类型
                            else:
                                row_data.append(value)
                        
                        postgres_cursor.execute(insert_sql, row_data)
                        migrated_count += 1
                        
                    except Exception as e:
                        # 忽略外键约束错误
                        if "foreign key" in str(e).lower():
                            continue
                        # 忽略唯一约束错误
                        if "unique" in str(e).lower():
                            continue
                        print(f"  ⚠️ 迁移行失败: {e}")
                        continue
                
                print(f"  ✅ 迁移了 {migrated_count} 条记录")
                
            except Exception as e:
                print(f"  ❌ 迁移失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # ============ 3. 验证迁移结果 ============
        print(f"\n{'='*80}")
        print("步骤3: 验证迁移结果")
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
