/**
 * 语言的 DOM、存储与宿主对象副作用。
 *
 * 与 theme/themeModeDom.ts 同构：全部写成"接收依赖的纯函数"，而不是直接摸
 * window / document / localStorage / navigator。项目没有 jsdom，只有这样这些
 * 分支才能被单元测试覆盖，React 层也才能保持薄。
 */

import {
  LANGUAGE_STORAGE_KEY,
  getLanguageDescriptor,
  readStoredLanguage,
  resolveInitialLanguage,
} from './language'
import type { AttributeTarget, ReadableStorage, WritableStorage } from '@/utils/domContracts'
import type { AppLanguage } from './language'

/** 写到 <html> 上的属性名。 */
export const LANGUAGE_DOM_ATTRIBUTE = 'lang'

/**
 * navigator 的最小面：只取语言偏好，不引入整个 Navigator 类型。
 *
 * 两个字段都可选——旧浏览器与部分 WebView 只暴露 language，
 * 而极少数宿主两个都没有。
 */
export interface NavigatorLanguageSource {
  readonly languages?: readonly string[] | undefined
  readonly language?: string | undefined
}

/**
 * 把语言的 BCP-47 标记写到 <html lang>。
 *
 * 这个属性驱动屏幕阅读器的发音规则、浏览器的"是否翻译此页"提示与搜索引擎的
 * 语言判定，必须是合法 BCP-47 而不是内部语言码（两者当前恰好同形）。
 */
export function applyLanguageToElement(
  element: AttributeTarget | null,
  language: AppLanguage,
): void {
  element?.setAttribute(LANGUAGE_DOM_ATTRIBUTE, getLanguageDescriptor(language).bcp47)
}

/**
 * 文档标题取哪条译文。
 *
 * 复用产品名而不是另开一条 documentTitle：品牌名已经改过一轮（七个地方），
 * 多一个 key 就多一处会漏改的副本。index.html 里的静态 <title> 与它在事实源
 * 语言下的取值必须一致，这条由 languageDom.test.ts 钉住。
 */
export const DOCUMENT_TITLE_KEY = 'app.name'

/** 文档标题宿主的最小面：只用到 title 这一个可写属性。 */
export interface DocumentTitleTarget {
  title: string
}

/**
 * 把当前语言下的产品名写进 <title>。
 *
 * 与 <html lang> 同属"文档级的语言副作用"，因此归属在同一个模块、由同两处
 * 调用（main.tsx 引导阶段 + I18nProvider 的语言 effect）。
 *
 * title 允许为空：译文缺失时与其把标签页清空，不如留住 index.html 里的静态
 * 标题——那至少还是个认得出的产品名。
 */
export function applyDocumentTitle(
  doc: DocumentTitleTarget | null,
  title: string | null | undefined,
): void {
  if (!doc || !title) {
    return
  }

  doc.title = title
}

/**
 * 持久化用户的语言选择。
 *
 * Safari 隐私模式与配额耗尽都会抛异常；存不下偏好的代价只是下次加载回到
 * 浏览器语言，不该让用户点一下切换就把应用打崩。
 */
export function persistLanguage(storage: WritableStorage | null, language: AppLanguage): void {
  try {
    storage?.setItem(LANGUAGE_STORAGE_KEY, language)
  } catch {
    /* 忽略：下次加载回退到浏览器语言。 */
  }
}

/**
 * 读出浏览器的语言候选，按用户自己的排序。
 *
 * navigator.languages 是显式排过序的偏好列表，优先于单一的 navigator.language。
 * 返回副本：直接把宿主数组交出去，调用方一旦 push 就改到了浏览器对象上。
 */
export function readNavigatorLanguages(
  source: NavigatorLanguageSource | null | undefined,
): string[] {
  if (!source) {
    return []
  }

  const list = source.languages

  if (list && list.length > 0) {
    return [...list]
  }

  return source.language ? [source.language] : []
}

/**
 * 定出首帧语言：已持久化的选择 > 浏览器偏好。
 *
 * 兜底方向由 resolveInitialLanguage 负责，这里只把两个信号源按优先级拼起来：
 * "没有信号"回到 zh-CN，"有信号但不支持"回到 en-US——后者是海外用户第一眼
 * 看到英文而非满屏汉字的唯一保证。
 */
export function resolveBootLanguage(
  storage: ReadableStorage | null,
  navigatorLanguages: readonly string[],
): AppLanguage {
  return resolveInitialLanguage([readStoredLanguage(storage), ...navigatorLanguages])
}
