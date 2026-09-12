/**
 * 语言副作用层的契约。
 *
 * 与 themeModeDom 同构：所有 DOM / Storage / navigator 访问都写成"接收依赖的
 * 纯函数"，项目没有 jsdom，只有这样才能被覆盖。
 *
 * 这里最要紧的一条是 resolveBootLanguage 的兜底方向——法语浏览器必须拿到英文
 * 而不是中文，反了的话海外用户第一眼就是满屏汉字。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
  LANGUAGE_STORAGE_KEY,
  DEFAULT_LANGUAGE,
  FALLBACK_LANGUAGE,
  SUPPORTED_LANGUAGES,
  getLanguageDescriptor,
} from '../language'
import {
  DOCUMENT_TITLE_KEY,
  LANGUAGE_DOM_ATTRIBUTE,
  applyDocumentTitle,
  applyLanguageToElement,
  persistLanguage,
  readNavigatorLanguages,
  resolveBootLanguage,
} from '../languageDom'
import type { DocumentTitleTarget, NavigatorLanguageSource } from '../languageDom'

/**
 * 元素替身。
 *
 * 同时记调用序列与最终属性表：setAttribute 在真实 DOM 上是覆盖语义，
 * 只留调用历史会让"写两次取哪次"这件事失真。
 */
function createElementStub() {
  const calls: Array<[string, string]> = []
  const attributes = new Map<string, string>()

  return {
    element: {
      setAttribute(name: string, value: string) {
        calls.push([name, value])
        attributes.set(name, value)
      },
    },
    calls,
    valueOf(name: string) {
      return attributes.get(name) ?? null
    },
  }
}

/** 可编程的 storage 替身。 */
function createStorageStub(initial?: Record<string, string>, options?: { throwOnWrite?: boolean }) {
  const store = new Map(Object.entries(initial ?? {}))

  return {
    storage: {
      getItem(key: string) {
        return store.get(key) ?? null
      },
      setItem(key: string, value: string) {
        if (options?.throwOnWrite) {
          throw new Error('QuotaExceededError')
        }
        store.set(key, value)
      },
    },
    store,
  }
}

describe('applyLanguageToElement', () => {
  it('writes the lang attribute', () => {
    const stub = createElementStub()

    applyLanguageToElement(stub.element, 'en-US')

    expect(stub.calls).toEqual([[LANGUAGE_DOM_ATTRIBUTE, 'en-US']])
  })

  it('writes the BCP-47 tag of every supported language, not the internal code', () => {
    // 两者当前恰好同形，但 <html lang> 必须是合法 BCP-47：
    // 屏幕阅读器、浏览器翻译提示与搜索引擎都只认这个。
    for (const descriptor of SUPPORTED_LANGUAGES) {
      const stub = createElementStub()

      applyLanguageToElement(stub.element, descriptor.code)

      expect(stub.valueOf(LANGUAGE_DOM_ATTRIBUTE), descriptor.code).toBe(descriptor.bcp47)
    }
  })

  it('overwrites a previous language instead of appending', () => {
    const stub = createElementStub()

    applyLanguageToElement(stub.element, 'zh-CN')
    applyLanguageToElement(stub.element, 'en-US')

    expect(stub.valueOf(LANGUAGE_DOM_ATTRIBUTE)).toBe('en-US')
  })

  it('tolerates a missing element so SSR and detached trees do not throw', () => {
    expect(() => applyLanguageToElement(null, 'en-US')).not.toThrow()
  })
})

describe('applyDocumentTitle', () => {
  it('writes the product name into the tab', () => {
    const doc: DocumentTitleTarget = { title: '拾光工坊' }

    applyDocumentTitle(doc, 'Shiguang Studio')

    expect(doc.title).toBe('Shiguang Studio')
  })

  it('tolerates a missing document so SSR and detached trees do not throw', () => {
    expect(() => applyDocumentTitle(null, 'Shiguang Studio')).not.toThrow()
  })

  it('keeps the existing title rather than blanking the tab', () => {
    // 标题是标签页上唯一看得见的产品名：这条 key 缺失时 t() 给的是空值，
    // 与其把标签页清空，不如留住 index.html 里的静态标题。
    for (const missing of ['', null, undefined]) {
      const doc: DocumentTitleTarget = { title: '拾光工坊' }

      applyDocumentTitle(doc, missing)

      expect(doc.title, String(missing)).toBe('拾光工坊')
    }
  })
})

