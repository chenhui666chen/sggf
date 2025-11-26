"""
WebSocket 管理器 - 基于 Socket.IO
"""
import socketio
from typing import Dict, Set, Optional
import logging
from jose import JWTError, jwt
from app.core.config import settings
from app.db.base import get_db
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)

# 创建 Socket.IO 服务器实例
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',  # 生产环境应该限制为具体的前端地址
    logger=True,
    engineio_logger=True,
    # 🔧 心跳配置：防止 ping timeout
    ping_timeout=600,  # 600秒（10分钟）- 基于实际测试数据（最长阶段338秒）
    ping_interval=25,  # 每25秒发送一次ping（默认25秒）
    # 🔧 长轮询配置
    max_http_buffer_size=10000000,  # 10MB（支持大文件传输）
    allow_upgrades=True,  # 允许从轮询升级到WebSocket
    http_compression=True,  # 启用HTTP压缩
    compression_threshold=1024  # 压缩阈值1KB
)

# 房间管理：project_id -> set of session_ids
project_rooms: Dict[int, Set[str]] = {}


class WorkflowWebSocketManager:
    """工作流 WebSocket 管理器"""
    
    @staticmethod
    async def broadcast_to_project(project_id: int, event: str, data: dict):
        """向指定项目的所有连接广播消息"""
        room = f'project_{project_id}'
        try:
            await sio.emit(event, data, room=room)
            logger.info(f"📡 广播到房间 {room}: {event}")
        except Exception as e:
            logger.error(f"❌ 广播失败: {e}")
    
    @staticmethod
    async def send_stage_update(project_id: int, stage: str, status: str, output: str | None = None, progress: int | None = None):
        """发送阶段更新"""
        data = {
            'project_id': project_id,
            'stage': stage,
            'status': status,
            'output': output,
            'progress': progress,
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'stage_update', data)
    
    @staticmethod
    async def send_task_progress(project_id: int, task_id: str, progress: int, message: str | None = None):
        """发送任务进度"""
        data = {
            'project_id': project_id,
            'task_id': task_id,
            'progress': progress,
            'message': message,
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'task_progress', data)
    
    @staticmethod
    async def send_task_complete(project_id: int, task_id: str, result: dict):
        """发送任务完成"""
        data = {
            'project_id': project_id,
            'task_id': task_id,
            'status': 'completed',
            'result': result,
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'task_complete', data)
    
    @staticmethod
    async def send_task_error(project_id: int, task_id: str, error: str):
        """发送任务错误"""
        data = {
            'project_id': project_id,
            'task_id': task_id,
            'status': 'failed',
            'error': error,
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'task_error', data)
    
    @staticmethod
    async def send_agent_status(
        project_id: int, 
        stage: str | None, 
        agent_id: str | None, 
        agent_name: str, 
        status: str, 
        progress: int | None = None, 
        message: str | None = None
    ):
        """发送 Agent 状态"""
        data = {
            'project_id': project_id,
            'stage': stage,
            'agent_id': agent_id,
            'agent_name': agent_name,
            'status': status,
            'progress': progress,
            'message': message,
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'agent_status', data)


# Socket.IO 事件处理器
@sio.event
async def connect(sid, environ):
    """客户端连接"""
    logger.info(f"🔌 客户端连接: {sid}")
    await sio.emit('connected', {'message': 'WebSocket 连接成功'}, room=sid)


@sio.event
async def disconnect(sid):
    """客户端断开"""
    logger.info(f"🔌 客户端断开: {sid}")
    # 从所有房间中移除
    for project_id, sessions in list(project_rooms.items()):
        if sid in sessions:
            sessions.remove(sid)
            logger.info(f"📤 从项目房间移除: project_{project_id}")


def verify_websocket_token(token: str) -> Optional[dict]:
    """验证 WebSocket JWT token"""
    try:
        # 尝试解码标准JWT
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        # JWT解码失败，尝试Base64旧格式
        try:
            import base64
            decoded = base64.b64decode(token).decode()
            # 旧格式: "user_id:username"
            if ':' in decoded:
                user_id, username = decoded.split(':', 1)
                return {"sub": user_id, "username": username}
        except Exception:
            pass

        logger.error(f"❌ Token验证失败: {e}")
        return None


@sio.event
async def join_project(sid, data):
    """加入项目房间 - 带项目所有权验证"""
    try:
        project_id = data.get('project_id')
        token = data.get('token')

        # 验证必要参数
        if not project_id:
            await sio.emit('error', {'message': '缺少 project_id'}, room=sid)
            return

        if not token:
            await sio.emit('error', {'message': '缺少认证令牌'}, room=sid)
            return

        # 验证 token
        payload = verify_websocket_token(token)
        if not payload:
            await sio.emit('error', {'message': '无效的认证令牌'}, room=sid)
            return

        user_id = payload.get("sub")
        if not user_id:
            await sio.emit('error', {'message': '令牌中缺少用户信息'}, room=sid)
            return

        # 验证项目所有权
        db = next(get_db())
        try:
            project = db.query(Project).filter(
                Project.id == project_id,
                Project.user_id == int(user_id)
            ).first()

            if not project:
                logger.warning(f"⚠️ 用户 {user_id} 尝试加入未授权的项目 {project_id}")
                await sio.emit('error', {'message': '无权访问该项目'}, room=sid)
                return

            # 验证通过，加入房间
            room = f'project_{project_id}'
            await sio.enter_room(sid, room)

            # 记录房间成员
            if project_id not in project_rooms:
                project_rooms[project_id] = set()
            project_rooms[project_id].add(sid)

            logger.info(f"📥 客户端 {sid} (用户 {user_id}) 加入房间: {room}")
            await sio.emit('joined_project', {'project_id': project_id, 'room': room}, room=sid)

        finally:
            db.close()

    except Exception as e:
        logger.error(f"❌ 加入房间失败: {e}")
        await sio.emit('error', {'message': f'加入房间失败: {str(e)}'}, room=sid)


@sio.event
async def leave_project(sid, data):
    """离开项目房间"""
    try:
        project_id = data.get('project_id')
        if not project_id:
            return
        
        room = f'project_{project_id}'
        await sio.leave_room(sid, room)
        
        # 从记录中移除
        if project_id in project_rooms and sid in project_rooms[project_id]:
            project_rooms[project_id].remove(sid)
        
        logger.info(f"📤 客户端 {sid} 离开房间: {room}")
        await sio.emit('left_project', {'project_id': project_id}, room=sid)
    except Exception as e:
        logger.error(f"❌ 离开房间失败: {e}")


def get_socket_app():
    """获取 Socket.IO ASGI 应用"""
    return socketio.ASGIApp(sio)


# 导出管理器实例
ws_manager = WorkflowWebSocketManager()
