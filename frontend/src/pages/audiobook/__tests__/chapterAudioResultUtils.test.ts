import { describe, expect, it } from 'vitest'

import {
  formatChapterAudioButtonLabel,
  formatResumeCheckpointChipLabel,
  resolveAudioStatusChip,
  resolveScriptStatusChip,
} from '../chapterAudioResultUtils'
import type { GenerationCheckpoint } from '../types'

const checkpoint: GenerationCheckpoint = {
  chapter_id: 1,
  total_segments: 10,
  completed_segments: 4,
  can_resume: true,
}

describe('chapter audio result utils', () => {
  it('resolves script status chip metadata', () => {
    expect(resolveScriptStatusChip({ script_status: 'approved', has_script: true }).label).toBe('剧本：已审批')
    expect(resolveScriptStatusChip({ script_status: 'reviewed', has_script: true }).label).toBe('剧本：已修改')
    expect(resolveScriptStatusChip({ script_status: 'pending', has_script: true }).label).toBe('剧本：已生成')
    expect(resolveScriptStatusChip({ script_status: 'pending', has_script: false }).label).toBe('剧本：待处理')
    expect(resolveScriptStatusChip({ script_status: '', has_script: false }).label).toBe('剧本：待处理')
  })

  it('resolves audio status chip metadata', () => {
    expect(resolveAudioStatusChip({ audio_path: '/audio.mp3' }).label).toBe('音频：已生成')
    expect(resolveAudioStatusChip({ audio_path: null }).label).toBe('音频：未生成')
  })

  it('formats chapter and checkpoint labels', () => {
    expect(formatChapterAudioButtonLabel({ chapter_id: 9 }, { chapter_number: 3 })).toBe('第3章')
    expect(formatChapterAudioButtonLabel({ chapter_id: 9 }, null)).toBe('章节9')
    expect(formatResumeCheckpointChipLabel(checkpoint)).toBe('断点：4/10')
    expect(formatResumeCheckpointChipLabel({ ...checkpoint, total_segments: 0 })).toBe('断点：可继续生成')
    expect(formatResumeCheckpointChipLabel(null)).toBe('断点：可继续生成')
  })
})
