/**
 * index.html 的启动契约。
 *
 * 内联防闪烁脚本与启动样式是纯字符串，TypeScript 完全管不到；一旦它和 token
 * 或 themeMode.ts 的常量走岔，症状是"刷新时闪一下白底"这种极难复现的问题。
 * 这里把两边逐字比对，让漂移在测试里就红掉。
 */

import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { LANGUAGE_DOM_ATTRIBUTE, LANGUAGE_STORAGE_KEY, SUPPORTED_LANGUAGES } from '@/i18n'
import {
  SYSTEM_COLOR_SCHEME_QUERY,
  THEME_MODE_DOM_ATTRIBUTE,
  THEME_MODE_STORAGE_KEY,
} from '../themeMode'
import { BOOT_COLORS, THEME_COLOR_META_NAME } from '../themeModeDom'
import enCommon from '../../i18n/resources/en-US/common.json'
import zhCommon from '../../i18n/resources/zh-CN/common.json'

// 源码断言统一按 LF 归一化，避免 Windows 检出 CRLF 行尾导致裸 \n 匹配失败
const html = readFileSync(new URL('../../../index.html', import.meta.url), 'utf8').replace(
  /\r\n/g,
  '\n',
)

/** 只取 <style> 块，避免把注释里举例的颜色也算成生效规则。 */
const bootStyle = html.slice(html.indexOf('<style>'), html.indexOf('</style>'))

/** 内联启动脚本是 head 里第一个不带 src 的 script，因此裸标签就能定位。 */
const bootScript = html.slice(html.indexOf('<script>'), html.indexOf('</script>'))

/**
 * 语言启动脚本是 head 里第二个内联 script，从主题脚本结束的位置往后找。
 *
 * 它必须排在主题脚本之后：上面的 bootScript 按"第一个"定位，插到前面去
 * 会让整套主题契约静默地去比对语言脚本。
 */
const languageScriptStart = html.indexOf('<script>', html.indexOf('</script>'))
const languageBootScript = html.slice(
  languageScriptStart,
  html.indexOf('</script>', languageScriptStart),
)

/** 内联脚本里那份标题副本应该等于的东西，按语言码索引。 */
const RESOURCE_TITLES: Record<string, string> = {
  'zh-CN': zhCommon.app.name,
  'en-US': enCommon.app.name,
}

describe('index.html boot contract', () => {
  it('declares UTF-8 before any content so the Chinese title cannot mojibake', () => {
    expect(html.indexOf('<meta charset="UTF-8"')).toBeLessThan(html.indexOf('<title>'))
  })

  it('declares Chinese as the document language for screen readers and translation', () => {
    expect(html).toContain('<html lang="zh-CN"')
  })

  it('carries a static data-theme so the boot style applies even before the script runs', () => {
    expect(html).toContain(`<html lang="zh-CN" ${THEME_MODE_DOM_ATTRIBUTE}="light">`)
  })

  it('ships the theme-color meta that ThemeModeProvider keeps in sync', () => {
    expect(html).toContain(`<meta name="${THEME_COLOR_META_NAME}"`)
  })

  it('paints both modes with the token colors in the boot style', () => {
    expect(bootStyle).toContain("html[data-theme='light']")
    expect(bootStyle).toContain("html[data-theme='dark']")
    expect(bootStyle).toContain(`background-color: ${BOOT_COLORS.light.background}`)
    expect(bootStyle).toContain(`background-color: ${BOOT_COLORS.dark.background}`)
    expect(bootStyle).toContain(`color: ${BOOT_COLORS.light.text}`)
    expect(bootStyle).toContain(`color: ${BOOT_COLORS.dark.text}`)
    expect(bootStyle).toContain('color-scheme: light')
    expect(bootStyle).toContain('color-scheme: dark')
  })

  it('reads the documented storage key in the boot script', () => {
    expect(bootScript).toContain(`'${THEME_MODE_STORAGE_KEY}'`)
  })

  it('queries the documented media feature in the boot script', () => {
    expect(bootScript).toContain(`'${SYSTEM_COLOR_SCHEME_QUERY}'`)
  })

  it('writes the documented attribute in the boot script', () => {
    expect(bootScript).toContain(`setAttribute('${THEME_MODE_DOM_ATTRIBUTE}'`)
  })

  it('accepts exactly the three modes so a corrupted value falls back to system', () => {
    expect(bootScript).toContain("stored === 'light'")
    expect(bootScript).toContain("stored === 'dark'")
    expect(bootScript).toContain("stored === 'system'")
  })

  it('tints theme-color with the same token backgrounds it uses for the page', () => {
    expect(bootScript).toContain(`querySelector('meta[name="${THEME_COLOR_META_NAME}"]')`)
    expect(bootScript).toContain(`'${BOOT_COLORS.dark.background}'`)
    expect(bootScript).toContain(`'${BOOT_COLORS.light.background}'`)
  })

  it('runs inline and synchronously ahead of the app entry', () => {
    // 带 src 的 module 脚本会被推迟执行，等不到它来防闪烁。
    expect(bootScript).not.toContain('src=')
    expect(html.indexOf('<script>')).toBeLessThan(html.indexOf('<div id="root">'))
    expect(html.indexOf('<div id="root">')).toBeLessThan(html.indexOf('type="module"'))
  })

  it('keeps the application entry as a deferred module script', () => {
    expect(html).toContain('<script type="module" src="/src/main.tsx"></script>')
  })
})

describe('index.html language boot contract', () => {
  it('hard-codes exactly the product names the resources carry', () => {
    // 标签页标题在 HTML 里是静态中文，而写标题的代码要等语言 chunk 到位，
    // 所以这里多了一份副本。品牌名已经改过一轮（七个地方），不逐字比对
    // 一定会漂移；按 SUPPORTED_LANGUAGES 循环，加语言时忘了补也会红。
    for (const { code } of SUPPORTED_LANGUAGES) {
      expect(languageBootScript, code).toContain(`'${code}': '${RESOURCE_TITLES[code]}'`)
    }
  })

  it('reads the documented language storage key', () => {
    expect(languageBootScript).toContain(`'${LANGUAGE_STORAGE_KEY}'`)
  })

  it('writes the documented lang attribute alongside the title', () => {
    expect(languageBootScript).toContain(`setAttribute('${LANGUAGE_DOM_ATTRIBUTE}'`)
  })

  it('runs after the static title so the parser cannot overwrite it', () => {
    // 解析器读到 <title> 会把 document.title 设成它的内容，因此这段脚本排到
    // <title> 前面就白写了——一个位置错误、且只在线上看得出来的坑。
    expect(languageScriptStart).toBeGreaterThan(html.indexOf('<title>'))
  })

  it('runs inline and synchronously ahead of the app entry', () => {
    expect(languageBootScript).not.toContain('src=')
    expect(languageScriptStart).toBeLessThan(html.indexOf('<div id="root">'))
  })
})
