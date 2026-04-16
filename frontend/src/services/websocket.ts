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

class WorkflowWebSocket {
  private socket: Socket | null = null
  private projectId: number | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
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
        reconnection: true,
        reconnectionAttempts: this.maxReconnectAttempts,
        reconnectionDelay: this.reconnectDelay,
        reconnectionDelayMax: 5000,
        timeout: 60000,
        forceNew: false,
        upgrade: true,
        rememberUpgrade: true,
      })

      this.socket = socket
      this.setupEventHandlers(socket)
    }

    const socket = this.socket
    if (!socket) {
      return Promise.reject(new Error('Socket initialization failed'))
    }

    this.connectPromise = new Promise((resolve, reject) => {
      const cleanup = () => {
        socket.off('connect', onConnect)
        socket.off('connect_error', onConnectError)
        socket.off('connect_timeout', onConnectTimeout)
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

      const onConnectError = () => {
        // Wait for the built-in reconnect cycle to finish.
      }

      const onConnectTimeout = () => {
        if (this.socket !== socket) {
          cleanup()
          return
        }

        cleanup()
        this.connectPromise = null
        reject(new Error('Connection timeout'))
      }

      socket.once('connect', onConnect)
      socket.on('connect_error', onConnectError)
      socket.once('connect_timeout', onConnectTimeout)

      if (!socket.active) {
        socket.connect()
      }
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
    if (!socket || this.socket !== socket) {
      return
    }

    if (!socket.connected) {
      if (retryCount < 3) {
        setTimeout(() => this.joinProject(projectId, retryCount + 1, socket), 500)
      }
      return
    }

    const token = localStorage.getItem('access_token')
    if (!token) return

    if (this.projectId && this.projectId !== projectId) {
      socket.emit('leave_project', { project_id: this.projectId })
    }

    this.projectId = projectId
    socket.emit('join_project', {
      project_id: projectId,
      token,
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
  }

  disconnect() {
    if (!this.socket) return
    this.removeAllListeners()
    this.socket.disconnect()
    this.socket = null
    this.projectId = null
    this.connectPromise = null
  }

  isConnected(): boolean {
    return this.socket?.connected || false
  }
}

export const workflowWebSocket = new WorkflowWebSocket()
