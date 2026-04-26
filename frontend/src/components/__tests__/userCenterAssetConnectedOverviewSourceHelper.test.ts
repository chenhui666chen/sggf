import { describe, expect, it } from 'vitest'

import { buildUserCenterAssetConnectedOverviewSource } from '../user-assets/userCenterAssetConnectedOverviewSourceHelper'

describe('userCenterAssetConnectedOverviewSourceHelper', () => {
  it('builds connected overview source from points overview fields', () => {
    expect(buildUserCenterAssetConnectedOverviewSource({
      pointsOverview: {
        connected_overview: {
          project_count: 7,
          user_asset_count: 9,
          audiobook_project_count: 5,
          audiobook_total_cost: 88,
          dreamweaver_run_count: 12,
        },
      },
      projectCount: 4,
      overviewMetrics: {
        audiobookProjects: 3,
      },
    })).toEqual({
      projectCount: 7,
      audiobookProjectCount: 5,
      audiobookTotalCost: 88,
      dreamweaverRunCount: 12,
    })
  })

  it('falls back to page values when connected overview fields are absent or invalid', () => {
    expect(buildUserCenterAssetConnectedOverviewSource({
      pointsOverview: {
        connected_overview: {
          project_count: -1,
          user_asset_count: 0,
          audiobook_project_count: Number.NaN,
          audiobook_total_cost: -5,
          dreamweaver_run_count: Number.POSITIVE_INFINITY,
        },
      },
      projectCount: 6,
      overviewMetrics: {
        audiobookProjects: 4,
      },
    })).toEqual({
      projectCount: 6,
      audiobookProjectCount: 4,
      audiobookTotalCost: 0,
      dreamweaverRunCount: 0,
    })
  })
})
