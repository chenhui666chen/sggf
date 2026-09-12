import { beforeAll, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import type { i18n as I18nInstance } from 'i18next'

import { bootstrapI18n, I18nProvider } from '@/i18n'

import UserAssetWorkspaceContent from '../user-assets/UserAssetWorkspaceContent'

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
 * 工作区里的本地目录面板与资产卡片都会读当前界面语言（时间文案跟着语言走），
 * 因此渲染必须包一层 I18nProvider，与 main.tsx 的层级一致。
 */
let i18nInstance: I18nInstance

beforeAll(async () => {
  i18nInstance = await bootstrapI18n('zh-CN')
})

function renderWithI18n(node: ReactElement): string {
  return renderToStaticMarkup(<I18nProvider instance={i18nInstance}>{node}</I18nProvider>)
}

describe('UserAssetWorkspaceContent', () => {
  it('能渲染资产工作区概览、诊断提示与空态文案', () => {
    const text = extractVisibleText(renderWithI18n(
      <UserAssetWorkspaceContent
        workspaceSectionProps={{
          overviewMetrics: [
            {
              key: 'active-assets',
              title: '活跃资产',
              value: 0,
              helper: '用于验证内容容器渲染。',
              color: '#2563eb',
            },
          ],
          listSection: {
            filterToolbar: {
              filters: {
                viewFilter: 'all',
                kindFilter: 'all',
                sourceFilter: 'all',
                archiveFilter: 'active',
                tagFilter: 'all',
              },
              kindOptions: [],
              sourceOptions: [],
              tagOptions: [],
              filteredCount: 0,
              onViewFilterChange: vi.fn(),
              onKindFilterChange: vi.fn(),
              onSourceFilterChange: vi.fn(),
              onArchiveFilterChange: vi.fn(),
              onTagFilterChange: vi.fn(),
              onRefresh: vi.fn(),
            },
            batchToolbar: null,
            localStoragePanel: {
              status: {
                supported: true,
                configured: false,
                directoryName: null,
                permission: 'unknown',
              },
              healthSummary: null,
              submittingLabel: null,
              lastActionReport: null,
              loading: false,
              submitting: false,
              onRefresh: vi.fn(),
              onExportLocalAssetInventory: vi.fn(),
              onRestoreMissingLocalCopies: vi.fn(),
              onRestoreIssueItem: vi.fn(),
              onPreviewFilteredMissingLocalCopies: vi.fn(),
              onRestoreFilteredMissingLocalCopies: vi.fn(),
              onExportLocalAssetRebuildList: vi.fn(),
              onPickDirectory: vi.fn(),
              onRecoverAccess: vi.fn(),
              onClearDirectory: vi.fn(),
            },
            statusNotices: [
              {
                severity: 'warning',
                text: '检测到本地副本迁移未完全完成',
              },
              {
                severity: 'warning',
                text: '已记录用户目录“Novel Assets”，但当前权限已失效。',
              },
            ],
            warningMessage: null,
            isLoading: false,
            hasAssets: false,
            hasFilteredAssets: false,
            emptyCollectionMessage: '暂无资产可展示',
            emptyFilterMessage: '当前筛选下暂无资产',
          },
          editorDialog: {
            open: false,
            formData: {
              title: '',
              description: '',
              tagsText: '',
            },
            hasAsset: false,
            onClose: vi.fn(),
            onSave: vi.fn(),
            onFormDataChange: vi.fn(),
          },
        }}
        cardsGridProps={{
          assets: [],
          assetSelectionState: {
            selectedAssetIdSet: new Set<number>(),
          },
          onToggleSelection: vi.fn(),
          onNavigateToPath: vi.fn(),
          onEditAsset: vi.fn(),
          onRestoreLocalCopyAsset: vi.fn(),
          onClearLocalCopyAsset: vi.fn(),
          onUpdateAsset: vi.fn(),
        }}
      />,
    ))

    expect(text).toContain('活跃资产')
    expect(text).toContain('资产视角')
    expect(text).toContain('用户目录存储')
    expect(text).toContain('当前优先入口：Asset Studio 显式收录、Audiobook 手动收录')
    expect(text).toContain('刷新资产')
    expect(text).toContain('检测到本地副本迁移未完全完成')
    expect(text).toContain('已记录用户目录“Novel Assets”，但当前权限已失效。')
    expect(text).toContain('暂无资产可展示')
  })
})
