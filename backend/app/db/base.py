"""
数据库基类配置
"""
import os

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
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
is_postgresql = "postgresql" in settings.DATABASE_URL
sqlite_timeout_s = max(1.0, _env_float("SQLITE_TIMEOUT_S", 30.0)) if is_sqlite else 0.0

# Enforce PostgreSQL-only usage
if not is_postgresql:
    raise RuntimeError("DATABASE_URL must use PostgreSQL (postgresql://...)")

# 根据数据库类型配置连接池
if is_sqlite:
    # SQLite不使用连接池
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.SQLALCHEMY_ECHO,
        poolclass=NullPool,
        connect_args=(
            {"check_same_thread": False, "timeout": float(sqlite_timeout_s)}
            if is_sqlite
            else {}
        ),
    )
elif is_postgresql:
    # PostgreSQL使用QueuePool连接池
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.SQLALCHEMY_ECHO,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=UTC"
        }
    )
else:
    # 其他数据库使用默认配置
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.SQLALCHEMY_ECHO,
        poolclass=NullPool if settings.DEBUG else None,
    )

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        # 减少并发读写导致的 "database is locked" 失败：
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
