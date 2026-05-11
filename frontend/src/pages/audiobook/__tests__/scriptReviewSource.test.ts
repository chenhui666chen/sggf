import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const metricSectionsSource = readFileSync(
  new URL('../ScriptReviewMetricSections.tsx', import.meta.url),
  'utf8',
)

const utilsSource = readFileSync(
  new URL('../utils.ts', import.meta.url),
  'utf8',
)

describe('Script review report source guards', () => {
  it('keeps unresolved sound effect asset warnings visible in the report', () => {
    expect(metricSectionsSource).toContain('未解析音效')
    expect(metricSectionsSource).toContain('unresolved_effect_count')
    expect(metricSectionsSource).toContain('placeholder_effect_count')
    expect(metricSectionsSource).toContain('missing_effect_file_count')
    expect(utilsSource).toContain('audio_assets')
  })
})
