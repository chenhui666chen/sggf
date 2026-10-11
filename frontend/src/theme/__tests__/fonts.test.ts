/**
 * 字体装载点的守护测试。
 *
 * typography.ts 里的 family 名是字符串，真正让字体存在的是 fonts.ts 的 CSS
 * import。两边脱节的症状是"标题静默变成系统宋体"——不报错、不飘红，只有肉眼
 * 看得出。这里从 node_modules 里真实的 @font-face 反查 family 名做比对，
 * 而不是手抄一份映射表，避免映射表本身成为第二个会漂移的事实源。
 */

import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { fontFamilies } from '../typography'

// 源码断言统一按 LF 归一化，避免 Windows 检出 CRLF 行尾导致裸 \n 匹配失败
const readSource = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r\n/g, '\n')

const fontsSource = readSource('../fonts.ts')
const mainSource = readSource('../../main.tsx')

const projectRoot = new URL('../../../', import.meta.url)
const nodeModules = new URL('node_modules/', projectRoot)

/** fonts.ts 里所有 import 的包路径，顺序即样式入栈顺序。 */
const importedPackages = [...fontsSource.matchAll(/import\s+'([^']+)'/g)].map((match) => match[1])

/** 从该包的 CSS 里反查它注册的 font-family。 */
function familyOf(specifier: string): string {
  const css = readFileSync(new URL(specifier, nodeModules), 'utf8')
  const family = css.match(/font-family:\s*'([^']+)'/)?.[1]

  if (!family) {
    throw new Error(`无法从 ${specifier} 解析出 font-family`)
  }

  return family
}

const loadedFamilies = importedPackages.map(familyOf)

/** 设计里声明的全部字体栈。 */
const stacks = [fontFamilies.display, fontFamilies.sans, fontFamilies.mono]

describe('font loading', () => {
  it('is pulled in by the application entry, otherwise nothing here takes effect', () => {
    expect(mainSource).toContain("import '@/theme/fonts'")
  })

  it('loads a webfont for each of the three branded faces', () => {
    expect(new Set(loadedFamilies)).toEqual(
      new Set(['Fraunces Variable', 'Schibsted Grotesk Variable', 'IBM Plex Mono']),
    )
  })

  it('names every loaded face first in its stack so a fallback cannot silently win', () => {
    loadedFamilies.forEach((family) => {
      const stack = stacks.find((candidate) => candidate.includes(`'${family}'`))

      if (!stack) {
        throw new Error(`${family} 已下载却未出现在任何字体栈中`)
      }

      expect(stack.startsWith(`'${family}'`), `${family} 应当排在字体栈首位`).toBe(true)
    })
  })

  it('loads every webfont the stacks name, so no stack silently falls back', () => {
    // 反向检查：字体栈里出现的 webfont 名必须都被装载，否则就是静默回退。
    const quoted = stacks.flatMap((stack) => [...stack.matchAll(/'([^']+)'/g)].map((m) => m[1]))
    const suspicious = quoted.filter((family) => /Variable|Plex|Fraunces|Schibsted/.test(family))

    expect(new Set(suspicious)).toEqual(new Set(loadedFamilies))
  })

  it('loads no CJK webfont, which would add megabytes for no visible gain', () => {
    importedPackages.forEach((specifier) => {
      expect(specifier).not.toMatch(/noto|source-han|cjk|han-sans|han-serif/i)
    })

    loadedFamilies.forEach((family) => {
      expect(family).not.toMatch(/CJK|Han|Songti|YaHei|PingFang|Heiti/i)
    })
  })

  it('takes only the weight axis of the variable faces, not every axis permutation', () => {
    // Fraunces 另有 full / opsz / soft / wonk 等轴组合，每多一个就是一整套重复字体。
    expect(importedPackages.filter((specifier) => specifier.startsWith('@fontsource-variable/'))).toEqual([
      '@fontsource-variable/fraunces/wght.css',
      '@fontsource-variable/schibsted-grotesk/wght.css',
    ])
  })

  it('never pulls the all-weights index.css of the static monospace face', () => {
    // index.css 会拉进 100-700 全部字重 × 5 个子集，代码与数字只用得到两档。
    expect(importedPackages).not.toContain('@fontsource/ibm-plex-mono')
    expect(importedPackages).not.toContain('@fontsource/ibm-plex-mono/index.css')
    expect(importedPackages.filter((specifier) => specifier.includes('ibm-plex-mono'))).toEqual([
      '@fontsource/ibm-plex-mono/latin-400.css',
      '@fontsource/ibm-plex-mono/latin-500.css',
    ])
  })

  it('declares no italic face, which the design system does not use', () => {
    expect(importedPackages.some((specifier) => specifier.includes('italic'))).toBe(false)
  })
})
