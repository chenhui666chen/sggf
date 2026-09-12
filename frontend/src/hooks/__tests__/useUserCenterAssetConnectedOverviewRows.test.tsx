import { beforeAll, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import UserCenterAssetConnectedOverviewRow from '@/components/user-assets/UserCenterAssetConnectedOverviewRow'

import {
  buildUserCenterAssetConnectedOverviewRowsFacade,
  type UserCenterAssetConnectedOverviewRowsFacade,
  useUserCenterAssetConnectedOverviewRows,
} from '../useUserCenterAssetConnectedOverviewRows'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('useUserCenterAssetConnectedOverviewRows', () => {
  it('builds a facade from shared rows output', () => {
    const strategyRowSlot = <UserCenterAssetConnectedOverviewRow
      overviewBridge={{ sectionProps: { items: [] } }}
      companionTitle="资产接入策略"
      companionContent={<div>策略内容</div>}
    />
    const pointsRulesRowSlot = <UserCenterAssetConnectedOverviewRow
      overviewBridge={{ sectionProps: { items: [] } }}
      companionTitle="当前积分规则"
      companionContent={<div>规则内容</div>}
    />

    expect(buildUserCenterAssetConnectedOverviewRowsFacade({
      strategyRowSlot,
      pointsRulesRowSlot,
    })).toEqual({
      strategyRowSlot,
      pointsRulesRowSlot,
    })
  })

  it('adapts page inputs into reusable strategy and points rules row slots through the hook', () => {
    let capturedRows:
      | UserCenterAssetConnectedOverviewRowsFacade
      | null = null

    function Harness() {
      capturedRows = useUserCenterAssetConnectedOverviewRows({
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
        projectCount: 4,
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

    const rows: UserCenterAssetConnectedOverviewRowsFacade = capturedRows

    expect(rows.strategyRowSlot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(rows.strategyRowSlot.props.companionTitle).toBe('资产接入策略')
    expect(rows.pointsRulesRowSlot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(rows.pointsRulesRowSlot.props.companionTitle).toBe('当前积分规则')
    expect(renderToStaticMarkup(rows.pointsRulesRowSlot)).toContain('后台规则快照')
    expect(renderToStaticMarkup(rows.pointsRulesRowSlot)).toContain('最近更新：FMT(2026-04-24T00:00:00Z)')
  })
})
