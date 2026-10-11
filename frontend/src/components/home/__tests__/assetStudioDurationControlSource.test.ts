import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(fileURLToPath(new URL('../AssetStudioWorkbench.tsx', import.meta.url)), 'utf8')

describe('Asset Studio duration control source contract', () => {
  it('区间模型走滑块 + 数字输入 + 智能时长，档位模型保留下拉', () => {
    expect(source).toContain("from '@/utils/assetStudioDurationControls'")
    expect(source).toContain('  Slider,')
    expect(source).toContain('<DurationRangeControl')
    expect(source).toContain('range={videoDurationRange}')
    expect(source).toContain('range={motionDurationRange}')
    expect(source).toContain('videoDurationOptions.map')
    expect(source).toContain('motionDurationOptions.map')
  })

  it('提交与回写都经过区间归一，且智能时长用 -1', () => {
    expect(source).toContain('resolveDurationSelection(')
    expect(source).toContain('SMART_DURATION_VALUE')
    expect(source).toContain("formData.append('duration', videoDuration)")
    expect(source).toContain("formData.append('duration', motionDuration)")
  })

  it('不再在工作台内维护会过期的时长兜底表', () => {
    expect(source).not.toContain('const VIDEO_DURATION_OPTIONS_BY_MODEL')
    expect(source).not.toContain('const VIDEO_DURATION_RANGES_BY_MODEL')
    expect(source).not.toContain('function getRuntimeDurationOptions')
    expect(source).not.toContain('function mapDurationValuesToOptions')
  })
})
