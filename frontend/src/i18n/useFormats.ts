/**
 * 把 format.ts 的格式化函数绑定到当前语言。
 *
 * format.ts 刻意保持 React 无关——每个函数都接受 locale 参数，因此能在 Node 里
 * 单独测。这一层只做柯里化：业务组件不必到处传 locale，也不会有人忘了传，
 * 让某个角落的日期悄悄退回 zh-CN 格式（这正是全站现存 25 处写死 locale 的成因）。
 *
 * 键名与 format.ts 的函数同名，"某个格式化能力有没有被绑定"可以直接对照；
 * useFormats.test.tsx 也正是用反射比对两边清单的，漏绑会红。
 *
 * 每个函数都把 language 放在 spread 之前，因此调用方仍能用 options.locale 覆盖——
 * 中文界面里引用一段英文原文的日期时需要这个逃生口。
 */

import { useMemo } from 'react'

import { useAppLanguage } from './I18nProvider'
import {
  compareText,
  formatCompactNumber,
  formatCurrency,
  formatDate,
  formatDateNumeric,
  formatDateTime,
  formatDateTimeWithSeconds,
  formatFileSize,
  formatList,
  formatMonthDayTime,
  formatMonthDayTimeWithSeconds,
  formatNumber,
  formatPercent,
  formatRelativeTime,
  formatTime,
  formatTimeWithSeconds,
  formatWeekday,
} from './format'
import type {
  CollatorOptions,
  CurrencyFormatOptions,
  DateLike,
  DateFormatOptions,
  NumberFormatOptions,
} from './format'

/** 数值类函数共用的入参形状：允许 null / undefined / NaN，一律渲染成空串。 */
type Numeric = number | null | undefined

/** 文本类函数共用的入参形状。 */
type Text = string | null | undefined

export function useFormats() {
  const { language } = useAppLanguage()

  // 依赖数组只有 language：切语言时整组函数换一批新引用，正好让所有用过它的
  // 组件重渲染；语言不变时引用稳定，不会打断下游的 memo。
  return useMemo(
    () => ({
      formatDate: (value: DateLike, options?: DateFormatOptions) =>
        formatDate(value, { locale: language, ...options }),

      formatTime: (value: DateLike, options?: DateFormatOptions) =>
        formatTime(value, { locale: language, ...options }),

      /** “最后保存 16:30:45”这类要看到秒的时刻。 */
      formatTimeWithSeconds: (value: DateLike, options?: DateFormatOptions) =>
        formatTimeWithSeconds(value, { locale: language, ...options }),

      formatDateTime: (value: DateLike, options?: DateFormatOptions) =>
        formatDateTime(value, { locale: language, ...options }),

      formatDateTimeWithSeconds: (value: DateLike, options?: DateFormatOptions) =>
        formatDateTimeWithSeconds(value, { locale: language, ...options }),

      /** 省年份：“3月15日 16:30”，给历史面板这类全是近期事件的列表。 */
      formatMonthDayTime: (value: DateLike, options?: DateFormatOptions) =>
        formatMonthDayTime(value, { locale: language, ...options }),

      formatMonthDayTimeWithSeconds: (value: DateLike, options?: DateFormatOptions) =>
        formatMonthDayTimeWithSeconds(value, { locale: language, ...options }),

      /** YYYY-MM-DD，跨语言等宽，密集表格里用它而不是 formatDate。 */
      formatDateNumeric: (value: DateLike, options?: DateFormatOptions) =>
        formatDateNumeric(value, { locale: language, ...options }),

      formatWeekday: (value: DateLike, options?: DateFormatOptions) =>
        formatWeekday(value, { locale: language, ...options }),

      formatRelativeTime: (value: DateLike, base?: DateLike, options?: DateFormatOptions) =>
        // base 传 undefined 时原函数的 Date.now() 默认值照常生效。
        formatRelativeTime(value, base, { locale: language, ...options }),

      formatNumber: (value: Numeric, options?: NumberFormatOptions) =>
        formatNumber(value, { locale: language, ...options }),

      /** 中文走万/亿，英文走 K/M/B。 */
      formatCompactNumber: (value: Numeric, options?: NumberFormatOptions) =>
        formatCompactNumber(value, { locale: language, ...options }),

      /** 入参是 0-1 的比率，不是已经乘过 100 的数。 */
      formatPercent: (value: Numeric, options?: NumberFormatOptions) =>
        formatPercent(value, { locale: language, ...options }),

      formatCurrency: (value: Numeric, options?: CurrencyFormatOptions) =>
        formatCurrency(value, { locale: language, ...options }),

      formatFileSize: (bytes: Numeric, options?: NumberFormatOptions) =>
        formatFileSize(bytes, { locale: language, ...options }),

      /** 返回比较结果而非布尔，直接可用作 sort 的比较器。 */
      compareText: (a: Text, b: Text, options?: CollatorOptions) =>
        compareText(a, b, { locale: language, ...options }),

      formatList: (items: readonly Text[], options?: DateFormatOptions) =>
        formatList(items, { locale: language, ...options }),
    }),
    [language],
  )
}
