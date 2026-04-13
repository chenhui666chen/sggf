import { beforeEach, describe, expect, it, vi } from 'vitest'

type Listener = (...args: unknown[]) => void

class MockSocket {
  active = false
  connected = false
  private listeners = new Map<string, Set<Listener>>()
  emit = vi.fn()
  connect = vi.fn(() => {
    this.active = true
  })
  disconnect = vi.fn(() => {
    this.connected = false
    this.active = false
  })

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

const ioMock = vi.fn()

vi.mock('socket.io-client', () => ({
  io: ioMock,
}))

describe('workflowWebSocket', () => {
  beforeEach(() => {
    ioMock.mockReset()
    vi.resetModules()
    if ('localStorage' in globalThis) {
      globalThis.localStorage.clear()
    }
  })

  it('connect 会复用进行中的连接请求，只创建一个 socket', async () => {
    const socket = new MockSocket()
    ioMock.mockReturnValue(socket)

    const { workflowWebSocket } = await import('../websocket')

    const first = workflowWebSocket.connect()
    const second = workflowWebSocket.connect()

    expect(ioMock).toHaveBeenCalledTimes(1)
    expect(first).toBe(second)

    socket.connected = true
    socket.trigger('connect')

    await expect(first).resolves.toBeUndefined()
    await expect(second).resolves.toBeUndefined()
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
})
