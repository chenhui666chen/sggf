import { describe, expect, it } from 'vitest'

import type { AssetStudioModelCatalogOption } from '@/services/api'

import {
  SMART_DURATION_VALUE,
  buildCatalogDurationOptionsByModel,
  buildCatalogDurationRangesByModel,
  getDurationRange,
  getRecommendedDuration,
  getRuntimeDurationOptions,
  getSliderDurationValue,
  resolveDurationSelection,
} from '../assetStudioDurationControls'

function catalogOption(
  overrides: Partial<AssetStudioModelCatalogOption> & { model_id: string },
): AssetStudioModelCatalogOption {
  return {
    catalog_model_key: overrides.model_id,
    label: overrides.model_id,
    helper: '',
    provider: '',
    category: '',
    status: 'active',
    modalities: ['video'],
    tags: [],
    duration_options: [],
    ...overrides,
  }
}

const WAN30_RANGE = { min: 2, max: 30, step: 1, defaultValue: 5, supportsAuto: true }

describe('资产工作台时长控件', () => {
  it('把 catalog 区间元数据归一成滑块可用的区间', () => {
    const ranges = buildCatalogDurationRangesByModel({
      video_generation: [
        catalogOption({
          model_id: 'wan3.0-video',
          duration_options: [2, 3, 5, 30],
          duration_min: 2,
          duration_max: 30,
          duration_step: 1,
          duration_default: 5,
          duration_supports_auto: true,
        }),
      ],
    })

    expect(ranges['wan3.0-video']).toEqual(WAN30_RANGE)
  })

  it('档位模型不进区间表，只保留下拉档位', () => {
    const groups = {
      video_edit: [
        catalogOption({
          model_id: 'doubao-seedance-2-0',
          duration_options: [4, 5, 10, 15],
          duration_min: null,
          duration_max: null,
          duration_step: null,
          duration_default: null,
          duration_supports_auto: false,
        }),
      ],
    }

    expect(buildCatalogDurationRangesByModel(groups)).toEqual({})
    expect(buildCatalogDurationOptionsByModel(groups)['doubao-seedance-2-0']).toEqual([
      { value: '4' },
      { value: '5' },
      { value: '10' },
      { value: '15' },
    ])
  })

  it('catalog 未就绪时兜底表按官方口径给区间', () => {
    expect(getDurationRange('wan3.0-video', {})).toEqual(WAN30_RANGE)
    expect(getDurationRange('kling/kling-v3-video-generation', {})).toEqual({
      min: 3,
      max: 15,
      step: 1,
      defaultValue: 5,
      supportsAuto: false,
    })
    expect(getDurationRange('vidu-q3-pro-img2video', {})).toEqual({
      min: 1,
      max: 16,
      step: 1,
      defaultValue: 5,
      supportsAuto: false,
    })
    // pixverse-v6-t2v 官方是 [1,15] 整数区间，档案改成区间写法后离线镜像同步落到兜底区间表
    expect(getDurationRange('pixverse-v6-t2v', {})).toEqual({
      min: 1,
      max: 15,
      step: 1,
      defaultValue: 5,
      supportsAuto: false,
    })
    expect(getDurationRange('doubao-seedance-2-0', {})).toBeNull()
  })

  it('catalog 优先于兜底表', () => {
    const catalogRanges = buildCatalogDurationRangesByModel({
      motion: [
        catalogOption({
          model_id: 'wan3.0-video',
          duration_min: 2,
          duration_max: 12,
          duration_step: 1,
          duration_default: 8,
          duration_supports_auto: false,
        }),
      ],
    })

    expect(getDurationRange('wan3.0-video', catalogRanges)).toEqual({
      min: 2,
      max: 12,
      step: 1,
      defaultValue: 8,
      supportsAuto: false,
    })
  })

  it('兜底档位表不再给出官方不接受的秒数', () => {
    expect(getRuntimeDurationOptions('doubao-seedance-2-0', null, {})).toEqual([
      { value: '4' },
      { value: '5' },
      { value: '10' },
      { value: '15' },
    ])
    expect(getRuntimeDurationOptions('doubao-seedance-2-0-fast', null, {})).toEqual([
      { value: '4' },
      { value: '5' },
      { value: '10' },
      { value: '15' },
    ])
    expect(getRuntimeDurationOptions('doubao-seedance-2-5', null, {})).toEqual([
      { value: '4' },
      { value: '5' },
      { value: '10' },
      { value: '15' },
      { value: '20' },
      { value: '30' },
    ])
  })

  it('未知模型只兜底到各模型都合法的安全档位', () => {
    expect(getRuntimeDurationOptions('some-unknown-model', null, {})).toEqual([
      { value: '5' },
      { value: '10' },
    ])
  })

  it('档位模型按 catalog 档位渲染，运行时档位优先', () => {
    const catalogOptions = buildCatalogDurationOptionsByModel({
      video_generation: [catalogOption({ model_id: 'doubao-seedance-2-5', duration_options: [4, 5, 10, 15, 20, 30] })],
    })
    expect(getRuntimeDurationOptions('doubao-seedance-2-5', null, catalogOptions).length).toBe(6)
    expect(
      getRuntimeDurationOptions('doubao-seedance-2-5', { duration_values: [6, 4, 4, 9] }, catalogOptions),
    ).toEqual([{ value: '4' }, { value: '6' }, { value: '9' }])
  })

  it('区间模型保留合法整数秒，越界或小数回落默认档', () => {
    expect(resolveDurationSelection('20', WAN30_RANGE, [])).toBe('20')
    expect(resolveDurationSelection('2', WAN30_RANGE, [])).toBe('2')
    expect(resolveDurationSelection('30', WAN30_RANGE, [])).toBe('30')
    expect(resolveDurationSelection('31', WAN30_RANGE, [])).toBe('5')
    expect(resolveDurationSelection('1', WAN30_RANGE, [])).toBe('5')
    expect(resolveDurationSelection('1.5', WAN30_RANGE, [])).toBe('5')
    expect(resolveDurationSelection('', WAN30_RANGE, [])).toBe('5')
  })

  it('只有声明支持智能时长的模型才保留 -1', () => {
    expect(resolveDurationSelection(SMART_DURATION_VALUE, WAN30_RANGE, [])).toBe(SMART_DURATION_VALUE)
    expect(
      resolveDurationSelection(SMART_DURATION_VALUE, { ...WAN30_RANGE, supportsAuto: false }, []),
    ).toBe('5')
    expect(resolveDurationSelection(SMART_DURATION_VALUE, null, [{ value: '5' }, { value: '10' }])).toBe('5')
  })

  it('档位模型仍按精确档位校验', () => {
    const options = [{ value: '4' }, { value: '5' }, { value: '10' }, { value: '15' }]
    expect(resolveDurationSelection('15', null, options)).toBe('15')
    expect(resolveDurationSelection('30', null, options)).toBe('5')
  })

  it('推荐档位优先取区间默认档', () => {
    expect(getRecommendedDuration([], WAN30_RANGE)).toBe('5')
    expect(getRecommendedDuration([{ value: '7' }, { value: '12' }], null)).toBe('7')
    expect(getRecommendedDuration([{ value: '4' }, { value: '5' }, { value: '10' }], null)).toBe('5')
  })

  it('滑块值在智能时长时落回默认档并按边界夹取', () => {
    expect(getSliderDurationValue(SMART_DURATION_VALUE, WAN30_RANGE)).toBe(5)
    expect(getSliderDurationValue('7', WAN30_RANGE)).toBe(7)
    expect(getSliderDurationValue('99', WAN30_RANGE)).toBe(30)
    expect(getSliderDurationValue('abc', WAN30_RANGE)).toBe(5)
    expect(getSliderDurationValue('', WAN30_RANGE)).toBe(5)
    expect(getSliderDurationValue('  ', WAN30_RANGE)).toBe(5)
  })
})
