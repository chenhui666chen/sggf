/**
 * WebSocket service based on Socket.IO.
 */
import { io, Socket } from 'socket.io-client'

const DEFAULT_SOCKET_IO_PATH = '/socket.io'

interface SocketEndpointConfig {
  url?: string
  path: string
}

function getBrowserOrigin(): string | undefined {
  if (typeof window === 'undefined' || !window.location?.origin || window.location.origin === 'null') {
    return undefined
  }
  return window.location.origin
}

function normalizeSocketPath(rawPath?: string | null): string {
  const value = String(rawPath || '').trim()
  if (!value || value === '/') {
    return DEFAULT_SOCKET_IO_PATH
  }
  return value.startsWith('/') ? value : `/${value}`
}

function resolveSocketEndpoint(rawTarget?: string | null): SocketEndpointConfig {
  const value = String(rawTarget || '').trim()
  if (!value) {
    return {
      url: getBrowserOrigin(),
      path: DEFAULT_SOCKET_IO_PATH,
    }
  }

  if (value.startsWith('/')) {
    return {
      url: getBrowserOrigin(),
      path: normalizeSocketPath(value),
    }
  }

  const normalizedUrl = value
    .replace(/^ws:\/\//i, 'http://')
    .replace(/^wss:\/\//i, 'https://')

  try {
    const parsed = new URL(normalizedUrl)
    return {
      url: parsed.origin,
      path: normalizeSocketPath(parsed.pathname),
    }
  } catch {
    return {
      url: normalizedUrl,
      path: DEFAULT_SOCKET_IO_PATH,
    }
  }
}

const SOCKET_ENDPOINT = resolveSocketEndpoint(import.meta.env.VITE_WS_URL)

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
  result: unknown
}

export interface TaskErrorData {
  project_id: number
  task_id: string
  status: 'failed'
  error: string
}

export interface AgentStatusData {
  project_id: number
  stage?: string
  agent_id?: string
  agent_name: string
  status: string
  progress?: number
  message?: string
}

export interface StreamChunkData {
  project_id: number
  stage: string
  chunk: string
  chunk_index: number
  is_complete: boolean
  extra?: Record<string, unknown>
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

export interface ModelUsedData {
  project_id: number
  stage: string
  model: string
  extra?: unknown
}

export interface NotificationData {
  project_id: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error' | 'system_collections_created'
  data?: unknown
}

export interface DreamweaverEventData {
  event_id: number
  run_id: string
  project_id: number
  stage?: string | null
  event_type: string
  payload?: Record<string, unknown>
  created_at?: string | null
}

export interface AudiobookProgressData {
  audiobook_project_id: number
  chapter_id: number
  stage: string
  progress: number
  message?: string | null
  stage_metrics?: Record<string, unknown>
}

class WorkflowWebSocket {
  private socket: Socket | null = null
  private projectId: number | null = null
  private audiobookProjectId: number | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private connectionTimeout = 60000
  private onRoomJoinedCallback: ((projectId: number) => void) | null = null

  connect(): Promise<void> {
    if (this.socket?.connected) {
      return Promise.resolve()
    }

    if (this.connectPromise) {
      return this.connectPromise
    }

    if (!this.socket) {
      const socket = io(SOCKET_ENDPOINT.url, {
        path: SOCKET_ENDPOINT.path,
        transports: ['websocket', 'polling'],
        tryAllTransports: true,
        reconnection: true,
        reconnectionAttempts: this.maxReconnectAttempts,
        reconnectionDelay: this.reconnectDelay,
        reconnectionDelayMax: 5000,
        timeout: this.connectionTimeout,
        forceNew: false,
        autoConnect: false,
        upgrade: true,
        rememberUpgrade: false,
      })

      this.socket = socket
      this.setupEventHandlers(socket)
    }

    const socket = this.socket
    if (!socket) {
      return Promise.reject(new Error('Socket initialization failed'))
    }

    if (socket.connected) {
      return Promise.resolve()
    }

    this.connectPromise = new Promise((resolve, reject) => {
      let lastError: Error | null = null
      const manager = socket.io
      const timeoutId = setTimeout(() => {
        if (this.socket !== socket) {
          cleanup()
          return
        }

        cleanup()
        this.connectPromise = null
        reject(lastError ?? new Error('Connection timeout'))
      }, this.connectionTimeout + 1000)

      const cleanup = () => {
        socket.off('connect', onConnect)
        socket.off('connect_error', onConnectError)
        manager.off('reconnect_failed', onReconnectFailed)
        clearTimeout(timeoutId)
      }

      const onConnect = () => {
        if (this.socket !== socket) {
          cleanup()
          return
        }

        cleanup()
        this.connectPromise = null
        resolve()
      }

      const onConnectError = (error: Error) => {
        if (this.socket !== socket) {
          cleanup()
          return
        }

        lastError = error
      }

      const onReconnectFailed = () => {
        if (this.socket !== socket) {
          cleanup()
          return
        }

        cleanup()
        this.connectPromise = null
        reject(lastError ?? new Error('WebSocket connection failed'))
      }

      socket.once('connect', onConnect)
      socket.on('connect_error', onConnectError)
      manager.once('reconnect_failed', onReconnectFailed)

      socket.connect()
    })

    return this.connectPromise
  }

  private setupEventHandlers(socket: Socket) {
    socket.on('connect', () => {
      if (this.socket !== socket) {
        return
      }

      this.reconnectAttempts = 0
      this.connectPromise = null
      if (this.projectId) {
        this.joinProject(this.projectId, 0, socket)
      }
      if (this.audiobookProjectId) {
        this.joinAudiobook(this.audiobookProjectId, socket)
      }
    })

    socket.on('disconnect', () => {
      if (this.socket !== socket) {
        return
      }

      this.connectPromise = null
    })

    socket.on('connect_error', () => {
      if (this.socket !== socket) {
        return
      }

      this.reconnectAttempts++
    })

    socket.on('connected', () => {
      if (this.socket !== socket) {
        return
      }
    })

    socket.on('joined_project', (data) => {
      if (this.socket !== socket) {
        return
      }

      if (this.onRoomJoinedCallback && data.project_id) {
        this.onRoomJoinedCallback(data.project_id)
      }
    })

    socket.on('left_project', () => {
      if (this.socket !== socket) {
        return
      }
    })

    socket.on('error', () => {
      if (this.socket !== socket) {
        return
      }
    })

    socket.on('model_used', () => {
      if (this.socket !== socket) {
        return
      }
    })
  }

  joinProject(projectId: number, retryCount = 0, socket: Socket | null = this.socket) {
    const previousProjectId = this.projectId
    this.projectId = projectId

    if (!socket) {
      void this.connect().catch(() => undefined)
      return
    }

    if (this.socket !== socket) {
      return
    }

    if (!socket.connected) {
      if (!socket.active) {
        socket.connect()
      }

      if (retryCount < 10) {
        setTimeout(() => this.joinProject(projectId, retryCount + 1, socket), 500)
      }
      return
    }

    // P2-4.5 收尾：认证来自握手 httpOnly cookie（后端 join_project 从 sid 会话取用户）
    if (previousProjectId && previousProjectId !== projectId) {
      socket.emit('leave_project', { project_id: previousProjectId })
    }

    socket.emit('join_project', {
      project_id: projectId,
    })
  }

  leaveProject(projectId: number) {
    if (this.socket?.connected) {
      this.socket.emit('leave_project', { project_id: projectId })
    }

    if (this.projectId === projectId) {
      this.projectId = null
    }
  }

  joinAudiobook(audiobookProjectId: number, socket: Socket | null = this.socket) {
    const previousAudiobookProjectId = this.audiobookProjectId
    this.audiobookProjectId = audiobookProjectId

    if (!socket) {
      void this.connect().catch(() => undefined)
      return
    }
    if (this.socket !== socket) {
      return
    }
    if (!socket.connected) {
      if (!socket.active) {
        socket.connect()
      }
      return
    }

    // P2-4.5 收尾：认证来自握手 httpOnly cookie（后端 join_audiobook 从 sid 会话取用户）
    if (
      previousAudiobookProjectId
      && previousAudiobookProjectId !== audiobookProjectId
    ) {
      socket.emit('leave_audiobook', {
        audiobook_project_id: previousAudiobookProjectId,
      })
    }
    socket.emit('join_audiobook', {
      audiobook_project_id: audiobookProjectId,
    })
  }

  leaveAudiobook(audiobookProjectId: number) {
    if (this.socket?.connected) {
      this.socket.emit('leave_audiobook', {
        audiobook_project_id: audiobookProjectId,
      })
    }
    if (this.audiobookProjectId === audiobookProjectId) {
      this.audiobookProjectId = null
    }
  }

  setOnRoomJoined(callback: (projectId: number) => void) {
    this.onRoomJoinedCallback = callback
  }

  private subscribeDataEvent<T>(eventName: string, callback: (data: T) => void): () => void {
    const socket = this.socket
    if (!socket) {
      return () => undefined
    }

    const listener = (data: T) => {
      callback(data)
    }

    socket.on(eventName, listener)
    return () => {
      socket.off(eventName, listener)
    }
  }

  private subscribeVoidEvent(eventName: string, callback: () => void): () => void {
    const socket = this.socket
    if (!socket) {
      return () => undefined
    }

    const listener = () => {
      callback()
    }

    socket.on(eventName, listener)
    return () => {
      socket.off(eventName, listener)
    }
  }

  onStageUpdate(callback: (data: StageUpdateData) => void) {
    return this.subscribeDataEvent('stage_update', callback)
  }

  onTaskProgress(callback: (data: TaskProgressData) => void) {
    return this.subscribeDataEvent('task_progress', callback)
  }

  onTaskComplete(callback: (data: TaskCompleteData) => void) {
    return this.subscribeDataEvent('task_complete', callback)
  }

  onTaskError(callback: (data: TaskErrorData) => void) {
    return this.subscribeDataEvent('task_error', callback)
  }

  onAgentStatus(callback: (data: AgentStatusData) => void) {
    return this.subscribeDataEvent('agent_status', callback)
  }

  onStreamStart(callback: (data: StreamStartData) => void) {
    return this.subscribeDataEvent('stream_start', callback)
  }

  onStreamChunk(callback: (data: StreamChunkData) => void) {
    return this.subscribeDataEvent('stream_chunk', callback)
  }

  onStreamEnd(callback: (data: StreamEndData) => void) {
    return this.subscribeDataEvent('stream_end', callback)
  }

  onPostSaveTaskStart(callback: (data: { chapter_id: number; chapter_number: number; status: string }) => void) {
    return this.subscribeDataEvent('post_save_task_start', callback)
  }

  onPostSaveTaskComplete(callback: (data: { chapter_id: number; chapter_number: number; status: string }) => void) {
    return this.subscribeDataEvent('post_save_task_complete', callback)
  }

  onDisconnect(callback: () => void) {
    return this.subscribeVoidEvent('disconnect', callback)
  }

  onNotification(callback: (data: NotificationData) => void) {
    return this.subscribeDataEvent('notification', callback)
  }

  onDreamweaverEvent(callback: (data: DreamweaverEventData) => void) {
    return this.subscribeDataEvent('dreamweaver_event', callback)
  }

  onAudiobookProgress(callback: (data: AudiobookProgressData) => void) {
    return this.subscribeDataEvent('audiobook_progress', callback)
  }

  removeAllListeners() {
    if (!this.socket) return
    this.socket.off('stage_update')
    this.socket.off('task_progress')
    this.socket.off('task_complete')
    this.socket.off('task_error')
    this.socket.off('agent_status')
    this.socket.off('stream_start')
    this.socket.off('stream_chunk')
    this.socket.off('stream_end')
    this.socket.off('post_save_task_start')
    this.socket.off('post_save_task_complete')
    this.socket.off('model_used')
    this.socket.off('notification')
    this.socket.off('dreamweaver_event')
    this.socket.off('audiobook_progress')
  }

  removeEventListeners() {
    if (!this.socket) return
    this.socket.off('stage_update')
    this.socket.off('task_progress')
    this.socket.off('task_complete')
    this.socket.off('task_error')
    this.socket.off('agent_status')
    this.socket.off('stream_start')
    this.socket.off('stream_chunk')
    this.socket.off('stream_end')
    this.socket.off('post_save_task_start')
    this.socket.off('post_save_task_complete')
    this.socket.off('model_used')
    this.socket.off('notification')
    this.socket.off('dreamweaver_event')
    this.socket.off('audiobook_progress')
  }

  disconnect() {
    if (!this.socket) return
    this.removeAllListeners()
    this.socket.disconnect()
    this.socket = null
    this.projectId = null
    this.audiobookProjectId = null
    this.connectPromise = null
  }

  isConnected(): boolean {
    return this.socket?.connected || false
  }
}

export const workflowWebSocket = new WorkflowWebSocket()
