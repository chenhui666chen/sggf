/**
 * 禁止在 theme 层之外写死颜色字面量（hex / rgb / rgba）。
 *
 * 全站曾有上千处硬编码色散落在页面与组件里：它们被冻结在浅色调值上，暗色模式
 * 一旦生效就会露馅——深蓝 hero 上的白字压到浅黄铜底变成一片糊、浅灰卡片底在
 * 墨色页面里亮得刺眼。深浅色要真正贯通，颜色就必须只从 tokens.ts 这一个事实源
 * 流出，经 palette（MUI）与 --sg-* CSS 变量（第三方表面）两条通道消费；使用处
 * 需要透明度时用 contrast.ts 的 withAlpha 从不透明 token 派生，而不是再写一个
 * rgba() 字面量。这条契约守的就是"别再绕开 token 写死颜色"。
 *
 * 三个合法逃生口：
 * 1. theme 目录整体排除——那是颜色被定义的地方，本就持有字面量；
 * 2. FILE_ALLOWLIST 整文件豁免——"颜色即数据"或非 MUI 消费的表面（模块自带
 *    调色板、拼 HTML 字符串导出），它们不跟随主题反相是刻意为之；
 * 3. 行内 `sg-color-fixed` 标记——品牌色（OAuth 支付宝蓝/微信绿）、体裁身份色
 *    等刻意固定的颜色，在该行尾注明来源即可跳过，避免为了几处固定色把整个文件
 *    挂进豁免名单。
 *
 * 纯注释行跳过：文档注释里举例提到的 hex（如"把 #667eea 换成 token"）不算违规。
 * 测试文件排除，否则本文件里的正则会匹配到自己。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const srcRoot = fileURLToPath(new URL('..', import.meta.url))
const projectRoot = fileURLToPath(new URL('../../', import.meta.url))

/** 颜色的家：token 定义与派生都在 theme 层，不参与扫描。 */
const THEME_DIR = 'theme'

