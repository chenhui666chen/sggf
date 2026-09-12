import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import TaskPointsPrecheckAlert from '../TaskPointsPrecheckAlert'
import { extractTaskPointsPrecheckErrorDetail } from '@/services/api'
import { I18nProvider } from '@/i18n'

function buildAxiosLikeError(detail: Record<string, unknown>) {
  return {
    isAxiosError: true,
    message: 'Request failed with status code 400',
    response: {
      data: {
        detail,
      },
    },
  }
}

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

describe('TaskPointsPrecheckAlert', () => {
  it('能把后端返回的有声书积分不足详情渲染为可见告警文案', async () => {
    const detail = await extractTaskPointsPrecheckErrorDetail(
      buildAxiosLikeError({
        message: '有声书积分不足',
        module_key: 'audiobook',
        module_label: '有声书',
        failure_code: 'insufficient_available_points',
        effective_available_points: '15',
        additional_frozen_points: '22',
        required_frozen_points: '22',
        existing_frozen_points: '6',
        estimated_yuan: '1',
        estimated_points: '100',
      }),
    )

    expect(detail).not.toBeNull()

    const text = extractVisibleText(renderToStaticMarkup(
      <I18nProvider>
        <TaskPointsPrecheckAlert detail={detail!} />
      </I18nProvider>,
    ))
    expect(text).toContain('有声书积分不足')
    expect(text).toContain('还差 7.00 积分')
    expect(text).toContain('可用（含回收）：15.00 积分')
    expect(text).toContain('需冻结：22.00 积分')
    expect(text).toContain('已正式冻结：6.00 积分')
    expect(text).toContain('建议优先减少本次生成章节')
  })

  it('能把后端返回的负毛利拦截详情渲染为风险提示卡片', async () => {
    const detail = await extractTaskPointsPrecheckErrorDetail(
      buildAxiosLikeError({
        message: '短剧当前任务不满足定价策略',
        module_key: 'dreamweaver',
        module_label: '短剧',
        failure_code: 'negative_margin_blocked',
        estimated_shot_count: 12,
        operating_snapshot: {
          margin_status: 'negative',
          negative_margin_blocked: true,
          platform_gross_profit_yuan: '-3.2',
        },
      }),
    )

    expect(detail).not.toBeNull()

    const text = extractVisibleText(renderToStaticMarkup(
      <I18nProvider>
        <TaskPointsPrecheckAlert detail={detail!} />
      </I18nProvider>,
    ))

    expect(text).toContain('短剧被定价策略拦截')
    expect(text).toContain('短剧当前任务不满足定价策略')
    expect(text).toContain('预估镜头：12 个')
    expect(text).toContain('毛利状态：负毛利')
    expect(text).toContain('如需继续请联系管理员检查定价配置')
  })
})
