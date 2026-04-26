import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import UserAssetListSection from '../user-assets/UserAssetListSection'

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

function createFilterToolbarProps() {
  return {
    filters: {
      viewFilter: 'all' as const,
      kindFilter: 'all',
      sourceFilter: 'all',
      archiveFilter: 'active' as const,
      tagFilter: 'all',
    },
    kindOptions: ['image', 'video'],
    sourceOptions: [{ value: 'asset_studio', label: '资产工坊' }],
    tagOptions: ['角色'],
    filteredCount: 42,
    loading: false,
    onViewFilterChange: vi.fn(),
    onKindFilterChange: vi.fn(),
    onSourceFilterChange: vi.fn(),
    onArchiveFilterChange: vi.fn(),
    onTagFilterChange: vi.fn(),
    onRefresh: vi.fn(),
  }
}

describe('UserAssetListSection', () => {
  it('renders the pagination summary and navigation when paginated assets are visible', () => {
    const markup = renderToStaticMarkup(
      <UserAssetListSection
        filterToolbar={createFilterToolbarProps()}
        warningMessage={null}
        isLoading={false}
        hasAssets
        hasFilteredAssets
        pagination={{
          page: 2,
          totalPages: 5,
          totalItems: 42,
          pageSize: 24,
          currentPageCount: 18,
          onPageChange: vi.fn(),
        }}
        emptyCollectionMessage="暂无资产"
        emptyFilterMessage="当前筛选无结果"
      >
        <div>asset-card</div>
      </UserAssetListSection>,
    )

    const text = extractVisibleText(markup)

    expect(text).toContain('第 2 / 5 页，共 42 条，当前展示 18 条，每页 24 条')
    expect(markup).toContain('pagination navigation')
  })

  it('does not render pagination when the collection is empty', () => {
    const markup = renderToStaticMarkup(
      <UserAssetListSection
        filterToolbar={createFilterToolbarProps()}
        warningMessage={null}
        isLoading={false}
        hasAssets={false}
        hasFilteredAssets={false}
        pagination={{
          page: 1,
          totalPages: 0,
          totalItems: 0,
          pageSize: 24,
          currentPageCount: 0,
          onPageChange: vi.fn(),
        }}
        emptyCollectionMessage="暂无资产"
        emptyFilterMessage="当前筛选无结果"
      >
        <div>asset-card</div>
      </UserAssetListSection>,
    )

    const text = extractVisibleText(markup)

    expect(text).toContain('暂无资产')
    expect(markup).not.toContain('pagination navigation')
  })
})
