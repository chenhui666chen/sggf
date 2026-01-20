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
                
                # 迁移用户数据
                logger.info("迁移用户数据...")
                users = sqlite_session.query(User).all()
                for user in users:
                    # 创建新对象（避免session冲突）
                    new_user = User(
                        username=user.username,
                        email=user.email,
                        hashed_password=user.hashed_password,
                        is_active=user.is_active,
                        created_at=user.created_at,
                        updated_at=user.updated_at
                    )
                    postgres_session.add(new_user)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(users)} 个用户")
                
                # 迁移项目数据
                logger.info("迁移项目数据...")
                projects = sqlite_session.query(Project).all()
                for project in projects:
                    new_project = Project(
                        title=project.title,
                        description=project.description,
                        user_id=project.user_id,
                        created_at=project.created_at,
                        updated_at=project.updated_at
                    )
                    postgres_session.add(new_project)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(projects)} 个项目")
                
                # 迁移角色数据
                logger.info("迁移角色数据...")
                characters = sqlite_session.query(Character).all()
                for char in characters:
                    new_char = Character(
                        name=char.name,
                        description=char.description,
                        personality=char.personality,
                        background=char.background,
                        project_id=char.project_id,
                        created_at=char.created_at,
                        updated_at=char.updated_at
                    )
                    postgres_session.add(new_char)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(characters)} 个角色")
                
                # 迁移记忆数据
                logger.info("迁移记忆数据...")
                memories = sqlite_session.query(Memory).all()
                for memory in memories:
                    new_memory = Memory(
                        content=memory.content,
                        character_id=memory.character_id,
                        created_at=memory.created_at
                    )
                    postgres_session.add(new_memory)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(memories)} 条记忆")
                
                # 迁移书籍数据
                logger.info("迁移书籍数据...")
                book_sources = sqlite_session.query(BookSource).all()
                for book in book_sources:
                    new_book = BookSource(
                        title=book.title,
                        author=book.author,
                        file_path=book.file_path,
                        user_id=book.user_id,
                        created_at=book.created_at,
                        updated_at=book.updated_at
                    )
                    postgres_session.add(new_book)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(book_sources)} 本书籍")
                
                # 迁移章节数据
                logger.info("迁移章节数据...")
                chapters = sqlite_session.query(BookChapter).all()
                for chapter in chapters:
                    new_chapter = BookChapter(
                        book_id=chapter.book_id,
                        chapter_number=chapter.chapter_number,
                        title=chapter.title,
                        content=chapter.content,
                        created_at=chapter.created_at,
                        updated_at=chapter.updated_at
                    )
                    postgres_session.add(new_chapter)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(chapters)} 个章节")
                
                # 迁移有声书项目数据
                logger.info("迁移有声书项目数据...")
                audiobook_projects = sqlite_session.query(AudiobookProject).all()
                for project in audiobook_projects:
                    new_project = AudiobookProject(
                        title=project.title,
                        description=project.description,
                        user_id=project.user_id,
                        created_at=project.created_at,
                        updated_at=project.updated_at
                    )
                    postgres_session.add(new_project)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(audiobook_projects)} 个有声书项目")
                
                # 迁移章节音频数据
                logger.info("迁移章节音频数据...")
                chapter_audios = sqlite_session.query(ChapterAudio).all()
                for audio in chapter_audios:
                    new_audio = ChapterAudio(
                        audiobook_project_id=audio.audiobook_project_id,
                        chapter_number=audio.chapter_number,
                        audio_file_path=audio.audio_file_path,
                        duration=audio.duration,
                        created_at=audio.created_at,
                        updated_at=audio.updated_at
                    )
                    postgres_session.add(new_audio)
                postgres_session.commit()
                logger.info(f"✅ 迁移了 {len(chapter_audios)} 个章节音频")
        
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
