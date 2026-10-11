/**
 * WCAG 2.1 相对亮度与对比度计算。
 *
 * 设计 token 的可达性约束由 tokens.test.ts 直接调用本模块校验，
 * 因此这里必须是纯函数、不依赖 DOM，并且对脏输入安全降级。
 */

export interface Rgb {
  r: number
  g: number
  b: number
}

export type WcagLevel = 'AA' | 'AAA' | 'AA_LARGE' | 'AAA_LARGE'

/** WCAG 2.1 对比度门槛：正文 / 正文增强 / 大字 / 大字增强。 */
export const WCAG_THRESHOLDS: Record<WcagLevel, number> = {
  AA: 4.5,
  AAA: 7,
  AA_LARGE: 3,
  AAA_LARGE: 4.5,
}

const HEX_PATTERN = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i

/** 只接受 3/6 位十六进制；rgba() 与颜色关键字返回 null，避免算出错误结论。 */
export function parseHexColor(value: string): Rgb | null {
  if (typeof value !== 'string') {
    return null
  }

  const normalized = value.trim()

  if (!HEX_PATTERN.test(normalized)) {
    return null
  }

  let hex = normalized.slice(1)

  if (hex.length === 3) {
    hex = hex
      .split('')
      .map((channel) => channel + channel)
      .join('')
  }

  return {
    r: Number.parseInt(hex.slice(0, 2), 16),
    g: Number.parseInt(hex.slice(2, 4), 16),
    b: Number.parseInt(hex.slice(4, 6), 16),
  }
}

// sRGB 通道线性化门槛与系数取自 WCAG 2.1 定义。
const CHANNEL_THRESHOLD = 0.04045
const CHANNEL_DIVISOR = 12.92

function linearizeChannel(channel: number): number {
  const srgb = channel / 255

  if (srgb <= CHANNEL_THRESHOLD) {
    return srgb / CHANNEL_DIVISOR
  }

  return ((srgb + 0.055) / 1.055) ** 2.4
}

export function relativeLuminance(rgb: Rgb): number {
  const r = linearizeChannel(rgb.r)
  const g = linearizeChannel(rgb.g)
  const b = linearizeChannel(rgb.b)

  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/**
 * 对比度。无法解析任一颜色时返回 1（最低值），
 * 让上游的"必须 >= 4.5"断言失败而不是抛异常中断整批检查。
 */
export function contrastRatio(a: string, b: string): number {
  const rgbA = parseHexColor(a)
  const rgbB = parseHexColor(b)

  if (!rgbA || !rgbB) {
    return 1
  }

  const luminanceA = relativeLuminance(rgbA)
  const luminanceB = relativeLuminance(rgbB)
  const lighter = Math.max(luminanceA, luminanceB)
  const darker = Math.min(luminanceA, luminanceB)

  return (lighter + 0.05) / (darker + 0.05)
}

export function meetsWcag(foreground: string, background: string, level: WcagLevel): boolean {
  return contrastRatio(foreground, background) >= WCAG_THRESHOLDS[level]
}

/**
 * 由十六进制色派生带透明度的 rgba()。
 *
 * token 表里只存不透明十六进制色，透明度一律在使用处派生，
 * 这样对比度校验可以对不透明色精确计算。
 */
export function withAlpha(hex: string, alpha: number): string {
  const rgb = parseHexColor(hex)

  if (!rgb) {
    return hex
  }

  const clamped = Math.min(1, Math.max(0, alpha))

  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${Number(clamped.toFixed(3))})`
}
