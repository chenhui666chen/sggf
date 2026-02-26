import sqlite3
import psycopg2
from psycopg2.extras import execute_batch
import json
from datetime import datetime

# SQLite 备份数据库路径
sqlite_db_path = '/root/novel_writing_agent/database_backups/novel_app.db.bak-20260102-181959'

# PostgreSQL 连接配置
pg_config = {
    'host': 'localhost',
    'port': 5432,
    'database': 'novel_db',
    'user': 'novel_user',
    'password': 'NovelPostgres0t649OyRUaI'
}

def migrate_data():
    # 连接 SQLite
    sqlite_conn = sqlite3.connect(sqlite_db_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    # 连接 PostgreSQL
    pg_conn = psycopg2.connect(**pg_config)
    pg_cursor = pg_conn.cursor()
    
    try:
        # 1. 迁移用户数据
        print("迁移用户数据...")
        sqlite_cursor.execute("SELECT * FROM users")
        users = sqlite_cursor.fetchall()
        
        for user in users:
            created_at = user['created_at'] if 'created_at' in user.keys() and user['created_at'] else datetime.now()
            updated_at = user['updated_at'] if 'updated_at' in user.keys() and user['updated_at'] else created_at
            
            pg_cursor.execute("""
                INSERT INTO users (id, username, email, password_hash, full_name, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    password_hash = EXCLUDED.password_hash,
                    full_name = EXCLUDED.full_name,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
            """, (
                user['id'],
                user['username'],
                user['email'],
                user['password_hash'],
                user['full_name'] if 'full_name' in user.keys() else None,
                bool(user['is_active']) if 'is_active' in user.keys() else True,
                created_at,
                updated_at
            ))
        
        pg_conn.commit()
        print(f"✅ 迁移了 {len(users)} 个用户")
        
        # 2. 迁移项目数据
        print("\n迁移项目数据...")
        sqlite_cursor.execute("SELECT * FROM projects")
        projects = sqlite_cursor.fetchall()
        
        for project in projects:
            created_at = project['created_at'] if 'created_at' in project.keys() and project['created_at'] else datetime.now()
            updated_at = project['updated_at'] if 'updated_at' in project.keys() and project['updated_at'] else created_at
            
            pg_cursor.execute("""
                INSERT INTO projects (id, user_id, title, description, genre, status, word_count, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    genre = EXCLUDED.genre,
                    status = EXCLUDED.status,
                    word_count = EXCLUDED.word_count,
                    updated_at = EXCLUDED.updated_at
            """, (
                project['id'],
                project['user_id'],
                project['title'],
                project['description'] if 'description' in project.keys() else None,
                project['genre'] if 'genre' in project.keys() else None,
                'draft',  # 默认状态
                0,  # 默认字数
                created_at,
                updated_at
            ))
        
        pg_conn.commit()
        print(f"✅ 迁移了 {len(projects)} 个项目")
        
        # 3. 迁移章节数据
        print("\n迁移章节数据...")
        sqlite_cursor.execute("SELECT * FROM chapters")
        chapters = sqlite_cursor.fetchall()
        
        for chapter in chapters:
            created_at = chapter['created_at'] if 'created_at' in chapter.keys() and chapter['created_at'] else datetime.now()
            updated_at = chapter['updated_at'] if 'updated_at' in chapter.keys() and chapter['updated_at'] else created_at
            
            pg_cursor.execute("""
                INSERT INTO chapters (id, project_id, chapter_number, title, content, status, word_count, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    chapter_number = EXCLUDED.chapter_number,
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    status = EXCLUDED.status,
                    word_count = EXCLUDED.word_count,
                    updated_at = EXCLUDED.updated_at
            """, (
                chapter['id'],
                chapter['project_id'],
                chapter['chapter_number'] if 'chapter_number' in chapter.keys() else 0,
                chapter['title'],
                chapter['content'] if 'content' in chapter.keys() else None,
                'draft',  # 默认状态
                0,  # 默认字数
                created_at,
                updated_at
            ))
        
        pg_conn.commit()
        print(f"✅ 迁移了 {len(chapters)} 个章节")
        
        # 4. 迁移角色数据
        print("\n迁移角色数据...")
        sqlite_cursor.execute("SELECT * FROM characters")
        characters = sqlite_cursor.fetchall()
        
        for char in characters:
            created_at = char['created_at'] if 'created_at' in char.keys() and char['created_at'] else datetime.now()
            updated_at = char['updated_at'] if 'updated_at' in char.keys() and char['updated_at'] else created_at
            
            pg_cursor.execute("""
                INSERT INTO characters (id, project_id, name, summary, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    name = EXCLUDED.name,
                    summary = EXCLUDED.summary,
                    updated_at = EXCLUDED.updated_at
            """, (
                char['id'],
                char['project_id'],
                char['name'],
                char['description'] if 'description' in char.keys() else None,
                created_at,
                updated_at
            ))
        
        pg_conn.commit()
        print(f"✅ 迁移了 {len(characters)} 个角色")
        
        # 5. 迁移记忆数据
        print("\n迁移记忆数据...")
        sqlite_cursor.execute("SELECT * FROM memories")
        memories = sqlite_cursor.fetchall()
        
        for memory in memories:
            created_at = memory['created_at'] if 'created_at' in memory.keys() and memory['created_at'] else datetime.now()
            updated_at = memory['updated_at'] if 'updated_at' in memory.keys() and memory['updated_at'] else created_at
            
            pg_cursor.execute("""
                INSERT INTO memories (id, project_id, user_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    user_id = EXCLUDED.user_id,
                    updated_at = EXCLUDED.updated_at
            """, (
                memory['id'],
                memory['project_id'],
                memory['user_id'] if 'user_id' in memory.keys() else 1,
                created_at,
                updated_at
            ))
        
        pg_conn.commit()
        print(f"✅ 迁移了 {len(memories)} 个记忆")
        
        print("\n✅ 数据迁移完成！")
        
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        pg_conn.rollback()
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == '__main__':
    migrate_data()
