/**
 * i18n 的 React 层。
 *
 * 职责：持有 i18next 实例、把当前语言写到 `<html lang>` 与 `<title>`、持久化用户的选择，
 * 并通过 context 把 language / setLanguage 交给组件树。译文本身由
 * react-i18next 的 I18nextProvider 注入，业务组件直接用 useTranslation。
 *
 * 与 ThemeModeProvider 同构：副作用全部下沉到 languageDom.ts 的纯函数，
 * 这一层只做编排，因此它薄到几乎不需要独立测试。
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { I18nextProvider } from 'react-i18next'

import { createI18n, switchLanguage } from './client'
import { DEFAULT_LANGUAGE, isAppLanguage } from './language'
import {
  DOCUMENT_TITLE_KEY,
  applyDocumentTitle,
  applyLanguageToElement,
  persistLanguage,
} from './languageDom'
import type { ReactNode } from 'react'
import type { AppLanguage } from './language'
import type { i18n as I18nInstance } from 'i18next'

export interface AppLanguageContextValue {
  /** 当前生效的语言。 */
  readonly language: AppLanguage
  /**
   * 切换语言。
   *
   * 返回 promise 是因为非事实源语言的资源要现拉 chunk，调用方需要 catch：
   * 加载失败时界面停在原语言，而不是崩掉或退化成裸 key。
   */
  readonly setLanguage: (language: AppLanguage) => Promise<void>
}

const AppLanguageContext = createContext<AppLanguageContextValue | null>(null)

export function useAppLanguage(): AppLanguageContextValue {
  const value = useContext(AppLanguageContext)

  if (!value) {
    // 静默返回默认语言会让"忘了包 Provider"变成只在某些页面出现的怪现象。
    throw new Error('useAppLanguage 必须在 <I18nProvider> 内部调用')
  }

  return value
}

export interface I18nProviderProps {
  children: ReactNode
  /**
   * 预先引导好的实例。
   *
   * 缺省时这里自建一个事实源语言的实例——资源齐备，首帧既不闪也不裸 key。
   * 但要让用户上次选的语言在首帧就生效，必须在 render 之前 await
   * bootstrapI18n()（见 main.tsx）：en-US 的资源是懒加载 chunk，等它到了再挂载，
   * 才不会先闪一帧中文。语言检测因此属于引导阶段，不在这里做。
   */
  readonly instance?: I18nInstance
}

/**
 * 取 localStorage。
 *
 * try 包的是**属性访问本身**而不只是读写：应用被嵌进跨域 iframe、或浏览器把
 * 第三方存储整个禁掉时，`window.localStorage` 这个 getter 就会抛 SecurityError，
 * 而 persistLanguage / readStoredLanguage 里的 try 在它之后，兜不住。
 */
function getLocalStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    return window.localStorage
  } catch {
    return null
  }
}

function getDocumentElement(): HTMLElement | null {
  return typeof document === 'undefined' ? null : document.documentElement
}

function getDocument(): Document | null {
  return typeof document === 'undefined' ? null : document
}

/** instance.language 在 i18next 里是宽泛的 string，收窄回受支持语言。 */
function readInstanceLanguage(instance: I18nInstance): AppLanguage {
  return isAppLanguage(instance.language) ? instance.language : DEFAULT_LANGUAGE
}

export function I18nProvider({ children, instance: provided }: I18nProviderProps) {
  // 惰性初始化：实例只在首次渲染时确定一次。外部传了就用外部的，
  // 这样引导阶段拉齐的资源不会被这里重建的实例丢掉。
  const [instance] = useState<I18nInstance>(() => provided ?? createI18n())
  const [language, setLanguageState] = useState<AppLanguage>(() => readInstanceLanguage(instance))

  useEffect(() => {
    // 驱动屏幕阅读器的发音规则、浏览器的"是否翻译此页"提示与搜索引擎语言判定。
    applyLanguageToElement(getDocumentElement(), language)
    // 首帧的标题已由引导阶段在 render 前写过（main.tsx），这里管的是会话中
    // 切换语言：否则标签页会停在上一门语言的产品名上。
    applyDocumentTitle(getDocument(), instance.t(DOCUMENT_TITLE_KEY))
  }, [language, instance])

  const setLanguage = useCallback(
    async (next: AppLanguage) => {
      // 先持久化再切换：万一切换失败（chunk 拉不到），用户的选择也已经记下，
      // 下次加载会重试，而不是每次都悄悄回到浏览器语言。
      persistLanguage(getLocalStorage(), next)

      await switchLanguage(instance, next)
      setLanguageState(next)
    },
    [instance],
  )

  const value = useMemo<AppLanguageContextValue>(
    () => ({ language, setLanguage }),
    [language, setLanguage],
  )

  return (
    <AppLanguageContext.Provider value={value}>
      <I18nextProvider i18n={instance}>{children}</I18nextProvider>
    </AppLanguageContext.Provider>
  )
}
