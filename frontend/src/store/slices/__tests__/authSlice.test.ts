import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function createMemoryStorage(): Storage {
  const store = new Map<string, string>()

  return {
    get length() {
      return store.size
    },
    clear() {
      store.clear()
    },
    getItem(key) {
      return store.get(key) ?? null
    },
    key(index) {
      return Array.from(store.keys())[index] ?? null
    },
    removeItem(key) {
      store.delete(key)
    },
    setItem(key, value) {
      store.set(key, String(value))
    },
  }
}

describe('authSlice persisted state', () => {
  beforeEach(() => {
    vi.resetModules()

    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: createMemoryStorage(),
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'localStorage')
    vi.resetModules()
  })

  it('clears malformed persisted auth instead of throwing during module load', async () => {
    localStorage.setItem('access_token', 'stale-token')
    localStorage.setItem('user', '{bad json')

    const { default: authReducer } = await import('../authSlice')
    const state = authReducer(undefined, { type: '@@test/init' })

    expect(state.user).toBeNull()
    expect(state.isAuthenticated).toBe(false)
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('登录成功后只持久化非 PII user 快照（token 全走 cookie），登出清理', async () => {
    localStorage.setItem('access_token', 'stale-access')
    localStorage.setItem('refresh_token', 'stale-refresh')

    const { default: authReducer, login, logout } = await import('../authSlice')

    const fulfilled = {
      type: login.fulfilled.type,
      payload: {
        user: {
          id: 1,
          username: 'writer',
          email: 'writer@example.com',
          is_active: true,
          created_at: '2026-08-28T00:00:00Z',
          updated_at: '2026-08-28T00:00:00Z',
        },
      },
    }

    const state = authReducer(undefined, fulfilled)
    expect(state.isAuthenticated).toBe(true)
    // P2-4.5 收尾：token 只经 httpOnly cookie，localStorage 不再写入任何令牌
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()

    // user 快照收窄，PII（email/phone）不落 localStorage
    const persistedUser = JSON.parse(localStorage.getItem('user') as string)
    expect(persistedUser.username).toBe('writer')
    expect(persistedUser).not.toHaveProperty('email')
    expect(persistedUser).not.toHaveProperty('phone')

    const afterLogout = authReducer(state, logout())
    expect(afterLogout.isAuthenticated).toBe(false)
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('会话恢复失败不写 error（避免登录页首屏误报红框）；主动登录失败仍要提示', async () => {
    const { default: authReducer, getCurrentUser, login } = await import('../authSlice')

    const sessionRejected = { type: getCurrentUser.rejected.type, payload: 'Not authenticated' }
    const state = authReducer(undefined, sessionRejected)
    expect(state.isAuthenticated).toBe(false)
    expect(state.user).toBeNull()
    expect(state.error).toBeNull()

    const loginRejected = { type: login.rejected.type, payload: '用户名或密码错误' }
    expect(authReducer(undefined, loginRejected).error).toBe('用户名或密码错误')
  })

  it('会话恢复未落定前 sessionStatus 为 checking，落定后一律 ready', async () => {
    const { default: authReducer, getCurrentUser } = await import('../authSlice')

    const initial = authReducer(undefined, { type: '@@test/init' })
    expect(initial.sessionStatus).toBe('checking')
    // 初始 isAuthenticated 恒为 false（令牌只在 httpOnly cookie 里），
    // 这正是硬刷新保护页被误判成未登录的源头
    expect(initial.isAuthenticated).toBe(false)

    const pending = authReducer(initial, { type: getCurrentUser.pending.type })
    expect(pending.sessionStatus).toBe('checking')

    const restored = authReducer(pending, {
      type: getCurrentUser.fulfilled.type,
      payload: {
        id: 3,
        username: '晨辉',
        email: 'writer@example.com',
        is_active: true,
        created_at: '2026-08-28T00:00:00Z',
        updated_at: '2026-08-28T00:00:00Z',
      },
    })
    expect(restored.sessionStatus).toBe('ready')
    expect(restored.isAuthenticated).toBe(true)

    const rejected = authReducer(pending, { type: getCurrentUser.rejected.type, payload: 'Not authenticated' })
    expect(rejected.sessionStatus).toBe('ready')
    expect(rejected.isAuthenticated).toBe(false)
  })
})
