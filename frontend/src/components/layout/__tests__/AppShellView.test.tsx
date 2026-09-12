/**
 * AppShell 展示层的骨架契约。
 *
 * AppShell 本体是连接组件（redux 取 user、router 取 navigate、Outlet 承接路由页），
 * 按项目约定（AdminLayout 亦然）不做静态单测；把 chrome 的组装抽成展示组件
 * AppShellView——user / 回调 / children 全走 props，于是能用 renderToStaticMarkup
 * 锁住顶栏骨架：拾光字标（可点回首页）、控件簇、账户菜单、<main> 里的路由出口。
 *
 * 各部件自身的细节由各自测试负责（BrandWordmark / ControlCluster / UserAccountMenu），
 * 这里只验"它们被正确组装进了 shell"，不复验部件内部。
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'

import AppShellView from '../AppShellView'
import type { UserAccountSource } from '@/components/common/UserAccountMenu'
import { I18nProvider, bootstrapI18n } from '@/i18n'
import { ThemeModeProvider } from '@/theme'

const noop = () => {}

const ADMIN_USER: UserAccountSource = {
  username: 'chenhui',
  email: 'chenhui@example.com',
  full_name: '晨辉',
  roles: [{ code: 'super_admin' }],
}

function renderShell(children?: ReactNode): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <ThemeModeProvider>
        <AppShellView user={ADMIN_USER} onNavigate={noop} onLogout={noop}>
          {children}
        </AppShellView>
      </ThemeModeProvider>
    </I18nProvider>,
  )
}

describe('AppShellView', () => {
  it('brands the top bar with the wordmark and a home link', () => {
    const markup = renderShell()

    expect(markup).toContain('拾光工坊')
    expect(markup).toContain('回到拾光工坊首页')
  })

  it('mounts the control cluster in the top bar', () => {
    const markup = renderShell()

    // aria-haspopup="menu" 是 LanguageSwitcher 独有的指纹（账户菜单用的是 "true"）。
    expect(markup).toContain('aria-haspopup="menu"')
  })

  it('mounts the account menu wired to the signed-in user', () => {
    const markup = renderShell()

    expect(markup).toContain('晨辉')
  })

  it('hosts the routed page inside a main landmark', () => {
    const markup = renderShell(<div>__ROUTED_PAGE__</div>)

    expect(markup).toContain('<main')
    expect(markup).toContain('__ROUTED_PAGE__')
  })

  it('follows the interface language', async () => {
    const instance = await bootstrapI18n('en-US')
    const markup = renderToStaticMarkup(
      <I18nProvider instance={instance}>
        <ThemeModeProvider>
          <AppShellView user={ADMIN_USER} onNavigate={noop} onLogout={noop} />
        </ThemeModeProvider>
      </I18nProvider>,
    )

    expect(markup).toContain('Shiguang Studio')
    expect(markup).toContain('Back to Shiguang Studio home')
    expect(markup).not.toContain('拾光工坊')
  })
})
