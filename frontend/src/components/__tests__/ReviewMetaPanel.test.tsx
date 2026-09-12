import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import ReviewMetaPanel, { extractSourceModels } from '../workflow/ReviewMetaPanel'

// 组件已 i18n 化：mock useTranslation，返回 zh 映射（未映射的 key 原样返回）
vi.mock('react-i18next', () => ({
  useTranslation: () => {
    const zhMap: Record<string, string> = {
      'workflow.reviewMeta.multiModel': '多模型评审',
      'workflow.reviewMeta.singleFallback': '单模型回退',
      'workflow.reviewMeta.chiefModel': '主审 {{model}}',
      'workflow.reviewMeta.chiefReused': '主审参与独立评审',
      'workflow.reviewMeta.consensus': '一致意见',
      'workflow.reviewMeta.divergence': '分歧意见',
      'workflow.reviewMeta.fallbackDefaultReason': '多模型评审未产出足够结果，已回退单模型评审',
      'workflow.reviewMeta.participantModels': '参与模型',
      'workflow.reviewMeta.sourceModels': 'source_models',
      'workflow.reviewMeta.presetBalanced3': '普通增强 3 评审',
      'workflow.reviewMeta.presetKeyChapter5': '重点章节 5 评审',
      'workflow.reviewMeta.presetDeep7': '深度 7 评审',
    }
    return {
      t: (key: string, params?: Record<string, string>) =>
        (zhMap[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => params?.[name] || ''),
    }
  },
}))

function visibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('ReviewMetaPanel', () => {
  it('renders multi-model sources and report trace markers', () => {
    const markup = renderToStaticMarkup(
      <ReviewMetaPanel
        reviewMeta={{
          multi_model: true,
          preset: 'deep_7',
          chief_model: 'deepseek-v4-pro',
          chief_model_reused_as_reviewer: true,
          reviewer_models: ['qwen3.7-plus', 'glm-5.2'],
          reviewer_profiles: ['general_literary', 'long_context_consistency'],
          per_model_reports: [
            {
              requested_model_id: 'deepseek-v4-pro',
              resolved_model_id: 'deepseek-v4-flash',
              profile: 'logic_continuity',
              status: 'success',
            },
          ],
        }}
        reviewText={'### 一致意见\n- 节奏稳定 [source_models: qwen3.7-plus, glm-5.2]\n### 分歧意见\n无'}
      />,
    )

    const text = visibleText(markup)

    expect(text).toContain('多模型评审')
    expect(text).toContain('深度 7 评审')
    expect(text).toContain('主审 deepseek-v4-pro')
    expect(text).toContain('主审参与独立评审')
    expect(text).toContain('一致意见')
    expect(text).toContain('分歧意见')
    expect(text).toContain('qwen3.7-plus')
    expect(text).toContain('glm-5.2')
    expect(text).toContain('deepseek-v4-pro -> deepseek-v4-flash')
    expect(text).toContain('source_models')
  })

  it('extracts source_models from bracketed suggestions', () => {
    expect(extractSourceModels('[source_models: qwen3.7-plus / glm-5.2，deepseek-v4-pro]')).toEqual([
      'qwen3.7-plus',
      'glm-5.2',
      'deepseek-v4-pro',
    ])
  })

  it('prefers structured summary source models over text extraction', () => {
    const markup = renderToStaticMarkup(
      <ReviewMetaPanel
        reviewMeta={{
          multi_model: true,
          structured_summary: {
            consensus: ['节奏稳定'],
            divergence: ['角色动机有争议'],
            final_suggestions: [],
            conclusion: '继续修改',
            source_models: ['structured-a', 'structured-b'],
          },
        }}
        reviewText={'### 一致意见\n- [source_models: text-only-model]'}
      />,
    )

    const text = visibleText(markup)

    expect(text).toContain('structured-a')
    expect(text).toContain('structured-b')
    expect(text).not.toContain('text-only-model')
    expect(text).toContain('一致意见')
    expect(text).toContain('分歧意见')
  })
})
