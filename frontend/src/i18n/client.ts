/**
 * i18next 实例的构造与语言切换。
 *
 * 不用全局单例：createInstance 出来的实例彼此隔离，测试之间不会互相污染，
 * 也让"同时存在两棵不同语言的树"成为可能。React 侧由 I18nProvider 经
 * I18nextProvider 注入，完全不依赖 i18next 的全局状态。
 *
 * 刻意不用 i18next-browser-languagedetector：language.ts 的检测语义比它精确
 * （区分"没有信号"与"有信号但不支持"、把 zh-TW 归一到 zh-CN），插件表达不了，
 * 装上只会变成又一个没人调用的依赖。
 */

import { createInstance } from 'i18next'
import { initReactI18next } from 'react-i18next'

import { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGE_CODES, resolveFallbackChain } from './language'
import { DEFAULT_NAMESPACE, NAMESPACES, NAMESPACE_NAMES, loadNamespace } from './namespaces'
import type { AppLanguage } from './language'
import type { ResourceBundle } from './namespaces'
import type { i18n as I18nInstance } from 'i18next'

export interface CreateI18nOptions {
  /** 初始语言；缺省用事实源语言。 */
  readonly language?: AppLanguage
}

/** 把注册表里事实源语言的内联资源摊成 i18next 要的 resources 形状。 */
function buildSourceResources(): Record<string, Record<string, ResourceBundle>> {
  const namespaces: Record<string, ResourceBundle> = {}

  for (const entry of NAMESPACES) {
    namespaces[entry.name] = entry.source
  }

  return { [DEFAULT_LANGUAGE]: namespaces }
}

/**
 * 构造一个**已经初始化完成**的实例。
 *
 * i18next v26 的 init 在拿到 resources 时走同步分支（runtime 里是
 * `if (this.options.resources || !this.options.initAsync) load()`），所以本函数
 * 返回时 t() 就已可用——这是全站不需要 Suspense、也不可能首帧渲染裸 key 的原因。
 */
export function createI18n(options: CreateI18nOptions = {}): I18nInstance {
  const language = options.language ?? DEFAULT_LANGUAGE
  const instance = createInstance()

  instance.use(initReactI18next)

  const pending = instance.init({
    lng: language,
    fallbackLng: resolveFallbackChain(language),
    supportedLngs: [...SUPPORTED_LANGUAGE_CODES],
    ns: [...NAMESPACE_NAMES],
    defaultNS: DEFAULT_NAMESPACE,
    resources: buildSourceResources(),
    // 资源已内联，显式关掉异步分支。v26 用它取代了旧版的 initImmediate，
    // 后者在类型与运行时里都已不存在。
    initAsync: false,
    // 只带了事实源语言，其余语言由 switchLanguage 按需补；不开这个开关
    // i18next 会因为"声明支持却没有资源"而告警。
    partialBundledLanguages: true,
    // 缺 key 时渲染出可搜索的裸 key，而不是让 null 渗进 React 树。
    returnNull: false,
    interpolation: {
      // React 已经转义过一遍，这里再转用户就会看见 &amp;lt;b&amp;gt;。
      escapeValue: false,
    },
  })

  // 同步分支下这个 promise 已经 settle。挂 catch 只是防止将来配置出错时
  // 变成 unhandled rejection 掀掉整个页面——那时 t() 会退回裸 key，可诊断。
  pending.catch(() => {
    /* 资源是内联的，走到这里说明 init 配置本身有问题。 */
  })

  return instance
}

/**
 * 建实例并把目标语言的资源拉齐。
 *
 * createI18n 是同步的、只带事实源语言，所以直接拿它渲染 en-US 会先看到一帧中文
 * 再跳成英文。挂载前 await 这一步，首屏就是用户上次选的那个语言。
 *
 * 只有引导阶段需要它：运行时切换走 switchLanguage——那时界面已经在了，
 * 过渡状态由切换按钮自己表达，不需要阻塞整棵树。
 */
export async function bootstrapI18n(language: AppLanguage): Promise<I18nInstance> {
  const instance = createI18n({ language })

  await switchLanguage(instance, language)

  return instance
}

/**
 * 切换语言：先补齐资源，最后才 changeLanguage。
 *
 * 顺序不能反——先切语言会让已挂载的组件立刻用新语言重渲染一帧，
 * 而那时 chunk 还没到，整屏都是裸 key。
 *
 * 已注册过的命名空间直接跳过：来回切语言是常见操作，没必要每次都重新拉
 * chunk、重新深合并一遍。
 *
 * loadNamespace 抛错时不吞：chunk 404 若被静默降级成中文，线上就只剩
 * "某些用户某些时候看到中文"这种无从复现的现象。由调用方决定怎么提示。
 */
export async function switchLanguage(
  instance: I18nInstance,
  language: AppLanguage,
): Promise<void> {
  for (const entry of NAMESPACES) {
    if (instance.hasResourceBundle(language, entry.name)) {
      continue
    }

    const bundle = await loadNamespace(entry, language)

    if (bundle) {
      instance.addResourceBundle(language, entry.name, bundle, true, true)
    }
  }

  await instance.changeLanguage(language)
}
