import { describe, expect, it } from 'vitest'

import {
  EMPTY_PLACEHOLDER,
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
  getDateParts,
  toDate,
} from '../format'

// 2026-03-15T08:30:45Z 是周日。所有断言都固定 timeZone，避免受运行环境时区影响。
const UTC = { timeZone: 'UTC' } as const
const SAMPLE = '2026-03-15T08:30:45Z'

describe('date coercion', () => {
  it('accepts Date, epoch millis and ISO strings', () => {
    const expected = Date.parse(SAMPLE)

    expect(toDate(new Date(expected))?.getTime()).toBe(expected)
    expect(toDate(expected)?.getTime()).toBe(expected)
    expect(toDate(SAMPLE)?.getTime()).toBe(expected)
  })

  it('returns null for anything that is not a real point in time', () => {
    expect(toDate(null)).toBeNull()
    expect(toDate(undefined)).toBeNull()
    expect(toDate('')).toBeNull()
    expect(toDate('not a date')).toBeNull()
    expect(toDate(Number.NaN)).toBeNull()
  })
})

describe('date parts', () => {
  it('splits a timestamp into locale-independent numeric parts', () => {
    expect(getDateParts(SAMPLE, UTC)).toEqual({
      year: 2026,
      month: 3,
      day: 15,
      hour: 8,
      minute: 30,
      second: 45,
      weekday: 0,
    })
  })

  it('returns null for invalid input', () => {
    expect(getDateParts('not a date', UTC)).toBeNull()
    expect(getDateParts(null, UTC)).toBeNull()
  })
})

