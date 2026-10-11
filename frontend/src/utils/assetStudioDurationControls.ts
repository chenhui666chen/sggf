import type { AssetStudioModelCatalogOption } from '@/services/api'

export interface DurationOption {
  value: string
  label?: string
}

export interface DurationRange {
  min: number
  max: number
  step: number
  defaultValue: number
  supportsAuto: boolean
}

interface DurationConstraintSource {
  duration_values?: number[]
}

// 与后端 schemas/model_spec.SMART_DURATION_VALUE 同源：上游用 -1 表示"由模型自行决定时长"
export const SMART_DURATION_VALUE = '-1'

const DURATION_CATALOG_GROUPS = ['video_generation', 'video_edit', 'motion'] as const

// 目录不可用时的兜底档位：只保留各视频模型都合法的秒数，避免离线态给出上游会拒绝的时长
const SAFE_FALLBACK_DURATION_OPTIONS: DurationOption[] = [
  { value: '5' },
  { value: '10' },
]

// 档位列表模型（constraints.duration 写成数组）的离线镜像，与 config/models.yaml 同源
const VIDEO_DURATION_OPTIONS_BY_MODEL: Record<string, DurationOption[]> = {
  'doubao-seedance-2-5': [
    { value: '4' },
    { value: '5' },
    { value: '10' },
    { value: '15' },
    { value: '20' },
    { value: '30' },
  ],
  'doubao-seedance-2-0': [
    { value: '4' },
    { value: '5' },
    { value: '10' },
    { value: '15' },
  ],
  'doubao-seedance-2-0-fast': [
    { value: '4' },
    { value: '5' },
    { value: '10' },
    { value: '15' },
  ],
}

// 区间模型（constraints.duration 写成 {min,max,default,supports_auto}）的离线镜像，
// 这类模型渲染滑块 + 数字输入，不落到档位下拉里。区间上限取官方刊例值（2026-10-09 核对）：
// kling [3,15]、vidu q3-pro [1,16]、pixverse-v6-t2v [1,15]
const VIDEO_DURATION_RANGES_BY_MODEL: Record<string, DurationRange> = {
  'wan3.0-video': { min: 2, max: 30, step: 1, defaultValue: 5, supportsAuto: true },
  'kling/kling-v3-video-generation': { min: 3, max: 15, step: 1, defaultValue: 5, supportsAuto: false },
  'kling/kling-v3-omni-video-generation': { min: 3, max: 15, step: 1, defaultValue: 5, supportsAuto: false },
  'vidu-q3-pro-text2video': { min: 1, max: 16, step: 1, defaultValue: 5, supportsAuto: false },
  'vidu-q3-pro-img2video': { min: 1, max: 16, step: 1, defaultValue: 5, supportsAuto: false },
  'vidu-q3-pro-start-end2video': { min: 1, max: 16, step: 1, defaultValue: 5, supportsAuto: false },
  'pixverse-v6-t2v': { min: 1, max: 15, step: 1, defaultValue: 5, supportsAuto: false },
}

export function normalizeDurationValue(value: number): string {
  return Number.isInteger(value)
    ? String(Math.trunc(value))
    : String(value).replace(/\.0+$/, '').replace(/(\.\d*?[1-9])0+$/, '$1')
}

function toPositiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function clampToRange(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function mapDurationValuesToOptions(values: number[] | undefined | null): DurationOption[] {
  if (!Array.isArray(values) || values.length === 0) {
    return []
  }

  const normalizedValues = Array.from(
    new Set(
      values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value)),
    ),
  ).sort((left, right) => left - right)

  return normalizedValues.map((value) => ({ value: normalizeDurationValue(value) }))
}

function forEachCatalogOption(
  groups: Record<string, AssetStudioModelCatalogOption[]> | undefined,
  visit: (option: AssetStudioModelCatalogOption) => void,
): void {
  if (!groups) {
    return
  }
  for (const groupKey of DURATION_CATALOG_GROUPS) {
    for (const option of groups[groupKey] || []) {
      visit(option)
    }
  }
}