describe('persistLanguage', () => {
  it('stores the choice under the shared key', () => {
    const stub = createStorageStub()

    persistLanguage(stub.storage, 'en-US')

    expect(stub.store.get(LANGUAGE_STORAGE_KEY)).toBe('en-US')
  })

  it('replaces an earlier choice', () => {
    const stub = createStorageStub({ [LANGUAGE_STORAGE_KEY]: 'en-US' })

    persistLanguage(stub.storage, 'zh-CN')

    expect(stub.store.get(LANGUAGE_STORAGE_KEY)).toBe('zh-CN')
  })

  it('tolerates a missing storage', () => {
    expect(() => persistLanguage(null, 'en-US')).not.toThrow()
  })

  it('swallows write failures rather than crashing the switch', () => {
    // Safari 隐私模式与配额耗尽都会抛。存不下偏好的代价只是下次回到浏览器语言，
    // 不该让用户点一下切换就把应用打崩。
    const stub = createStorageStub({}, { throwOnWrite: true })

    expect(() => persistLanguage(stub.storage, 'en-US')).not.toThrow()
  })
})

describe('readNavigatorLanguages', () => {
  it('prefers the ordered languages list', () => {
    const source: NavigatorLanguageSource = { languages: ['fr-FR', 'en-GB'], language: 'fr-FR' }

    expect(readNavigatorLanguages(source)).toEqual(['fr-FR', 'en-GB'])
  })

  it('falls back to the single language field', () => {
    // 旧浏览器与部分 WebView 只暴露 navigator.language。
    expect(readNavigatorLanguages({ language: 'ja-JP' })).toEqual(['ja-JP'])
  })

  it('ignores an empty languages list and falls back', () => {
    expect(readNavigatorLanguages({ languages: [], language: 'de-DE' })).toEqual(['de-DE'])
  })

  it('returns an empty list when there is no signal at all', () => {
    expect(readNavigatorLanguages(null)).toEqual([])
    expect(readNavigatorLanguages({})).toEqual([])
    expect(readNavigatorLanguages({ language: '' })).toEqual([])
  })

  it('hands back a copy so callers cannot mutate the host object', () => {
    const languages = ['en-US']
    const source: NavigatorLanguageSource = { languages }

    const result = readNavigatorLanguages(source)
    result.push('zh-CN')

    expect(languages).toEqual(['en-US'])
  })
})

describe('resolveBootLanguage', () => {
  it('honours a persisted choice over the browser preference', () => {
    const stub = createStorageStub({ [LANGUAGE_STORAGE_KEY]: 'zh-CN' })

    expect(resolveBootLanguage(stub.storage, ['en-US'])).toBe('zh-CN')
  })

  it('uses the browser preference when nothing is persisted', () => {
    expect(resolveBootLanguage(null, ['en-GB'])).toBe('en-US')
  })

  it('walks down the browser list until one is supported', () => {
    // navigator.languages 是用户自己排的顺序，第一个不支持就该看第二个。
    expect(resolveBootLanguage(null, ['fr-FR', 'de-DE', 'zh-TW'])).toBe('zh-CN')
  })

  it('routes Traditional Chinese to Simplified until zh-TW resources exist', () => {
    expect(resolveBootLanguage(null, ['zh-TW'])).toBe('zh-CN')
    expect(resolveBootLanguage(null, ['zh-HK'])).toBe('zh-CN')
  })

  it('falls back to the international language when the browser speaks something unsupported', () => {
    // 最关键的一条：法语/日语用户看到英文，而不是满屏汉字。
    expect(resolveBootLanguage(null, ['fr-FR'])).toBe(FALLBACK_LANGUAGE)
    expect(resolveBootLanguage(null, ['ja-JP'])).toBe(FALLBACK_LANGUAGE)
  })

  it('falls back to the source language when there is no signal at all', () => {
    expect(resolveBootLanguage(null, [])).toBe(DEFAULT_LANGUAGE)
  })

  it('ignores a persisted value that is not a supported language', () => {
    // 手改 localStorage 或旧版本遗留的脏值不该把应用带进未定义状态。
    const stub = createStorageStub({ [LANGUAGE_STORAGE_KEY]: 'fr' })

    expect(resolveBootLanguage(stub.storage, ['en-US'])).toBe('en-US')
  })

  it('tolerates a storage that throws on read', () => {
    const throwing = {
      getItem() {
        throw new Error('SecurityError')
      },
    }

    expect(resolveBootLanguage(throwing, ['en-US'])).toBe('en-US')
  })
})