describe('controlled date templates', () => {
  it('renders the Chinese literary date form', () => {
    expect(formatDate(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('2026年3月15日')
    expect(formatDateTime(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('2026年3月15日 08:30')
    expect(formatDateTimeWithSeconds(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('2026年3月15日 08:30:45')
  })

  it('renders the English editorial date form', () => {
    expect(formatDate(SAMPLE, { locale: 'en-US', ...UTC })).toBe('Mar 15, 2026')
    expect(formatDateTime(SAMPLE, { locale: 'en-US', ...UTC })).toBe('Mar 15, 2026, 08:30')
    expect(formatDateTimeWithSeconds(SAMPLE, { locale: 'en-US', ...UTC })).toBe('Mar 15, 2026, 08:30:45')
  })

  it('keeps a shared ISO-like form for dense tables in both locales', () => {
    expect(formatDateNumeric(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('2026-03-15')
    expect(formatDateNumeric(SAMPLE, { locale: 'en-US', ...UTC })).toBe('2026-03-15')
  })

  it('zero-pads clock time identically in both locales', () => {
    expect(formatTime(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('08:30')
    expect(formatTime(SAMPLE, { locale: 'en-US', ...UTC })).toBe('08:30')
  })

  it('keeps seconds on the bare clock when the caller needs that precision', () => {
    // 编辑器的“最后保存”与日志类时刻要精确到秒，纯数字写法两种语言一致。
    expect(formatTimeWithSeconds(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('08:30:45')
    expect(formatTimeWithSeconds(SAMPLE, { locale: 'en-US', ...UTC })).toBe('08:30:45')
  })

  it('drops the year for recent events without losing the locale idiom', () => {
    // 历史面板与冲突提示里年份是噪声。中文不补零（与“2026年3月15日”同调），
    // 英文沿用月名缩写，两者之间按各自惯例决定是否加逗号。
    expect(formatMonthDayTime(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('3月15日 08:30')
    expect(formatMonthDayTime(SAMPLE, { locale: 'en-US', ...UTC })).toBe('Mar 15, 08:30')
  })

  it('keeps seconds on the year-less form when asked', () => {
    expect(formatMonthDayTimeWithSeconds(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('3月15日 08:30:45')
    expect(formatMonthDayTimeWithSeconds(SAMPLE, { locale: 'en-US', ...UTC })).toBe('Mar 15, 08:30:45')
  })

  it('localizes the weekday name', () => {
    expect(formatWeekday(SAMPLE, { locale: 'zh-CN', ...UTC })).toBe('周日')
    expect(formatWeekday(SAMPLE, { locale: 'en-US', ...UTC })).toBe('Sun')
  })

  it('returns an empty string for invalid input so callers decide the placeholder', () => {
    expect(EMPTY_PLACEHOLDER).toBe('—')
    for (const format of [
      formatDate,
      formatDateTime,
      formatDateTimeWithSeconds,
      formatTime,
      formatTimeWithSeconds,
      formatMonthDayTime,
      formatMonthDayTimeWithSeconds,
      formatDateNumeric,
      formatWeekday,
    ]) {
      expect(format(null, UTC), format.name).toBe('')
      expect(format('not a date', UTC), format.name).toBe('')
    }
  })
})

describe('relative time', () => {
  const base = Date.parse(SAMPLE)

  it('collapses sub-minute deltas into a just-now label', () => {
    expect(formatRelativeTime(base - 20_000, base, { locale: 'zh-CN' })).toBe('刚刚')
    expect(formatRelativeTime(base - 20_000, base, { locale: 'en-US' })).toBe('just now')
  })

  it('expresses the past with the locale idiom', () => {
    const zh = formatRelativeTime(base - 3 * 60_000, base, { locale: 'zh-CN' })
    const en = formatRelativeTime(base - 3 * 60_000, base, { locale: 'en-US' })

    expect(zh).toBe('3分钟前')
    expect(en).toBe('3 minutes ago')
  })

  it('expresses the future with the locale idiom', () => {
    const zh = formatRelativeTime(base + 2 * 3_600_000, base, { locale: 'zh-CN' })
    const en = formatRelativeTime(base + 2 * 3_600_000, base, { locale: 'en-US' })

    expect(zh).toContain('后')
    expect(en).toMatch(/^in /)
  })

  it('scales up to days and years', () => {
    expect(formatRelativeTime(base - 5 * 86_400_000, base, { locale: 'zh-CN' })).toContain('天前')
    expect(formatRelativeTime(base - 400 * 86_400_000, base, { locale: 'en-US' })).toContain('year')
  })

  it('uses natural wording instead of "1 年前" where the locale has one', () => {
    // numeric: 'auto' 会在语言有习惯说法时用“昨天/去年”而不是机械数字。
    expect(formatRelativeTime(base - 86_400_000, base, { locale: 'zh-CN' })).toBe('昨天')
    expect(formatRelativeTime(base - 86_400_000, base, { locale: 'en-US' })).toBe('yesterday')
    expect(formatRelativeTime(base - 400 * 86_400_000, base, { locale: 'zh-CN' })).toBe('去年')
    expect(formatRelativeTime(base - 400 * 86_400_000, base, { locale: 'en-US' })).toBe('last year')
  })

  it('returns an empty string when either side is invalid', () => {
    expect(formatRelativeTime(null, base, { locale: 'zh-CN' })).toBe('')
    expect(formatRelativeTime(SAMPLE, null, { locale: 'zh-CN' })).toBe('')
  })
})

describe('number formatting', () => {
  it('groups thousands identically in both locales', () => {
    expect(formatNumber(1234567, { locale: 'zh-CN' })).toBe('1,234,567')
    expect(formatNumber(1234567, { locale: 'en-US' })).toBe('1,234,567')
    expect(formatNumber(-1234, { locale: 'en-US' })).toBe('-1,234')
  })

  it('honours explicit fraction digits', () => {
    expect(formatNumber(1234.5, { locale: 'en-US', fractionDigits: 2 })).toBe('1,234.50')
    expect(formatNumber(1234.567, { locale: 'en-US', fractionDigits: 0 })).toBe('1,235')
  })

  it('caps fraction digits without padding when only a maximum is given', () => {
    // 账户指标一类“整数就别带小数点”的场景：压最大位，但不补尾零。
    expect(formatNumber(1234, { locale: 'zh-CN', maxFractionDigits: 2 })).toBe('1,234')
    expect(formatNumber(1234.5, { locale: 'zh-CN', maxFractionDigits: 2 })).toBe('1,234.5')
    expect(formatNumber(1234.5678, { locale: 'zh-CN', maxFractionDigits: 2 })).toBe('1,234.57')
  })

  it('lets an explicit fractionDigits win over a looser maximum', () => {
    expect(formatNumber(1234.5, { locale: 'zh-CN', fractionDigits: 2, maxFractionDigits: 0 })).toBe('1,234.50')
  })

  it('returns an empty string for non-finite input', () => {
    expect(formatNumber(Number.NaN)).toBe('')
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe('')
    expect(formatNumber(null)).toBe('')
    expect(formatNumber(undefined)).toBe('')
  })

  it('uses 万/亿 for Chinese and K/M/B for English compact numbers', () => {
    expect(formatCompactNumber(999, { locale: 'zh-CN' })).toBe('999')
    expect(formatCompactNumber(999, { locale: 'en-US' })).toBe('999')
    expect(formatCompactNumber(12345, { locale: 'zh-CN' })).toContain('万')
    expect(formatCompactNumber(12345, { locale: 'en-US' })).toMatch(/K$/)
    expect(formatCompactNumber(123456789, { locale: 'zh-CN' })).toContain('亿')
    expect(formatCompactNumber(123456789, { locale: 'en-US' })).toMatch(/M$/)
  })

  it('treats percent input as a 0-1 ratio', () => {
    expect(formatPercent(0.85, { locale: 'en-US' })).toBe('85%')
    expect(formatPercent(0.1234, { locale: 'en-US', fractionDigits: 1 })).toBe('12.3%')
    expect(formatPercent(1, { locale: 'zh-CN' })).toBe('100%')
    expect(formatPercent(Number.NaN)).toBe('')
  })
})

describe('currency formatting', () => {
  it('defaults to CNY and uses the narrow symbol in both locales', () => {
    expect(formatCurrency(1234.5, { locale: 'zh-CN' })).toBe('¥1,234.50')
    expect(formatCurrency(1234.5, { locale: 'en-US', currency: 'USD' })).toBe('$1,234.50')
    expect(formatCurrency(1234.5, { locale: 'en-US', currency: 'CNY' })).toBe('¥1,234.50')
  })

  it('honours fraction digits and rejects non-finite input', () => {
    expect(formatCurrency(1234.5, { locale: 'en-US', fractionDigits: 0 })).toBe('¥1,235')
    expect(formatCurrency(Number.NaN)).toBe('')
    expect(formatCurrency(null)).toBe('')
  })
})

describe('file size formatting', () => {
  it('uses binary steps and drops a trailing zero fraction', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(1024)).toBe('1 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
    expect(formatFileSize(1048576)).toBe('1 MB')
    expect(formatFileSize(1073741824)).toBe('1 GB')
  })

  it('stays locale independent because units are shared', () => {
    expect(formatFileSize(1536, { locale: 'zh-CN' })).toBe(formatFileSize(1536, { locale: 'en-US' }))
  })

  it('returns an empty string for negative or non-finite sizes', () => {
    expect(formatFileSize(-1)).toBe('')
    expect(formatFileSize(Number.NaN)).toBe('')
    expect(formatFileSize(null)).toBe('')
  })
})

describe('text collation', () => {
  it('is antisymmetric and reflexive', () => {
    expect(compareText('a', 'b')).toBeLessThan(0)
    expect(compareText('b', 'a')).toBeGreaterThan(0)
    expect(compareText('a', 'a')).toBe(0)
  })

  it('sorts embedded numbers naturally when asked, which matters for chapter titles', () => {
    expect(compareText('第2章', '第10章', { locale: 'zh-CN', numeric: true })).toBeLessThan(0)
    expect(compareText('第2章', '第10章', { locale: 'zh-CN' })).toBeGreaterThan(0)
  })

  it('treats empty and missing values as equal and sorts them first', () => {
    expect(compareText('', '')).toBe(0)
    expect(compareText(null, undefined)).toBe(0)
    expect(compareText('', 'a')).toBeLessThan(0)
  })
})

describe('list formatting', () => {
  it('joins with the locale conjunction idiom', () => {
    expect(formatList(['A', 'B'], { locale: 'en-US' })).toBe('A and B')
    expect(formatList(['A', 'B', 'C'], { locale: 'en-US' })).toBe('A, B, and C')
    expect(formatList(['甲', '乙'], { locale: 'zh-CN' })).toContain('和')
    expect(formatList(['甲', '乙', '丙'], { locale: 'zh-CN' })).toContain('、')
  })

  it('degrades cleanly for zero, one and empty-string entries', () => {
    expect(formatList([], { locale: 'en-US' })).toBe('')
    expect(formatList(['only'], { locale: 'en-US' })).toBe('only')
    expect(formatList(['', 'B'], { locale: 'en-US' })).toBe('B')
  })
})
