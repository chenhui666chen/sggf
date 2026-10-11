/**
 * 认证页共享外壳 AuthScreen 的骨架契约。
 *
 * 登录/注册/找回三页都是连接组件（redux 或 useNavigate），按项目约定不做静态单测；
 * 把三页重复的 chrome（整屏 token wash + 控件簇 + 居中卡片 + 字标/标题/副标题）抽成
 * 纯展示组件 AuthScreen——title / subtitle / children 全走 props，于是能用
 * renderToStaticMarkup 锁住骨架。各部件细节由各自测试负责（BrandWordmark /
 * ControlCluster），这里只验"它们被正确组装进了认证外壳"。
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'

import AuthScreen from '../AuthScreen'
import { I18nProvider, bootstrapI18n } from '@/i18n'
import { ThemeModeProvider } from '@/theme'

interface RenderOptions {
  readonly title?: ReactNode
  readonly subtitle?: ReactNode
  readonly children?: ReactNode
}

function renderScreen({ children = <div>__AUTH_FORM__</div>, ...rest }: RenderOptions = {}): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <ThemeModeProvider>
        <AuthScreen {...rest}>{children}</AuthScreen>
      </ThemeModeProvider>
    </I18nProvider>,
  )
}

describe('AuthScreen', () => {
  it('brands the card with the wordmark', () => {
    const markup = renderScreen()

    expect(markup).toContain('拾光工坊')
  })

  it('mounts the control cluster in the top corner', () => {
    const markup = renderScreen()

    // aria-haspopup="menu" 是 LanguageSwitcher 独有的指纹；ControlCluster 同时带主题切换。
    expect(markup).toContain('aria-haspopup="menu"')
  })

  it('renders the page heading as an h1 with its subtitle', () => {
    const markup = renderScreen({ title: '__TITLE__', subtitle: '__SUBTITLE__' })

    expect(markup).toContain('<h1')
    expect(markup).toContain('__TITLE__')
    expect(markup).toContain('__SUBTITLE__')
  })

  it('falls back to the wordmark as the h1 when no title is given', () => {
    const markup = renderScreen()

    // 登录页省略 title：字标本身承担 h1，保证每屏都有唯一主标题地标。
    expect(markup).toContain('<h1')
  })

  it('hosts the form body', () => {
    const markup = renderScreen({ children: <div>__AUTH_FORM__</div> })

    expect(markup).toContain('__AUTH_FORM__')
  })

  it('follows the interface language', async () => {
    const instance = await bootstrapI18n('en-US')
    const markup = renderToStaticMarkup(
      <I18nProvider instance={instance}>
        <ThemeModeProvider>
          <AuthScreen>
            <div>__AUTH_FORM__</div>
          </AuthScreen>
        </ThemeModeProvider>
      </I18nProvider>,
    )

    expect(markup).toContain('Shiguang Studio')
    expect(markup).not.toContain('拾光工坊')
  })
})
