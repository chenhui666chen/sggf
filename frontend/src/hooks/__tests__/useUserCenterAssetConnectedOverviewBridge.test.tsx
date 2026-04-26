import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  buildUserCenterAssetConnectedOverviewBridge,
  useUserCenterAssetConnectedOverviewBridge,
} from '../useUserCenterAssetConnectedOverviewBridge'

describe('useUserCenterAssetConnectedOverviewBridge', () => {
  it('builds a bridge from connected overview view-model output', () => {
    expect(buildUserCenterAssetConnectedOverviewBridge({
      sectionProps: {
        items: [
          {
            key: 'connected-project-count',
            label: '项目数',
            value: 3,
          },
        ],
      },
    })).toEqual({
      sectionProps: {
        items: [
          {
            key: 'connected-project-count',
            label: '项目数',
            value: 3,
          },
        ],
      },
    })
  })

  it('adapts page inputs into reusable section props through the hook', () => {
    let capturedBridge:
      | ReturnType<typeof useUserCenterAssetConnectedOverviewBridge>
      | null = null

    function Harness() {
      capturedBridge = useUserCenterAssetConnectedOverviewBridge({
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
        formatCurrencyLabel: (value) => `CNY ${value.toFixed(2)}`,
      })

      return null
    }

    renderToStaticMarkup(<Harness />)

    expect(capturedBridge).toEqual({
      sectionProps: {
        items: [
          expect.objectContaining({ key: 'connected-project-count', value: 7 }),
          expect.objectContaining({ key: 'connected-user-asset-count', value: 9 }),
          expect.objectContaining({ key: 'connected-audiobook-project-count', value: 5 }),
          expect.objectContaining({ key: 'connected-audiobook-total-cost', value: 'CNY 88.00' }),
          expect.objectContaining({ key: 'connected-dreamweaver-run-count', value: 12 }),
        ],
      },
    })
  })
})
