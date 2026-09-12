/**
 * locale 感知的日期、数字、货币、文件大小、排序与列表格式化。
 *
 * 两个刻意的设计取舍：
 * 1. 日期不直接吐 Intl 的字符串，而是先取"日期分量"再套受控模板。
 *    这样 ICU 版本差异不会让 UI 文案漂移，也便于中英文各用自己的书写习惯
 *    （中文"2026年3月15日"，英文"Mar 15, 2026"）。
 * 2. 所有格式化函数对无效输入返回空串，而不是 'Invalid Date' 或 'NaN'；
 *    展示层用 EMPTY_PLACEHOLDER 决定占位符。
 *
 * 本模块必须保持 React 与 DOM 无关，绑定当前语言的 hook 在 useFormats.ts。
 */

import { DEFAULT_LANGUAGE, getLanguageDescriptor } from './language'
import type { AppLanguage } from './language'

/** 表格与空值统一占位符。 */
export const EMPTY_PLACEHOLDER = '—'

export type DateLike = Date | number | string | null | undefined

export interface DateFormatOptions {
  locale?: AppLanguage
  /** 仅测试与跨时区场景需要显式指定；默认按用户本地时区。 */
  timeZone?: string
}

export interface NumberFormatOptions {
  locale?: AppLanguage
  /** 同时锁定最小与最大小数位，因此会补尾零。 */
  fractionDigits?: number
  /** 只压最大位、不补尾零；与 fractionDigits 同给时后者优先。 */
  maxFractionDigits?: number
}

export interface CollatorOptions {
  locale?: AppLanguage
  /** 自然数字序，用于"第2章 < 第10章"这类标题排序。 */
  numeric?: boolean
}

export interface DateParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
  /** 0 = 周日，与 Date#getDay 一致。 */
  weekday: number
}

const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const EN_WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const ZH_WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const FILE_SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'] as const
const FILE_SIZE_BASE = 1024

/** 小于该毫秒差直接显示"刚刚"，避免"0 秒前"这种噪声。 */
const JUST_NOW_THRESHOLD_MS = 45_000

function resolveBcp47(locale?: AppLanguage): string {
  return getLanguageDescriptor(locale ?? DEFAULT_LANGUAGE).bcp47
}

function isChinese(locale?: AppLanguage): boolean {
  return (locale ?? DEFAULT_LANGUAGE) === 'zh-CN'
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

export function toDate(value: DateLike): Date | null {
  if (value === null || value === undefined || value === '') {
    return null
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  if (typeof value === 'number') {
    return Number.isFinite(value) ? new Date(value) : null
  }

  if (typeof value === 'string') {
    const parsed = Date.parse(value)

    return Number.isNaN(parsed) ? null : new Date(parsed)
  }

  return null
}

function readPart(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): number {
  const found = parts.find((part) => part.type === type)

  return found ? Number.parseInt(found.value, 10) : 0
}

/** 取指定时区下的日期分量；hourCycle 用 h23 避免午夜出现 24 点。 */
export function getDateParts(value: DateLike, options: DateFormatOptions = {}): DateParts | null {
  const date = toDate(value)

  if (!date) {
    return null
  }

  const parts = new Intl.DateTimeFormat(resolveBcp47(options.locale), {
    timeZone: options.timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    second: 'numeric',
    hourCycle: 'h23',
  }).formatToParts(date)

  const year = readPart(parts, 'year')
  const month = readPart(parts, 'month')
  const day = readPart(parts, 'day')

  return {
    year,
    month,
    day,
    hour: readPart(parts, 'hour'),
    minute: readPart(parts, 'minute'),
    second: readPart(parts, 'second'),
    // 由年月日在 UTC 上重算星期，避免时区把星期算偏一天。
    weekday: new Date(Date.UTC(year, month - 1, day)).getUTCDay(),
  }
}

/** 拼装时分（可选带秒）。纯数字写法，与语言无关，因此中英文列宽一致。 */
function clockOf(parts: DateParts, withSeconds: boolean): string {
  return withSeconds
    ? `${pad2(parts.hour)}:${pad2(parts.minute)}:${pad2(parts.second)}`
    : `${pad2(parts.hour)}:${pad2(parts.minute)}`
}

export function formatDate(value: DateLike, options: DateFormatOptions = {}): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  if (isChinese(options.locale)) {
    return `${parts.year}年${parts.month}月${parts.day}日`
  }

  return `${EN_MONTHS[parts.month - 1]} ${parts.day}, ${parts.year}`
}

export function formatTime(value: DateLike, options: DateFormatOptions = {}): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  return clockOf(parts, false)
}

