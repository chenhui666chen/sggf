import { describe, expect, it } from 'vitest'

import { resolveProtectedRouteDecision } from '../ProtectedRoute'

describe('resolveProtectedRouteDecision', () => {
  it('会话恢复未落定时既不授权也不重定向', () => {
    // 硬刷新时 store 里的 isAuthenticated 还是 false（令牌只在 httpOnly cookie 里），
    // 此时重定向会把已登录用户弹到登录页
    expect(resolveProtectedRouteDecision({ sessionStatus: 'checking', isAuthenticated: false })).toBe('pending')
    expect(resolveProtectedRouteDecision({ sessionStatus: 'checking', isAuthenticated: true })).toBe('pending')
  })

  it('恢复完成后才按登录态放行或重定向', () => {
    expect(resolveProtectedRouteDecision({ sessionStatus: 'ready', isAuthenticated: true })).toBe('grant')
    expect(resolveProtectedRouteDecision({ sessionStatus: 'ready', isAuthenticated: false })).toBe('redirect')
  })
})
