"""
在正确的数据库中创建 audiobook 相关表
"""
import sqlite3
from pathlib import Path
from datetime import datetime

# 数据库路径 - 项目根目录下的 novel_app.db（后端实际使用的数据库）
db_path = Path(__file__).parent.parent / "novel_app.db"

print(f"数据库路径：{db_path}")
print(f"数据库文件存在：{db_path.exists()}")

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # 创建 audiobook_projects 表
    print("\n📋 创建 audiobook_projects 表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audiobook_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            tts_provider VARCHAR(20) DEFAULT 'aliyun',
            voice_mapping TEXT,
            enable_cache BOOLEAN DEFAULT 1,
            total_chapters INTEGER DEFAULT 0,
            completed_chapters INTEGER DEFAULT 0,
            failed_chapters INTEGER DEFAULT 0,
            total_duration REAL DEFAULT 0.0,
            total_size INTEGER DEFAULT 0,
            total_cost REAL DEFAULT 0.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            deleted_at DATETIME,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)
    
    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS ix_audiobook_projects_deleted_at 
        ON audiobook_projects(deleted_at)
    """)
    print("✓ audiobook_projects 表创建成功")
    
    # 创建 chapter_audios 表
    print("\n📋 创建 chapter_audios 表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chapter_audios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audiobook_project_id INTEGER NOT NULL,
            chapter_id INTEGER NOT NULL,
            task_id VARCHAR(100),
            audio_path VARCHAR(500),
            duration REAL DEFAULT 0.0,
            file_size INTEGER DEFAULT 0,
            segment_count INTEGER DEFAULT 0,
            dialogue_count INTEGER DEFAULT 0,
            narration_count INTEGER DEFAULT 0,
            character_count INTEGER DEFAULT 0,
            generation_time REAL DEFAULT 0.0,
            tts_cost REAL DEFAULT 0.0,
            cache_hit_rate REAL DEFAULT 0.0,
            script_json TEXT,
            script_review_json TEXT,
            script_status VARCHAR(20) DEFAULT 'pending',
            final_audio_review_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            deleted_at DATETIME,
            FOREIGN KEY (audiobook_project_id) REFERENCES audiobook_projects(id),
            FOREIGN KEY (chapter_id) REFERENCES chapters(id)
        )
    """)
    
    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS ix_chapter_audios_deleted_at 
        ON chapter_audios(deleted_at)
    """)
    print("✓ chapter_audios 表创建成功")
    
    # 创建 audiobook_delete_audit 表
    print("\n📋 创建 audiobook_delete_audit 表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audiobook_delete_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audiobook_project_id INTEGER,
            user_id INTEGER,
            delete_reason TEXT,
            deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✓ audiobook_delete_audit 表创建成功")
    
    # 创建 audiobook_tasks 表
    print("\n📋 创建 audiobook_tasks 表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audiobook_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audiobook_project_id INTEGER NOT NULL,
            chapter_id INTEGER NOT NULL,
            task_id VARCHAR(100),
            status VARCHAR(20) DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            error_message TEXT,
            FOREIGN KEY (audiobook_project_id) REFERENCES audiobook_projects(id),
            FOREIGN KEY (chapter_id) REFERENCES chapters(id)
        )
    """)
    print("✓ audiobook_tasks 表创建成功")
    
    # 提交更改
    conn.commit()
    print("\n✅ 所有表创建完成！")
    
    # 验证表结构
    print("\n📋 验证表结构：")
    
    cursor.execute("PRAGMA table_info(audiobook_projects)")
    print("\naudiobook_projects 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")
    
    cursor.execute("PRAGMA table_info(chapter_audios)")
    print("\nchapter_audios 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")
    
    cursor.execute("PRAGMA table_info(audiobook_delete_audit)")
    print("\naudiobook_delete_audit 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")
    
    cursor.execute("PRAGMA table_info(audiobook_tasks)")
    print("\naudiobook_tasks 表列：")
    for col in cursor.fetchall():
        print(f"  - {col[1]} ({col[2]})")

except Exception as e:
    print(f"❌ 错误：{e}")
    import traceback
    traceback.print_exc()
    conn.rollback()
finally:
    conn.close()
