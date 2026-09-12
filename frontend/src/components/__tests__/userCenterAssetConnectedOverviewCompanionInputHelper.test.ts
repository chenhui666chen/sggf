import { describe, expect, it, vi } from 'vitest'
import type { TFunction } from 'i18next'

import {
  buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput,
  buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput,
} from '../user-assets/userCenterAssetConnectedOverviewCompanionInputHelper'

describe('userCenterAssetConnectedOverviewCompanionInputHelper', () => {
  it('builds shared strategy companion items without page-local literals', () => {
    expect(buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput()).toEqual({
      items: [
        'userCenter.points.strategyKeepProcess',
        'userCenter.points.strategyCentralizeStable',
        'userCenter.points.strategyDifferentiated',
      ],
    })

    const translate = ((key: string) => `T:${key}`) as TFunction
    expect(buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput(translate).items[0]).toBe(
      'T:userCenter.points.strategyKeepProcess',
    )
  })

  it('adapts points rules into shared companion content options', () => {
    const formatPointsValueLabel = vi.fn((value: number) => `P${value.toFixed(1)}`)
    const formatUpdatedAtLabel = vi.fn((value: string) => `FMT(${value})`)
    const getSourceLabel = vi.fn(() => 'userCenter.points.sourceAdmin')

    const options = buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput({
      pointsRules: {
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
      formatPointsValueLabel,
      formatUpdatedAtLabel,
      getSourceLabel,
    })

    expect(formatPointsValueLabel).toHaveBeenCalledWith(2)
    expect(formatPointsValueLabel).toHaveBeenCalledWith(12)
    expect(formatUpdatedAtLabel).toHaveBeenCalledWith('2026-04-24T00:00:00Z')
    expect(getSourceLabel).toHaveBeenCalledWith('admin_log')
    expect(options).toEqual({
      content: {
        sourceLabel: 'userCenter.points.sourceAdmin',
        sourceColor: 'primary',
        updatedAtLabel: 'userCenter.points.recentlyUpdated',
        description: 'userCenter.points.rulesDescription',
        summaryItems: [
          { label: 'userCenter.points.reusableReward', value: 'userCenter.points.pointsValue' },
          { label: 'userCenter.points.deliverableReward', value: 'userCenter.points.pointsValue' },
          { label: 'userCenter.points.audiobookCompletionReward', value: 'userCenter.points.pointsValue' },
          { label: 'userCenter.points.dreamweaverCompletionReward', value: 'userCenter.points.pointsValue' },
          { label: 'userCenter.points.runningAudiobookFrozen', value: 'userCenter.points.pointsValue' },
          { label: 'userCenter.points.runningDreamweaverFrozen', value: 'userCenter.points.pointsValue' },
          { label: 'userCenter.points.rewardValidity', value: 'userCenter.points.days' },
          { label: 'userCenter.points.expiringNoticeWindow', value: 'userCenter.points.days' },
        ],
        updatedByLabel: 'userCenter.points.updatedBy',
      },
      emptyText: 'userCenter.points.rulesEmpty',
    })
  })

  it('localizes points rules companion content when a translator is provided', () => {
    const translate = ((key: string) => `T:${key}`) as TFunction
    const options = buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput({
      pointsRules: {
        reusable_asset_reward: 2,
        deliverable_asset_reward: 4,
        audiobook_completion_reward: 6,
        dreamweaver_completion_reward: 8,
        running_audiobook_frozen: 10,
        running_dreamweaver_frozen: 12,
        reward_ttl_days: 30,
        expiring_notice_days: 7,
        source: 'admin_log',
        updated_at: null,
        updated_by_user_id: 1,
        updated_by_username: 'ops',
      },
      formatPointsValueLabel: (value: number) => `P${value.toFixed(1)}`,
      formatUpdatedAtLabel: (value: string) => `FMT(${value})`,
      getSourceLabel: () => 'userCenter.points.sourceAdmin',
      t: translate,
    })

    expect(options.content).toEqual({
      sourceLabel: 'T:userCenter.points.sourceAdmin',
      sourceColor: 'primary',
      updatedAtLabel: 'T:userCenter.points.notAdjusted',
      description: 'T:userCenter.points.rulesDescription',
      summaryItems: [
        { label: 'T:userCenter.points.reusableReward', value: 'T:userCenter.points.pointsValue' },
        { label: 'T:userCenter.points.deliverableReward', value: 'T:userCenter.points.pointsValue' },
        { label: 'T:userCenter.points.audiobookCompletionReward', value: 'T:userCenter.points.pointsValue' },
        { label: 'T:userCenter.points.dreamweaverCompletionReward', value: 'T:userCenter.points.pointsValue' },
        { label: 'T:userCenter.points.runningAudiobookFrozen', value: 'T:userCenter.points.pointsValue' },
        { label: 'T:userCenter.points.runningDreamweaverFrozen', value: 'T:userCenter.points.pointsValue' },
        { label: 'T:userCenter.points.rewardValidity', value: 'T:userCenter.points.days' },
        { label: 'T:userCenter.points.expiringNoticeWindow', value: 'T:userCenter.points.days' },
      ],
      updatedByLabel: 'T:userCenter.points.updatedBy',
    })
    expect(options.emptyText).toBe('T:userCenter.points.rulesEmpty')
  })

  it('keeps points rules companion empty state when rules are unavailable', () => {
    expect(buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput({
      pointsRules: null,
      formatPointsValueLabel: (value) => `${value}`,
      formatUpdatedAtLabel: (value) => value,
      getSourceLabel: () => '默认规则',
    })).toEqual({
      content: null,
      emptyText: 'userCenter.points.rulesEmpty',
    })
  })
})
