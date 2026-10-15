import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(fileURLToPath(new URL('../AssetStudioWorkbench.tsx', import.meta.url)), 'utf8')
// 样式事实源已抽到共享模块，字段层的断言改为盯住那个模块。
const styleSource = readFileSync(fileURLToPath(new URL('../assetStudioFieldStyles.tsx', import.meta.url)), 'utf8')

function sliceBetween(startMarker: string, endMarker: string, text = source): string {
  const start = text.indexOf(startMarker)
  const end = text.indexOf(endMarker, start)
  expect(start).toBeGreaterThanOrEqual(0)
  expect(end).toBeGreaterThanOrEqual(0)
  return text.slice(start, end)
}

function countMatches(pattern: RegExp, text = source): number {
  return (text.match(pattern) || []).length
}

describe('Asset Studio workbench field style source contract', () => {
  it('图片页不再读音频页的生成类型状态', () => {
    const imageTab = sliceBetween("{activeTabId === 'image' ? (", "{activeTabId === 'video' ? (")
    expect(imageTab).not.toContain('audioGenerationType')
    expect(imageTab).not.toContain('cosyVoice')
    expect(imageTab).not.toContain('voiceText')
  })

  it('控件表面与卡片底只保留一个事实源', () => {
    expect(styleSource).toContain('const WORKBENCH_INPUT_SURFACE_SX')
    expect(styleSource).toContain('const WORKBENCH_SELECT_SX: SxProps<Theme> = WORKBENCH_INPUT_SURFACE_SX')
    expect(styleSource).toContain("'& .MuiInputBase-root': WORKBENCH_INPUT_SURFACE_SX")
    expect(styleSource).toContain('const WORKBENCH_DIALOG_FIELD_SX: SxProps<Theme> = WORKBENCH_TEXTFIELD_SX')
    expect(styleSource).toContain('const WORKBENCH_INNER_CARD_SX')
    // 页面里不再逐处手写第二套输入框表面与卡片底
    expect(countMatches(/'& \.MuiOutlinedInput-root': \{ color: 'white', backgroundColor:/g)).toBe(0)
    expect(countMatches(/borderRadius: 3, border: '1px solid rgba\(255,255,255,0\.1\)', backgroundColor: 'rgba\(255,255,255,0\.03\)'/g)).toBe(0)
  })

  it('Select、TextField、InputLabel、FormHelperText 全部走共享包装组件', () => {
    expect(styleSource).toContain('TextField as MuiTextField')
    expect(styleSource).toContain('FormHelperText as MuiFormHelperText')
    expect(styleSource).toContain('function TextField(')
    expect(styleSource).toContain('function FormHelperText(')
    expect(source).toContain("from './assetStudioFieldStyles'")
    expect(countMatches(/<FormHelperText sx=/g)).toBe(0)
    expect(countMatches(/<InputLabel sx=\{/g)).toBe(0)
    expect(countMatches(/InputLabelProps=\{\{ sx: \{ color:/g)).toBe(0)
    expect(countMatches(/sx=\{\{ color: 'white' \}\}/g)).toBe(0)
  })

  it('模型选择器统一封装，关闭态只回显模型名', () => {
    expect(source).toContain('function ModelSelect(')
    expect(countMatches(/<ModelSelect[\s]/g)).toBe(4)
    expect(source).toContain('renderValue=')
    expect(source).not.toContain('renderModelOptionMenuItem(option as ModelOption, catalogRuntimeEntries[option.value]')
    // 但校验状态 chip 不能被一起省掉：无信号时它展示"未校验"，属于选型信息
    const modelSelect = sliceBetween('function ModelSelect(', 'function parseSizeValue')
    expect(modelSelect).toContain('label={getRoutingStatusLabel(routingSignal, t)}')
    expect(modelSelect).not.toContain('{routingSignal ? (')
  })

  it('深色面板上输入框逐态钉住底色，单行控件共用同一基线', () => {
    const surface = sliceBetween('const WORKBENCH_INPUT_SURFACE_SX', 'const WORKBENCH_TEXTFIELD_SX', styleSource)
    expect(surface).toContain("backgroundColor: WORKBENCH_FIELD_COLORS.surface,")
    expect(surface).toContain("'&:hover': {\n    backgroundColor: WORKBENCH_FIELD_COLORS.surfaceHover,")
    expect(surface).toContain("'&.Mui-focused': {\n    backgroundColor: WORKBENCH_FIELD_COLORS.surfaceFocus,")
    expect(surface).toContain("'&.Mui-disabled': {\n    backgroundColor: WORKBENCH_FIELD_COLORS.surfaceDisabled,")
    expect(surface).toContain("minHeight: '1.4375em'")
    expect(surface).toContain("lineHeight: '1.4375em'")
    expect(countMatches(/surfaceHover|surfaceFocus|surfaceDisabled/g, styleSource)).toBeGreaterThanOrEqual(6)
  })

  it('聚焦描边与标签高亮的层叠顺序锁死', () => {
    // fieldset 标签选择器权重低于 MUI 的聚焦规则，实测会漏出浅色主题主色
    expect(countMatches(/'& fieldset'/g)).toBe(0)
    expect(countMatches(/'& fieldset'/g, styleSource)).toBe(0)
    expect(countMatches(/'&:hover fieldset'/g, styleSource)).toBe(0)
    expect(countMatches(/'&\.Mui-focused fieldset'/g, styleSource)).toBe(0)
    expect(styleSource).toContain("'&.Mui-focused .MuiOutlinedInput-notchedOutline'")
    // focused 必须排在 filled 之后，否则已填写字段聚焦时高亮被同权重的 filled 吃掉
    const labelBlocks = [
      sliceBetween('const WORKBENCH_TEXTFIELD_SX', 'const WORKBENCH_SELECT_SX', styleSource),
      sliceBetween('const WORKBENCH_INPUT_LABEL_SX', 'const WORKBENCH_HELPER_SX', styleSource),
    ]
    for (const block of labelBlocks) {
      expect(block).toContain("'&.MuiFormLabel-filled'")
      expect(block).toContain("'&.Mui-focused'")
      expect(block.indexOf("'&.MuiFormLabel-filled'")).toBeLessThan(block.indexOf("'&.Mui-focused'"))
    }
  })

  it('每个 FormControl 显式声明 outlined，不依赖 MUI 默认值', () => {
    expect(countMatches(/<FormControl(?![^>]*variant="outlined")/g)).toBe(0)
    expect(countMatches(/<FormControl[^>]*variant="outlined"/g)).toBeGreaterThanOrEqual(10)
  })

  it('底部参数条统一成同一个壳', () => {
    expect(source).toContain('function ParamBar(')
    expect(countMatches(/<ParamBar[\s]/g)).toBe(4)
    expect(countMatches(/justifyContent="space-between" alignItems=\{\{ xs: 'stretch', md: 'center' \}\}/g)).toBe(0)
  })

  it('退役模型留下的死条件 chip 已移除', () => {
    expect(source).not.toContain("imageModelId === 'qwen-image-edit-max'")
    expect(source).not.toContain("t('assetStudio.workbench.chip.recommendedMain')")
    expect(source).not.toContain("t('assetStudio.workbench.chip.qualityFirst')")
  })
})
