"""
FastAPI主应用
"""
import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 允许后端直接 import 项目根目录下的轻量模块（如：pipeline/agents/adapters）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# ⚠️ 重要：首先加载环境变量（必须在所有导入之前）
from dotenv import load_dotenv
# 兼容从项目根目录或 backend/ 目录启动：优先加载 backend/.env，其次加载根目录 .env（作为兜底）。
load_dotenv(PROJECT_ROOT / "backend" / ".env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.db.base import Base, engine
from app.api.v1 import auth, projects, chapters, reviews, workflow, settings as settings_api, knowledge, memories, ai_assist, statistics, characters, ai_detect, prompt_evolution, ai_trace, book_parser, audiobook, monitoring, script_review, dreamweaver
from app.api.v1.admin import router as admin_router
import socketio


# 🔧 自定义 Handler，强制每次写入后刷新缓冲区
class FlushHandler(logging.StreamHandler):
    """每次写入后强制刷新的 Handler"""
    def emit(self, record):
        super().emit(record)
        self.flush()


# 🔧 配置日志 - 确保所有模块的日志都能输出
# 清除已有的 handlers，避免重复
root_logger = logging.getLogger()
root_logger.handlers.clear()

# 日志格式
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 1. 控制台 Handler（强制刷新）
flush_handler = FlushHandler(sys.stdout)
flush_handler.setLevel(logging.INFO)
flush_handler.setFormatter(log_formatter)

# 2. 文件 Handler（自动轮转）
# 创建日志目录
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "app.log"

# RotatingFileHandler: 单个文件最大 5MB，保留 3 个备份
# 总共最多占用 5MB * 4 = 20MB 空间
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=3,              # 保留 app.log.1, app.log.2, app.log.3
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[flush_handler, file_handler],
    force=True  # 强制重新配置
)

# 设置特定模块的日志级别
logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("app.api").setLevel(logging.INFO)
logging.getLogger("app.services").setLevel(logging.INFO)
logging.getLogger("app.websocket").setLevel(logging.INFO)
logging.getLogger("app.services.prompt_evolution").setLevel(logging.INFO)

logging.info(f"📁 日志文件位置: {log_file}")

# 🔧 导入所有模型（确保在 Alembic 迁移之前）
from app.models import (
    User, Project, Memory, SettingCollection, SettingItem,
    Character, CharacterTechnique, Review, KnowledgeGraphEdge,
    BookSource, BookChapter, BookAnalysis,
    AudiobookProject, ChapterAudio  # 有声书模型
)

# ⚠️ 生产环境请使用 Alembic 迁移，不要使用 create_all
# 开发环境如果需要快速重置数据库，可以取消下面的注释
# Base.metadata.create_all(bind=engine)

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)


# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": settings.APP_VERSION}


# 包含路由
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(chapters.router)
app.include_router(knowledge.router)  # 向量搜索API
app.include_router(memories.router)  # 记忆管理API
app.include_router(ai_assist.router)  # AI辅助功能API
app.include_router(reviews.router)
app.include_router(workflow.router)
app.include_router(settings_api.router)
app.include_router(statistics.router)
app.include_router(characters.router)
app.include_router(ai_detect.router)  # AI 生成检测 API
app.include_router(ai_trace.router)  # 织文无迹 API
app.include_router(prompt_evolution.router)  # 提示词进化优化 API（实验性）
app.include_router(book_parser.router)  # 拆书工具 API
app.include_router(audiobook.router)  # 耳畔星河 - 有声书生成 API
app.include_router(monitoring.router)  # 监控与指标 API
app.include_router(script_review.router)  # 剧本审核与调整 API
app.include_router(dreamweaver.router)  # 织梦映心 - 短剧生成 API
app.include_router(admin_router)  # 管理控制台 API


# 🔌 挂载 Socket.IO
# 导入 WebSocket 事件处理器
from app.websocket.manager import sio as websocket_sio
# 将 Socket.IO 包装为 ASGI 应用并挂载到 FastAPI
socket_asgi_app = socketio.ASGIApp(websocket_sio, other_asgi_app=app)

# 导出组合后的应用（用于 uvicorn 启动）
application = socket_asgi_app


# 错误处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    import traceback
    import logging

    # 记录详细错误日志
    logger = logging.getLogger("uvicorn.error")
    logger.error(f"❌ 全局异常捕获: {str(exc)}")
    logger.error(f"请求路径: {request.url.path}")
    logger.error(f"请求方法: {request.method}")
    logger.error(f"详细追踪:\n{traceback.format_exc()}")

    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc() if settings.DEBUG else None
        }
    )


if __name__ == "__main__":
    import uvicorn
    # 直接运行组合后的应用
    uvicorn.run(
        "app.main:application",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )

