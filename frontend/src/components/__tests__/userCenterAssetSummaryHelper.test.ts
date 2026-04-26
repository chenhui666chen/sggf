import { describe, expect, it, vi } from 'vitest'

import {
  resolveUserCenterUserAssetCount,
  runUserCenterAssetRefresh,
} from '../user-assets/userCenterAssetSummaryHelper'

describe('userCenterAssetSummaryHelper', () => {
  it('prefers connected user asset count when it is valid', () => {
    expect(resolveUserCenterUserAssetCount(12, 3)).toBe(12)
    expect(resolveUserCenterUserAssetCount(0, 8)).toBe(0)
  })

  it('falls back to local user asset count when connected count is missing or invalid', () => {
    expect(resolveUserCenterUserAssetCount(undefined, 5)).toBe(5)
    expect(resolveUserCenterUserAssetCount(null, 7)).toBe(7)
    expect(resolveUserCenterUserAssetCount(Number.NaN, 4)).toBe(4)
    expect(resolveUserCenterUserAssetCount(-1, 6)).toBe(6)
  })

  it('runs both user center refresh and user asset refresh in silent mode', () => {
    const refreshUserCenterData = vi.fn()
    const refreshUserAssets = vi.fn()

    runUserCenterAssetRefresh({
      refreshUserCenterData,
      refreshUserAssets,
    })

    expect(refreshUserCenterData).toHaveBeenCalledWith(true)
    expect(refreshUserAssets).toHaveBeenCalledWith(true)
  })
})
