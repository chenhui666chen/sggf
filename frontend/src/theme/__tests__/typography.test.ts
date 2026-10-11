/**
 * 字体栈与字阶的守护测试。
 *
 * 这里锁的是两条容易被无意改坏的排版事实：
 * 1. 拉丁品牌字体必须排在 CJK 回退之前，且 CJK 不加载 webfont（体积原因）；
 * 2. textTransform 一律 none —— uppercase 对中文是空操作，对品牌标签是错误。
 */

import { describe, expect, it } from 'vitest'

import { createTypography, fontFamilies, typeScaleTokens } from '../typography'

/** 返回字体名在栈中的位置，-1 表示不存在。 */
function positionOf(stack: string, family: string): number {
  return stack.indexOf(`'${family}'`)
}

describe('fontFamilies', () => {
  it('leads the display stack with the latin serif before every CJK fallback', () => {
    const stack = fontFamilies.display

    expect(stack.startsWith("'Fraunces Variable'")).toBe(true)
    expect(stack.endsWith('serif')).toBe(true)
    expect(stack).not.toContain('sans-serif')
    expect(positionOf(stack, 'Fraunces Variable')).toBeLessThan(positionOf(stack, 'Songti SC'))
  })

  it('covers the serif faces actually shipped by the three major CJK platforms', () => {
    const stack = fontFamilies.display

    // macOS/iOS、Adobe/Google 思源、Windows 各自的名字都要出现，缺一档就会掉到通用 serif。
    expect(stack).toContain("'Songti SC'")
    expect(stack).toContain("'Source Han Serif SC'")
    expect(stack).toContain("'Noto Serif CJK SC'")
    expect(stack).toContain("'SimSun'")
  })

  it('leads the body stack with the latin humanist sans before every CJK fallback', () => {
    const stack = fontFamilies.sans

    expect(stack.startsWith("'Schibsted Grotesk Variable'")).toBe(true)
    expect(stack.endsWith('sans-serif')).toBe(true)
    expect(positionOf(stack, 'Schibsted Grotesk Variable')).toBeLessThan(positionOf(stack, 'PingFang SC'))
  })

  it('puts PingFang ahead of Microsoft YaHei so macOS renders before Windows fallback', () => {
    const stack = fontFamilies.sans

    expect(stack).toContain("'PingFang SC'")
    expect(stack).toContain("'Microsoft YaHei'")
    expect(stack).toContain("'Source Han Sans SC'")
    expect(positionOf(stack, 'PingFang SC')).toBeLessThan(positionOf(stack, 'Microsoft YaHei'))
  })

  it('declares a monospace stack ending in the generic monospace keyword', () => {
    expect(fontFamilies.mono.startsWith("'IBM Plex Mono'")).toBe(true)
    expect(fontFamilies.mono.endsWith('monospace')).toBe(true)
  })

  it('loads no CJK webfont, which would add megabytes to the bundle for marginal gain', () => {
    const stacks = [fontFamilies.display, fontFamilies.sans, fontFamilies.mono]

    stacks.forEach((stack) => {
      // 思源/Noto 的 webfont 包名里带 woff 或 fontsource 痕迹，这里确认没有把它们写进栈。
      expect(stack).not.toContain('woff')
      expect(stack).not.toContain('NotoSansSC-')
      expect(stack).not.toContain('SourceHanSansSC-')
    })
  })
})

describe('typeScaleTokens', () => {
  it('keeps CJK body copy at a comfortable line height', () => {
    // 中文方块字在 1.7 以下会显得拥挤，长文阅读尤其明显。
    expect(typeScaleTokens.bodyLineHeight).toBeGreaterThanOrEqual(1.7)
    expect(typeScaleTokens.bodySmallLineHeight).toBeGreaterThanOrEqual(1.6)
  })

  it('raises the root size above the MUI default of 14px', () => {
    expect(typeScaleTokens.rootFontSize).toBeGreaterThanOrEqual(15)
  })
})

describe('createTypography', () => {
  const typography = createTypography()

  it('uses the sans stack as the document default', () => {
    expect(typography.fontFamily).toBe(fontFamilies.sans)
    expect(typography.fontSize).toBe(typeScaleTokens.rootFontSize)
  })

  it('reserves the serif display face for the three largest headings only', () => {
    // 中文衬线在 h4 以下的小字号里发糊，因此只有大标题用衬线做品牌感。
    expect(typography.h1?.fontFamily).toBe(fontFamilies.display)
    expect(typography.h2?.fontFamily).toBe(fontFamilies.display)
    expect(typography.h3?.fontFamily).toBe(fontFamilies.display)
    expect(typography.h4?.fontFamily).toBe(fontFamilies.sans)
    expect(typography.h5?.fontFamily).toBe(fontFamilies.sans)
    expect(typography.h6?.fontFamily).toBe(fontFamilies.sans)
    expect(typography.body1?.fontFamily).toBe(fontFamilies.sans)
  })

  it('never uppercases text', () => {
    expect(typography.button?.textTransform).toBe('none')
    expect(typography.overline?.textTransform).toBe('none')
  })

  it('gives body copy the CJK-friendly line height', () => {
    expect(typography.body1?.lineHeight).toBe(typeScaleTokens.bodyLineHeight)
    expect(typography.body2?.lineHeight).toBe(typeScaleTokens.bodySmallLineHeight)
  })

  it('steps heading sizes down monotonically', () => {
    const sizes = [
      typography.h1,
      typography.h2,
      typography.h3,
      typography.h4,
      typography.h5,
      typography.h6,
    ].map((variant) => Number(variant?.fontSize))

    sizes.forEach((size, index) => {
      expect(size, `h${index + 1} has no numeric font size`).toBeGreaterThan(0)

      if (index > 0) {
        expect(sizes[index - 1], `h${index} is not smaller than h${index + 1}`).toBeGreaterThan(size)
      }
    })
  })

  it('declares a letter spacing for every variant so none inherits the browser default', () => {
    const variants = [
      typography.h1,
      typography.h2,
      typography.h3,
      typography.h4,
      typography.h5,
      typography.h6,
      typography.subtitle1,
      typography.subtitle2,
      typography.body1,
      typography.body2,
      typography.button,
      typography.caption,
      typography.overline,
    ]

    variants.forEach((variant, index) => {
      expect(variant?.letterSpacing, `variant ${index} lacks letterSpacing`).toBeDefined()
    })
  })

  it('tightens the serif headings, which need less tracking than the sans body', () => {
    expect(Number.parseFloat(String(typography.h1?.letterSpacing))).toBeLessThan(
      Number.parseFloat(String(typography.body1?.letterSpacing)),
    )
  })
})
