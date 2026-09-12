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
    expect(pageSource).toContain("t('modelCatalog.page.styleControlMode')")
    expect(pageSource).toContain('control_message_roles')
    expect(pageSource).toContain("t('modelCatalog.page.styleControlRole'")
    expect(pageSource).toContain("t('modelCatalog.page.styleControlAdvanced'")
    expect(pageSource).toContain('supports_audio_tags')
  })

  it('documents fixed-voice pitch and voice-design boundaries', () => {
    const pageSource = readSource('../ModelCatalogPage.tsx')

    expect(pageSource).toContain("label: 'volume'")
    expect(pageSource).toContain('固定 voice_id 的段落试听与工作台会删除片段级 pitch')
    expect(pageSource).toContain('支持 instruction 的模型通过表演指令控制语速')
    expect(pageSource).toContain('仅用于创建新的设计音色资产')
    expect(pageSource).not.toContain("label: 'volume / speed'")
    expect(pageSource).not.toContain("label: 'volume / speed / pitch'")
    expect(pageSource).not.toContain('段落试听和工作台链路会按场景透传')
  })
})
