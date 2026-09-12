import { beforeAll, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import UserCenterAssetConnectedOverviewRow from '@/components/user-assets/UserCenterAssetConnectedOverviewRow'

import {
  useUserCenterAssetConnectedOverviewRowsFromInput,
  type UserCenterAssetConnectedOverviewRowsFromInputFacade,
} from '../useUserCenterAssetConnectedOverviewRowsFromInput'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('useUserCenterAssetConnectedOverviewRowsFromInput', () => {
  it('adapts page-facing input into reusable strategy and points rules row slots', () => {
    let capturedRows:
      | UserCenterAssetConnectedOverviewRowsFromInputFacade
      | null = null

    function Harness() {
      capturedRows = useUserCenterAssetConnectedOverviewRowsFromInput({
        pointsOverview: {
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
          connected_overview: {
            project_count: 7,
            user_asset_count: 0,
            audiobook_project_count: 5,
            audiobook_total_cost: 88,
            dreamweaver_run_count: 12,
          },
        },
        projects: [{ id: 1 }, { id: 2 }, { id: 3 }],
        userAssetCount: 9,
        overviewMetrics: {
          audiobookProjects: 3,
        },
        formatCurrencyLabel: (value) => `CNY ${value.toFixed(2)}`,
        formatPointsValueLabel: (value) => `P${value.toFixed(1)}`,
        formatUpdatedAtLabel: (value) => `FMT(${value})`,
        getSourceLabel: () => '后台规则快照',
        t,
      })

      return null
    }

    renderToStaticMarkup(<Harness />)

    if (!capturedRows) {
      throw new Error('expected rows to be captured')
    }

    const rows: UserCenterAssetConnectedOverviewRowsFromInputFacade = capturedRows

    expect(rows.strategyRowSlot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(rows.pointsRulesRowSlot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(rows.pointsRulesRowSlot.props.companionTitle).toBe('当前积分规则')
    expect(renderToStaticMarkup(rows.pointsRulesRowSlot)).toContain('后台规则快照')
    expect(renderToStaticMarkup(rows.pointsRulesRowSlot)).toContain('最近更新：FMT(2026-04-24T00:00:00Z)')
  })

  it('derives projectCount from projects length before building rows', () => {
    let capturedRows:
      | UserCenterAssetConnectedOverviewRowsFromInputFacade
      | null = null

    function Harness() {
      capturedRows = useUserCenterAssetConnectedOverviewRowsFromInput({
        pointsOverview: null,
        projects: [{ id: 1 }, { id: 2 }],
        userAssetCount: 5,
        overviewMetrics: {
          audiobookProjects: 1,
        },
        formatCurrencyLabel: (value) => `CNY ${value.toFixed(2)}`,
        formatPointsValueLabel: (value) => `${value}`,
        formatUpdatedAtLabel: (value) => value,
        getSourceLabel: () => '默认规则',
        t,
      })

      return null
    }

    renderToStaticMarkup(<Harness />)

    if (!capturedRows) {
      throw new Error('expected rows to be captured')
    }

    const rows: UserCenterAssetConnectedOverviewRowsFromInputFacade = capturedRows
    const connectedProjectItem = rows.strategyRowSlot.props.overviewBridge.sectionProps.items.find(
      (item: { key: string }) => item.key === 'connected-project-count',
    )

    expect(connectedProjectItem).toEqual(expect.objectContaining({ value: 2 }))
  })
})