// 源码断言统一按 LF 归一化，避免 Windows 检出 CRLF 行尾导致裸 \n 匹配失败
const readSource = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r\n/g, '\n')

/**
 * 引导接线的守护测试。
 *
 * applyLanguageToElement 自身的行为上面已经覆盖完，但它还得在 main.tsx 里被按
 * 正确的顺序调用才有效果。这个顺序跑不出单元测试——项目没有 jsdom，而
 * main.tsx 一被导入就 createRoot——所以按源码契约钉住，口径与
 * theme/__tests__/fonts.test.ts 一致。
 */
describe('boot wiring', () => {
  const mainSource = readSource('../../main.tsx')
  // 从 mount 起截取，把 import 块排除在外：bootstrapI18n 在那里也出现一次，
  // 拿全文比位置会比出假阳性。
  const mountBody = mainSource.slice(mainSource.indexOf('async function mount()'))

  it('is pulled in by the application entry', () => {
    expect(mountBody).toContain('applyLanguageToElement(document.documentElement, language)')
  })

  it('applies lang only after the resources have arrived', () => {
    // 顺序就是这条测试的全部意义：先写 lang 再等 chunk 的话，chunk 拉不到时
    // 会留下 <html lang="en-US"> 配一屏中文。
    expect(mountBody.indexOf('bootstrapI18n')).toBeLessThan(
      mountBody.indexOf('applyLanguageToElement'),
    )
  })

  it('applies lang before the first render rather than in a passive effect', () => {
    // I18nProvider 里那个 useEffect 跑在首次绘制之后，只靠它的话英文用户会有
    // 一帧「lang=zh-CN 配英文内容」，屏幕阅读器会按中文规则去念英文。
    expect(mountBody.indexOf('renderApp(instance)')).toBeGreaterThan(-1)
    expect(mountBody.indexOf('applyLanguageToElement')).toBeLessThan(
      mountBody.indexOf('renderApp(instance)'),
    )
  })

  it('applies the document title before the first render as well', () => {
    // 标签页标题是英文用户在首屏之外唯一看得见的产品名，只靠 I18nProvider 的
    // effect 同步，上次选了英文的人会先看到一下「拾光工坊」再跳成英文。
    expect(mountBody.indexOf('applyDocumentTitle')).toBeGreaterThan(-1)
    expect(mountBody.indexOf('applyDocumentTitle')).toBeLessThan(
      mountBody.indexOf('renderApp(instance)'),
    )
  })

  it('keeps the static lang in index.html aligned with the source language', () => {
    // 降级路径（chunk 拉不到）刻意不写 lang，靠的就是 index.html 里这个静态值，
    // 而降级实例建的正是事实源语言。DEFAULT_LANGUAGE 改了却漏改这里，降级时
    // 就会留下一个与内容不符的 lang——和 theme 的 BOOT_COLORS 是同一类漂移。
    const html = readSource('../../../index.html')

    expect(html).toContain(`<html lang="${getLanguageDescriptor(DEFAULT_LANGUAGE).bcp47}"`)
  })

  it('resolves the title key to the static title in index.html', () => {
    // 静态标题是降级路径（chunk 拉不到）下用户看到的那个，它必须与
    // DOCUMENT_TITLE_KEY 在事实源语言里解析出的值一致：品牌名改过一轮，
    // 两边各写一份字面量一定会漂移。按 key 查资源而不是直接读 app.name，
    // 这样 key 本身改了也会红。
    const resources: unknown = JSON.parse(readSource('../resources/zh-CN/common.json'))
    const resolved = DOCUMENT_TITLE_KEY.split('.').reduce<unknown>(
      (node: unknown, part: string) => (node as Record<string, unknown> | null | undefined)?.[part],
      resources,
    )

    expect(readSource('../../../index.html')).toContain(`<title>${String(resolved)}</title>`)
  })
})
