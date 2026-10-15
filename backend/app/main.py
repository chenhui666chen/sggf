"""
FastAPI 主应用
"""
import logging
import sys
import os
import asyncio
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextlib import asynccontextmanager

# 允许后端直接 import 项目根目录下的轻量模块（如：pipeline/agents/adapters）
from app.core.env_loader import get_project_root, load_project_env

PROJECT_ROOT = get_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# ⚠️ 重要：首先加载环境变量（必须在所有导入之前）
# 统一兼容本地源码与 Docker 容器运行：优先 backend/.env，其次根目录 .env（作为兜底）。
load_project_env(override=False)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.db.base import Base, engine
from app.db.schema_compat import ensure_runtime_schema_compatibility
from app.api.v1 import auth, projects, chapters, reviews, workflow, settings as settings_api, knowledge, memories, ai_assist, statistics, characters, ai_detect, prompt_evolution, ai_trace, book_parser, audiobook, monitoring, script_review, dreamweaver, model_catalog, asset_studio, user_assets, user_center, smart_dispatch, feedback, agent_prompts, user_rights, video_api
from app.api.v1.admin import router as admin_router
import socketio


# 🔧 自定义 Handler，强制每次写入后刷新缓冲区
class FlushHandler(logging.StreamHandler):
    """每次写入后强制刷新的 Handler"""
    def emit(self, record):
        try:
            message = self.format(record)
            stream = self.stream
            payload = message + self.terminator

            try:
                stream.write(payload)
            except UnicodeEncodeError:
                stream_encoding = getattr(stream, "encoding", None) or "utf-8"
                safe_payload = payload.encode(stream_encoding, errors="replace").decode(
                    stream_encoding,
                    errors="replace",
                )
                stream.write(safe_payload)

            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


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

# 🔧 uvicorn 给 uvicorn.* 挂了自带 handler 且 propagate=False，而生成链路大量关键日志
# 直接借用 logging.getLogger("uvicorn.error") 打印，导致这些日志只上控制台、永不落盘。
# 本模块在 uvicorn configure_logging 之后导入，此处摘掉自带 handler 并打开传播统一落盘。
from app.core.logging_setup import attach_uvicorn_logs_to_root  # noqa: E402

attach_uvicorn_logs_to_root()

logging.info(f"📁 日志文件位置: {log_file}")

# 🔧 导入所有模型（确保在 Alembic 迁移之前）
from app.models import (
    User, Project, Memory, SettingCollection, SettingItem,
    Character, CharacterTechnique, Review, KnowledgeGraphEdge,
    BookSource, BookChapter, BookAnalysis,
    AudiobookProject, ChapterAudio,
    ModelCatalogEntry, ModelCatalogSource,  # 模型档案中心
    VideoApiApplication,
    UserAssetRecord,  # 用户资产记录
)

