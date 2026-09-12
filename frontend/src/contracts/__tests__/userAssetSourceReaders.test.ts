import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import type { UserAssetRecord } from '@/services/api'

import {
  formatDreamweaverViewLabel,
  getProtectedUserAssetRef,
  getUserAssetSourceInfo,
  getUserAssetSourceModule,
  isProtectedUserAsset,
} from '../userAssetSourceReaders'

function createUserAssetRecord(overrides: Partial<UserAssetRecord> = {}): UserAssetRecord {
  return {
    id: 1,
    user_id: 1,
    source_module: 'asset_studio',
    asset_kind: 'image',
    asset_class: 'reusable',
    asset_uuid: 'asset-1',
    storage_mode: 'local_mirror',
    title: 'asset',
    tags: [],
    is_favorite: false,
    created_at: '2026-04-23T00:00:00Z',
    updated_at: '2026-04-23T00:00:00Z',
    ...overrides,
  }
}

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetSourceReaders', () => {
  it('normalizes source module and dreamweaver view labels', () => {
    expect(getUserAssetSourceModule(createUserAssetRecord({ source_module: ' DreamWeaver_Library ' }))).toBe(
      'dreamweaver_library',
    )
    expect(formatDreamweaverViewLabel(' bust_three_quarter ', t)).toBe('半身四分之三侧')
    expect(formatDreamweaverViewLabel('', t)).toBeNull()
  })

  it('extracts protected asset refs only for supported protected source modules', () => {
    expect(
      getProtectedUserAssetRef(
        createUserAssetRecord({
          source_module: 'dreamweaver_library',
          source_payload_json: { asset_id: 12 },
        }),
      ),
    ).toEqual({
      kind: 'dreamweaver_library',
      libraryAssetId: 12,
    })

    expect(
      getProtectedUserAssetRef(
        createUserAssetRecord({
          source_module: 'dreamweaver_run',
          metadata_json: { run_id: 'run-22' },
        }),
      ),
    ).toEqual({
      kind: 'dreamweaver_run',
      runId: 'run-22',
    })

    expect(
      getProtectedUserAssetRef(
        createUserAssetRecord({
          source_module: 'audiobook',
          source_payload_json: {
            audiobook_project_id: 21,
            chapter_id: 7,
          },
        }),
      ),
    ).toEqual({
      kind: 'audiobook',
      audiobookProjectId: 21,
      chapterId: 7,
    })

    const assetStudioAsset = createUserAssetRecord({
      source_module: 'asset_studio',
      source_payload_json: { asset_id: 99, audiobook_project_id: 11, chapter_id: 4 },
      metadata_json: { run_id: 'ignored-run' },
    })
    expect(getProtectedUserAssetRef(assetStudioAsset)).toBeNull()
    expect(isProtectedUserAsset(assetStudioAsset)).toBe(false)
  })

  it('builds source info for asset studio and unknown assets', () => {
    const projectTitleMap = new Map([[8, '星海计划']])

    expect(
      getUserAssetSourceInfo(
        createUserAssetRecord({
          source_module: 'asset_studio',
          project_id: 8,
        }),
        projectTitleMap,
        t,
      ),
    ).toEqual({
      label: '资产工坊',
      summary: '来自资产工坊，关联项目：星海计划。',
      projectLabel: '星海计划',
      backPath: '/asset-studio',
      backLabel: '前往资产工坊',
    })

    expect(
      getUserAssetSourceInfo(
        createUserAssetRecord({
          source_module: 'custom_pipeline',
          project_id: 9,
        }),
        projectTitleMap,
        t,
      ),
    ).toEqual({
      label: 'custom_pipeline',
      summary: '该资产已进入用户中心统一治理，具体生产仍建议回到原模块处理。',
      projectLabel: '项目 #9',
    })
  })

  it('builds dreamweaver source info with trace labels and back links', () => {
    const projectTitleMap = new Map([[3, '海城剧场']])

    expect(
      getUserAssetSourceInfo(
        createUserAssetRecord({
          source_module: 'dreamweaver_library',
          project_id: 3,
          source_payload_json: {
            asset_id: 12,
          },
          metadata_json: {
            entity_type: 'character',
            view: 'bust_side',
          },
        }),
        projectTitleMap,
        t,
      ),
    ).toEqual({
      label: '短剧素材库',
      summary: '来自短剧素材库，沉淀于项目 海城剧场。',
      traceLabel: '角色 · 半身侧面',
      projectLabel: '海城剧场',
      backPath: '/drama/3/library?assetId=12',
      backLabel: '前往素材库',
    })

    expect(
      getUserAssetSourceInfo(
        createUserAssetRecord({
          source_module: 'dreamweaver_run',
          metadata_json: {
            project_id: 3,
            run_id: 'run-300',
          },
        }),
        projectTitleMap,
        t,
      ),
    ).toEqual({
      label: '短剧成片',
      summary: '来自短剧运行结果，关联项目：海城剧场。',
      traceLabel: 'run_id run-300',
      projectLabel: '海城剧场',
      backPath: '/drama/3?runId=run-300',
      backLabel: '回到短剧项目',
    })
  })

  it('builds audiobook source info with chapter trace and fallback navigation', () => {
    expect(
      getUserAssetSourceInfo(
        createUserAssetRecord({
          source_module: 'audiobook',
          source_payload_json: {
            audiobook_project_id: 21,
            chapter_id: 7,
          },
          metadata_json: {
            chapter_number: 3,
            chapter_title: '海上来信',
          },
        }),
        undefined,
        t,
      ),
    ).toEqual({
      label: '有声书音频',
      summary: '来自有声书章节成品。',
      traceLabel: '第3章 · 海上来信',
      projectLabel: null,
      backPath: '/audiobook-dashboard',
      backLabel: '前往有声书模块',
    })
  })

  it('builds project-scoped audiobook source info with deep-link query params', () => {
    const info = getUserAssetSourceInfo(
      createUserAssetRecord({
        source_module: 'audiobook',
        project_id: 5,
        source_payload_json: {
          audiobook_project_id: 21,
          chapter_id: 7,
        },
        metadata_json: {
          chapter_number: 3,
          chapter_title: '海上来信',
        },
      }),
      undefined,
      t,
    )

    expect(info.projectLabel).toContain('#5')
    expect(info.traceLabel).toContain('海上来信')
    expect(info.backPath).toBe('/audiobook/5?audiobookProjectId=21&chapterId=7&focus=script-editor')
  })
})
