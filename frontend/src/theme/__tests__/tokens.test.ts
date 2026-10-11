import { describe, expect, it } from 'vitest'

import { contrastRatio } from '../contrast'
import { lightTokens, darkTokens, resolveTokens } from '../tokens'
import type { ColorTokens } from '../tokens'

const HEX_ONLY = /^#[0-9a-f]{6}$/

// 填充按钮：标签色与其自身底色必须成对校验。
const FILLED_PAIRS = [
  ['onPrimary', 'primary'],
  ['onSecondary', 'secondary'],
  ['onSuccess', 'success'],
  ['onWarning', 'warning'],
  ['onError', 'error'],
  ['onInfo', 'info'],
] as const satisfies ReadonlyArray<readonly [keyof ColorTokens, keyof ColorTokens]>

// token 键集合必须完全对齐：任一模式漏键都会导致暗色下出现"未定义颜色"。
const colorTokenKeys = Object.keys(lightTokens) as (keyof typeof lightTokens)[]

describe('ink and light color tokens', () => {
  it('keeps the light and dark token key sets identical', () => {
    expect(Object.keys(darkTokens).sort()).toEqual([...colorTokenKeys].sort())
  })

  it('uses plain 6-digit hex everywhere so contrast math stays exact', () => {
    for (const key of colorTokenKeys) {
      expect(lightTokens[key], `light.${key}`).toMatch(HEX_ONLY)
      expect(darkTokens[key], `dark.${key}`).toMatch(HEX_ONLY)
    }
  })

  it('resolves tokens by mode and never returns the same palette for both', () => {
    expect(resolveTokens('light')).toBe(lightTokens)
    expect(resolveTokens('dark')).toBe(darkTokens)
    expect(resolveTokens('dark').bgDefault).not.toBe(resolveTokens('light').bgDefault)
  })

  it('separates the paper and ink layers in both modes', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      expect(tokens.bgDefault).not.toBe(tokens.bgPaper)
      expect(tokens.bgPaper).not.toBe(tokens.surface)
      expect(tokens.surface).not.toBe(tokens.surfaceRaised)
    }
  })

  it('keeps the warm paper base in light mode and the cool ink base in dark mode', () => {
    // 浅色走暖纸白（红通道高于蓝通道），深色走冷墨（蓝通道不低于红通道）。
    expect(Number.parseInt(lightTokens.bgPaper.slice(1, 3), 16))
      .toBeGreaterThan(Number.parseInt(lightTokens.bgPaper.slice(5, 7), 16))
    expect(Number.parseInt(darkTokens.bgDefault.slice(5, 7), 16))
      .toBeGreaterThanOrEqual(Number.parseInt(darkTokens.bgDefault.slice(1, 3), 16))
  })
})

describe('ink and light contrast guarantees', () => {
  it('reaches AAA for primary body text on the paper layer', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      expect(contrastRatio(tokens.textPrimary, tokens.bgPaper)).toBeGreaterThanOrEqual(7)
      expect(contrastRatio(tokens.textPrimary, tokens.surface)).toBeGreaterThanOrEqual(7)
    }
  })

  it('reaches AA for secondary text and every semantic color used as text', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      expect(contrastRatio(tokens.textSecondary, tokens.bgPaper)).toBeGreaterThanOrEqual(4.5)
      for (const key of ['primary', 'secondary', 'success', 'warning', 'error', 'info'] as const) {
        expect(contrastRatio(tokens[key], tokens.bgPaper), `${key} on bgPaper`)
          .toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('keeps filled-button labels legible against their own background', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      for (const [labelKey, backgroundKey] of FILLED_PAIRS) {
        expect(
          contrastRatio(tokens[labelKey], tokens[backgroundKey]),
          `${labelKey} on ${backgroundKey}`,
        ).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('keeps the focus ring visible against both the page and the raised surface', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      expect(contrastRatio(tokens.focusRing, tokens.bgPaper)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(tokens.focusRing, tokens.surfaceRaised)).toBeGreaterThanOrEqual(3)
    }
  })

  it('keeps soft tints distinct from their solid counterparts', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      expect(tokens.primarySoft).not.toBe(tokens.primary)
      expect(tokens.successSoft).not.toBe(tokens.success)
      expect(tokens.warningSoft).not.toBe(tokens.warning)
      expect(tokens.errorSoft).not.toBe(tokens.error)
      expect(tokens.infoSoft).not.toBe(tokens.info)
    }
  })

  it('keeps soft tints readable as chip backgrounds under their solid color', () => {
    for (const tokens of [lightTokens, darkTokens]) {
      for (const key of ['success', 'warning', 'error', 'info'] as const) {
        expect(contrastRatio(tokens[key], tokens[`${key}Soft` as const]), `${key} on ${key}Soft`)
          .toBeGreaterThanOrEqual(4.5)
      }
    }
  })
})
