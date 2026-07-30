import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'


function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')
}

describe('AI trace management wiring', () => {
  it('loads combination ranking and evaluation metrics for the selected genre', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('/api/v1/ai-trace/model-combinations')
    expect(source).toContain('/api/v1/ai-trace/evaluation-metrics')
    expect(source).toContain('avg_fidelity_similarity')
    expect(source).toContain('distinct_sample_count')
  })

  it('keeps internal prompt and route details out of the user result UI', () => {
    const source = readSource('../AITracePage.tsx')
    expect(source).not.toContain('promptVersionId')
    expect(source).not.toContain('selectionSource')
  })

  it('shows unified task budget and combination qualification in admin UI', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('/api/v1/ai-trace/background-status')
    expect(source).toContain('budget_remaining')
    expect(source).toContain('数据不足')
    expect(source).toContain('样本不足')
    expect(source).toContain('保真不合格')
    expect(source).toContain('策略已过期')
    expect(source).toContain('可参与路由')
    expect(source).toContain('当前生产使用')
  })

  it('shows semantic and local quality dimensions in prompt results', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('语义保真')
    expect(source).toContain('事实一致')
    expect(source).toContain('信息完整')
    expect(source).toContain('文笔自然')
    expect(source).toContain('本地规则')
    expect(source).toContain('llm_review')
    expect(source).toContain('rewritten_multi_score')
  })

  it('supports sequential all-genre evolution with recommended defaults', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('run_all_genres')
    expect(source).toContain('全部题材')
    expect(source).toContain('queue_current')
    expect(source).toContain('queue_total')
    expect(source).toContain('current_genre')
    expect(source).toContain('target_score: targetScore')
    expect(source).toContain('useState(25)')
    expect(source).toContain('useState(6)')
    expect(source).toContain('useState(4)')
  })

  it('allows base prompt evolution when only the multi-model budget is exhausted', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('disabled={backgroundStatus?.is_running}\n                >启动进化优化')
    expect(source).not.toContain(
      'disabled={backgroundStatus?.is_running || backgroundStatus?.budget_remaining === 0}\n                >启动进化优化',
    )
  })
})
