import { describe, expect, it } from 'vitest'

import { buildUserCenterAssetConnectedOverviewRowsOptionsFromInput } from '../user-assets/userCenterAssetConnectedOverviewRowsInputHelper'

describe('userCenterAssetConnectedOverviewRowsInputHelper', () => {
  it('builds rows hook options from page-facing input and derives projectCount from projects', () => {
    const formatCurrencyLabel = (value: number) => `CNY ${value.toFixed(2)}`
    const formatPointsValueLabel = (value: number) => `P${value}`
    const formatUpdatedAtLabel = (value: string) => `FMT(${value})`
    const getSourceLabel = (source?: string | null) => source || '默认规则'

    const options = buildUserCenterAssetConnectedOverviewRowsOptionsFromInput({
      pointsOverview: {
        connected_overview: {
          project_count: 7,
          user_asset_count: 0,
          audiobook_project_count: 5,
          audiobook_total_cost: 88,
          dreamweaver_run_count: 12,
        },
        points_rules: {
          reusable_asset_reward: 2,
          deliverable_asset_reward: 4,
          audiobook_completion_reward: 6,
          dreamweaver_completion_reward: 8,
          running_audiobook_frozen: 10,
          running_dreamweaver_frozen: 12,
          reward_ttl_days: 30,
          expiring_notice_days: 7,
          source: 'admin_log',
          updated_at: '2026-04-24T00:00:00Z',
          updated_by_user_id: 1,
          updated_by_username: 'ops',
        },
      },
      projects: [{ id: 1 }, { id: 2 }, { id: 3 }],
      userAssetCount: 9,
      overviewMetrics: {
        audiobookProjects: 3,
      },
      formatCurrencyLabel,
      formatPointsValueLabel,
      formatUpdatedAtLabel,
      getSourceLabel,
    })

    expect(options).toEqual({
      pointsOverview: {
        connected_overview: {
          project_count: 7,
          user_asset_count: 0,
          audiobook_project_count: 5,
          audiobook_total_cost: 88,
          dreamweaver_run_count: 12,
        },
        points_rules: {
          reusable_asset_reward: 2,
          deliverable_asset_reward: 4,
          audiobook_completion_reward: 6,
          dreamweaver_completion_reward: 8,
          running_audiobook_frozen: 10,
          running_dreamweaver_frozen: 12,
          reward_ttl_days: 30,
          expiring_notice_days: 7,
          source: 'admin_log',
          updated_at: '2026-04-24T00:00:00Z',
          updated_by_user_id: 1,
          updated_by_username: 'ops',
        },
      },
      projectCount: 3,
      userAssetCount: 9,
      overviewMetrics: {
        audiobookProjects: 3,
      },
      formatCurrencyLabel,
      formatPointsValueLabel,
      formatUpdatedAtLabel,
      getSourceLabel,
    })
  })

  it('falls back to zero projectCount when projects are unavailable', () => {
    expect(buildUserCenterAssetConnectedOverviewRowsOptionsFromInput({
      pointsOverview: null,
      projects: null,
      userAssetCount: 10,
      overviewMetrics: {
        audiobookProjects: 4,
      },
      formatCurrencyLabel: (value) => `CNY ${value.toFixed(2)}`,
      formatPointsValueLabel: (value) => `${value}`,
      formatUpdatedAtLabel: (value) => value,
      getSourceLabel: () => '默认规则',
    })).toEqual({
      pointsOverview: null,
      projectCount: 0,
      userAssetCount: 10,
      overviewMetrics: {
        audiobookProjects: 4,
      },
      formatCurrencyLabel: expect.any(Function),
      formatPointsValueLabel: expect.any(Function),
      formatUpdatedAtLabel: expect.any(Function),
      getSourceLabel: expect.any(Function),
    })
  })
})
