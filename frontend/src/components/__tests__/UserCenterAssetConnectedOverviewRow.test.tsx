import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import UserCenterAssetConnectedOverviewRow, {
  buildUserCenterAssetConnectedOverviewRowSlot,
} from '../user-assets/UserCenterAssetConnectedOverviewRow'

function extractVisibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('UserCenterAssetConnectedOverviewRow', () => {
  it('builds a reusable row slot from overview bridge and companion content', () => {
    const options = {
      overviewBridge: {
        sectionProps: {
          items: [
            {
              key: 'connected-project-count',
              label: '项目数',
              value: 3,
            },
          ],
        },
      },
      companionTitle: '资产接入策略',
      companionContent: <div>示例说明</div>,
    }

    const slot = buildUserCenterAssetConnectedOverviewRowSlot(options)

    expect(slot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(slot.props).toEqual(options)
  })

  it('renders overview section and companion card through the shared row layout', () => {
    const text = extractVisibleText(renderToStaticMarkup(
      <UserCenterAssetConnectedOverviewRow
        overviewBridge={{
          sectionProps: {
            items: [
              {
                key: 'connected-project-count',
                label: '项目数',
                value: 3,
              },
              {
                key: 'connected-user-asset-count',
                label: '用户资产数',
                value: 12,
              },
            ],
          },
        }}
        companionTitle="资产接入策略"
        companionContent={<div>示例说明</div>}
      />,
    ))

    expect(text).toContain('已接入概览')
    expect(text).toContain('项目数：3')
    expect(text).toContain('用户资产数：12')
    expect(text).toContain('资产接入策略')
    expect(text).toContain('示例说明')
  })
})
