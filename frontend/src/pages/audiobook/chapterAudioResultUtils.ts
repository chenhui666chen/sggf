import type {
  Chapter,
  ChapterAudio,
  GenerationCheckpoint,
} from './types'
import { audiobookColors } from './audiobookTheme'

export interface ChapterAudioStatusChipConfig {
  label: string
  backgroundColor: string
  color: string
}

export const resolveScriptStatusChip = (
  chapterAudio: Pick<ChapterAudio, 'script_status' | 'has_script'>,
): ChapterAudioStatusChipConfig => {
  const status = chapterAudio.script_status || 'pending'
  const scriptHasContent = chapterAudio.has_script

  if (status === 'approved') {
    return {
      label: '剧本：已审批',
      backgroundColor: audiobookColors.successChip,
      color: audiobookColors.success,
    }
  }

  if (status === 'reviewed') {
    return {
      label: '剧本：已修改',
      backgroundColor: audiobookColors.infoSoft,
      color: audiobookColors.primaryDark,
    }
  }

  if (scriptHasContent) {
    return {
      label: '剧本：已生成',
      backgroundColor: audiobookColors.brandSoft,
      color: audiobookColors.brand,
    }
  }

  return {
    label: status ? '剧本：待处理' : '剧本：未生成',
    backgroundColor: audiobookColors.neutralChip,
    color: audiobookColors.neutralText,
  }
}

export const resolveAudioStatusChip = (
  chapterAudio: Pick<ChapterAudio, 'audio_path'>,
): ChapterAudioStatusChipConfig => {
  const hasAudio = Boolean(chapterAudio.audio_path)
  return {
    label: hasAudio ? '音频：已生成' : '音频：未生成',
    backgroundColor: hasAudio ? audiobookColors.brandSoft : audiobookColors.neutralChipStrong,
    color: hasAudio ? audiobookColors.brandDark : audiobookColors.neutralText,
  }
}

export const formatChapterAudioButtonLabel = (
  chapterAudio: Pick<ChapterAudio, 'chapter_id'>,
  chapter?: Pick<Chapter, 'chapter_number'> | null,
): string =>
  chapter ? `第${chapter.chapter_number}章` : `章节${chapterAudio.chapter_id}`

export const formatResumeCheckpointChipLabel = (
  checkpoint?: GenerationCheckpoint | null,
): string => {
  if (checkpoint && checkpoint.total_segments > 0) {
    return `断点：${checkpoint.completed_segments}/${checkpoint.total_segments}`
  }
  return '断点：可继续生成'
}
