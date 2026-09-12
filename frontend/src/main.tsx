import ReactDOM from 'react-dom/client'
import { Provider } from 'react-redux'
import App from './App'
import { store } from './store/store'
import {
  DOCUMENT_TITLE_KEY,
  I18nProvider,
  applyDocumentTitle,
  applyLanguageToElement,
  bootstrapI18n,
  readNavigatorLanguages,
  resolveBootLanguage,
} from '@/i18n'
import {
  runLegacyLocalAssetMigrationWithStatus,
  shouldRunLegacyLocalAssetMigration,
} from './utils/localAssetMigration'
// 字体的 @font-face 必须先于其余样式入栈；不拉起这一行，主题里的衬线与
// 人文无衬线字体栈就只是字符串，标题会静默回退成系统宋体。
import '@/theme/fonts'
import './index.css'
import type { i18n as I18nInstance } from 'i18next'

// createRoot 只调一次：引导失败时要走降级渲染，重复 createRoot 会让 React 报警。
const root = ReactDOM.createRoot(document.getElementById('root')!)

function renderApp(instance?: I18nInstance) {
  root.render(
    <Provider store={store}>
      <I18nProvider instance={instance}>
        <App />
      </I18nProvider>
    </Provider>,
  )
}

/**
 * 挂载前把语言资源拉齐。
 *
 * 必须先 await 再 render：en-US 的资源是懒加载 chunk，等 React 挂载后再补的话，
 * 上次选了英文的用户会先看到一帧中文再跳成英文。zh-CN 是内联的，这条路径对
 * 中文用户等同于同步，不增加首屏延迟。
 *
 * I18nProvider 因此放在这里而不是 App.tsx：它和 ThemeModeProvider 不同，
 * 有一个必须在渲染前完成的异步前置步骤。<html lang> 与 <title> 也在这里同步写掉，
 * 而不是留给 Provider 的 effect：effect 是被动的，跑在首次绘制之后。
 *
 * index.html 里也有一段语言的防闪脚本，但它只认 localStorage：上次主动选过
 * 英文的人，标签页标题从解析阶段就是对的。首次访问、靠 navigator 语言判定
 * 的用户仍会闪一下——把这种"用户从没做过的选择"写进存储，等于悄悄把跟随
 * 浏览器改成冻结偏好，与 persistLanguage 只在用户主动切换时调用的口径相冲，
 * 因此不做。归一逻辑（zh-TW → zh-CN 之类）同理不在 HTML 里重抄：存进去的
 * 值本来就是归一后的语言码，而那份标题副本由 indexHtml.test.ts 逐字守护。
 */
async function mount() {
  try {
    // window.localStorage 的属性访问本身在跨域 iframe 下会抛 SecurityError，
    // 所以语言检测也要在 try 里，不能只包住 chunk 加载。
    const language = resolveBootLanguage(window.localStorage, readNavigatorLanguages(navigator))
    const instance = await bootstrapI18n(language)

    // 放在 await 之后：资源没到位就写 lang，chunk 失败时会留下
    // <html lang="en-US"> 配一屏中文。
    applyLanguageToElement(document.documentElement, language)
    // 标题跟 lang 同一批写：两者都是文档级的副作用，都不该等到首次绘制之后。
    applyDocumentTitle(document, instance.t(DOCUMENT_TITLE_KEY))

    renderApp(instance)
    return
  } catch (error) {
    // 目标语言的 chunk 没拉到（弱网、CDN 故障）不该让整个应用起不来。
    console.error('[i18n] 语言引导失败，回退到内联的中文资源', error)
  }

  // 缺省实例由 I18nProvider 自建，资源是内联的，这条路径不会再失败。
  // 这里刻意不写 lang 与 title：降级实例建的正是事实源语言，index.html 里
  // 静态的 lang="zh-CN" 与 <title> 都与它对得上。
  renderApp()
}

void mount()

// 在空闲时机触发 legacy IndexedDB → OPFS 的批量迁移，并把结果写入状态快照。
const scheduleLegacyMigration = () => {
  if (!shouldRunLegacyLocalAssetMigration()) {
    return
  }

  runLegacyLocalAssetMigrationWithStatus().then((status) => {
    if (status.phase === 'completed') {
      console.info('[localAssetVault] legacy 迁移完成', status)
      return
    }

    console.warn('[localAssetVault] legacy 迁移未完全成功', status)
  })
}

const ric = (window as unknown as { requestIdleCallback?: (cb: () => void) => number })
  .requestIdleCallback

if (typeof ric === 'function') {
  ric(scheduleLegacyMigration)
} else {
  setTimeout(scheduleLegacyMigration, 2000)
}