# ⚠️ 生产环境请使用 Alembic 迁移，不要使用 create_all
# 开发环境如果需要快速重置数据库，可以取消下面的注释
# Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """🆕 应用生命周期管理"""
    # 生产/staging 安全启动检查：拒绝默认密钥与 DEBUG 模式
    if settings.APP_ENV in ("production", "staging"):
        if settings.JWT_SECRET == "your-secret-key-change-in-production":
            raise RuntimeError(
                f"{settings.APP_ENV} 环境必须配置唯一 JWT_SECRET（当前为默认占位值）"
            )
        if settings.DEBUG:
            raise RuntimeError(f"{settings.APP_ENV} 环境 DEBUG 必须为 False")
        if not str(settings.VIDEO_GATEWAY_INTERNAL_URL or "").strip() or not str(
            settings.VIDEO_GATEWAY_INTERNAL_TOKEN or "").strip():
            raise RuntimeError(
                f"{settings.APP_ENV} 环境必须配置 VIDEO_GATEWAY_INTERNAL_URL 与 VIDEO_GATEWAY_INTERNAL_TOKEN"
            )
        # openid 加密存储（P2-4.1）：缺一把密钥都会让 OAuth 链路在运行时 fail-closed 503，
        # 启动即拦截，避免上线后才发现第三方登录不可用
        if not str(settings.OPENID_LOOKUP_KEY or "").strip() or not str(
            settings.OPENID_ENCRYPTION_KEY or ""
        ).strip():
            raise RuntimeError(
                f"{settings.APP_ENV} 环境必须配置 OPENID_LOOKUP_KEY 与 OPENID_ENCRYPTION_KEY"
            )
        # 密码历史 pepper（P2-4.6）：生产/staging 禁止为空或默认占位值
        if not str(settings.PASSWORD_HISTORY_PEPPER or "").strip() or (
            settings.PASSWORD_HISTORY_PEPPER == "your-password-history-pepper-change-in-production"
        ):
            raise RuntimeError(
                f"{settings.APP_ENV} 环境必须配置唯一的 PASSWORD_HISTORY_PEPPER"
            )
        # 生产 CORS 不允许 localhost 源（allow_credentials=True 时必须精确白名单）
        cors_origins = settings.CORS_ORIGINS or []
        if isinstance(cors_origins, str):
            cors_origins = [cors_origins]
        if any("localhost" in str(o) or "127.0.0.1" in str(o) for o in cors_origins):
            raise RuntimeError(
                f"{settings.APP_ENV} 环境 CORS_ORIGINS 不得包含 localhost / 127.0.0.1"
            )

    # 密码历史 pepper：任何环境都不得为空（空 key 的 HMAC 退化为已知 key 哈希，评审 #6）
    if not str(settings.PASSWORD_HISTORY_PEPPER or "").strip():
        raise RuntimeError("必须配置 PASSWORD_HISTORY_PEPPER（任何环境不得为空）")

    # 审计日志 pepper（P2-4.4）：任何环境不得为空，否则 IP/UA 脱敏哈希退化为已知 key
    if not str(settings.AUDIT_LOG_PEPPER or "").strip():
        raise RuntimeError("必须配置 AUDIT_LOG_PEPPER（任何环境不得为空）")

    # 预生成登录时序防护用的 dummy bcrypt 哈希，避免运行时首次生成阻塞请求
    try:
        from app.api.v1.auth import initialize_security_globals

        initialize_security_globals()
    except Exception:  # noqa: BLE001 - 预生成失败不阻断启动
        logging.warning("预生成登录时序防护 dummy 哈希失败（将惰性生成）")

    ensure_runtime_schema_compatibility()

    # 启动时：初始化主事件循环引用
    from app.services.chapter_post_save import set_main_event_loop
    loop = asyncio.get_running_loop()
    set_main_event_loop(loop)
    logging.info("✅ 主事件循环已初始化")

    # 启动自愈：清理上一进程残留的 running/pending 任务（进程内协程已随重启消亡）
    try:
        from app.db.base import SessionLocal
        from app.services.stale_task_cleaner import cleanup_stale_generation_tasks

        with SessionLocal() as session:
            cleaned = cleanup_stale_generation_tasks(session)
        if cleaned:
            logging.warning("🧹 启动自愈：已将 %d 条残留任务标记为 failed", cleaned)
    except Exception as exc:  # noqa: BLE001 - 清理失败不阻断启动
        logging.error("启动自愈清理残留任务失败（不影响启动）: %s", exc)

    yield
    
    # 关闭时：清理资源
    logging.info("👋 应用正在关闭...")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """P2-4.5：cookie 认证会话的 unsafe 方法需通过 CSRF 双重提交校验。

    校验逻辑在 security.csrf_check（与测试复用同一实现），此处仅做 HTTP 化。
    """
    from app.core.security import csrf_check

    error = csrf_check(request)
    if error:
        return JSONResponse(status_code=403, content={"detail": error})
    return await call_next(request)


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
app.include_router(agent_prompts.router)  # Agent 提示词管理 API
app.include_router(book_parser.router)  # 拆书工具 API
app.include_router(audiobook.router)  # 耳畔星河 - 有声书生成 API
app.include_router(monitoring.router)  # 监控与指标 API
app.include_router(script_review.router)  # 剧本审核与调整 API
app.include_router(dreamweaver.router)  # 织梦映心 - 短剧生成 API
app.include_router(model_catalog.router)  # 模型档案中心 API
app.include_router(asset_studio.router)  # 首页资产工作台 API
app.include_router(user_assets.router)  # 用户资产记录 API
app.include_router(user_center.router)  # 用户中心汇总与权益 API
app.include_router(video_api.router)  # 视频 API 应用管理
app.include_router(smart_dispatch.router)  # 智能调度 API
app.include_router(feedback.router)  # 生成反馈闭环 API
app.include_router(user_rights.router)  # 用户数据权利 API（P2-4.3）
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
    """全局异常处理。

    生产/staging 隐藏异常细节（防内部路径与结构泄露），开发环境返回完整 traceback。
    """
    import traceback
    import logging

    # 记录详细错误日志（服务端日志始终完整）
    logger = logging.getLogger("uvicorn.error")
    logger.error(f"❌ 全局异常捕获: {str(exc)}")
    logger.error(f"请求路径: {request.url.path}")
    logger.error(f"请求方法: {request.method}")
    logger.error(f"详细追踪:\n{traceback.format_exc()}")

    if settings.DEBUG or settings.APP_ENV == "development":
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            },
        )

    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
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

