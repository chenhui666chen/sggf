"""
数据库基类配置
"""
import os

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import settings


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


# 创建数据库引擎
is_sqlite = "sqlite" in settings.DATABASE_URL
sqlite_timeout_s = max(1.0, _env_float("SQLITE_TIMEOUT_S", 30.0)) if is_sqlite else 0.0
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.SQLALCHEMY_ECHO,
    poolclass=NullPool if (settings.DEBUG or is_sqlite) else None,
    connect_args=(
        {"check_same_thread": False, "timeout": float(sqlite_timeout_s)}
        if is_sqlite
        else {}
    ),
)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        # 减少并发读写导致的 “database is locked” 失败：
        # - WAL：读不阻塞写（适合 FastAPI + Celery 并发场景）
        # - busy_timeout：锁冲突时等待一段时间再报错
        cursor = dbapi_connection.cursor()
        try:
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception:  # noqa: BLE001
                pass
            try:
                cursor.execute("PRAGMA synchronous=NORMAL;")
            except Exception:  # noqa: BLE001
                pass
            try:
                cursor.execute(f"PRAGMA busy_timeout={int(sqlite_timeout_s * 1000)};")
            except Exception:  # noqa: BLE001
                pass
            try:
                cursor.execute("PRAGMA foreign_keys=ON;")
            except Exception:  # noqa: BLE001
                pass
        finally:
            cursor.close()

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基类（使用 SQLAlchemy 2.0 风格）
class Base(DeclarativeBase):
    pass


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
