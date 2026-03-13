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

export function storeOAuthContext(provider: OAuthProvider, state: string) {
  localStorage.setItem(OAUTH_PROVIDER_KEY, provider)
  localStorage.setItem(OAUTH_STATE_KEY, state)
}

export function getStoredOAuthContext() {
  return {
    provider: localStorage.getItem(OAUTH_PROVIDER_KEY) as OAuthProvider | null,
    state: localStorage.getItem(OAUTH_STATE_KEY),
  }
}

export function clearOAuthContext() {
  localStorage.removeItem(OAUTH_PROVIDER_KEY)
  localStorage.removeItem(OAUTH_STATE_KEY)
}