/**
 * 整文件豁免：颜色即数据 / 非 MUI 消费的表面 / 刻意常暗的沉浸画布。
 *
 * - audiobookTheme.ts：有声书模块自带的平行调色板，是它自己的 token 源；
 * - formatContent.ts：把 markdown 拼成独立 HTML 字符串导出，产物脱离 React 树、
 *   消费不到 MUI theme，内联色是导出格式的一部分。
 *
 * archetype-2 常暗沉浸画布（方案 A：画布常暗 + 外围 chrome 反相）：媒体卡/沉浸
 * 画廊整体作为自包含暗色表面，用模块暗调色板或白叠色渲染，不随主题反相——
 * 就像视频播放器/黑胶唱片在浅色模式下也保持暗色画布。其内部的语义 Chip
 * （color="success/warning/error"）不含字面量、仍走 token 自动反相，因此豁免整
 * 文件不会冻结这些家具。列入此名单是“刻意常暗”的终态，与 KNOWN_OFFENDERS 的
 * “待清零债务”语义相反，不要把它当债务去清理。
 * - ProjectCard.tsx：audiobook 黑胶媒体卡（消费 audiobookTheme 平行暗调色板）；
 * - LibraryCardGrid.tsx：dreamweaver 沉浸库画廊卡（渲染在 #0b1220 常暗库页上）；
 * - AICreationPlatformPage.tsx：WandAIGC 动态漫着陆页，整页 #0a0a0f 墨底 + 白叠色 +
 *   品牌紫渐变 hero/CTA 的自包含常暗设计；画布内继承主题的家具已钉白（返回按钮
 *   color 钉 rgba(255,255,255,0.85)），作品展示 Card 走 background.paper 作画廊白卡。
 * - ScriptEditorDialog.tsx：有声书全屏音频工作台（fullScreen Dialog），自带
 *   EDITOR_SURFACE_COLORS 平行暗色调色板（与 audiobookTheme 同构），timeline/轨道/
 *   波形/滑杆全部是常暗画布设计；内部 MUI 家具（Chip/Alert 等）仍走 token 自动反相。
 * - SegmentCueEditorDialog.tsx：仅由 ScriptEditorDialog 在其常暗画布上弹出的 cue
 *   编辑对话框（Paper 钉 #17191f 面板系），与宿主同一暗色家族。
 * - DreamWeaverPage.tsx / DreamWeaverLibraryPage.tsx：织梦映心项目库与素材库，整页墨灰渐变
 *   （#6b7280→#374151，即 slate 沉浸画布）+ 胶片打孔带/场记板视觉 + 白叠色 + 蓝渐变
 *   branding band 的自包含沉浸库，白字 hero 与白叠卡跟随画布而非主题；库内卡片走
 *   LibraryCardGrid 豁免。
 * - dreamweaver-run/runPageShell.tsx：生成跑页画布，整页紫渐变（#667eea→#764ba2）
 *   + 白字 hero 的自包含沉浸 scaffold，画布不随主题反相（家具在各自文件中 token 化）。
 * - AssetStudioPage.tsx / home/AssetStudioWorkbench.tsx / home/AssetStudioVisionReviewPanel.tsx /
 *   home/ModelUseEntryStrip.tsx / home/modelEntryData.ts：资产生成工作台家族，整页紫渐变
 *   （#667eea→#764ba2）或墨底专业工作台梯度（rgba(16,18,22,0.98)）+ 白叠色 + 品牌蓝渐变的
 *   自包含常暗设计（tab 身份色/生成状态色是模块数据色）；画布不随主题反相。
 * - AudiobookDashboardPage.tsx：耳畔星河有声项目库，整页墨灰渐变（#6b7280→#374151）+ 蓝渐变
 *   品牌 bar + 白叠玻璃/黑胶唱片视觉 + 体裁数据卡（深底浅字数据对）的自包含常暗沉浸库，
 *   白字跟随画布而非主题；删除确认 Dialog 内的红色为危险操作语义色，固定双模可读。
 * - pages/dashboard/bookVizData.ts：Dashboard 书卡体裁数据纹理色（颜色即数据）——题材标签色与
 *   封面调色板（深底浅字数据对 + 四段渐变）是书卡封面美术数据，渲在浅色页面上也刻意保持
 *   深色封面（同 audiobook 黑胶卡），不随主题反相；卡片渲染区的光影/金字美术层在宿主
 *   DashboardPage 内以 sg-color-fixed 行内豁免。
 */
const FILE_ALLOWLIST = new Set<string>([
  'src/pages/audiobook/audiobookTheme.ts',
  'src/utils/formatContent.ts',
  'src/components/audiobook/ProjectCard.tsx',
  'src/pages/dreamweaver-library/LibraryCardGrid.tsx',
  'src/pages/AICreationPlatformPage.tsx',
  'src/pages/audiobook/ScriptEditorDialog.tsx',
  'src/pages/audiobook/SegmentCueEditorDialog.tsx',
  'src/pages/DreamWeaverPage.tsx',
  'src/pages/DreamWeaverLibraryPage.tsx',
  'src/pages/dreamweaver-run/runPageShell.tsx',
  'src/pages/AssetStudioPage.tsx',
  'src/components/home/AssetStudioWorkbench.tsx',
  'src/components/home/AssetStudioVisionReviewPanel.tsx',
  'src/components/home/ModelUseEntryStrip.tsx',
  'src/components/home/modelEntryData.ts',
  'src/pages/AudiobookDashboardPage.tsx',
  'src/pages/dashboard/bookVizData.ts',
])

/** 行内豁免标记：品牌色 / 数据色等刻意固定的颜色，在该行注明来源即可跳过。 */
const FIXED_MARKER = 'sg-color-fixed'

/** 三位/六位/八位十六进制。八位覆盖 #rrggbbaa 写法。 */
const HEX_LITERAL = /#[0-9a-fA-F]{3,8}\b/

/** rgb() / rgba()。 */
const RGB_LITERAL = /rgba?\([^)]*\)/i

