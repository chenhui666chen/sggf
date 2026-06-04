import { describe, expect, it } from 'vitest'

import {
  buildAudioLibraryDetailItems,
  formatAudioAssetNameLabel,
  formatAudioKeywordLabel,
  formatMusicDurationLabel,
  formatSfxCategoryLabel,
  getVisibleSfxScenes,
  getVisibleSfxTags,
} from '../audioLibraryDisplay'

describe('audio library display helpers', () => {
  it('labels sound effect filters and tags in Chinese while keeping unknown values readable', () => {
    expect(formatSfxCategoryLabel('action/realistic')).toBe('动作 / 写实')
    expect(formatAudioKeywordLabel('indoor')).toBe('室内')
    expect(formatAudioKeywordLabel('mystery')).toBe('悬疑')
    expect(formatAudioKeywordLabel('battle')).toBe('战斗')
    expect(formatAudioKeywordLabel('romance')).toBe('浪漫')
    expect(formatAudioKeywordLabel('travel')).toBe('旅行')
    expect(formatAudioKeywordLabel('custom_alarm')).toBe('custom alarm')
  })

  it('hides generated scene placeholders from scene filters', () => {
    expect(getVisibleSfxScenes(['travel', 'scene 1', 'battle', 'scene_11', 'romance'])).toEqual([
      'travel',
      'battle',
      'romance',
    ])
  })

  it('formats library asset names into Chinese-readable labels', () => {
    expect(formatAudioAssetNameLabel('book_page_close_detail_01')).toBe('书页 合上 细节 01')
    expect(formatAudioAssetNameLabel('medicine_pill_bottle_shake_long')).toBe('药片 瓶子 摇晃 长版')
    expect(formatAudioAssetNameLabel('phase_jump_arcane_05')).toBe('相位 跳跃 奥术 05')
  })

  it('hides license-like tags from the compact user-facing summary', () => {
    expect(getVisibleSfxTags(['mystery', 'cc0', 'paper', 'license_commercial'])).toEqual([
      'mystery',
      'paper',
    ])
  })

  it('formats music duration for compact screening labels', () => {
    expect(formatMusicDurationLabel(45)).toBe('45 秒')
    expect(formatMusicDurationLabel(12.6)).toBe('13 秒')
    expect(formatMusicDurationLabel(Number.NaN)).toBe('时长未知')
  })

  it('keeps copyright and source metadata in detail rows instead of summary chips', () => {
    const items = buildAudioLibraryDetailItems({
      source: 'local_authorized',
      license: 'CC0',
      license_url: 'https://example.test/license',
      license_commercial: true,
      attribution_required: false,
      author: 'Little Robot Sound Factory',
      author_url: 'https://example.test/author',
      quality_score: 100,
      quality_grade: 'B',
      quality_status: 'accepted',
      retrieved_at: '2026-05-11T12:30:00Z',
      license_checked_at: '2026-05-12T12:30:00Z',
    })

    expect(items).toEqual([
      { key: 'quality', label: '质量', value: '100.0 / B 已通过' },
      { key: 'license', label: '授权', value: 'CC0', title: 'https://example.test/license' },
      { key: 'commercial', label: '商用', value: '允许商用' },
      { key: 'attribution', label: '署名', value: '免署名' },
      {
        key: 'author',
        label: '作者',
        value: 'Little Robot Sound Factory',
        title: 'https://example.test/author',
      },
      { key: 'source', label: '来源', value: '本地授权素材' },
      { key: 'retrieved_at', label: '入库', value: '2026-05-11' },
      { key: 'license_checked_at', label: '授权检查', value: '2026-05-12' },
    ])
  })
})
