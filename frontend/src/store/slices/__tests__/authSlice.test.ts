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
    expect(state.token).toBeNull()
    expect(state.isAuthenticated).toBe(false)
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })
})
