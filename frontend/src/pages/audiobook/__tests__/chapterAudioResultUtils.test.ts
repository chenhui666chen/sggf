import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
  formatChapterAudioButtonLabel,
  formatResumeCheckpointChipLabel,
  resolveAudioStatusChip,
  resolveScriptStatusChip,
} from '../chapterAudioResultUtils'
import type { GenerationCheckpoint } from '../types'
import type { TranslateFn } from '../audioLibraryDisplay'

// 从 zh-CN 资源构造测试用翻译函数（返回中文原文）
const zhResources = JSON.parse(
  readFileSync(new URL('../../../i18n/resources/zh-CN/common.json', import.meta.url), 'utf8'),
)
const lookup = (path: string): string => {
  let node: unknown = zhResources
  for (const key of path.split('.')) {
    if (node && typeof node === 'object' && key in node) {
      node = (node as Record<string, unknown>)[key]
    } else {
      return path
    }
  }
  return typeof node === 'string' ? node : path
}
const zhT: TranslateFn = (key, options) => {
  let text = lookup(key)
  if (options) {
    for (const [name, value] of Object.entries(options)) {
      text = text.split(`{{${name}}}`).join(String(value))
    }
  }
  return text
}

const checkpoint: GenerationCheckpoint = {
  chapter_id: 1,
  total_segments: 10,
  completed_segments: 4,
  can_resume: true,
}

describe('chapter audio result utils', () => {
  it('resolves script status chip metadata', () => {
    expect(resolveScriptStatusChip({ script_status: 'approved', has_script: true }, zhT).label).toBe('剧本：已审批')
    expect(resolveScriptStatusChip({ script_status: 'reviewed', has_script: true }, zhT).label).toBe('剧本：已修改')
    expect(resolveScriptStatusChip({ script_status: 'pending', has_script: true }, zhT).label).toBe('剧本：已生成')
    expect(resolveScriptStatusChip({ script_status: 'pending', has_script: false }, zhT).label).toBe('剧本：待处理')
    expect(resolveScriptStatusChip({ script_status: '', has_script: false }, zhT).label).toBe('剧本：待处理')
  })

  it('resolves audio status chip metadata', () => {
    expect(resolveAudioStatusChip({ audio_path: '/audio.mp3' }, zhT).label).toBe('音频：已生成')
    expect(resolveAudioStatusChip({ audio_path: null }, zhT).label).toBe('音频：未生成')
  })

  it('formats chapter and checkpoint labels', () => {
    expect(formatChapterAudioButtonLabel({ chapter_id: 9 }, { chapter_number: 3 }, zhT)).toBe('第3章')
    expect(formatChapterAudioButtonLabel({ chapter_id: 9 }, null, zhT)).toBe('章节9')
    expect(formatResumeCheckpointChipLabel(checkpoint, zhT)).toBe('断点：4/10')
    expect(formatResumeCheckpointChipLabel({ ...checkpoint, total_segments: 0 }, zhT)).toBe('断点：可继续生成')
    expect(formatResumeCheckpointChipLabel(null, zhT)).toBe('断点：可继续生成')
  })
})
