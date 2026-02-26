/**
 * WebSocket 服务 - 基于 Socket.IO
 * 用于实时接收工作流执行状态更新
 */
import { io, Socket } from 'socket.io-client'

// 获取 WebSocket 服务器地址
const SOCKET_URL = import.meta.env.VITE_WS_URL || 'http://localhost:8000'

export interface StageUpdateData {
  project_id: number
  stage: string
  status: string
  output?: string
  progress?: number
}

export interface TaskProgressData {
  project_id: number
  task_id: string
  progress: number
  message?: string
}

export interface TaskCompleteData {
  project_id: number
  task_id: string
  status: 'completed'
  result: any
}

export interface TaskErrorData {
  project_id: number
  task_id: string
  status: 'failed'
  error: string
}

export interface AgentStatusData {
  project_id: number
  stage?: string  // ✅ 添加阶段字段
  agent_id?: string  // ✅ 添加 Agent ID
  agent_name: string
  status: string
  progress?: number  // ✅ 添加进度字段
  message?: string
}

// 🆕 流式输出相关接口
export interface StreamChunkData {
  project_id: number
  stage: string
  chunk: string
  chunk_index: number
  is_complete: boolean
  extra?: Record<string, any> // 添加额外数据字段，用于传递target等信息
}

export interface StreamStartData {
  project_id: number
  stage: string
  message?: string
}

export interface StreamEndData {
  project_id: number
  stage: string
  total_chars: number
  message?: string
}

// 🆕 模型使用事件
export interface ModelUsedData {
  project_id: number
  stage: string
  model: string
  extra?: any
}

// 🆕 通知事件
export interface NotificationData {
  project_id: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error' | 'system_collections_created'
  data?: any
}

export interface DreamweaverEventData {
  event_id: number
  run_id: string
  project_id: number
  stage?: string | null
  event_type: string
  payload?: Record<string, any>
  created_at?: string | null
}

class WorkflowWebSocket {
  private socket: Socket | null = null
  private projectId: number | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  // 移除了未使用的 listenersRegistered 变量
  
  // 🔥 新增：加入房间成功后的回调
  private onRoomJoinedCallback: ((projectId: number) => void) | null = null

  /**
   * 连接到 WebSocket 服务器
   * @returns Promise，连接成功后 resolve
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.socket?.connected) {
        console.log('🔌 WebSocket 已连接，跳过重复连接')
        resolve()
        return
      }

      console.log('🔌 连接 WebSocket 服务器:', SOCKET_URL)

      this.socket = io(SOCKET_URL, {
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: this.maxReconnectAttempts,
        reconnectionDelay: this.reconnectDelay,
        reconnectionDelayMax: 5000,
        timeout: 60000,  // 🔧 连接超时 60 秒
        forceNew: false,
        upgrade: true,
        rememberUpgrade: true,
      })

      // 设置一次性连接监听
      const onConnect = () => {
        console.log('✅ WebSocket 连接成功')
        this.socket?.off('connect', onConnect)
        this.socket?.off('connect_error', onConnectError)
        this.socket?.off('connect_timeout', onConnectTimeout)
        resolve()
      }

      const onConnectError = (error: Error) => {
        console.error('❌ WebSocket 连接错误:', error)
        // 不立即 reject，等待重连
      }
      
      const onConnectTimeout = () => {
        console.error('❌ WebSocket 连接超时')
        this.socket?.off('connect', onConnect)
        this.socket?.off('connect_error', onConnectError)
        this.socket?.off('connect_timeout', onConnectTimeout)
        reject(new Error('Connection timeout'))
      }

      this.socket.once('connect', onConnect)
      this.socket.on('connect_error', onConnectError)
      this.socket.once('connect_timeout', onConnectTimeout)

      this.setupEventHandlers()
    })
  }

  /**
   * 设置事件处理器
   */
  private setupEventHandlers() {
    if (!this.socket) return

    this.socket.on('connect', () => {
      console.log('✅ WebSocket 连接成功')
      this.reconnectAttempts = 0

      // 如果有项目 ID，重新加入房间
      if (this.projectId) {
        this.joinProject(this.projectId)
      }
    })

    this.socket.on('disconnect', (reason) => {
      console.log('🔌 WebSocket 断开连接:', reason)
    })

    this.socket.on('connect_error', (error) => {
      console.error('❌ WebSocket 连接错误:', error)
      this.reconnectAttempts++

      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error('❌ WebSocket 重连失败次数过多，停止重连')
      }
    })

    this.socket.on('connected', (data) => {
      console.log('📡 收到服务器欢迎消息:', data)
    })

