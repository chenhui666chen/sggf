import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Listener = (...args: unknown[]) => void

class MockEmitter {
  private listeners = new Map<string, Set<Listener>>()

  on(eventName: string, listener: Listener) {
    const current = this.listeners.get(eventName) ?? new Set<Listener>()
    current.add(listener)
    this.listeners.set(eventName, current)
    return this
  }

  once(eventName: string, listener: Listener) {
    const wrapped: Listener = (...args) => {
      this.off(eventName, wrapped)
      listener(...args)
    }
    return this.on(eventName, wrapped)
  }

  off(eventName: string, listener?: Listener) {
    if (!listener) {
      this.listeners.delete(eventName)
      return this
    }

    const current = this.listeners.get(eventName)
    if (!current) {
      return this
    }

    current.delete(listener)
    if (current.size === 0) {
      this.listeners.delete(eventName)
    }
    return this
  }

  trigger(eventName: string, ...args: unknown[]) {
    const current = Array.from(this.listeners.get(eventName) ?? [])
    current.forEach((listener) => listener(...args))
  }
}

class MockSocket {
  active = false
  connected = false
  io = new MockEmitter()
  private emitter = new MockEmitter()

  emit = vi.fn()
  connect = vi.fn(() => {
    this.active = true
  })
  disconnect = vi.fn(() => {
    this.connected = false
    this.active = false
  })

  on(eventName: string, listener: Listener) {
    return this.emitter.on(eventName, listener)
  }

  once(eventName: string, listener: Listener) {
    return this.emitter.once(eventName, listener)
  }

  off(eventName: string, listener?: Listener) {
    return this.emitter.off(eventName, listener)
  }

  trigger(eventName: string, ...args: unknown[]) {
    this.emitter.trigger(eventName, ...args)
  }
}

const ioMock = vi.fn()

vi.mock('socket.io-client', () => ({
  io: ioMock,
}))

describe('workflowWebSocket', () => {
  beforeEach(() => {
    ioMock.mockReset()
    vi.resetModules()

    const storage = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value)
        },
        removeItem: (key: string) => {
          storage.delete(key)
        },
        clear: () => {
          storage.clear()
        },
      },
      configurable: true,
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'window')
    Reflect.deleteProperty(globalThis, 'localStorage')
  })

  it('会复用进行中的连接请求，只创建一个 socket', async () => {
    const socket = new MockSocket()
    ioMock.mockReturnValue(socket)

    const { workflowWebSocket } = await import('../websocket')

    const first = workflowWebSocket.connect()
    const second = workflowWebSocket.connect()

    expect(ioMock).toHaveBeenCalledTimes(1)
    expect(first).toBe(second)
    expect(socket.connect).toHaveBeenCalledTimes(1)

    socket.connected = true
    socket.trigger('connect')

    await expect(first).resolves.toBeUndefined()
    await expect(second).resolves.toBeUndefined()
  })

  it('使用更稳妥的连接配置建立 Socket.IO 连接', async () => {
    const socket = new MockSocket()
    ioMock.mockReturnValue(socket)
    Object.defineProperty(globalThis, 'window', {
      value: {
        location: {
          origin: 'https://sggf.net',
        },
      },
      configurable: true,
    })

    const { workflowWebSocket } = await import('../websocket')

    const connectPromise = workflowWebSocket.connect()

    expect(ioMock).toHaveBeenCalledWith(
      'https://sggf.net',
      expect.objectContaining({
        path: '/socket.io',
        autoConnect: false,
        rememberUpgrade: false,
        tryAllTransports: true,
        transports: ['websocket', 'polling'],
      }),
    )

    socket.connected = true
    socket.trigger('connect')

    await expect(connectPromise).resolves.toBeUndefined()
  })

  it('task_complete 监听可以并存，取消订阅只移除自身监听器', async () => {
    const socket = new MockSocket()
    ioMock.mockReturnValue(socket)

    const { workflowWebSocket } = await import('../websocket')

    const connectPromise = workflowWebSocket.connect()
    socket.connected = true
    socket.trigger('connect')
    await connectPromise

    const listenerA = vi.fn()
    const listenerB = vi.fn()
    const unsubscribeA = workflowWebSocket.onTaskComplete(listenerA)
    workflowWebSocket.onTaskComplete(listenerB)

    const payload = {
      project_id: 1,
      task_id: 'expand-story-1',
      status: 'completed' as const,
      result: { current_chapter_count: 12 },
    }

    socket.trigger('task_complete', payload)

    expect(listenerA).toHaveBeenCalledTimes(1)
    expect(listenerB).toHaveBeenCalledTimes(1)

    unsubscribeA()
    socket.trigger('task_complete', payload)

    expect(listenerA).toHaveBeenCalledTimes(1)
    expect(listenerB).toHaveBeenCalledTimes(2)
  })

  it('joinProject 可以在连接完成前缓存项目，并在连上后自动入房', async () => {
    const socket = new MockSocket()
    ioMock.mockReturnValue(socket)
    globalThis.localStorage.setItem('access_token', 'jwt-token')

    const { workflowWebSocket } = await import('../websocket')

    const connectPromise = workflowWebSocket.connect()
    workflowWebSocket.joinProject(13)

    expect(socket.emit).not.toHaveBeenCalledWith('join_project', expect.anything())

    socket.connected = true
    socket.trigger('connect')

    await expect(connectPromise).resolves.toBeUndefined()
    expect(socket.emit).toHaveBeenCalledWith('join_project', {
      project_id: 13,
      token: 'jwt-token',
    })
  })
})
