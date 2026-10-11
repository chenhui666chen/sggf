/**
 * I18nProvider 的渲染契约测试。
 *
 * 项目用 renderToStaticMarkup 而非 jsdom，因此 useEffect 不会执行——写 <html lang>
 * 与持久化这两条副作用由 languageDom.test.ts 覆盖，这里验的是另一半：
 * Provider 在没有 window/navigator 时不崩、首帧同步拿到中文（证明资源真的内联了、
 * I18nextProvider 真的接上了）、以及 hook 在 Provider 外会 fail fast。
 */

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createInstance } from 'i18next'
import { useTranslation } from 'react-i18next'

import { I18nProvider, useAppLanguage } from '../I18nProvider'
import { createI18n } from '../client'
import { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGE_CODES } from '../language'

function LanguageProbe() {
  const { language } = useAppLanguage()

  return <span data-language={language}>probe</span>
}

function SwitcherProbe() {
  const { setLanguage } = useAppLanguage()

  return <span data-can-switch={typeof setLanguage === 'function'}>probe</span>
}

function TranslationProbe() {
  const { t } = useTranslation()

  return (
    <span
      data-app-name={t('app.name')}
      data-save={t('action.save')}
      data-aria={t('theme.toggleAria', { mode: '深色' })}
      data-escape={t('theme.toggleAria', { mode: '<b>' })}
    >
      translated
    </span>
  )
}

/** 只渲染 t() 结果，模拟真实业务组件的用法。 */
function ButtonLabelProbe() {
  const { t } = useTranslation()

  return <button type="button">{t('action.submit')}</button>
}

describe('I18nProvider', () => {
  it('renders its children', () => {
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <span>child content</span>
      </I18nProvider>,
    )

    expect(markup).toContain('child content')
  })

  it('defaults to the source language when no instance is given', () => {
    // 缺省路径不做浏览器检测：它建的是事实源语言的实例，资源齐备，
    // 因此既不闪也不裸 key。语言检测属于引导阶段（main.tsx）的职责。
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    )

    expect(markup).toContain(`data-language="${DEFAULT_LANGUAGE}"`)
  })

  it('reflects the language of a pre-bootstrapped instance', () => {
    // main.tsx 的正常路径：先 await bootstrapI18n 把资源拉齐，再挂载。
    const markup = renderToStaticMarkup(
      <I18nProvider instance={createI18n({ language: 'en-US' })}>
        <LanguageProbe />
      </I18nProvider>,
    )

    expect(markup).toContain('data-language="en-US"')
  })

  it('narrows back to the source language when handed an instance in an unsupported one', () => {
    // instance.language 在 i18next 里是宽泛的 string，外部完全可能递进来一个
    // 我们没登记的语言；不校验就会让它渗进 <html lang> 与 Intl 调用。
    const stray = createInstance()
    void stray.init({ lng: 'fr', resources: {} })

    const markup = renderToStaticMarkup(
      <I18nProvider instance={stray}>
        <LanguageProbe />
      </I18nProvider>,
    )

    expect(markup).toContain(`data-language="${DEFAULT_LANGUAGE}"`)
  })

  it('exposes a language that is actually supported', () => {
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    )

    const rendered = markup.match(/data-language="([^"]+)"/)?.[1]

    expect(rendered).toBeDefined()
    expect(SUPPORTED_LANGUAGE_CODES).toContain(rendered)
  })

  it('resolves translations synchronously on the very first render', () => {
    // 这是整个方案的地基：能同步出中文，说明 zh-CN 资源确实内联在主包里，
    // 应用不需要 Suspense，也不会有一帧是裸 key。
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <TranslationProbe />
      </I18nProvider>,
    )

    expect(markup).toContain('data-app-name="拾光工坊"')
    expect(markup).toContain('data-save="保存"')
  })

  it('escapes interpolated values exactly once, on the React side', () => {
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <TranslationProbe />
      </I18nProvider>,
    )

    expect(markup).toContain('data-aria="切换外观，当前深色"')
    // escapeValue:false → i18next 不动，只由 React 转一次 → &lt;b&gt;。
    // 若 escapeValue 是默认的 true，这里会看到双重转义的 &amp;lt;b&amp;gt;。
    expect(markup).toContain('data-escape="切换外观，当前&lt;b&gt;"')
    expect(markup).not.toContain('&amp;lt;')
  })

  it('never renders a bare key for a registered namespace', () => {
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <ButtonLabelProbe />
      </I18nProvider>,
    )

    expect(markup).toContain('提交')
    expect(markup).not.toContain('action.submit')
  })

  it('hands out a callable setLanguage', () => {
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <SwitcherProbe />
      </I18nProvider>,
    )

    expect(markup).toContain('data-can-switch="true"')
  })

  it('fails fast when useAppLanguage is called outside the provider', () => {
    // 静默返回默认语言会让"忘了包 Provider"变成一个只在某些页面出现的怪现象。
    expect(() => renderToStaticMarkup(<LanguageProbe />)).toThrow('I18nProvider')
  })
})
