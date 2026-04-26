import { describe, expect, it, vi } from 'vitest'

import { buildUserCenterAssetFacade } from '../user-assets/userCenterAssetFacadeHelper'

describe('userCenterAssetFacadeHelper', () => {
  it('builds an asset facade from workspace content props and refresh action', () => {
    const refreshUserCenterAssets = vi.fn()
    const workspaceContentProps = {
      workspaceSectionProps: {
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
          emptyFilterMessage: '暂无结果',
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
      },
      cardsGridProps: {
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
      },
    }

    expect(buildUserCenterAssetFacade({
      userAssetCount: 7,
      refreshUserCenterAssets,
      workspaceContentProps,
    })).toEqual({
      userAssetCount: 7,
      refreshUserCenterAssets,
      workspaceContentProps,
    })
  })
})
