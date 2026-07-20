import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(fileURLToPath(new URL('../AssetStudioWorkbench.tsx', import.meta.url)), 'utf8')

describe('Asset Studio Seed Audio controls', () => {
  it('exposes scene audio generation and speaker references', () => {
    expect(source).toContain("'scene-audio'")
    expect(source).toContain('seed-audio-1.0')
    expect(source).toContain("formData.append('speaker_ids'")
    expect(source).toContain('场景音频提示词')
    expect(source).toContain('参考说话人 ID')
  })
})
