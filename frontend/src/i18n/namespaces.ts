/**
 * i18n 命名空间注册表。
 *
 * 加一门语言或一个命名空间，都只需要改这里一处：新增 JSON、登记一行。
 * 注册表之外的代码只认 NamespaceEntry，不关心资源从哪个 chunk 来。
 *
 * 分包口径：
 * - zh-CN 是事实源，静态 import，随主包一起下发。任何时刻 t() 都有中文可用，
 *   因此首帧不需要 Suspense，也不可能渲染出裸 key。
 * - 其余语言用动态 import，Vite 会切成独立 chunk，只在用户真的切过去时下载。
 */

import { DEFAULT_LANGUAGE } from './language'
import zhCommon from './resources/zh-CN/common.json'
import type { AppLanguage } from './language'

/** 一份资源包的形状：命名空间下的 key 树。 */
export type ResourceBundle = Record<string, unknown>

/**
 * 懒加载器。解析结果必须已经是资源本体，而不是 module namespace——
 * 解包在各 loader 内部就地完成，调用方不必知道 Vite 的 JSON 包装细节。
 */
export type NamespaceLoader = () => Promise<ResourceBundle>

export interface NamespaceEntry {
  readonly name: string
  /** 事实源语言的资源，内联在主包里。 */
  readonly source: ResourceBundle
  /** 其余语言的懒加载器；缺省即表示该语言尚未翻译。 */
  readonly loaders: Readonly<Partial<Record<AppLanguage, NamespaceLoader>>>
}

/** 默认命名空间：全站通用文案（动作、状态、外观、语言）。 */
export const DEFAULT_NAMESPACE = 'common'

export const NAMESPACES: readonly NamespaceEntry[] = [
  {
    name: 'common',
    source: zhCommon,
    loaders: {
      // Vite 把动态 import 的 JSON 包成 { default: ... }；不解包的话
      // addResourceBundle 会把 default 这层当成资源，所有 key 都多一级前缀。
      'en-US': async () => (await import('./resources/en-US/common.json')).default,
    },
  },
]

/** 由 NAMESPACES 派生，避免两处清单各写一份而悄悄漂移。 */
export const NAMESPACE_NAMES: readonly string[] = NAMESPACES.map((entry) => entry.name)

/**
 * 取某语言下某命名空间的资源。
 *
 * 事实源语言直接返回内联对象（同一个引用，不产生任何异步加载），包成 Promise
 * 只为统一签名。其余语言走 loader；没登记 loader 时返回 null，表示"这门语言
 * 还没有翻译"，由调用方决定是否回退。
 *
 * loader 抛错时刻意不吞：chunk 加载失败如果被静默降级成中文，线上就只剩下
 * "某些用户某些时候看到中文"这种无从复现的现象。降级策略属于调用方。
 */
export async function loadNamespace(
  entry: NamespaceEntry,
  language: AppLanguage,
): Promise<ResourceBundle | null> {
  if (language === DEFAULT_LANGUAGE) {
    return entry.source
  }

  const loader = entry.loaders[language]

  if (!loader) {
    return null
  }

  return loader()
}
