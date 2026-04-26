import { describe, expect, it } from 'vitest'

import { buildUserCenterAssetConnectedOverviewSectionPropsFromInput } from '../user-assets/userCenterAssetConnectedOverviewInputHelper'

describe('userCenterAssetConnectedOverviewInputHelper', () => {
  it('adapts normalized connected overview source into shared section props', () => {
    expect(buildUserCenterAssetConnectedOverviewSectionPropsFromInput({
      connectedOverviewSource: {
        projectCount: 7,
        audiobookProjectCount: 5,
        audiobookTotalCost: 88,
        dreamweaverRunCount: 12,
      },
      userAssetCount: 9,
      totalAudiobookCostLabel: '¥88.00',
    })).toEqual({
      items: [
        expect.objectContaining({ key: 'connected-project-count', value: 7 }),
        expect.objectContaining({ key: 'connected-user-asset-count', value: 9 }),
        expect.objectContaining({ key: 'connected-audiobook-project-count', value: 5 }),
        expect.objectContaining({ key: 'connected-audiobook-total-cost', value: '¥88.00' }),
        expect.objectContaining({ key: 'connected-dreamweaver-run-count', value: 12 }),
      ],
    })
  })

  it('uses source values directly without page fallback inputs', () => {
    expect(buildUserCenterAssetConnectedOverviewSectionPropsFromInput({
      connectedOverviewSource: {
        projectCount: 6,
        audiobookProjectCount: 4,
        audiobookTotalCost: 0,
        dreamweaverRunCount: 2,
      },
      userAssetCount: 10,
      totalAudiobookCostLabel: '¥0.00',
    })).toEqual({
      items: [
        expect.objectContaining({ key: 'connected-project-count', value: 6 }),
        expect.objectContaining({ key: 'connected-user-asset-count', value: 10 }),
        expect.objectContaining({ key: 'connected-audiobook-project-count', value: 4 }),
        expect.objectContaining({ key: 'connected-audiobook-total-cost', value: '¥0.00' }),
        expect.objectContaining({ key: 'connected-dreamweaver-run-count', value: 2 }),
      ],
    })
  })
})
