import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import UserCenterAssetConnectedOverviewCard from '../user-assets/UserCenterAssetConnectedOverviewCard'

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

describe('UserCenterAssetConnectedOverviewCard', () => {
  it('renders the shared connected overview title and items', () => {
    const text = extractVisibleText(renderToStaticMarkup(
      <UserCenterAssetConnectedOverviewCard
        items={[
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
        ]}
      />,
    ))

    expect(text).toContain('已接入概览')
    expect(text).toContain('项目数：3')
    expect(text).toContain('用户资产数：12')
  })
})
