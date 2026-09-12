import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

const typesSource = readSource('../types.ts')
const historyDialogSource = readSource('../HistoryDialog.tsx')

// 历史生成记录必须区分引擎模式与完成阶段：
// 剧本-only 批次 status 也是 completed，若不区分会被误读为"全部完成"
describe('history record mode and completion stage guards', () => {
  it('exposes engine mode and audio completion fields on history items', () => {
    expect(typesSource).toContain("engine_mode?: 'legacy_stems' | 'seed_scene' | null")
    expect(typesSource).toContain('audio_completed_chapters?: number | null')
  })

  it('labels each record with its engine mode', () => {
    expect(historyDialogSource).toContain("t('audiobook.audiobookSetupStep.seedSceneLabel')")
    expect(historyDialogSource).toContain("t('audiobook.audiobookSetupStep.legacyStemsLabel')")
  })

  it('separates script-only completion from full audio completion', () => {
    expect(historyDialogSource).toContain("t('audiobook.historyDialog.scriptOnlyCompleted')")
    expect(historyDialogSource).toContain("t('audiobook.historyDialog.allCompleted')")
    // 剧本-only 阶段提示使用橙色警示色而非绿色完成色
    expect(historyDialogSource).toContain('notice.warning')
  })
})
