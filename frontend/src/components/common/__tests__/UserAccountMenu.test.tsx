/**
 * 账户菜单的渲染契约。
 *
 * 与 LanguageSwitcher 同构：菜单展开后的内容在静态渲染里是关着的（MUI Menu 关闭
 * 时不入标记），所以把"从 user 派生展示身份"这段真正的逻辑抽成纯函数
 * resolveUserAccountIdentity 单独测；组件本身只验触发按钮那一半（显示名、副标题、
 * 头像首字母、可点、带 aria）。
 *
 * 组件刻意做成展示组件（user 与回调走 props 注入，不在内部摸 redux/router），
 * 因此能沿用项目既有的 renderToStaticMarkup 范式，无需引入 Provider/MemoryRouter。
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import UserAccountMenu, { resolveUserAccountIdentity, type UserAccountSource } from '../UserAccountMenu'
import { I18nProvider, bootstrapI18n } from '@/i18n'
import { ThemeModeProvider } from '@/theme'

describe('resolveUserAccountIdentity', () => {
  it('returns an empty identity for a null user', () => {
    expect(resolveUserAccountIdentity(null)).toEqual({
      displayName: null,
      identity: null,
      avatarSrc: null,
      isAdmin: false,
    })
  })

  it('prefers a trimmed full name over the username', () => {
    const identity = resolveUserAccountIdentity({
      username: 'chenhui',
      email: 'chenhui@example.com',
      full_name: '  晨辉  ',
    })

    expect(identity.displayName).toBe('晨辉')
  })

  it('falls back to the username when the full name is blank', () => {
    const identity = resolveUserAccountIdentity({
      username: 'chenhui',
      email: null,
      full_name: '   ',
    })

    expect(identity.displayName).toBe('chenhui')
    // email 为空时，身份行退回用户名
    expect(identity.identity).toBe('chenhui')
  })

  it('prefers the email for the identity line', () => {
    const identity = resolveUserAccountIdentity({
      username: 'chenhui',
      email: 'chenhui@example.com',
    })

    expect(identity.identity).toBe('chenhui@example.com')
  })

  it('signals null display name and identity so the caller applies the i18n fallback', () => {
    const identity = resolveUserAccountIdentity({ username: '', email: null })

    expect(identity.displayName).toBeNull()
    expect(identity.identity).toBeNull()
  })

  it('detects admin from either the admin or super_admin role code', () => {
    const withRole = (code: string) =>
      resolveUserAccountIdentity({ username: 'a', email: null, roles: [{ code }] }).isAdmin

    expect(withRole('user')).toBe(false)
    expect(withRole('admin')).toBe(true)
    expect(withRole('super_admin')).toBe(true)
  })

  it('treats a missing role list as non-admin', () => {
    expect(resolveUserAccountIdentity({ username: 'a', email: null }).isAdmin).toBe(false)
  })

  it('carries the avatar url when present, else null', () => {
    expect(
      resolveUserAccountIdentity({ username: 'a', email: null, avatar_url: 'https://x/a.png' })
        .avatarSrc,
    ).toBe('https://x/a.png')
    expect(resolveUserAccountIdentity({ username: 'a', email: null }).avatarSrc).toBeNull()
  })
})

const noop = () => {}

function renderMenu(user: UserAccountSource | null): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <ThemeModeProvider>
        <UserAccountMenu user={user} onNavigate={noop} onLogout={noop} />
      </ThemeModeProvider>
    </I18nProvider>,
  )
}

const ADMIN_USER: UserAccountSource = {
  username: 'chenhui',
  email: 'chenhui@example.com',
  full_name: '晨辉',
  roles: [{ code: 'super_admin' }],
}

const CREATOR_USER: UserAccountSource = {
  username: 'bob',
  email: null,
  full_name: null,
  roles: [{ code: 'user' }],
}

describe('UserAccountMenu trigger', () => {
  it('shows the display name and the admin subtitle for an admin', () => {
    const markup = renderMenu(ADMIN_USER)

    expect(markup).toContain('晨辉')
    expect(markup).toContain('管理员 · 用户中心')
  })

  it('shows the plain account subtitle for a non-admin', () => {
    const markup = renderMenu(CREATOR_USER)

    expect(markup).toContain('用户中心')
    expect(markup).not.toContain('管理员')
  })

  it('falls back to the i18n default name when the user carries none', () => {
    const markup = renderMenu({ username: '', email: null })

    expect(markup).toContain('创作者')
  })

  it('uppercases the first character into the avatar fallback', () => {
    const markup = renderMenu({ username: 'alice', email: null, full_name: 'alice' })

    expect(markup).toContain('alice')
    expect(markup).toContain('>A<')
  })

  it('renders a real button wired as a menu popup', () => {
    const markup = renderMenu(ADMIN_USER)

    expect(markup).toContain('<button')
    expect(markup).toContain('aria-haspopup="true"')
  })

  it('follows the interface language', async () => {
    const instance = await bootstrapI18n('en-US')
    const markup = renderToStaticMarkup(
      <I18nProvider instance={instance}>
        <ThemeModeProvider>
          <UserAccountMenu user={ADMIN_USER} onNavigate={noop} onLogout={noop} />
        </ThemeModeProvider>
      </I18nProvider>,
    )

    expect(markup).toContain('Admin · Account')
    expect(markup).not.toContain('管理员')
  })
})
