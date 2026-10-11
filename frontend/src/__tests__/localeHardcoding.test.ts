/**
 * 禁止在展示层写死或省略 locale。
 *
 * 全站曾有过 44 处日期/数字格式化绕过 i18n 层：29 处写死 `'zh-CN'`，15 处干脆不传
 * locale（跟随浏览器而非应用语言）。两者都会让英文界面上冒出中文格式的日期，
 * 或者用户切了语言而表格里的日期纹丝不动。格式化能力早已收敛到 i18n/format.ts +
 * i18n/useFormats.ts，这条契约守的就是"别再绕过去"。
 *
 * 写死任意 BCP 47 字面量都算违规，不只是 zh-CN：写死 'en-US' 一样会让中文界面
 * 出现英文格式。需要临时覆盖语言的合法场景（中文界面里引用一段英文原文的日期）
 * 走 useFormats 返回的 options.locale 逃生口，而不是直接调原生方法。
 *
 * 裸调用同样违规：`.toLocaleString()` 跟随的是浏览器语言，而应用语言是用户自己
 * 选的（存在 sg.lang），两者可以不一致——浏览器英文 + 应用中文时就会串味。
 *
 * 扫描范围排除 i18n 目录：格式化层本身必须持有语言码，那是它的职责所在。
 * 测试文件也排除，否则本文件里的正则会匹配到自己。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const srcRoot = fileURLToPath(new URL('..', import.meta.url))
const projectRoot = fileURLToPath(new URL('../../', import.meta.url))

/** 格式化层的家，locale 处理是它的职责，不参与扫描。 */
const FORMATTING_LAYER_DIR = 'i18n'

const isTestFile = (filePath: string): boolean =>
  /\.test\.(ts|tsx)$/.test(filePath) ||
  filePath.split(path.sep).includes('__tests__')

const isExcluded = (filePath: string): boolean => {
  const relative = path.relative(srcRoot, filePath)

  return (
    isTestFile(relative) || relative.split(path.sep)[0] === FORMATTING_LAYER_DIR
  )
}

const collectSourceFiles = (directory: string): string[] => {
  const entries = readdirSync(directory, { withFileTypes: true })

  return entries.flatMap((entry) => {
    const entryPath = path.join(directory, entry.name)

    if (entry.isDirectory()) {
      return collectSourceFiles(entryPath)
    }

    if (statSync(entryPath).isFile() && /\.(ts|tsx)$/.test(entry.name)) {
      return isExcluded(entryPath) ? [] : [entryPath]
    }

    return []
  })
}

/** 写死任意 BCP 47 字面量：toLocaleString('zh-CN') / new Intl.NumberFormat('en-US')。 */
const HARDCODED_LOCALE =
  /(?:\.toLocale(?:String|DateString|TimeString)|new\s+Intl\.\w+)\(\s*['"][a-z]{2,3}(?:-[A-Za-z0-9]+)*['"]/

/** 省略 locale：跟随浏览器语言而不是应用语言。 */
const BARE_LOCALE = /\.toLocale(?:String|DateString|TimeString)\(\s*\)/

const hasLocaleViolation = (filePath: string): boolean => {
  const source = readFileSync(filePath, 'utf8')

  return HARDCODED_LOCALE.test(source) || BARE_LOCALE.test(source)
}

const toRelative = (filePath: string): string =>
  path.relative(projectRoot, filePath).split(path.sep).join('/')

const collectOffenders = (): string[] =>
  collectSourceFiles(srcRoot)
    .filter(hasLocaleViolation)
    .map(toRelative)
    .sort()

/**
 * 已知债务登记，P0-7 分批清理期间只允许变短，现已清零。
 *
 * 留着空数组而不是把断言写成 toEqual([])，是为了保住临时豁免这个口子：
 * 将来真需要登记时往这里加一行即可，而集合相等断言同时守住两个方向——
 * 新增违规即红，文件已经干净了却还挂在名单上（陈旧条目）也即红，
 * 因此这份名单不会烂在这里变成永久豁免。
 */
const KNOWN_OFFENDERS: string[] = []

describe('locale source contract', () => {
  it('routes date and number formatting through the i18n layer', () => {
    expect(collectOffenders()).toEqual([...KNOWN_OFFENDERS].sort())
  })

  it('finds the formatting layer itself worth using', () => {
    // 契约成立的前提是那层东西真的存在并且导出了绑定语言的 hook，
    // 否则"请改用 useFormats"就是一句空话。
    const barrel = readFileSync(path.join(srcRoot, FORMATTING_LAYER_DIR, 'index.ts'), 'utf8')

    expect(barrel).toContain('useFormats')
  })
})
