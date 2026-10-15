import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

function readSibling(relativePath: string): string {
  const absolutePath = fileURLToPath(new URL(relativePath, import.meta.url))
  return existsSync(absolutePath) ? readFileSync(absolutePath, 'utf8') : ''
}

// 样式事实源模块：工作台与视觉识别页共用的同一套控件表面/卡片/菜单样式。
const stylesSource = readSibling('../assetStudioFieldStyles.tsx')
const workbenchSource = readSibling('../AssetStudioWorkbench.tsx')
const visionSource = readSibling('../AssetStudioVisionReviewPanel.tsx')

describe('资产工作台字段样式共享模块', () => {
  it('样式常量与包装组件集中在单一模块里', () => {
    expect(stylesSource).not.toBe('')
    expect(stylesSource).toContain('const WORKBENCH_FIELD_COLORS')
    expect(stylesSource).toContain('const WORKBENCH_INPUT_SURFACE_SX')
    expect(stylesSource).toContain('const WORKBENCH_TEXTFIELD_SX')
    expect(stylesSource).toContain('const WORKBENCH_INNER_CARD_SX')
    expect(stylesSource).toContain('function TextField(')
    expect(stylesSource).toContain('function Select<')
    expect(stylesSource).toContain('function InputLabel(')
    expect(stylesSource).toContain('function FormHelperText(')
  })

  it('工作台不再自带第二份样式常量，改为从共享模块导入', () => {
    expect(workbenchSource).not.toBe('')
    expect(workbenchSource).toContain("from './assetStudioFieldStyles'")
    expect(workbenchSource).not.toContain('const WORKBENCH_FIELD_COLORS')
    expect(workbenchSource).not.toContain('const WORKBENCH_INPUT_SURFACE_SX')
    expect(workbenchSource).not.toContain('function mergeSx(')
    expect(workbenchSource).not.toContain('function TextField(')
  })

  it('视觉识别页复用共享样式，不再手写第二套描边与浅色字面量', () => {
    expect(visionSource).toContain("from './assetStudioFieldStyles'")
    // 旧的本地副本必须消失
    expect(visionSource).not.toContain('const VISION_SELECT_SX')
    expect(visionSource).not.toContain('const VISION_MENU_PAPER_SX')
    expect(visionSource).not.toContain("'& .MuiOutlinedInput-notchedOutline'")
    expect(visionSource).not.toContain("sx={{ color: 'white' }}")
    expect(visionSource).not.toContain("InputLabelProps={{ sx: { color:")
    // 关闭态回显：模型项是两行（名称+定位说明），必须用 renderValue 只回显模型名
    expect(visionSource).toContain('renderValue=')
  })

  it('视觉识别页下拉与工作台同密度、同表面', () => {
    expect(visionSource).toContain('<FormControl fullWidth size="small" variant="outlined"')
    // 第二套输入框表面（含只读输出框的深色底）必须消失，统一由包装组件给
    expect(visionSource).not.toContain("'& .MuiOutlinedInput-root'")
    // 回显只取 catalog 里的 label，不再依赖页面自持的档位名单
    expect(visionSource).toContain('resolveVisionModelLabel(visionModelOptions, value)')
  })
})