export function buildCatalogDurationOptionsByModel(
  groups: Record<string, AssetStudioModelCatalogOption[]> | undefined,
): Record<string, DurationOption[]> {
  const result: Record<string, DurationOption[]> = {}
  forEachCatalogOption(groups, (option) => {
    const durationOptions = mapDurationValuesToOptions(option.duration_options)
    if (durationOptions.length > 0) {
      result[option.model_id] = durationOptions
    }
  })
  return result
}

function buildDurationRange(option: AssetStudioModelCatalogOption): DurationRange | null {
  const min = toPositiveNumber(option.duration_min)
  const max = toPositiveNumber(option.duration_max)
  if (min === null || max === null || max < min) {
    return null
  }
  const defaultValue = toPositiveNumber(option.duration_default)
  return {
    min,
    max,
    step: toPositiveNumber(option.duration_step) ?? 1,
    defaultValue: clampToRange(defaultValue ?? min, min, max),
    supportsAuto: option.duration_supports_auto === true,
  }
}

export function buildCatalogDurationRangesByModel(
  groups: Record<string, AssetStudioModelCatalogOption[]> | undefined,
): Record<string, DurationRange> {
  const result: Record<string, DurationRange> = {}
  forEachCatalogOption(groups, (option) => {
    const range = buildDurationRange(option)
    if (range) {
      result[option.model_id] = range
    }
  })
  return result
}

export function getDurationRange(
  modelId: string,
  catalogDurationRangesByModel?: Record<string, DurationRange>,
): DurationRange | null {
  return catalogDurationRangesByModel?.[modelId] || VIDEO_DURATION_RANGES_BY_MODEL[modelId] || null
}

export function getRecommendedDuration(
  options: DurationOption[],
  range: DurationRange | null = null,
): string {
  if (range) {
    return normalizeDurationValue(range.defaultValue)
  }
  return options.find((option) => option.value === '5')?.value || options[0]?.value || '5'
}

function isOptionStepValue(value: number, range: DurationRange): boolean {
  return Math.abs((value - range.min) % range.step) < 0.0001
}

export function resolveDurationSelection(
  rawValue: string,
  range: DurationRange | null,
  options: DurationOption[],
): string {
  if (range) {
    if (rawValue === SMART_DURATION_VALUE && range.supportsAuto) {
      return SMART_DURATION_VALUE
    }
    const parsed = Number(rawValue)
    const inRange = Number.isFinite(parsed) && parsed >= range.min && parsed <= range.max && isOptionStepValue(parsed, range)
    return inRange ? normalizeDurationValue(parsed) : normalizeDurationValue(range.defaultValue)
  }

  if (options.some((option) => option.value === rawValue)) {
    return rawValue
  }
  return getRecommendedDuration(options)
}

export function getSliderDurationValue(rawValue: string, range: DurationRange): number {
  if (rawValue === SMART_DURATION_VALUE || rawValue.trim() === '') {
    return range.defaultValue
  }
  const parsed = Number(rawValue)
  if (!Number.isFinite(parsed)) {
    return range.defaultValue
  }
  return clampToRange(Math.round(parsed), range.min, range.max)
}

export function getRuntimeDurationOptions(
  modelId: string,
  runtimeTaskConstraints?: DurationConstraintSource | null,
  catalogDurationOptionsByModel?: Record<string, DurationOption[]>,
): DurationOption[] {
  const durationValues = Array.isArray(runtimeTaskConstraints?.duration_values)
    ? runtimeTaskConstraints.duration_values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value))
    : []

  if (!durationValues.length) {
    const catalogOptions = catalogDurationOptionsByModel?.[modelId]
    if (catalogOptions && catalogOptions.length > 0) {
      return catalogOptions
    }
    return VIDEO_DURATION_OPTIONS_BY_MODEL[modelId] || SAFE_FALLBACK_DURATION_OPTIONS
  }

  const uniqueSortedValues = Array.from(new Set(durationValues)).sort((left, right) => left - right)
  return uniqueSortedValues.map((value) => ({ value: normalizeDurationValue(value) }))
}
