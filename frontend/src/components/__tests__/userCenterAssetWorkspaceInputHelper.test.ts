import { describe, expect, it } from 'vitest'

import {
  buildUserCenterAssetProjectTitleMap,
  buildUserCenterAssetWorkspaceInput,
  extractUserCenterConnectedUserAssetCount,
} from '../user-assets/userCenterAssetWorkspaceInputHelper'

describe('userCenterAssetWorkspaceInputHelper', () => {
  it('builds a project title map with trimmed titles and fallback labels', () => {
    const projectTitleMap = buildUserCenterAssetProjectTitleMap([
      { id: 1, title: ' 海城剧场 ' },
      { id: 2, title: '   ' },
    ])

    expect(projectTitleMap.get(1)).toBe('海城剧场')
    expect(projectTitleMap.get(2)).toBe('项目 #2')
  })

  it('extracts connected user asset count from points overview when valid', () => {
    expect(extractUserCenterConnectedUserAssetCount({
      connected_overview: {
        project_count: 1,
        user_asset_count: 12,
        audiobook_project_count: 0,
        audiobook_total_cost: 0,
        dreamweaver_run_count: 0,
      },
    })).toBe(12)

    expect(extractUserCenterConnectedUserAssetCount({
      connected_overview: {
        project_count: 1,
        user_asset_count: Number.NaN,
        audiobook_project_count: 0,
        audiobook_total_cost: 0,
        dreamweaver_run_count: 0,
      },
    })).toBeNull()
    expect(extractUserCenterConnectedUserAssetCount(null)).toBeNull()
  })

  it('builds combined workspace input from projects and points overview', () => {
    const input = buildUserCenterAssetWorkspaceInput({
      projects: [
        { id: 7, title: ' 星港计划 ' },
      ],
      pointsOverview: {
        connected_overview: {
          project_count: 1,
          user_asset_count: 5,
          audiobook_project_count: 0,
          audiobook_total_cost: 0,
          dreamweaver_run_count: 0,
        },
      },
    })

    expect(input.projectTitleMap.get(7)).toBe('星港计划')
    expect(input.connectedUserAssetCount).toBe(5)
  })
})
