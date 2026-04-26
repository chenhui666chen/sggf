import { describe, expect, it, vi } from 'vitest'

import { buildUserCenterAssetConnectedOverviewViewModel } from '../user-assets/userCenterAssetConnectedOverviewViewModelHelper'

describe('userCenterAssetConnectedOverviewViewModelHelper', () => {
  it('builds source and section props through the composed helper chain', () => {
    const formatCurrencyLabel = vi.fn((value: number) => `CNY ${value.toFixed(2)}`)

    const viewModel = buildUserCenterAssetConnectedOverviewViewModel({
      pointsOverview: {
        connected_overview: {
          project_count: 7,
          user_asset_count: 0,
          audiobook_project_count: 5,
          audiobook_total_cost: 88,
          dreamweaver_run_count: 12,
        },
      },
      projectCount: 4,
      userAssetCount: 9,
      overviewMetrics: {
        audiobookProjects: 3,
      },
      formatCurrencyLabel,
    })

    expect(formatCurrencyLabel).toHaveBeenCalledWith(88)
    expect(viewModel.source).toEqual({
      projectCount: 7,
      audiobookProjectCount: 5,
      audiobookTotalCost: 88,
      dreamweaverRunCount: 12,
    })
    expect(viewModel.sectionProps).toEqual({
      items: [
        expect.objectContaining({ key: 'connected-project-count', value: 7 }),
        expect.objectContaining({ key: 'connected-user-asset-count', value: 9 }),
        expect.objectContaining({ key: 'connected-audiobook-project-count', value: 5 }),
        expect.objectContaining({ key: 'connected-audiobook-total-cost', value: 'CNY 88.00' }),
        expect.objectContaining({ key: 'connected-dreamweaver-run-count', value: 12 }),
      ],
    })
  })

  it('uses fallback source values before building section props', () => {
    const viewModel = buildUserCenterAssetConnectedOverviewViewModel({
      pointsOverview: null,
      projectCount: 6,
      userAssetCount: 10,
      overviewMetrics: {
        audiobookProjects: 4,
      },
      formatCurrencyLabel: (value) => `CNY ${value.toFixed(2)}`,
    })

    expect(viewModel.source).toEqual({
      projectCount: 6,
      audiobookProjectCount: 4,
      audiobookTotalCost: 0,
      dreamweaverRunCount: 0,
    })
    expect(viewModel.sectionProps).toEqual({
      items: [
        expect.objectContaining({ key: 'connected-project-count', value: 6 }),
        expect.objectContaining({ key: 'connected-user-asset-count', value: 10 }),
        expect.objectContaining({ key: 'connected-audiobook-project-count', value: 4 }),
        expect.objectContaining({ key: 'connected-audiobook-total-cost', value: 'CNY 0.00' }),
        expect.objectContaining({ key: 'connected-dreamweaver-run-count', value: 0 }),
      ],
    })
  })
})