/** 整行注释：以 //、*（jsdoc 续行）、/* 开头。 */
const COMMENT_LINE = /^\s*(?:\/\/|\*|\/\*)/

const isTestFile = (relative: string): boolean =>
  /\.test\.(ts|tsx)$/.test(relative) ||
  relative.split(path.sep).includes('__tests__')

const isExcluded = (filePath: string): boolean => {
  const relative = path.relative(srcRoot, filePath)

  return (
    isTestFile(relative) || relative.split(path.sep)[0] === THEME_DIR
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

const toRelative = (filePath: string): string =>
  path.relative(projectRoot, filePath).split(path.sep).join('/')

const hasColorLiteral = (line: string): boolean =>
  HEX_LITERAL.test(line) || RGB_LITERAL.test(line)

/** 一行算违规：含颜色字面量，且不是注释行、未标注固定色豁免。 */
const isViolatingLine = (line: string): boolean =>
  hasColorLiteral(line) && !COMMENT_LINE.test(line) && !line.includes(FIXED_MARKER)

const fileViolates = (filePath: string): boolean => {
  if (FILE_ALLOWLIST.has(toRelative(filePath))) {
    return false
  }

  return readFileSync(filePath, 'utf8')
    .split(/\r?\n/)
    .some(isViolatingLine)
}

const collectOffenders = (): string[] =>
  collectSourceFiles(srcRoot)
    .filter(fileViolates)
    .map(toRelative)
    .sort()

/**
 * 已知债务登记：基线 60 个文件，P2 分批清理期间只允许变短，目标清零。
 *
 * 与 localeHardcoding 同款：清零后留着空数组而不是把断言写成 toEqual([])，
 * 是为了保住临时豁免这个口子。集合相等断言同时守住两个方向——新增违规即红，
 * 文件已经干净却还挂在名单上（陈旧条目）也即红，因此这份名单不会烂成永久豁免。
 */
const KNOWN_OFFENDERS: string[] = [
  // components（0）已清零：ReactFlow/SVG 表面走 var(--sg-*) 变量、user-assets 系/StoryExpansion 系
  // 家具 token 化（语义 token + withAlpha 派生 + grey.100/divider），teal/身份色等数据色
  // sg-color-fixed 行内豁免，AssetStudio 家族迁 FILE_ALLOWLIST 常暗豁免（方案 A 终态）
  // pages 顶层（0）已清零：DashboardPage 书卡体裁数据表抽 bookVizData 模块（FILE_ALLOWLIST
  // 常暗数据纹理），卡片渲染区美术层行内 sg-color-fixed；OAuth 品牌色/TTS 品牌 header/
  // 紫渐变家族/AudiobookDashboardPage 分别按 OAuth 品牌色、常暗品牌带、方案 A 终态豁免
  // pages/audiobook（0）已清零：六小文件 token 化出名单，两大户（全屏编辑画布 +
  // cue 对话框）迁 FILE_ALLOWLIST 常暗豁免（方案 A 终态）
  // pages/dreamweaver-library（0）已清零：CharacterViewDialog 家具 token 化出名单，
  // 库页画布/DreamWeaverPage 迁 FILE_ALLOWLIST 常暗豁免
  // pages/dreamweaver-run（0）已清零：13 个家具文件 token 化/sg-color-fixed 出名单，
  // 跑页 scaffold（runPageShell）迁 FILE_ALLOWLIST 常暗豁免（方案 A 终态）
]

describe('color source contract', () => {
  it('keeps hardcoded colors inside the theme layer', () => {
    expect(collectOffenders()).toEqual([...KNOWN_OFFENDERS].sort())
  })

  it('defines colors in a single theme source worth referencing', () => {
    // 契约成立的前提是 token 源真的存在并且浅暗两套齐全，
    // 否则"请改用 token"就是一句空话。
    const tokens = readFileSync(path.join(srcRoot, THEME_DIR, 'tokens.ts'), 'utf8')

    expect(tokens).toContain('lightTokens')
    expect(tokens).toContain('darkTokens')
  })
})
