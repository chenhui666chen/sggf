const OAUTH_PROVIDER_KEY = 'oauth_provider'
const OAUTH_STATE_KEY = 'oauth_state'

export type OAuthProvider = 'alipay' | 'wechat'

function generateFallbackState(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function generateOAuthState(): string {
  if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
    return window.crypto.randomUUID()
  }

  return generateFallbackState()
}

// 唤起支付宝 App 后，授权完成回跳可能落在另一个容器（App webview / 系统浏览器），
// localStorage 按源隔离会丢失，故 state 双写 cookie 作为回退。TTL 与后端
// OAuthStateService.STATE_TTL_SECONDS 对齐，避免长期残留。
const OAUTH_STATE_COOKIE_TTL_SECONDS = 600

const MOBILE_UA_PATTERN = /android|iphone|ipod|windows phone|blackberry|mobile/i

/** 判定是否为移动端 UA，用于决定是否尝试唤起支付宝 App（PC 继续走扫码）。 */
export function isMobileUserAgent(ua: string): boolean {
  return MOBILE_UA_PATTERN.test(ua)
}

// appId=20000067 为支付宝 Nebula 容器通用浏览器模式，用于在 App 内打开指定网页
const ALIPAY_APP_INVOKE_PREFIX = 'alipays://platformapi/startapp?appId=20000067&url='

/** 构造唤起支付宝 App 打开授权页的 scheme；未安装或唤起失败时需降级到普通授权 URL。 */
export function buildAlipayAppInvokeUrl(authUrl: string): string {
  return `${ALIPAY_APP_INVOKE_PREFIX}${encodeURIComponent(authUrl)}`
}

/** 决定支付宝跳转目标：移动端走 App 唤起 scheme，桌面端保持扫码授权页。 */
export function resolveAlipayTargetUrl(authUrl: string, isMobile: boolean): string {
  return isMobile ? buildAlipayAppInvokeUrl(authUrl) : authUrl
}

// 未安装支付宝 App 时 scheme 无响应，等待该时长后降级到 H5 授权页
const APP_INVOKE_FALLBACK_MS = 1200

/**
 * 跳转第三方授权：支付宝在移动端优先唤起 App（免扫码），其余情况沿用原授权页。
 * 唤起失败（未安装 App）时降级到 H5 授权页，用户仍可用账号密码完成授权。
 */
export function navigateToOAuthTarget(authUrl: string, provider: OAuthProvider): void {
  if (provider !== 'alipay' || !isMobileUserAgent(navigator.userAgent)) {
    window.location.href = authUrl
    return
  }

  let hasLeft = false
  const markLeft = () => {
    if (document.visibilityState === 'hidden') {
      hasLeft = true
    }
  }
  document.addEventListener('visibilitychange', markLeft)
  window.location.href = resolveAlipayTargetUrl(authUrl, true)

  window.setTimeout(() => {
    document.removeEventListener('visibilitychange', markLeft)
    if (!hasLeft) {
      window.location.href = authUrl
    }
  }, APP_INVOKE_FALLBACK_MS)
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const matched = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`))
  return matched ? decodeURIComponent(matched[1]) : null
}

function writeCookie(name: string, value: string, maxAgeSeconds: number): void {
  if (typeof document === 'undefined') return
  const secure = typeof window !== 'undefined' && window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAgeSeconds}; SameSite=Lax${secure}`
}

function clearCookie(name: string): void {
  if (typeof document === 'undefined') return
  document.cookie = `${name}=; path=/; max-age=0; SameSite=Lax`
}

export function storeOAuthContext(provider: OAuthProvider, state: string) {
  localStorage.setItem(OAUTH_PROVIDER_KEY, provider)
  localStorage.setItem(OAUTH_STATE_KEY, state)
  writeCookie(OAUTH_PROVIDER_KEY, provider, OAUTH_STATE_COOKIE_TTL_SECONDS)
  writeCookie(OAUTH_STATE_KEY, state, OAUTH_STATE_COOKIE_TTL_SECONDS)
}

export function getStoredOAuthContext() {
  const provider = (localStorage.getItem(OAUTH_PROVIDER_KEY) ??
    readCookie(OAUTH_PROVIDER_KEY)) as OAuthProvider | null
  const state = localStorage.getItem(OAUTH_STATE_KEY) ?? readCookie(OAUTH_STATE_KEY)
  return { provider, state }
}

export function clearOAuthContext() {
  localStorage.removeItem(OAUTH_PROVIDER_KEY)
  localStorage.removeItem(OAUTH_STATE_KEY)
  clearCookie(OAUTH_PROVIDER_KEY)
  clearCookie(OAUTH_STATE_KEY)
}

// 各平台回调白名单仅登记了单一域名（支付宝=裸域、微信=www），
// 且 OAuth state 存于 localStorage 按源隔离，发起与回调必须同源。
// 生产双域名并存期间，发起前需先跳转到该平台的授权域名。
const OAUTH_REQUIRED_ORIGINS: Record<OAuthProvider, string> = {
  alipay: 'https://sggf.net',
  wechat: 'https://www.sggf.net',
}

/**
 * 返回该第三方登录要求的生产域名；非生产域名访问（本地开发等）返回 null 表示无需跳转。
 */
export function getRequiredOAuthOrigin(provider: OAuthProvider): string | null {
  const { hostname } = window.location
  if (hostname !== 'sggf.net' && hostname !== 'www.sggf.net') {
    return null
  }
  return OAUTH_REQUIRED_ORIGINS[provider]
}
