import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf-8',
)

describe('ModelCatalogPage TTS style-control source guards', () => {
  it('renders model-aware TTS style-control specs in voice synthesis details', () => {
    const pageSource = readSource('../ModelCatalogPage.tsx')

    expect(pageSource).toContain('style_control?:')
    expect(pageSource).toContain('风格控制模式')
    expect(pageSource).toContain('control_message_roles')
    expect(pageSource).toContain('消息位置')
    expect(pageSource).toContain('高级控制')
    expect(pageSource).toContain('supports_audio_tags')
  })
})
