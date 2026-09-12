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
    expect(source).toContain('admin.promptEvolution.combo.qualNoData')
    expect(source).toContain('admin.promptEvolution.combo.qualNoSample')
    expect(source).toContain('admin.promptEvolution.combo.qualFidelityFail')
    expect(source).toContain('admin.promptEvolution.combo.qualExpired')
    expect(source).toContain('admin.promptEvolution.combo.qualEligible')
    expect(source).toContain('admin.promptEvolution.combo.qualCurrent')
  })

  it('shows semantic and local quality dimensions in prompt results', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('admin.promptEvolution.review.dimSemantic')
    expect(source).toContain('admin.promptEvolution.review.dimFact')
    expect(source).toContain('admin.promptEvolution.review.dimComplete')
    expect(source).toContain('admin.promptEvolution.review.dimNatural')
    expect(source).toContain('admin.promptEvolution.review.localRuleTitle')
    expect(source).toContain('llm_review')
    expect(source).toContain('rewritten_multi_score')
  })

  it('supports sequential all-genre evolution with recommended defaults', () => {
    const source = readSource('../admin/PromptEvolutionPage.tsx')
    expect(source).toContain('run_all_genres')
    expect(source).toContain('admin.promptEvolution.config.allGenres')
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
    expect(source).toContain('disabled={backgroundStatus?.is_running}\n                >{t(\'admin.promptEvolution.startBtn\')}')
    expect(source).not.toContain(
      'disabled={backgroundStatus?.is_running || backgroundStatus?.budget_remaining === 0}\n                >{t(\'admin.promptEvolution.startBtn\')}',
    )
  })
})
