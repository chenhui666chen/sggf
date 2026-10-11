/**
 * i18next 实例构造与语言切换的契约。
 *
 * 这里最关键的一条是"同步可用"：init 传了 resources 时 i18next v26 走同步分支，
 * 因此首帧 t() 就有中文，既不需要 Suspense 也不可能渲染出裸 key。整个应用
 * 的挂载路径都建立在这个前提上，一旦它变成异步，全站会同时退化。
 *
 * 第二条是切换顺序：先补资源再 changeLanguage。反过来的话，已挂载的组件会用
 * 新语言重渲染一帧，而那时资源还没到，整屏都是 key。
 */
import { describe, expect, it } from 'vitest'

import { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGE_CODES } from '../language'
import { NAMESPACE_NAMES } from '../namespaces'
import { createI18n, bootstrapI18n, switchLanguage } from '../client'

describe('createI18n', () => {
  it('is usable synchronously, before any await', () => {
    const instance = createI18n()

    expect(instance.isInitialized).toBe(true)
    expect(instance.t('action.save')).toBe('保存')
  })

  it('starts in the source language when no option is given', () => {
    expect(createI18n().language).toBe(DEFAULT_LANGUAGE)
  })

  it('honours an explicit language option', () => {
    expect(createI18n({ language: 'en-US' }).language).toBe('en-US')
  })

  it('resolves keys without a namespace prefix', () => {
    expect(createI18n().t('app.name')).toBe('拾光工坊')
  })

  it('inlines every namespace of the source language', () => {
    const instance = createI18n()

    for (const name of NAMESPACE_NAMES) {
      expect(instance.hasResourceBundle(DEFAULT_LANGUAGE, name), name).toBe(true)
    }
  })

  it('interpolates without HTML-escaping, because React already escapes', () => {
    // escapeValue 默认 true 会把 < > & 转成实体；React 再转一次，
    // 用户就直接看见 &amp;lt;b&amp;gt; 这种东西。
    const instance = createI18n()

    expect(instance.t('theme.toggleAria', { mode: '深色' })).toBe('切换外观，当前深色')
    expect(instance.t('theme.toggleAria', { mode: '<b>' })).toBe('切换外观，当前<b>')
  })

  it('renders a missing key as the key itself rather than as nothing', () => {
    // returnNull:false。裸 key 可以在代码库里直接搜到，空白只能靠肉眼找。
    expect(createI18n().t('nope.notThere')).toBe('nope.notThere')
  })

  it('declares every supported language so switching never warns', () => {
    const declared = createI18n().options.supportedLngs as readonly string[]

    for (const code of SUPPORTED_LANGUAGE_CODES) {
      expect(declared, code).toContain(code)
    }

    // i18next 会自己追加 'cimode'（把 key 原样输出的调试模式），这是库行为
    // 而不是漏配；除此之外不该出现任何我们没登记的语言。
    expect(declared.filter((code) => code !== 'cimode')).toEqual([...SUPPORTED_LANGUAGE_CODES])
  })

  it('declares a fallback chain that always contains the source language', () => {
    // zh-CN 是唯一保证 key 齐全的语言，任何链里没有它，缺翻译就会渲染成空白。
    for (const language of SUPPORTED_LANGUAGE_CODES) {
      const chain = createI18n({ language }).options.fallbackLng as readonly string[]

      expect(chain, language).toContain(DEFAULT_LANGUAGE)
    }
  })

  it('builds isolated instances so switching one does not touch the other', async () => {
    // 走 createInstance 而不是全局单例：单例一旦被某处初始化过，
    // 之后所有拿到它的代码都在共享脏状态，失败原因会指向毫不相关的地方。
    const first = createI18n()
    const second = createI18n()

    await switchLanguage(first, 'en-US')

    expect(first.t('app.name')).toBe('Shiguang Studio')
    expect(second.t('app.name')).toBe('拾光工坊')
  })
})

describe('bootstrapI18n', () => {
  it('resolves with an instance whose target language is fully loaded', async () => {
    const instance = await bootstrapI18n('en-US')

    expect(instance.language).toBe('en-US')
    expect(instance.t('app.name')).toBe('Shiguang Studio')
  })

  it('is a no-op for the source language, whose resources are already inlined', async () => {
    const instance = await bootstrapI18n(DEFAULT_LANGUAGE)

    expect(instance.language).toBe(DEFAULT_LANGUAGE)
    expect(instance.t('app.name')).toBe('拾光工坊')
  })

  it('is what keeps a returning English user from seeing one frame of Chinese', async () => {
    // 这条钉住了 bootstrapI18n 存在的理由。createI18n 是同步的、只带 zh-CN，
    // 所以少了这一步，上次选了英文的用户首屏会先看到中文再跳成英文。
    const bare = createI18n({ language: 'en-US' })
    const booted = await bootstrapI18n('en-US')

    expect(bare.t('app.name')).toBe('拾光工坊')
    expect(booted.t('app.name')).toBe('Shiguang Studio')
  })

  it('hands back a fresh instance each call', async () => {
    expect(await bootstrapI18n('en-US')).not.toBe(await bootstrapI18n('en-US'))
  })
})

describe('switchLanguage', () => {
  it('makes the target language resolve once it settles', async () => {
    const instance = createI18n()

    await switchLanguage(instance, 'en-US')

    expect(instance.language).toBe('en-US')
    expect(instance.t('app.name')).toBe('Shiguang Studio')
    expect(instance.t('action.retry')).toBe('Try again')
  })

  it('registers every namespace for the target language', async () => {
    const instance = createI18n()

    await switchLanguage(instance, 'en-US')

    for (const name of NAMESPACE_NAMES) {
      expect(instance.hasResourceBundle('en-US', name), name).toBe(true)
    }
  })

  it('switches back to the source language', async () => {
    const instance = createI18n()

    await switchLanguage(instance, 'en-US')
    await switchLanguage(instance, DEFAULT_LANGUAGE)

    expect(instance.language).toBe(DEFAULT_LANGUAGE)
    expect(instance.t('app.name')).toBe('拾光工坊')
  })

  it('loads each lazy bundle at most once', async () => {
    // 来回切语言是很常见的操作，每次都重新拉 chunk 是白花的网络与解析成本。
    const instance = createI18n()

    await switchLanguage(instance, 'en-US')
    const first = instance.getResourceBundle('en-US', 'common')

    await switchLanguage(instance, 'en-US')
    const second = instance.getResourceBundle('en-US', 'common')

    expect(second).toBe(first)
  })

  it('leaves the source bundle in place so untranslated keys still fall back', async () => {
    const instance = createI18n()

    await switchLanguage(instance, 'en-US')

    expect(instance.hasResourceBundle(DEFAULT_LANGUAGE, 'common')).toBe(true)
    expect(instance.t('action.save', { lng: DEFAULT_LANGUAGE })).toBe('保存')
  })
})
