"""
数据库迁移脚本：从SQLite迁移到PostgreSQL

使用方法：
1. 确保PostgreSQL容器正在运行
2. 运行此脚本：python migrate_to_postgres.py
3. 验证数据迁移成功
"""

import os
import sys
from pathlib import Path

# 添加backend到路径
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# 加载环境变量（优先加载 backend/.env）
from dotenv import load_dotenv
load_dotenv(backend_dir / ".env", override=True)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models import (
    User, Project, Memory, SettingCollection, SettingItem,
    Character, CharacterTechnique, Review, KnowledgeGraphEdge,
    BookSource, BookChapter, BookAnalysis,
    AudiobookProject, ChapterAudio
)
from app.db.base import Base
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_sqlite_to_postgres():
    """从SQLite迁移数据到PostgreSQL"""

    # SQLite数据库路径
    sqlite_db_path = Path(__file__).parent / "novel_app.db"

    if not sqlite_db_path.exists():
        logger.warning(f"SQLite数据库不存在: {sqlite_db_path}")
        logger.info("跳过数据迁移")
        return

    # SQLite连接
    sqlite_url = f"sqlite:///{sqlite_db_path}"
    sqlite_engine = create_engine(sqlite_url)
    SQLiteSession = sessionmaker(bind=sqlite_engine)

    # PostgreSQL连接
    postgres_url = settings.DATABASE_URL
    postgres_engine = create_engine(postgres_url)
    PostgresSession = sessionmaker(bind=postgres_engine)

    try:
        logger.info("开始数据迁移...")

        # 创建所有表
        logger.info("创建PostgreSQL表结构...")
        Base.metadata.create_all(bind=postgres_engine)

        # 迁移数据
        with SQLiteSession() as sqlite_session:
            with PostgresSession() as postgres_session:
                
                # 1. 用户表（无依赖）
                logger.info("迁移用户数据...")
                users = sqlite_session.execute(text("SELECT * FROM users")).fetchall()
                for user in users:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO users (id, username, email, password_hash, full_name, created_at, avatar_url, is_active, updated_at)
                            VALUES (:id, :username, :email, :password_hash, :full_name, :created_at, :avatar_url, :is_active, :updated_at)
                        """), {
                            'id': user[0],
                            'username': user[1],
                            'email': user[2],
                            'password_hash': user[3],
                            'full_name': user[4],
                            'created_at': user[5],
                            'avatar_url': user[6],
                            'is_active': bool(user[7]),  # 转换为布尔值
                            'updated_at': user[8] if user[8] else user[5]  # 如果 updated_at 为空，使用 created_at
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移用户 {user[1]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(users)} 个用户")
                
                # 2. 项目表（依赖 users）
                logger.info("迁移项目数据...")
                projects = sqlite_session.execute(text("SELECT * FROM projects")).fetchall()
                for project in projects:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO projects (id, user_id, title, description, genre, status, word_count, created_at, updated_at, sub_genre, planned_length_type, planned_chapters_min, planned_chapters_max, user_outline_plan, audio_config)
                            VALUES (:id, :user_id, :title, :description, :genre, :status, :word_count, :created_at, :updated_at, :sub_genre, :planned_length_type, :planned_chapters_min, :planned_chapters_max, :user_outline_plan, :audio_config)
                        """), {
                            'id': project[0],
                            'user_id': project[1],
                            'title': project[2],
                            'description': project[3],
                            'genre': project[4],
                            'status': project[5],
                            'word_count': project[6],
                            'created_at': project[7],
                            'updated_at': project[8],
                            'sub_genre': project[9],
                            'planned_length_type': project[10],
                            'planned_chapters_min': project[11],
                            'planned_chapters_max': project[12],
                            'user_outline_plan': project[13],
                            'audio_config': project[14]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移项目 {project[2]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(projects)} 个项目")
                
                # 3. 记忆表（依赖 users, projects）
                logger.info("迁移记忆数据...")
                memories = sqlite_session.execute(text("SELECT * FROM memories")).fetchall()
                for memory in memories:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO memories (id, project_id, user_id, messages, current_chapter, current_scene, active_characters, writing_goal, created_at, updated_at)
                            VALUES (:id, :project_id, :user_id, :messages, :current_chapter, :current_scene, :active_characters, :writing_goal, :created_at, :updated_at)
                        """), {
                            'id': memory[0],
                            'project_id': memory[1],
                            'user_id': memory[2],
                            'messages': memory[3],
                            'current_chapter': memory[4],
                            'current_scene': memory[5],
                            'active_characters': memory[6],
                            'writing_goal': memory[7],
                            'created_at': memory[8],
                            'updated_at': memory[9]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移记忆 {memory[0]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(memories)} 条记忆")
                
                # 3.5. 章节表（依赖 projects）
                logger.info("迁移章节数据...")
                chapters = sqlite_session.execute(text("SELECT * FROM chapters")).fetchall()
                for chapter in chapters:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO chapters (id, project_id, chapter_number, title, content, status, word_count, created_at, updated_at, summary, summary_data, deleted_at)
                            VALUES (:id, :project_id, :chapter_number, :title, :content, :status, :word_count, :created_at, :updated_at, :summary, :summary_data, :deleted_at)
                        """), {
                            'id': chapter[0],
                            'project_id': chapter[1],
                            'chapter_number': chapter[2],
                            'title': chapter[3],
                            'content': chapter[4],
                            'status': chapter[5],
                            'word_count': chapter[6],
                            'created_at': chapter[7],
                            'updated_at': chapter[8],
                            'summary': chapter[9],
                            'summary_data': chapter[10],
                            'deleted_at': chapter[11]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移章节 {chapter[3]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(chapters)} 个章节")
                
                # 4. 书籍表（依赖 users）
                logger.info("迁移书籍数据...")
                book_sources = sqlite_session.execute(text("SELECT * FROM book_sources")).fetchall()
                for book in book_sources:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO book_sources (id, user_id, title, author, isbn, publisher, publish_year, genre, description, cover_url, source_type, file_path, original_url, total_words, total_chapters, total_volumes, status, parse_progress, error_message, imported_project_id, created_at, updated_at, parsed_at)
                            VALUES (:id, :user_id, :title, :author, :isbn, :publisher, :publish_year, :genre, :description, :cover_url, :source_type, :file_path, :original_url, :total_words, :total_chapters, :total_volumes, :status, :parse_progress, :error_message, :imported_project_id, :created_at, :updated_at, :parsed_at)
                        """), {
                            'id': book[0],
                            'user_id': book[1],
                            'title': book[2],
                            'author': book[3],
                            'isbn': book[4],
                            'publisher': book[5],
                            'publish_year': book[6],
                            'genre': book[7],
                            'description': book[8],
                            'cover_url': book[9],
                            'source_type': book[10],
                            'file_path': book[11],
                            'original_url': book[12],
                            'total_words': book[13],
                            'total_chapters': book[14],
                            'total_volumes': book[15],
                            'status': book[16],
                            'parse_progress': book[17],
                            'error_message': book[18],
                            'imported_project_id': book[19],
                            'created_at': book[20],
                            'updated_at': book[21],
                            'parsed_at': book[22]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移书籍 {book[2]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(book_sources)} 本书籍")
                
                # 5. 章节表（依赖 book_sources）
                logger.info("迁移章节数据...")
                book_chapters = sqlite_session.execute(text("SELECT * FROM book_chapters")).fetchall()
                for chapter in book_chapters:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO book_chapters (id, book_id, chapter_number, title, content, word_count, volume_number, volume_title, part_number, part_title, chapter_type, start_position, end_position, summary, key_events, appearing_characters, created_at, outline_data)
                            VALUES (:id, :book_id, :chapter_number, :title, :content, :word_count, :volume_number, :volume_title, :part_number, :part_title, :chapter_type, :start_position, :end_position, :summary, :key_events, :appearing_characters, :created_at, :outline_data)
                        """), {
                            'id': chapter[0],
                            'book_id': chapter[1],
                            'chapter_number': chapter[2],
                            'title': chapter[3],
                            'content': chapter[4],
                            'word_count': chapter[5],
                            'volume_number': chapter[6],
                            'volume_title': chapter[7],
                            'part_number': chapter[8],
                            'part_title': chapter[9],
                            'chapter_type': chapter[10],
                            'start_position': chapter[11],
                            'end_position': chapter[12],
                            'summary': chapter[13],
                            'key_events': chapter[14],
                            'appearing_characters': chapter[15],
                            'created_at': chapter[16],
                            'outline_data': chapter[17]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移章节 {chapter[3]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(book_chapters)} 个章节")
                
                # 6. 有声书项目表（依赖 projects）
                logger.info("迁移有声书项目数据...")
                audiobook_projects = sqlite_session.execute(text("SELECT * FROM audiobook_projects")).fetchall()
                for project in audiobook_projects:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO audiobook_projects (id, project_id, status, tts_provider, voice_mapping, enable_cache, total_chapters, completed_chapters, failed_chapters, total_duration, total_size, total_cost, created_at, updated_at, completed_at, deleted_at)
                            VALUES (:id, :project_id, :status, :tts_provider, :voice_mapping, :enable_cache, :total_chapters, :completed_chapters, :failed_chapters, :total_duration, :total_size, :total_cost, :created_at, :updated_at, :completed_at, :deleted_at)
                        """), {
                            'id': project[0],
                            'project_id': project[1],
                            'status': project[2],
                            'tts_provider': project[3],
                            'voice_mapping': project[4],
                            'enable_cache': bool(project[5]) if project[5] is not None else None,
                            'total_chapters': project[6],
                            'completed_chapters': project[7],
                            'failed_chapters': project[8],
                            'total_duration': project[9],
                            'total_size': project[10],
                            'total_cost': project[11],
                            'created_at': project[12],
                            'updated_at': project[13],
                            'completed_at': project[14],
                            'deleted_at': project[16]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移有声书项目 {project[0]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(audiobook_projects)} 个有声书项目")
                
                # 7. 章节音频表（依赖 audiobook_projects, chapters）
                logger.info("迁移章节音频数据...")
                chapter_audios = sqlite_session.execute(text("SELECT * FROM chapter_audios")).fetchall()
                for audio in chapter_audios:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO chapter_audios (id, audiobook_project_id, chapter_id, audio_path, duration, file_size, segment_count, dialogue_count, narration_count, character_count, generation_time, tts_cost, cache_hit_rate, created_at, updated_at, task_id, script_json, script_review_json, script_status, final_audio_review_json, deleted_at)
                            VALUES (:id, :audiobook_project_id, :chapter_id, :audio_path, :duration, :file_size, :segment_count, :dialogue_count, :narration_count, :character_count, :generation_time, :tts_cost, :cache_hit_rate, :created_at, :updated_at, :task_id, :script_json, :script_review_json, :script_status, :final_audio_review_json, :deleted_at)
                        """), {
                            'id': audio[0],
                            'audiobook_project_id': audio[1],
                            'chapter_id': audio[2],
                            'audio_path': audio[3],
                            'duration': audio[4],
                            'file_size': audio[5],
                            'segment_count': audio[6],
                            'dialogue_count': audio[7],
                            'narration_count': audio[8],
                            'character_count': audio[9],
                            'generation_time': audio[10],
                            'tts_cost': audio[11],
                            'cache_hit_rate': audio[12],
                            'created_at': audio[13],
                            'updated_at': audio[14],
                            'task_id': audio[15],
                            'script_json': audio[16],
                            'script_review_json': audio[17],
                            'script_status': audio[18],
                            'final_audio_review_json': audio[19],
                            'deleted_at': audio[20]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移章节音频 {audio[0]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(chapter_audios)} 个章节音频")
                
                # 8. 角色表（依赖 projects, chapters）
                logger.info("迁移角色数据...")
                characters = sqlite_session.execute(text("SELECT * FROM characters")).fetchall()
                for char in characters:
                    try:
                        postgres_session.execute(text("""
                            INSERT INTO characters (id, project_id, name, role, gender, age, faction, importance_level, appearance_status, life_status, current_realm_item_id, faction_item_id, profession_item_id, race_item_id, techniques_json, artifacts_json, related_locations_json, first_mention_chapter_id, last_appearance_chapter_id, appearance_chapters, relationship_network, first_appearance_chapter, summary, profile, tags, relations, created_at, updated_at)
                            VALUES (:id, :project_id, :name, :role, :gender, :age, :faction, :importance_level, :appearance_status, :life_status, :current_realm_item_id, :faction_item_id, :profession_item_id, :race_item_id, :techniques_json, :artifacts_json, :related_locations_json, :first_mention_chapter_id, :last_appearance_chapter_id, :appearance_chapters, :relationship_network, :first_appearance_chapter, :summary, :profile, :tags, :relations, :created_at, :updated_at)
                        """), {
                            'id': char[0],
                            'project_id': char[1],
                            'name': char[2],
                            'role': char[3],
                            'gender': char[4],
                            'age': char[5],
                            'faction': char[6],
                            'importance_level': char[7],
                            'appearance_status': char[8],
                            'life_status': char[9],
                            'current_realm_item_id': char[10],
                            'faction_item_id': char[18],
                            'profession_item_id': char[19],
                            'race_item_id': char[20],
                            'techniques_json': char[28],
                            'artifacts_json': char[29],
                            'related_locations_json': char[30],
                            'first_mention_chapter_id': char[24],
                            'last_appearance_chapter_id': char[25],
                            'appearance_chapters': char[26],
                            'relationship_network': char[27],
                            'first_appearance_chapter': char[11],
                            'summary': char[12],
                            'profile': char[13],
                            'tags': char[14],
                            'relations': char[15],
                            'created_at': char[16],
                            'updated_at': char[17]
                        })
                        postgres_session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ 迁移角色 {char[2]} 失败: {e}")
                        postgres_session.rollback()
                logger.info(f"✅ 迁移了 {len(characters)} 个角色")

        logger.info("✅ 数据迁移完成！")

        # 备份SQLite数据库
        backup_path = sqlite_db_path.with_suffix('.db.backup')
        import shutil
        shutil.copy2(sqlite_db_path, backup_path)
        logger.info(f"✅ SQLite数据库已备份到: {backup_path}")

        logger.info("\n迁移完成！请验证PostgreSQL中的数据是否正确。")
        logger.info("验证无误后，可以删除SQLite数据库文件。")

    except Exception as e:
        logger.error(f"❌ 数据迁移失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("SQLite 到 PostgreSQL 数据迁移工具")
    logger.info("=" * 60)

    # 检查环境变量
    if "postgresql" not in settings.DATABASE_URL:
        logger.error("❌ DATABASE_URL未配置为PostgreSQL")
        logger.error("请先在.env文件中配置PostgreSQL连接")
        sys.exit(1)

    # 执行迁移
    migrate_sqlite_to_postgres()