/** 编辑器的“最后保存”、日志时刻这类需要秒级精度的场合。 */
export function formatTimeWithSeconds(value: DateLike, options: DateFormatOptions = {}): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  return clockOf(parts, true)
}

function formatClock(value: DateLike, options: DateFormatOptions, withSeconds: boolean): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  const date = formatDate(value, options)

  // 英文日期与时分之间按惯例加逗号，中文不加。
  return isChinese(options.locale)
    ? `${date} ${clockOf(parts, withSeconds)}`
    : `${date}, ${clockOf(parts, withSeconds)}`
}

export function formatDateTime(value: DateLike, options: DateFormatOptions = {}): string {
  return formatClock(value, options, false)
}

export function formatDateTimeWithSeconds(value: DateLike, options: DateFormatOptions = {}): string {
  return formatClock(value, options, true)
}

/**
 * 省年份的月日时分。历史面板、跨标签冲突提示这类“都是近期发生的事”的列表里，
 * 年份是纯噪声，去掉还能让中英文都短一截。
 */
function formatMonthDayClock(value: DateLike, options: DateFormatOptions, withSeconds: boolean): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  // 中文不补零，与“2026年3月15日”同调；英文沿用月名缩写并按惯例加逗号。
  return isChinese(options.locale)
    ? `${parts.month}月${parts.day}日 ${clockOf(parts, withSeconds)}`
    : `${EN_MONTHS[parts.month - 1]} ${parts.day}, ${clockOf(parts, withSeconds)}`
}

export function formatMonthDayTime(value: DateLike, options: DateFormatOptions = {}): string {
  return formatMonthDayClock(value, options, false)
}

export function formatMonthDayTimeWithSeconds(value: DateLike, options: DateFormatOptions = {}): string {
  return formatMonthDayClock(value, options, true)
}

