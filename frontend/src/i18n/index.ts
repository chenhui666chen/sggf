/**
 * i18n 的公共出口。
 *
 * 只导出组件与引导阶段真正会用到的东西。createI18n / switchLanguage / loadNamespace
 * 这些内部机制刻意不转出——业务代码绕过 Provider 直接摸 i18next 实例，是"某些页面
 * 语言不跟着切"这类怪现象的常见成因。
 */

export { I18nProvider, useAppLanguage } from './I18nProvider'
export type { AppLanguageContextValue, I18nProviderProps } from './I18nProvider'

export { useFormats } from './useFormats'

/** 只有 main.tsx 在挂载前调用一次。 */
export { bootstrapI18n } from './client'

export {
  DEFAULT_LANGUAGE,
  FALLBACK_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
  SUPPORTED_LANGUAGE_CODES,
  getLanguageDescriptor,
  isAppLanguage,
  matchSupportedLanguage,
} from './language'
export type { AppLanguage, LanguageDescriptor } from './language'

/**
 * 引导阶段用：读浏览器语言、定首帧语言，并把结果同步写进 <html lang> 与 <title>。
 * persistLanguage 刻意不转出——写偏好只应该发生在用户主动切换时，
 * 而那是 I18nProvider 的职责。
 */
export {
  DOCUMENT_TITLE_KEY,
  LANGUAGE_DOM_ATTRIBUTE,
  applyDocumentTitle,
  applyLanguageToElement,
  readNavigatorLanguages,
  resolveBootLanguage,
} from './languageDom'
export type { DocumentTitleTarget, NavigatorLanguageSource } from './languageDom'

export { DEFAULT_NAMESPACE, NAMESPACE_NAMES } from './namespaces'

// format.ts 的函数不从这里转出：要"跟着当前语言"的版本请用 useFormats；
// 确实需要显式指定 locale 的场合（构建脚本、测试）直接从 './format' 导入。
// EMPTY_PLACEHOLDER 是纯常量，与语言无关，业务表格里的空值占位都用它。
export { EMPTY_PLACEHOLDER } from './format'
export type { DateLike, DateParts } from './format'
