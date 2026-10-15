import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(fileURLToPath(new URL('../AssetStudioVisionReviewPanel.tsx', import.meta.url)), 'utf-8')

describe('Asset Studio vision review model list source contract', () => {
  it('档位名单与默认值只从后端统一模型清单取，页面不再自持档位表', () => {
    expect(source).toContain("from '@/hooks/useAssetStudioModelCatalog'")
    expect(source).toContain('groups.vision_review')
    expect(source).toContain('defaults.asset_studio_vision_review')
  })

  it('不再保留会与后端白名单漂移的硬编码模型常量与模型名字面量', () => {
    expect(source).not.toContain('VISION_MODELS')
    expect(source).not.toContain('DEFAULT_VISION_MODEL_ID')
    expect(source).not.toContain("'qwen3-vl-plus'")
    expect(source).not.toContain("'qwen3.5-omni-plus'")
    expect(source).not.toContain("'doubao-seed-2-1-lite'")
    expect(source).not.toContain("'doubao-seed-2-1-pro'")
    expect(source).not.toContain("'qwen-plus'")
  })

  it('清单为空或未就绪时下拉不可选，避免把空档位提交给后端', () => {
    expect(source).toContain('visionModelOptions.length === 0')
    expect(source).toContain('if (visionModelId) {')
  })
})
