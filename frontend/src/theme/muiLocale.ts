/**
 * MUI 内置文案的语言数据。
 *
 * MUI 组件自带一批写死的英文（Alert 的关闭按钮、Autocomplete 的空选项提示、
 * TablePagination 的每页行数、Breadcrumbs 的展开、Rating 的空标签）。它们不走
 * i18next，资源文件里也没有对应位置——这批字符串的所有权在 MUI 手上，我们只
 * 负责挑哪一套。
 *
 * MUI 5.18 已经删掉了 LocalizationProvider，locale 只能作为
 * `createTheme(options, ...locales)` 的 deep-merge 参数注入。这里不自己调
 * createTheme（全站唯一的调用点是 createAppTheme），而是把 locale 拆成
 * components 交给 createAppTheme 现成的 components 出口，因此主题工厂本身
 * 不需要知道"语言"这件事的存在。
 */

import { enUS, zhCN } from '@mui/material/locale'

import type { AppLanguage } from '@/i18n'
import type { ThemeOptions } from '@mui/material/styles'

/**
 * 用 Record 而不是查找函数：加一门语言时漏配 locale 会在编译期就报错，
 * 而不是等用户切过去才发现 MUI 的按钮还是英文。
 *
 * enUS 在 MUI 里是个空对象——英文本来就是它的内置默认，没有数据可注入，
 * 所以这一项的 components 是 undefined，对 createAppTheme 等价于"不追加"。
 */
export const MUI_LOCALES: Record<AppLanguage, ThemeOptions['components']> = {
  'zh-CN': zhCN.components,
  'en-US': enUS.components,
}