/** 密集表格用的跨语言一致写法，避免中英文列宽跳动。 */
export function formatDateNumeric(value: DateLike, options: DateFormatOptions = {}): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`
}

export function formatWeekday(value: DateLike, options: DateFormatOptions = {}): string {
  const parts = getDateParts(value, options)

  if (!parts) {
    return ''
  }

  return isChinese(options.locale) ? ZH_WEEKDAYS[parts.weekday] : EN_WEEKDAYS[parts.weekday]
}

type RelativeUnit = 'second' | 'minute' | 'hour' | 'day' | 'month' | 'year'

function pickRelativeUnit(absDiffMs: number): { unit: RelativeUnit; value: number } {
  const seconds = Math.round(absDiffMs / 1000)
  const minutes = Math.round(absDiffMs / 60_000)
  const hours = Math.round(absDiffMs / 3_600_000)
  const days = Math.round(absDiffMs / 86_400_000)

  if (seconds < 60) {
    return { unit: 'second', value: seconds }
  }

  if (minutes < 60) {
    return { unit: 'minute', value: minutes }
  }

  if (hours < 24) {
    return { unit: 'hour', value: hours }
  }

  if (days < 30) {
    return { unit: 'day', value: days }
  }

  if (days < 365) {
    return { unit: 'month', value: Math.max(1, Math.round(days / 30)) }
  }

  return { unit: 'year', value: Math.max(1, Math.round(days / 365)) }
}

/** "3 分钟前 / 3 minutes ago"。base 缺省为当前时刻，测试里显式传入以固定时间轴。 */
export function formatRelativeTime(
  value: DateLike,
  base: DateLike = Date.now(),
  options: DateFormatOptions = {},
): string {
  const target = toDate(value)
  const reference = toDate(base)

  if (!target || !reference) {
    return ''
  }

  const diffMs = target.getTime() - reference.getTime()
  const absDiffMs = Math.abs(diffMs)

  if (absDiffMs < JUST_NOW_THRESHOLD_MS) {
    return isChinese(options.locale) ? '刚刚' : 'just now'
  }

  const { unit, value: amount } = pickRelativeUnit(absDiffMs)
  const signed = diffMs < 0 ? -amount : amount

  return new Intl.RelativeTimeFormat(resolveBcp47(options.locale), { numeric: 'auto' }).format(
    signed,
    unit,
  )
}

export function formatNumber(value: number | null | undefined, options: NumberFormatOptions = {}): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return ''
  }

  const digits = options.fractionDigits

  return new Intl.NumberFormat(resolveBcp47(options.locale), {
    minimumFractionDigits: digits ?? 0,
    // 只给 maxFractionDigits 时不补尾零：1234.5 仍是 "1,234.5" 而不是 "1,234.50"。
    maximumFractionDigits: digits ?? options.maxFractionDigits ?? 3,
  }).format(value)
}

/** 中文走"万/亿"，英文走"K/M/B"，由 Intl compact 记法自动处理。 */
export function formatCompactNumber(
  value: number | null | undefined,
  options: NumberFormatOptions = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return ''
  }

  return new Intl.NumberFormat(resolveBcp47(options.locale), {
    notation: 'compact',
    maximumFractionDigits: options.fractionDigits ?? 1,
  }).format(value)
}

/** 入参是 0-1 的比率，不是已经乘过 100 的百分数。 */
export function formatPercent(value: number | null | undefined, options: NumberFormatOptions = {}): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return ''
  }

  const digits = options.fractionDigits ?? 0

  return new Intl.NumberFormat(resolveBcp47(options.locale), {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

export interface CurrencyFormatOptions extends NumberFormatOptions {
  currency?: string
}

/** 默认人民币；narrowSymbol 让中英文都显示 ¥ / $ 而不是 CN¥ / US$。 */
export function formatCurrency(
  value: number | null | undefined,
  options: CurrencyFormatOptions = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return ''
  }

  const digits = options.fractionDigits ?? 2

  return new Intl.NumberFormat(resolveBcp47(options.locale), {
    style: 'currency',
    currency: options.currency ?? 'CNY',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

/** 二进制步长（1024），单位中英文共用，因此结果与 locale 无关。 */
export function formatFileSize(
  bytes: number | null | undefined,
  options: NumberFormatOptions = {},
): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) {
    return ''
  }

  if (bytes < FILE_SIZE_BASE) {
    return `${Math.round(bytes)} ${FILE_SIZE_UNITS[0]}`
  }

  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(FILE_SIZE_BASE)),
    FILE_SIZE_UNITS.length - 1,
  )
  const scaled = bytes / FILE_SIZE_BASE ** exponent
  // 用 Number 往返去掉 "1.0" 的尾零，得到 "1 KB"。
  const text = Number(scaled.toFixed(options.fractionDigits ?? 1)).toString()

  return `${text} ${FILE_SIZE_UNITS[exponent]}`
}

/** 本地化排序；numeric 打开后"第2章"排在"第10章"前面。 */
export function compareText(a: string | null | undefined, b: string | null | undefined, options: CollatorOptions = {}): number {
  const left = a ?? ''
  const right = b ?? ''

  return new Intl.Collator(resolveBcp47(options.locale), {
    numeric: options.numeric ?? false,
  }).compare(left, right)
}

/**
 * 连接词列表，自动丢弃空串项。
 *
 * 手写而不用 Intl.ListFormat：后者属于 ES2021 lib，为一个函数抬高全局
 * tsconfig lib 不划算；手写还能锁定中文顿号与英文牛津逗号的具体形态。
 */
export function formatList(
  items: readonly (string | null | undefined)[],
  options: DateFormatOptions = {},
): string {
  const cleaned = items.filter((item): item is string => typeof item === 'string' && item.trim() !== '')

  if (cleaned.length === 0) {
    return ''
  }

  if (cleaned.length === 1) {
    return cleaned[0]
  }

  const leading = cleaned.slice(0, -1)
  const last = cleaned[cleaned.length - 1]

  if (isChinese(options.locale)) {
    // 两项：甲和乙；三项及以上：甲、乙和丙
    return leading.length === 1
      ? `${leading[0]}和${last}`
      : `${leading.join('、')}和${last}`
  }

  // 两项：A and B；三项及以上保留牛津逗号：A, B, and C
  return leading.length === 1
    ? `${leading[0]} and ${last}`
    : `${leading.join(', ')}, and ${last}`
}
