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

_socket_manager = None
if isinstance(getattr(settings, "REDIS_URL", None), str) and str(settings.REDIS_URL or "").strip():
    try:
        _socket_manager = socketio.AsyncRedisManager(str(settings.REDIS_URL).strip())
        logger.info("Socket.IO 使用 Redis 消息队列: %s", str(settings.REDIS_URL).strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Socket.IO Redis 管理器初始化失败，将回退为本进程广播: %s", exc)
        _socket_manager = None

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
    compression_threshold=1024,  # 压缩阈值1KB
    client_manager=_socket_manager,
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

    @staticmethod
    async def send_stream_chunk(
        project_id: int,
        stage: str,
        chunk: str,
        chunk_index: int = 0,
        is_complete: bool = False,
        extra: dict | None = None
    ):
        """
        🆕 发送流式输出块（用于实时显示 AI 生成的内容）

        Args:
            project_id: 项目 ID
            stage: 当前阶段（content/review/iteration）
            chunk: 文本块内容
            chunk_index: 块索引（用于前端排序）
            is_complete: 是否为最后一块
            extra: 额外数据（用于前端区分内容类型等）
        """
        data = {
            'project_id': project_id,
            'stage': stage,
            'chunk': chunk,
            'chunk_index': chunk_index,
            'is_complete': is_complete,
            'extra': extra or {},
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'stream_chunk', data)

    @staticmethod
    async def send_stream_start(project_id: int, stage: str, message: str | None = None):
        """
        🆕 发送流式输出开始通知
        """
        data = {
            'project_id': project_id,
            'stage': stage,
            'message': message or f'{stage} 阶段开始生成内容...',
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'stream_start', data)

    @staticmethod
    async def send_stream_end(project_id: int, stage: str, total_chars: int = 0, message: str | None = None):
        """
        🆕 发送流式输出结束通知
        """
        data = {
            'project_id': project_id,
            'stage': stage,
            'total_chars': total_chars,
            'message': message or f'{stage} 阶段内容生成完成',
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'stream_end', data)

    @staticmethod
    async def send_model_used(project_id: int, stage: str, model: str, extra: dict | None = None):
        """🆕 发送模型使用信息到前端控制台"""
        data = {
            'project_id': project_id,
            'stage': stage,
            'model': model,
            'extra': extra or {},
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'model_used', data)
    
    @staticmethod
    async def send_notification(
        project_id: int,
        message: str,
        type: str = "info",
        data: dict | None = None
    ):
        """
        🆕 发送通知消息
        
        Args:
            project_id: 项目ID
            message: 通知消息
            type: 消息类型（info/success/warning/error/system_collections_created）
            data: 附加数据
        """
        notification_data = {
            'project_id': project_id,
            'message': message,
            'type': type,
            'data': data or {},
        }
        await WorkflowWebSocketManager.broadcast_to_project(project_id, 'notification', notification_data)
    
    # ==================== 有声书专用推送 ====================
    
    @staticmethod
    async def send_audiobook_progress(
        audiobook_project_id: int,
        chapter_id: int,
        stage: str,
        progress: int,
        message: str | None = None,
        stage_metrics: dict | None = None
    ):
        """
        发送有声书章节生成进度（细粒度推送）
        
        Args:
            audiobook_project_id: 有声书项目ID
            chapter_id: 章节ID
            stage: 当前阶段（strategy/script_adaptation/voice_design/...）
            progress: 进度0-100
            message: 进度消息
            stage_metrics: 阶段指标（如segments_count, tts_stats等）
        """
        data = {
            'audiobook_project_id': audiobook_project_id,
            'chapter_id': chapter_id,
            'stage': stage,
            'progress': progress,
            'message': message,
            'stage_metrics': stage_metrics or {},
        }
        # 使用 audiobook_project_id 作为房间标识（前端可监听整个有声书项目）
        room = f'audiobook_{audiobook_project_id}'
        await sio.emit('audiobook_progress', data, room=room)
    
    @staticmethod
    async def send_audiobook_chapter_complete(
        audiobook_project_id: int,
        chapter_id: int,
        audio_info: dict,
        task_id: str | None = None
    ):
        """
        发送章节音频生成完成通知
        
        Args:
            audiobook_project_id: 有声书项目ID
            chapter_id: 章节ID
            audio_info: 音频信息（duration, file_size, stats等）
            task_id: 任务ID（可选）
        """
        data = {
            'audiobook_project_id': audiobook_project_id,
            'chapter_id': chapter_id,
            'status': 'completed',
            'audio_info': audio_info,
            'task_id': task_id,
        }
        room = f'audiobook_{audiobook_project_id}'
        await sio.emit('audiobook_chapter_complete', data, room=room)
    
    @staticmethod
    async def send_audiobook_chapter_error(
        audiobook_project_id: int,
        chapter_id: int,
        error: str,
        task_id: str | None = None
    ):
        """
        发送章节音频生成失败通知
        
        Args:
            audiobook_project_id: 有声书项目ID
            chapter_id: 章节ID
            error: 错误信息
            task_id: 任务ID（可选）
        """
        data = {
            'audiobook_project_id': audiobook_project_id,
            'chapter_id': chapter_id,
            'status': 'failed',
            'error': error,
            'task_id': task_id,
        }
        room = f'audiobook_{audiobook_project_id}'
        await sio.emit('audiobook_chapter_error', data, room=room)
    
    @staticmethod
    async def send_audiobook_project_summary(
        audiobook_project_id: int,
        total_chapters: int,
        completed_chapters: int,
        failed_chapters: int,
        total_duration: float,
        total_cost: float
    ):
        """
        发送有声书项目整体进度汇总
        
        Args:
            audiobook_project_id: 有声书项目ID
            total_chapters: 总章节数
            completed_chapters: 已完成章节数
            failed_chapters: 失败章节数
            total_duration: 总时长（秒）
            total_cost: 总成本（元）
        """
        data = {
            'audiobook_project_id': audiobook_project_id,
            'total_chapters': total_chapters,
            'completed_chapters': completed_chapters,
            'failed_chapters': failed_chapters,
            'total_duration': total_duration,
            'total_cost': total_cost,
            'overall_progress': int((completed_chapters + failed_chapters) / total_chapters * 100) if total_chapters > 0 else 0,
        }
        room = f'audiobook_{audiobook_project_id}'
        await sio.emit('audiobook_project_summary', data, room=room)


# Socket.IO 事件处理器
@sio.event
async def connect(sid, environ):
    """客户端连接"""
    print(f"🔌 [WebSocket] 客户端连接: {sid}")  # 使用 print 确保输出
    logger.info(f"🔌 客户端连接: {sid}")
    await sio.emit('connected', {'message': 'WebSocket 连接成功'}, room=sid)


@sio.event
async def disconnect(sid):
    """客户端断开"""
    print(f"🔌 [WebSocket] 客户端断开: {sid}")  # 使用 print 确保输出
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
    print(f"📥 [WebSocket] 收到 join_project 请求: sid={sid}, data={data}")  # 调试日志
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


@sio.event
async def join_audiobook(sid, data):
    """加入有声书项目房间 - 用于接收实时进度推送"""
    print(f"📥 [WebSocket] 收到 join_audiobook 请求: sid={sid}, data={data}")
    try:
        audiobook_project_id = data.get('audiobook_project_id')
        token = data.get('token')

        # 验证必要参数
        if not audiobook_project_id:
            await sio.emit('error', {'message': '缺少 audiobook_project_id'}, room=sid)
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

        # 验证有声书项目所有权
        from app.models.audiobook import AudiobookProject
        db = next(get_db())
        try:
            audiobook_project = db.query(AudiobookProject).filter(
                AudiobookProject.id == audiobook_project_id
            ).first()

            if not audiobook_project:
                await sio.emit('error', {'message': '有声书项目不存在'}, room=sid)
                return

            # 验证原始项目权限
            project = db.query(Project).filter(
                Project.id == audiobook_project.project_id,
                Project.user_id == int(user_id)
            ).first()

            if not project:
                logger.warning(f"⚠️ 用户 {user_id} 尝试加入未授权的有声书项目 {audiobook_project_id}")
                await sio.emit('error', {'message': '无权访问该有声书项目'}, room=sid)
                return

            # 验证通过，加入房间
            room = f'audiobook_{audiobook_project_id}'
            await sio.enter_room(sid, room)

            logger.info(f"📥 客户端 {sid} (用户 {user_id}) 加入有声书房间: {room}")
            await sio.emit('joined_audiobook', {'audiobook_project_id': audiobook_project_id, 'room': room}, room=sid)

        finally:
            db.close()

    except Exception as e:
        logger.error(f"❌ 加入有声书房间失败: {e}")
        await sio.emit('error', {'message': f'加入房间失败: {str(e)}'}, room=sid)


@sio.event
async def leave_audiobook(sid, data):
    """离开有声书项目房间"""
    try:
        audiobook_project_id = data.get('audiobook_project_id')
        if not audiobook_project_id:
            return
        
        room = f'audiobook_{audiobook_project_id}'
        await sio.leave_room(sid, room)
        
        logger.info(f"📤 客户端 {sid} 离开有声书房间: {room}")
        await sio.emit('left_audiobook', {'audiobook_project_id': audiobook_project_id}, room=sid)
    except Exception as e:
        logger.error(f"❌ 离开有声书房间失败: {e}")


def get_socket_app():
    """获取 Socket.IO ASGI 应用"""
    return socketio.ASGIApp(sio)


# 导出管理器实例
ws_manager = WorkflowWebSocketManager()
