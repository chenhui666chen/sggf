"""
FastAPI主应用
"""
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.db.base import Base, engine
from app.api.v1 import auth, projects, chapters, knowledge_base, reviews, workflow, settings as settings_api, knowledge, memories, ai_assist, statistics, characters, ai_detect, prompt_evolution, ai_trace
import socketio

# 🔧 配置日志 - 确保所有模块的日志都能输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # 输出到控制台
    ]
)

# 设置特定模块的日志级别
logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("app.api").setLevel(logging.INFO)
logging.getLogger("app.services").setLevel(logging.INFO)
logging.getLogger("app.websocket").setLevel(logging.INFO)

# 创建数据库表
Base.metadata.create_all(bind=engine)

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
app.include_router(knowledge_base.router)
app.include_router(knowledge.router)  # 向量搜索API
app.include_router(memories.router)  # 记忆管理API
app.include_router(ai_assist.router)  # AI辅助功能API
app.include_router(reviews.router)
app.include_router(workflow.router)
app.include_router(settings_api.router)
app.include_router(statistics.router)
app.include_router(characters.router)
app.include_router(ai_detect.router)  # AI 生成检测 API
app.include_router(ai_trace.router)  # AI 痕迹降低 API
app.include_router(prompt_evolution.router)  # 提示词进化优化 API（实验性）


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

