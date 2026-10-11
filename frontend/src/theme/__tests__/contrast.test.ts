import { describe, expect, it } from 'vitest'

import {
  WCAG_THRESHOLDS,
  contrastRatio,
  meetsWcag,
  parseHexColor,
  relativeLuminance,
} from '../contrast'

describe('hex color parsing', () => {
  it('parses 6-digit hex in any letter case', () => {
    expect(parseHexColor('#ffffff')).toEqual({ r: 255, g: 255, b: 255 })
    expect(parseHexColor('#FFFFFF')).toEqual({ r: 255, g: 255, b: 255 })
    expect(parseHexColor('#1a1815')).toEqual({ r: 26, g: 24, b: 21 })
  })

  it('expands 3-digit hex shorthand', () => {
    expect(parseHexColor('#fff')).toEqual({ r: 255, g: 255, b: 255 })
    expect(parseHexColor('#000')).toEqual({ r: 0, g: 0, b: 0 })
    expect(parseHexColor('#f0a')).toEqual({ r: 255, g: 0, b: 170 })
  })

  it('returns null for anything that is not a plain hex color', () => {
    expect(parseHexColor('rgb(0, 0, 0)')).toBeNull()
    expect(parseHexColor('rgba(0, 0, 0, 0.5)')).toBeNull()
    expect(parseHexColor('white')).toBeNull()
    expect(parseHexColor('#gggggg')).toBeNull()
    expect(parseHexColor('#12345')).toBeNull()
    expect(parseHexColor('')).toBeNull()
  })
})

describe('relative luminance', () => {
  it('maps black to 0 and white to 1', () => {
    expect(relativeLuminance({ r: 0, g: 0, b: 0 })).toBe(0)
    expect(relativeLuminance({ r: 255, g: 255, b: 255 })).toBeCloseTo(1, 5)
  })

  it('weights green above red and red above blue', () => {
    const green = relativeLuminance({ r: 0, g: 255, b: 0 })
    const red = relativeLuminance({ r: 255, g: 0, b: 0 })
    const blue = relativeLuminance({ r: 0, g: 0, b: 255 })

    expect(green).toBeGreaterThan(red)
    expect(red).toBeGreaterThan(blue)
  })
})

describe('contrast ratio', () => {
  it('returns 21 for black on white and 1 for identical colors', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5)
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
  })

  it('is symmetric', () => {
    expect(contrastRatio('#1a1815', '#faf8f4')).toBeCloseTo(contrastRatio('#faf8f4', '#1a1815'), 10)
  })

  it('matches the canonical WCAG boundary grays', () => {
    // #767676 是公认的 AA 临界灰，#777777 恰好差一点点不达标。
    expect(contrastRatio('#767676', '#ffffff')).toBeCloseTo(4.54, 1)
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 1)
  })

  it('degrades to 1 instead of throwing on unparseable input', () => {
    expect(contrastRatio('not-a-color', '#ffffff')).toBe(1)
    expect(contrastRatio('#ffffff', 'rgba(0,0,0,0.5)')).toBe(1)
  })
})

describe('wcag level checks', () => {
  it('exposes the standard thresholds', () => {
    expect(WCAG_THRESHOLDS.AA).toBe(4.5)
    expect(WCAG_THRESHOLDS.AAA).toBe(7)
    expect(WCAG_THRESHOLDS.AA_LARGE).toBe(3)
    expect(WCAG_THRESHOLDS.AAA_LARGE).toBe(4.5)
  })

  it('separates passing from failing grays at AA', () => {
    expect(meetsWcag('#767676', '#ffffff', 'AA')).toBe(true)
    expect(meetsWcag('#777777', '#ffffff', 'AA')).toBe(false)
    expect(meetsWcag('#777777', '#ffffff', 'AA_LARGE')).toBe(true)
  })

  it('requires a higher ratio for AAA body text', () => {
    expect(meetsWcag('#767676', '#ffffff', 'AAA')).toBe(false)
    expect(meetsWcag('#000000', '#ffffff', 'AAA')).toBe(true)
  })
})