    this.socket.on('joined_project', (data) => {
      console.log('📥 已加入项目房间:', data)
      
      // 🔥 关键修复：加入房间成功后，触发回调通知页面刷新状态
      if (this.onRoomJoinedCallback && data.project_id) {
        console.log('🔔 [房间加入成功] 触发回调，projectId=', data.project_id)
        this.onRoomJoinedCallback(data.project_id)
      }
    })

    this.socket.on('left_project', (data) => {
      console.log('📤 已离开项目房间:', data)
    })

    this.socket.on('error', (data) => {
      console.error('❌ WebSocket 错误:', data)
    })

    // 🆕 模型使用事件：直接在控制台打印
    this.socket.on('model_used', (data: any) => {
      const { project_id, stage, model, extra } = data || {}
      console.log(
        '[MODEL_USED]',
        `project=${project_id}`,
        `stage=${stage}`,
        `model=${model}`,
        extra || ''
      )
    })
  }

  /**
   * 加入项目房间
   * @param projectId 项目 ID
   * @param retryCount 重试次数（内部使用）
   */
  joinProject(projectId: number, retryCount = 0) {
    if (!this.socket?.connected) {
      if (retryCount < 3) {
        console.log(`⏳ WebSocket 尚未连接，${500}ms 后重试...`)
        setTimeout(() => this.joinProject(projectId, retryCount + 1), 500)
      } else {
        console.warn('⚠️  WebSocket 未连接，无法加入房间（已重试3次）')
      }
      return
    }

    // 获取认证 token
    const token = localStorage.getItem('access_token')
    if (!token) {
      console.error('❌ 缺少认证令牌，无法加入房间')
      return
    }

    this.projectId = projectId
    console.log('📥 加入项目房间:', projectId)
    this.socket.emit('join_project', {
      project_id: projectId,
      token: token  // ✅ 传递认证令牌
    })
  }

  /**
   * 离开项目房间
   */
  leaveProject(projectId: number) {
    if (!this.socket?.connected) {
      return
    }

    console.log('📤 离开项目房间:', projectId)
    this.socket.emit('leave_project', { project_id: projectId })

    if (this.projectId === projectId) {
      this.projectId = null
    }
  }

  /**
   * 🔥 设置加入房间成功后的回调
   * @param callback 回调函数，接收 projectId 作为参数
   */
  setOnRoomJoined(callback: (projectId: number) => void) {
    this.onRoomJoinedCallback = callback
    console.log('✅ [回调注册] 已注册加入房间成功回调')
  }

  /**
   * 监听阶段更新
   */
  onStageUpdate(callback: (data: StageUpdateData) => void) {
    if (!this.socket) return

    // 🆕 防止重复注册：先移除旧监听器
    this.socket.off('stage_update')
    this.socket.on('stage_update', (data: StageUpdateData) => {
      console.log('📊 收到阶段更新:', data)
      callback(data)
    })
  }

  /**
   * 监听任务进度
   */
  onTaskProgress(callback: (data: TaskProgressData) => void) {
    if (!this.socket) return

    // 🆕 防止重复注册
    this.socket.off('task_progress')
    this.socket.on('task_progress', (data: TaskProgressData) => {
      console.log('📈 收到任务进度:', data)
      callback(data)
    })
  }

  /**
   * 监听任务完成
   */
  onTaskComplete(callback: (data: TaskCompleteData) => void) {
    if (!this.socket) return

    // 🆕 防止重复注册
    this.socket.off('task_complete')
    this.socket.on('task_complete', (data: TaskCompleteData) => {
      console.log('✅ 收到任务完成:', data)
      callback(data)
    })
  }

  /**
   * 监听任务错误
   */
  onTaskError(callback: (data: TaskErrorData) => void) {
    if (!this.socket) return

    // 🆕 防止重复注册
    this.socket.off('task_error')
    this.socket.on('task_error', (data: TaskErrorData) => {
      console.log('❌ 收到任务错误:', data)
      callback(data)
    })
  }

  /**
   * 监听 Agent 状态
   */
  onAgentStatus(callback: (data: AgentStatusData) => void) {
    if (!this.socket) return

    // 🆕 防止重复注册
    this.socket.off('agent_status')
    this.socket.on('agent_status', (data: AgentStatusData) => {
      console.log('🤖 收到 Agent 状态:', data)
      callback(data)
    })
  }

  // 🆕 流式输出监听器

  /**
   * 监听流式输出开始
   */
  onStreamStart(callback: (data: StreamStartData) => void) {
    if (!this.socket) return

    this.socket.off('stream_start')
    this.socket.on('stream_start', (data: StreamStartData) => {
      console.log('🌊 流式输出开始:', data)
      callback(data)
    })
  }

  /**
   * 监听流式输出块
   */
  onStreamChunk(callback: (data: StreamChunkData) => void) {
    if (!this.socket) return

    this.socket.off('stream_chunk')
    this.socket.on('stream_chunk', (data: StreamChunkData) => {
      // 不打印每个块的日志，避免刷屏
      callback(data)
    })
  }

  /**
   * 监听流式输出结束
   */
  onStreamEnd(callback: (data: StreamEndData) => void) {
    if (!this.socket) return

    this.socket.off('stream_end')
    this.socket.on('stream_end', (data: StreamEndData) => {
      console.log('🌊 流式输出结束:', data)
      callback(data)
    })
  }

  /**
   * 🆕 监听章节保存后台任务开始
   */
  onPostSaveTaskStart(callback: (data: { chapter_id: number; chapter_number: number; status: string }) => void) {
    if (!this.socket) return

    this.socket.off('post_save_task_start')
    this.socket.on('post_save_task_start', (data) => {
      console.log('📡 收到后台任务开始:', data)
      callback(data)
    })
  }

  /**
   * 🆕 监听章节保存后台任务完成
   */
  onPostSaveTaskComplete(callback: (data: { chapter_id: number; chapter_number: number; status: string }) => void) {
    if (!this.socket) return

    this.socket.off('post_save_task_complete')
    this.socket.on('post_save_task_complete', (data) => {
      console.log('✅ 收到后台任务完成:', data)
      callback(data)
    })
  }

  /**
   * 🆕 监听WebSocket断开连接
   */
  onDisconnect(callback: () => void) {
    if (!this.socket) return

    this.socket.off('disconnect')
    this.socket.on('disconnect', (reason) => {
      console.log('🔌 WebSocket 断开连接:', reason)
      callback()
    })
  }

  /**
   * 🆕 监听通知消息
   */
  onNotification(callback: (data: NotificationData) => void) {
    if (!this.socket) return

    this.socket.off('notification')
    this.socket.off('dreamweaver_event')
    this.socket.on('notification', (data: NotificationData) => {
      console.log('🔔 收到通知:', data)
      callback(data)
    })
  }

  onDreamweaverEvent(callback: (data: DreamweaverEventData) => void) {
    if (!this.socket) return

    this.socket.off('dreamweaver_event')
    this.socket.on('dreamweaver_event', (data: DreamweaverEventData) => {
      callback(data)
    })
  }

  /**
   * 移除所有监听器
   */
  removeAllListeners() {
    if (!this.socket) return

    console.log('🗑️ 移除 WebSocket 监听器...')
    this.socket.off('stage_update')
    this.socket.off('task_progress')
    this.socket.off('task_complete')
    this.socket.off('task_error')
    this.socket.off('agent_status')
    // 🆕 移除流式输出监听器
    this.socket.off('stream_start')
    this.socket.off('stream_chunk')
    this.socket.off('stream_end')
    // 🆕 移除后台任务监听器
    this.socket.off('post_save_task_start')
    this.socket.off('post_save_task_complete')
    // 🆕 移除模型事件监听
    this.socket.off('model_used')
    // 🆕 移除通知监听
    this.socket.off('notification')
    this.socket.off('dreamweaver_event')
    console.log('✅ 监听器已移除')
  }

  /**
   * 🆕 清除特定事件的监听器（用于组件卸载时）
   */
  removeEventListeners() {
    if (!this.socket) return

    console.log('🗑️ 清除事件监听器（保持连接）...')
    // ✅ 只移除事件监听，不断开连接
    this.socket.off('stage_update')
    this.socket.off('task_progress')
    this.socket.off('task_complete')
    this.socket.off('task_error')
    this.socket.off('agent_status')
    // 🆕 移除流式输出监听器
    this.socket.off('stream_start')
    this.socket.off('stream_chunk')
    this.socket.off('stream_end')
    // 🆕 移除后台任务监听器
    this.socket.off('post_save_task_start')
    this.socket.off('post_save_task_complete')
    // 🆕 移除模型事件监听
    this.socket.off('model_used')
    // 🆕 移除通知监听
    this.socket.off('notification')
    this.socket.off('dreamweaver_event')
    console.log('✅ 事件监听器已清除，连接保持')
  }

  /**
   * 断开连接
   */
  disconnect() {
    if (!this.socket) return

    console.log('🔌 断开 WebSocket 连接')
    this.removeAllListeners()
    this.socket.disconnect()
    this.socket = null
    this.projectId = null
  }

  /**
   * 检查连接状态
   */
  isConnected(): boolean {
    return this.socket?.connected || false
  }
}

// 导出单例实例
export const workflowWebSocket = new WorkflowWebSocket()
