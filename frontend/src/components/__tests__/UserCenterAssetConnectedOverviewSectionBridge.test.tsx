import { beforeAll, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import type { i18n as I18nInstance } from 'i18next'

import { bootstrapI18n, I18nProvider } from '@/i18n'

import UserCenterAssetConnectedOverviewSectionBridge, {
  buildUserCenterAssetConnectedOverviewSectionSlot,
} from '../user-assets/UserCenterAssetConnectedOverviewSectionBridge'

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

let i18nInstance: I18nInstance

beforeAll(async () => {
  i18nInstance = await bootstrapI18n('zh-CN')
})

function renderWithI18n(node: ReactElement): string {
  return renderToStaticMarkup(<I18nProvider instance={i18nInstance}>{node}</I18nProvider>)
}

describe('UserCenterAssetConnectedOverviewSectionBridge', () => {
  it('builds a reusable slot from bridge section props', () => {
    const bridge = {
      sectionProps: {
        items: [
          {
            key: 'connected-project-count',
            label: '项目数',
            value: 3,
          },
        ],
      },
    }

    const slot = buildUserCenterAssetConnectedOverviewSectionSlot(bridge)

    expect(slot.type).toBe(UserCenterAssetConnectedOverviewSectionBridge)
    expect(slot.props).toEqual({ bridge })
  })

  it('renders the connected overview section through the bridge component', () => {
    const text = extractVisibleText(renderWithI18n(
      <UserCenterAssetConnectedOverviewSectionBridge
        bridge={{
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
      />,
    ))

    expect(text).toContain('已接入概览')
    expect(text).toContain('项目数：3')
    expect(text).toContain('用户资产数：12')
  })
})
