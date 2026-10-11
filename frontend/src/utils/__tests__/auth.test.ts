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

// node 环境无 document，用最小 cookie jar 桩支持读写与 max-age=0 删除
function installCookieStub(): Map<string, string> {
  const jar = new Map<string, string>()

  vi.stubGlobal('document', {
    get cookie() {
      return Array.from(jar.entries())
        .map(([k, v]) => `${k}=${v}`)
        .join('; ')
    },
    set cookie(raw: string) {
      const parts = raw.split(';')
      const pair = parts[0] ?? ''
      const eq = pair.indexOf('=')
      if (eq < 0) return
      const name = pair.slice(0, eq).trim()
      const value = pair.slice(eq + 1).trim()
      const expired = parts.some((p) => /^\s*max-age=\s*0\s*$/i.test(p))
      if (!value || expired) {
        jar.delete(name)
        return
      }
      jar.set(name, value)
    },
  })

  return jar
}

describe('OAuth 移动端唤起与 state 双写回退', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: createMemoryStorage(),
    })
    installCookieStub()
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'localStorage')
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  describe('isMobileUserAgent', () => {
    it('iPhone UA 判定为移动端', async () => {
      const { isMobileUserAgent } = await import('../auth')
      const ua =
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
      expect(isMobileUserAgent(ua)).toBe(true)
    })

    it('Android 手机 UA 判定为移动端', async () => {
      const { isMobileUserAgent } = await import('../auth')
      const ua =
        'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
      expect(isMobileUserAgent(ua)).toBe(true)
    })

    it('桌面 Windows Chrome UA 判定为非移动端', async () => {
      const { isMobileUserAgent } = await import('../auth')
      const ua =
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      expect(isMobileUserAgent(ua)).toBe(false)
    })
  })

  describe('buildAlipayAppInvokeUrl', () => {
    it('构造 alipays scheme 并对授权地址整体编码', async () => {
      const { buildAlipayAppInvokeUrl } = await import('../auth')
      const authUrl =
        'https://openauth.alipay.com/oauth2/publicAppAuthorize.htm?app_id=2021001&state=abc-123'
      const prefix = 'alipays://platformapi/startapp?appId=20000067&url='

      const result = buildAlipayAppInvokeUrl(authUrl)

      expect(result.startsWith(prefix)).toBe(true)
      expect(decodeURIComponent(result.slice(prefix.length))).toBe(authUrl)
    })
  })

  describe('resolveAlipayTargetUrl', () => {
    it('移动端返回 alipays 唤起 scheme', async () => {
      const { resolveAlipayTargetUrl } = await import('../auth')
      const authUrl = 'https://openauth.alipay.com/oauth2/publicAppAuthorize.htm?app_id=1'

      expect(resolveAlipayTargetUrl(authUrl, true)).toBe(
        'alipays://platformapi/startapp?appId=20000067&url=' + encodeURIComponent(authUrl),
      )
    })

    it('桌面端保持原授权地址不变（继续走扫码）', async () => {
      const { resolveAlipayTargetUrl } = await import('../auth')
      const authUrl = 'https://openauth.alipay.com/oauth2/publicAppAuthorize.htm?app_id=1'

      expect(resolveAlipayTargetUrl(authUrl, false)).toBe(authUrl)
    })
  })

  describe('state 双写与回退（跨容器回跳）', () => {
    it('storeOAuthContext 同时写入 localStorage 与 cookie', async () => {
      const { storeOAuthContext } = await import('../auth')

      storeOAuthContext('alipay', 'state-xyz')

      expect(localStorage.getItem('oauth_state')).toBe('state-xyz')
      expect(document.cookie).toContain('oauth_state=state-xyz')
    })

    it('localStorage 缺失时从 cookie 回退读取，避免误报登录状态校验失败', async () => {
      const { storeOAuthContext, getStoredOAuthContext } = await import('../auth')

      storeOAuthContext('alipay', 'state-xyz')
      // 模拟唤起 App 后回跳到另一个容器，localStorage 按源隔离而丢失
      localStorage.removeItem('oauth_state')

      const ctx = getStoredOAuthContext()
      expect(ctx.state).toBe('state-xyz')
      expect(ctx.provider).toBe('alipay')
    })

    it('clearOAuthContext 同时清理 localStorage 与 cookie', async () => {
      const { storeOAuthContext, clearOAuthContext, getStoredOAuthContext } = await import('../auth')

      storeOAuthContext('alipay', 'state-xyz')
      clearOAuthContext()

      expect(localStorage.getItem('oauth_state')).toBeNull()
      expect(getStoredOAuthContext().state).toBeNull()
    })
  })
})
