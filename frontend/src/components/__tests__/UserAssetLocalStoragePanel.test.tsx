import { beforeAll, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import type { i18n as I18nInstance } from 'i18next'

import { I18nProvider, bootstrapI18n } from '@/i18n'
import type { UserAssetRecord } from '@/services/api'

import UserAssetLocalStoragePanel from '../user-assets/UserAssetLocalStoragePanel'
import {
  buildUserAssetLocalStorageActionReport,
  buildUserAssetLocalStorageBackupGuide,
  buildUserAssetLocalStorageInventoryExport,
  buildUserAssetLocalStorageRebuildListExport,
} from '../user-assets/userAssetLocalStoragePanelPresentation'

function extractVisibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * 面板会读当前界面语言（导出的备份说明里时间要跟着语言走），因此渲染必须
 * 包一层 I18nProvider，与 main.tsx 的层级一致。
 */
let i18nInstance: I18nInstance

beforeAll(async () => {
  i18nInstance = await bootstrapI18n('zh-CN')
})

function renderWithI18n(node: ReactElement): string {
  return renderToStaticMarkup(<I18nProvider instance={i18nInstance}>{node}</I18nProvider>)
}

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

describe('UserAssetLocalStoragePanel', () => {
  it('在未配置目录时展示选择入口与说明', () => {
    const text = extractVisibleText(renderWithI18n(
      <UserAssetLocalStoragePanel
        status={{
          supported: true,
          configured: false,
          directoryName: null,
          permission: 'unknown',
        }}
        submittingLabel={null}
        lastActionReport={null}
        loading={false}
        submitting={false}
        onRefresh={vi.fn()}
        onExportLocalAssetInventory={vi.fn()}
        onRestoreMissingLocalCopies={vi.fn()}
        onRestoreIssueItem={vi.fn()}
        onNavigateToIssueSource={vi.fn()}
        onPreviewFilteredMissingLocalCopies={vi.fn()}
        onRestoreFilteredMissingLocalCopies={vi.fn()}
        onExportLocalAssetRebuildList={vi.fn()}
        onPickDirectory={vi.fn()}
        onRecoverAccess={vi.fn()}
        onClearDirectory={vi.fn()}
      />,
    ))

    expect(text).toContain('用户目录存储')
    expect(text).toContain('尚未配置用户目录')
    expect(text).toContain('状态：未配置')
    expect(text).toContain('选择目录')
    expect(text).toContain('当前优先入口：Asset Studio 显式收录、Audiobook 手动收录')
    expect(text).toContain('仍走浏览器存储：播放器试听缓存等自动本地缓存')
    expect(text).toContain('待重建清单：当前没有待导出的重建项。')
    expect(text).toContain('跨页重建：可按当前筛选条件补扫全部分页结果，并尝试重建其中缺失的本地副本。')
    expect(text).toContain('导出本地资产清单')
    expect(text).toContain('扫描当前筛选（预览）')
    expect(text).toContain('扫描当前筛选并重建')
    expect(text).toContain('导出重建清单')
    expect(text).toContain('导出备份说明')
  })

  it('在目录可用时展示已连接状态、导出入口与备份建议', () => {
    const text = extractVisibleText(renderWithI18n(
      <UserAssetLocalStoragePanel
        status={{
          supported: true,
          configured: true,
          directoryName: 'Novel Assets',
          permission: 'granted',
        }}
        submittingLabel={null}
        lastActionReport={null}
        loading={false}
        submitting={false}
        onRefresh={vi.fn()}
        onExportLocalAssetInventory={vi.fn()}
        onRestoreMissingLocalCopies={vi.fn()}
        onRestoreIssueItem={vi.fn()}
        onNavigateToIssueSource={vi.fn()}
        onPreviewFilteredMissingLocalCopies={vi.fn()}
        onRestoreFilteredMissingLocalCopies={vi.fn()}
        onExportLocalAssetRebuildList={vi.fn()}
        onPickDirectory={vi.fn()}
        onRecoverAccess={vi.fn()}
        onClearDirectory={vi.fn()}
      />,
    ))

    expect(text).toContain('已连接用户目录：Novel Assets')
    expect(text).toContain('状态：已连接')
    expect(text).toContain('已记录目录：Novel Assets')
    expect(text).toContain('更换目录')
    expect(text).toContain('备份建议：该目录已经是真实系统目录，可直接纳入你自己的常规文件备份或同步流程。')
    expect(text).toContain('清除目录配置')
    expect(text).toContain('导出本地资产清单')
    expect(text).toContain('重建当前页缺失副本')
    expect(text).toContain('扫描当前筛选（预览）')
    expect(text).toContain('扫描当前筛选并重建')
    expect(text).toContain('导出重建清单')
    expect(text).toContain('导出备份说明')
    expect(text).toContain('刷新状态')
  })

  it('在权限失效时展示恢复访问入口', () => {
    const text = extractVisibleText(renderWithI18n(
      <UserAssetLocalStoragePanel
        status={{
          supported: true,
          configured: true,
          directoryName: 'Novel Assets',
          permission: 'denied',
        }}
        submittingLabel={null}
        lastActionReport={null}
        loading={false}
        submitting={false}
        onRefresh={vi.fn()}
        onExportLocalAssetInventory={vi.fn()}
        onRestoreMissingLocalCopies={vi.fn()}
        onRestoreIssueItem={vi.fn()}
        onNavigateToIssueSource={vi.fn()}
        onPreviewFilteredMissingLocalCopies={vi.fn()}
        onRestoreFilteredMissingLocalCopies={vi.fn()}
        onExportLocalAssetRebuildList={vi.fn()}
        onPickDirectory={vi.fn()}
        onRecoverAccess={vi.fn()}
        onClearDirectory={vi.fn()}
      />,
    ))

    expect(text).toContain('当前权限已失效')
    expect(text).toContain('状态：权限失效')
    expect(text).toContain('恢复访问')
    expect(text).toContain('恢复建议：先尝试“恢复访问”，如果浏览器仍拒绝，再重新选择目录。')
    expect(text).toContain('备份建议：恢复访问后，建议再确认该目录中的资产文件是否已纳入你的常规备份流程。')
    expect(text).toContain('重新选择目录')
  })

  it('在存在缺失副本时展示重建清单提示', () => {
    const healthSummary = {
      trackedAssetCount: 3,
      inaccessibleAssetCount: 1,
      missingLocalCopyCount: 1,
      inaccessibleAssets: [
        {
          assetId: 11,
          assetUuid: 'asset-11',
          title: '目录不可访问资产',
          sourceModule: 'asset_studio',
          localStorageDriver: 'external_directory',
          localStoragePath: 'images/asset-11.png',
          externalRelativePath: 'images/asset-11.png',
          sourceUri: 'https://example.com/source-11.png',
          previewUri: 'https://example.com/preview-11.png',
          downloadUri: 'https://example.com/download-11.png',
        },
      ],
      missingLocalCopyAssets: [
        {
          assetId: 12,
          assetUuid: 'asset-12',
          title: '缺失副本资产',
          sourceModule: 'audiobook',
          localStorageDriver: 'external_directory',
          localStoragePath: 'audio/asset-12.mp3',
          externalRelativePath: 'audio/asset-12.mp3',
          sourceUri: 'https://example.com/source-12.mp3',
          previewUri: 'https://example.com/preview-12.mp3',
          downloadUri: 'https://example.com/download-12.mp3',
        },
      ],
    }

    const text = extractVisibleText(renderWithI18n(
      <UserAssetLocalStoragePanel
        status={{
          supported: true,
          configured: true,
          directoryName: 'Novel Assets',
          permission: 'granted',
        }}
        healthSummary={healthSummary}
        submittingLabel="正在扫描当前筛选并校验目录副本..."
        lastActionReport={buildUserAssetLocalStorageActionReport({
          mode: 'restore',
          scope: 'filtered_scope',
          scannedAssetCount: 24,
          trackedAssetCount: 5,
          missingLocalCopyCount: 2,
          inaccessibleAssetCount: 1,
          restoredCount: 1,
          existingCount: 1,
          blockedCount: 0,
          failedCount: 0,
          healthSummary,
          t: i18nInstance.t.bind(i18nInstance),
          issueAssets: [
            createUserAssetRecord({
              id: 11,
              asset_uuid: 'asset-11',
              asset_kind: 'image',
              title: '目录不可访问资产',
              source_module: 'asset_studio',
              metadata_json: {
                local_storage_driver: 'external_directory',
                local_storage_path: 'images/asset-11.png',
                external_relative_path: 'images/asset-11.png',
              },
            }),
            createUserAssetRecord({
              id: 12,
              project_id: 8,
              asset_uuid: 'asset-12',
              asset_kind: 'audio',
              title: '缺失副本资产',
              source_module: 'audiobook',
              mime_type: 'audio/mpeg',
              file_size: 2048,
              source_uri: 'https://example.com/source-12.mp3',
              preview_uri: 'https://example.com/preview-12.mp3',
              download_uri: 'https://example.com/download-12.mp3',
              metadata_json: {
                local_storage_driver: 'external_directory',
                local_storage_path: 'audio/asset-12.mp3',
                external_relative_path: 'audio/asset-12.mp3',
              },
            }),
          ],
          completedAt: new Date('2026-04-25T00:20:00Z'),
        })}
        loading={false}
        submitting={false}
        onRefresh={vi.fn()}
        onExportLocalAssetInventory={vi.fn()}
        onRestoreMissingLocalCopies={vi.fn()}
        onRestoreIssueItem={vi.fn()}
        onNavigateToIssueSource={vi.fn()}
        onPreviewFilteredMissingLocalCopies={vi.fn()}
        onRestoreFilteredMissingLocalCopies={vi.fn()}
        onExportLocalAssetRebuildList={vi.fn()}
        onPickDirectory={vi.fn()}
        onRecoverAccess={vi.fn()}
        onClearDirectory={vi.fn()}
      />,
    ))

    expect(text).toContain('待重建清单：当前有 2 项待处理记录，可导出重建清单后逐项补录。')
    expect(text).toContain('当前页缺失副本：检测到 1 项可尝试直接重新收录到本地。')
    expect(text).toContain('当前页目录异常：有 1 项登记为用户目录副本，需先恢复目录访问后再校验或重建。')
    expect(text).toContain('正在扫描当前筛选并校验目录副本...')
    expect(text).toContain('当前筛选重建结果')
    expect(text).toContain('已扫描当前筛选 24 项资产，5 项登记为用户目录副本，其中 2 项缺失副本已进入重建流程。')
    expect(text).toContain('已扫描：24')
    expect(text).toContain('目录副本：5')
    expect(text).toContain('缺失副本：2')
    expect(text).toContain('已恢复：1')
    expect(text).toContain('已存在：1')
    expect(text).toContain('目录异常：1')
    expect(text).toContain('以下为本次扫描命中的问题资产明细，便于回看处理范围与后续补录。')
    expect(text).toContain('本次扫描命中的缺失副本（1）')
    expect(text).toContain('目录异常明细（1）')
    expect(text).toContain('缺失副本资产')
    expect(text).toContain('目录不可访问资产')
    expect(text).toContain('来源：audiobook')
    expect(text).toContain('来源：asset_studio')
    expect(text).toContain('问题类型：缺失副本')
    expect(text).toContain('问题类型：目录异常')
    expect(text).toContain('资产 UUID：asset-12')
    expect(text).toContain('资产 UUID：asset-11')
    expect(text).toContain('目录相对路径：audio/asset-12.mp3')
    expect(text).toContain('目录相对路径：images/asset-11.png')
    expect(text).toContain('处理建议：从来源页重新收录该资产，补回用户目录中的长期副本。')
    expect(text).toContain('处理建议：先恢复用户目录访问，再重新验证目录副本；若目录已迁移，请重新选择目录并按来源页重新收录。')
    expect(text).toContain('前往资产工坊')
    expect(text).toContain('回到有声书项目')
    expect(text).toContain('重新收录到本地')
    expect(text).toContain('重建当前页缺失副本')
    expect(text).toContain('扫描当前筛选（预览）')
    expect(text).toContain('扫描当前筛选并重建')
    expect(text).toContain('导出重建清单')
  })

  it('builds a local-storage action report for filtered preview runs', () => {
    const healthSummary = {
      trackedAssetCount: 12,
      inaccessibleAssetCount: 2,
      missingLocalCopyCount: 4,
      inaccessibleAssets: [
        {
          assetId: 31,
          assetUuid: 'asset-31',
          title: '目录暂不可访问',
          sourceModule: 'asset_studio',
          localStorageDriver: 'external_directory',
          localStoragePath: 'image/asset-31.png',
          externalRelativePath: 'image/asset-31.png',
          sourceUri: null,
          previewUri: null,
          downloadUri: null,
        },
      ],
      missingLocalCopyAssets: [
        {
          assetId: 32,
          assetUuid: 'asset-32',
          title: '待补录图片',
          sourceModule: 'audiobook',
          localStorageDriver: 'external_directory',
          localStoragePath: 'image/asset-32.png',
          externalRelativePath: 'image/asset-32.png',
          sourceUri: null,
          previewUri: null,
          downloadUri: null,
        },
      ],
    }

    const report = buildUserAssetLocalStorageActionReport({
      mode: 'preview',
      scope: 'filtered_scope',
      scannedAssetCount: 48,
      trackedAssetCount: 12,
      missingLocalCopyCount: 4,
      inaccessibleAssetCount: 2,
      restoredCount: 3,
      existingCount: 1,
      blockedCount: 0,
      failedCount: 0,
      healthSummary,
      t: i18nInstance.t.bind(i18nInstance),
      issueAssets: [
        createUserAssetRecord({
          id: 31,
          asset_uuid: 'asset-31',
          title: '目录暂不可访问',
          source_module: 'asset_studio',
          metadata_json: {
            local_storage_driver: 'external_directory',
            local_storage_path: 'image/asset-31.png',
            external_relative_path: 'image/asset-31.png',
          },
        }),
        createUserAssetRecord({
          id: 32,
          project_id: 18,
          asset_uuid: 'asset-32',
          title: '待补录图片',
          source_module: 'audiobook',
          metadata_json: {
            local_storage_driver: 'external_directory',
            local_storage_path: 'image/asset-32.png',
            external_relative_path: 'image/asset-32.png',
          },
        }),
      ],
      completedAt: new Date('2026-04-25T00:30:00Z'),
    })

    expect(report).toMatchObject({
      mode: 'preview',
      scope: 'filtered_scope',
      severity: 'warning',
      title: '当前筛选扫描结果',
      summary: '已扫描当前筛选 48 项资产，12 项登记为用户目录副本，其中 4 项缺失副本可执行重建。',
    })
    expect(report.metrics).toEqual([
      { key: 'scanned-assets', label: '已扫描', value: 48 },
      { key: 'tracked-assets', label: '目录副本', value: 12 },
      { key: 'missing-assets', label: '缺失副本', value: 4 },
      { key: 'restored-assets', label: '已恢复', value: 3 },
      { key: 'existing-assets', label: '已存在', value: 1 },
      { key: 'inaccessible-assets', label: '目录异常', value: 2 },
    ])
    expect(report.issueItems).toEqual([
      {
        key: 'missing_local_copy:32:asset-32',
        assetId: 32,
        issueType: 'missing_local_copy',
        title: '待补录图片',
        assetUuid: 'asset-32',
        sourceModule: 'audiobook',
        localStoragePath: 'image/asset-32.png',
        externalRelativePath: 'image/asset-32.png',
        actionHint: '从来源页重新收录该资产，补回用户目录中的长期副本。',
        restorableAsset: expect.objectContaining({
          id: 32,
          asset_uuid: 'asset-32',
          storage_mode: 'local_mirror',
        }),
        sourceActionPath: '/audiobook/18',
        sourceActionLabel: '回到有声书项目',
      },
      {
        key: 'directory_inaccessible:31:asset-31',
        assetId: 31,
        issueType: 'directory_inaccessible',
        title: '目录暂不可访问',
        assetUuid: 'asset-31',
        sourceModule: 'asset_studio',
        localStoragePath: 'image/asset-31.png',
        externalRelativePath: 'image/asset-31.png',
        actionHint: '先恢复用户目录访问，再重新验证目录副本；若目录已迁移，请重新选择目录并按来源页重新收录。',
        restorableAsset: expect.objectContaining({
          id: 31,
          asset_uuid: 'asset-31',
        }),
        sourceActionPath: '/asset-studio',
        sourceActionLabel: '前往资产工坊',
      },
    ])
  })

  it('builds a local-storage action report for filtered restore runs', () => {
    const report = buildUserAssetLocalStorageActionReport({
      mode: 'restore',
      scope: 'filtered_scope',
      scannedAssetCount: 48,
      trackedAssetCount: 12,
      missingLocalCopyCount: 4,
      inaccessibleAssetCount: 2,
      restoredCount: 3,
      existingCount: 1,
      blockedCount: 0,
      failedCount: 0,
      completedAt: new Date('2026-04-25T00:30:00Z'),
      t: i18nInstance.t.bind(i18nInstance),
    })

    expect(report).toMatchObject({
      severity: 'warning',
      title: '当前筛选重建结果',
      summary: '已扫描当前筛选 48 项资产，12 项登记为用户目录副本，其中 4 项缺失副本已进入重建流程。',
    })
  })

  it('builds an exportable backup guide from the current panel status', () => {
    const guide = buildUserAssetLocalStorageBackupGuide({
      status: {
        supported: true,
        configured: true,
        directoryName: 'Novel Assets',
        permission: 'granted',
      },
      loading: false,
      generatedAt: new Date('2026-04-24T12:34:56Z'),
      t: i18nInstance.t.bind(i18nInstance),
    })

    expect(guide).toContain('# 用户资产本地目录备份说明')
    expect(guide).toContain('当前状态：已连接')
    expect(guide).toContain('已记录目录：Novel Assets')
    expect(guide).toContain('## 当前优先入口')
    expect(guide).toContain('- Asset Studio 显式收录')
    expect(guide).toContain('- Audiobook 手动收录')
    expect(guide).toContain('## 恢复与备份建议')
    expect(guide).toContain('常规文件备份或同步流程')
    expect(guide).toContain('## 使用边界')
  })

  it('builds an exportable local asset inventory payload', () => {
    const inventory = JSON.parse(buildUserAssetLocalStorageInventoryExport({
      status: {
        supported: true,
        configured: true,
        directoryName: 'Novel Assets',
        permission: 'granted',
      },
      loading: false,
      inventory: [
        {
          assetUuid: 'asset-1',
          mediaKind: 'image',
          mimeType: 'image/png',
          fileSize: 128,
          sourceModule: 'asset_studio',
          title: '测试资产',
          sourceUri: 'https://example.com/source.png',
          previewUri: 'https://example.com/preview.png',
          downloadUri: 'https://example.com/download.png',
          metadata: {
            local_storage_driver: 'external_directory',
          },
          createdAt: '2026-04-24T00:00:00Z',
          updatedAt: '2026-04-24T12:00:00Z',
          storageDriver: 'external_directory' as const,
          storagePath: 'image/asset-1.png',
          externalRelativePath: 'image/asset-1.png',
          persistLevel: 'user_directory' as const,
        },
      ],
      generatedAt: new Date('2026-04-24T12:34:56Z'),
      t: i18nInstance.t.bind(i18nInstance),
    }))

    expect(inventory.directory_status.status_label).toBe('已连接')
    expect(inventory.summary.total_assets).toBe(1)
    expect(inventory.summary.storage_drivers.external_directory).toBe(1)
    expect(inventory.summary.persist_levels.user_directory).toBe(1)
    expect(inventory.items[0]).toMatchObject({
      asset_uuid: 'asset-1',
      storage_driver: 'external_directory',
      external_relative_path: 'image/asset-1.png',
    })
  })

  it('builds an exportable local asset rebuild list payload', () => {
    const rebuildList = JSON.parse(buildUserAssetLocalStorageRebuildListExport({
      status: {
        supported: true,
        configured: true,
        directoryName: 'Novel Assets',
        permission: 'prompt',
      },
      loading: false,
      healthSummary: {
        trackedAssetCount: 3,
        inaccessibleAssetCount: 1,
        missingLocalCopyCount: 1,
        inaccessibleAssets: [
          {
            assetId: 21,
            assetUuid: 'asset-21',
            title: '目录不可访问资产',
            sourceModule: 'asset_studio',
            localStorageDriver: 'external_directory',
            localStoragePath: 'image/asset-21.png',
            externalRelativePath: 'image/asset-21.png',
            sourceUri: 'https://example.com/source-21.png',
            previewUri: 'https://example.com/preview-21.png',
            downloadUri: 'https://example.com/download-21.png',
          },
        ],
        missingLocalCopyAssets: [
          {
            assetId: 22,
            assetUuid: 'asset-22',
            title: '缺失本地副本资产',
            sourceModule: 'audiobook',
            localStorageDriver: 'external_directory',
            localStoragePath: 'audio/asset-22.mp3',
            externalRelativePath: 'audio/asset-22.mp3',
            sourceUri: 'https://example.com/source-22.mp3',
            previewUri: 'https://example.com/preview-22.mp3',
            downloadUri: 'https://example.com/download-22.mp3',
          },
        ],
      },
      generatedAt: new Date('2026-04-24T12:34:56Z'),
      t: i18nInstance.t.bind(i18nInstance),
    }))

    expect(rebuildList.directory_status.status_label).toBe('待恢复授权')
    expect(rebuildList.summary).toMatchObject({
      tracked_assets: 3,
      inaccessible_asset_count: 1,
      missing_local_copy_count: 1,
      rebuild_candidate_count: 2,
    })
    expect(rebuildList.items).toHaveLength(2)
    expect(rebuildList.items[0]).toMatchObject({
      issue_type: 'directory_inaccessible',
      asset_id: 21,
      asset_uuid: 'asset-21',
      local_storage_driver: 'external_directory',
    })
    expect(rebuildList.items[1]).toMatchObject({
      issue_type: 'missing_local_copy',
      asset_id: 22,
      asset_uuid: 'asset-22',
      external_relative_path: 'audio/asset-22.mp3',
    })
  })
})
