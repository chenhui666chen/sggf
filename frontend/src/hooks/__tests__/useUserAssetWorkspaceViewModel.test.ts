import { describe, expect, it, vi } from 'vitest'

import type { UserAssetCardsGridProps } from '@/components/user-assets/UserAssetCardsGrid'
import type { UserAssetRecord } from '@/services/api'

import {
  buildUserAssetCardsGridProps,
  buildUserAssetWorkspaceContentProps,
  resolveUserAssetWorkspacePreviewAssets,
  resolveUserAssetWorkspaceNavigationPath,
} from '../useUserAssetWorkspaceViewModel'

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

describe('useUserAssetWorkspaceViewModel helpers', () => {
  it('resolves empty navigation paths to the fallback path', () => {
    expect(resolveUserAssetWorkspaceNavigationPath(' /drama/7 ')).toBe('/drama/7')
    expect(resolveUserAssetWorkspaceNavigationPath('   ', '/fallback')).toBe('/fallback')
    expect(resolveUserAssetWorkspaceNavigationPath(undefined, '/fallback')).toBe('/fallback')
  })

  it('builds cards grid props from workspace state and preview object urls', () => {
    const assets = [createUserAssetRecord({ id: 7 })]
    const onToggleSelection = vi.fn()
    const onNavigateToPath = vi.fn()
    const onEditAsset = vi.fn()
    const onRestoreLocalCopyAsset = vi.fn()
    const onClearLocalCopyAsset = vi.fn()
    const onUpdateAsset = vi.fn()

    const props = buildUserAssetCardsGridProps({
      filteredUserAssets: assets,
      projectTitleMap: new Map([[3, '海城剧场']]),
      assetActionKey: 'asset-7',
      assetBatchSubmitting: true,
      assetSelectionState: {
        selectedAssetIdSet: new Set([7]),
      } as UserAssetCardsGridProps['assetSelectionState'],
      previewObjectUrls: {
        localObjectUrls: { 7: 'blob:local-preview' },
        protectedObjectUrls: { 7: 'blob:protected-preview' },
      },
      handleToggleAssetSelection: onToggleSelection,
      onNavigateToPath,
      handleOpenAssetEditor: onEditAsset,
      handleRestoreLocalAssetCopy: onRestoreLocalCopyAsset,
      handleClearLocalAssetCopy: onClearLocalCopyAsset,
      handleUpdateUserAsset: onUpdateAsset,
    })

    expect(props.assets).toBe(assets)
    expect(props.assetActionKey).toBe('asset-7')
    expect(props.assetBatchSubmitting).toBe(true)
    expect(props.assetSelectionState.selectedAssetIdSet.has(7)).toBe(true)
    expect(props.previewObjectUrls).toEqual({
      localObjectUrls: { 7: 'blob:local-preview' },
      protectedObjectUrls: { 7: 'blob:protected-preview' },
    })
    expect(props.onToggleSelection).toBe(onToggleSelection)
    expect(props.onNavigateToPath).toBe(onNavigateToPath)
    expect(props.onEditAsset).toBe(onEditAsset)
    expect(props.onRestoreLocalCopyAsset).toBe(onRestoreLocalCopyAsset)
    expect(props.onClearLocalCopyAsset).toBe(onClearLocalCopyAsset)
    expect(props.onUpdateAsset).toBe(onUpdateAsset)
  })

  it('builds workspace content props from section props and cards grid props', () => {
    const workspaceSectionProps = {
      overviewMetrics: [],
      listSection: {
        filterToolbar: {
          filters: {
            viewFilter: 'all' as const,
            kindFilter: 'all',
            sourceFilter: 'all',
            archiveFilter: 'active' as const,
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
        localStoragePanel: null,
        statusNotices: [],
        warningMessage: null,
        isLoading: false,
        hasAssets: false,
        hasFilteredAssets: false,
        emptyCollectionMessage: '暂无资产',
        emptyFilterMessage: '暂无筛选结果',
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
    }
    const cardsGridProps = {
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
    } as UserAssetCardsGridProps
    const onNavigateToIssueSource = vi.fn()

    expect(buildUserAssetWorkspaceContentProps({
      workspaceSectionProps,
      cardsGridProps,
      onNavigateToIssueSource,
    })).toEqual({
      workspaceSectionProps: {
        ...workspaceSectionProps,
        listSection: {
          ...workspaceSectionProps.listSection,
          localStoragePanel: workspaceSectionProps.listSection.localStoragePanel,
        },
      },
      cardsGridProps,
    })
  })

  it('injects issue-source navigation into the local storage panel when present', () => {
    const onNavigateToIssueSource = vi.fn()
    const workspaceSectionProps = {
      overviewMetrics: [],
      listSection: {
        filterToolbar: {
          filters: {
            viewFilter: 'all' as const,
            kindFilter: 'all',
            sourceFilter: 'all',
            archiveFilter: 'active' as const,
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
          status: null,
          healthSummary: null,
          submittingLabel: null,
          lastActionReport: null,
          loading: false,
          submitting: false,
          onRefresh: vi.fn(),
          onExportLocalAssetInventory: vi.fn(),
          onExportLocalAssetRebuildList: vi.fn(),
          onRestoreMissingLocalCopies: vi.fn(),
          onRestoreIssueItem: vi.fn(),
          onPreviewFilteredMissingLocalCopies: vi.fn(),
          onRestoreFilteredMissingLocalCopies: vi.fn(),
          onPickDirectory: vi.fn(),
          onRecoverAccess: vi.fn(),
          onClearDirectory: vi.fn(),
        },
        statusNotices: [],
        warningMessage: null,
        isLoading: false,
        hasAssets: false,
        hasFilteredAssets: false,
        emptyCollectionMessage: '暂无资产',
        emptyFilterMessage: '暂无筛选结果',
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
    }
    const cardsGridProps = {
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
    } as UserAssetCardsGridProps

    const result = buildUserAssetWorkspaceContentProps({
      workspaceSectionProps,
      cardsGridProps,
      onNavigateToIssueSource,
    })

    expect(result.workspaceSectionProps.listSection.localStoragePanel).toEqual(expect.objectContaining({
      onNavigateToIssueSource,
    }))
  })

  it('only exposes preview assets while the workspace is enabled', () => {
    const assets = [
      createUserAssetRecord({ id: 1 }),
      createUserAssetRecord({ id: 2, asset_uuid: 'asset-2' }),
    ]

    expect(resolveUserAssetWorkspacePreviewAssets(assets, true)).toBe(assets)
    expect(resolveUserAssetWorkspacePreviewAssets(assets, false)).toEqual([])
  })
})
