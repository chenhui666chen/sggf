import type {
  Chapter,
  ChapterAudio,
  GenerationCheckpoint,
} from './types'
import { audiobookColors } from './audiobookTheme'
import type { TranslateFn } from './audioLibraryDisplay'

export interface ChapterAudioStatusChipConfig {
  label: string
  backgroundColor: string
  color: string
}

export const resolveScriptStatusChip = (
  chapterAudio: Pick<ChapterAudio, 'script_status' | 'has_script'>,
  t: TranslateFn,
): ChapterAudioStatusChipConfig => {
  const status = chapterAudio.script_status || 'pending'
  const scriptHasContent = chapterAudio.has_script

  if (status === 'approved') {
    return {
      label: t('audiobook.chapterAudioResultUtils.scriptApproved'),
      backgroundColor: audiobookColors.successChip,
      color: audiobookColors.success,
    }
  }

  if (status === 'reviewed') {
    return {
      label: t('audiobook.chapterAudioResultUtils.scriptReviewed'),
      backgroundColor: audiobookColors.infoSoft,
      color: audiobookColors.primaryDark,
    }
  }

  if (scriptHasContent) {
    return {
      label: t('audiobook.chapterAudioResultUtils.scriptGenerated'),
      backgroundColor: audiobookColors.brandSoft,
      color: audiobookColors.brand,
    }
  }

  return {
    label: status
      ? t('audiobook.chapterAudioResultUtils.scriptPending')
      : t('audiobook.chapterAudioResultUtils.scriptNotGenerated'),
    backgroundColor: audiobookColors.neutralChip,
    color: audiobookColors.neutralText,
  }
}

export const resolveAudioStatusChip = (
  chapterAudio: Pick<ChapterAudio, 'audio_path'>,
  t: TranslateFn,
): ChapterAudioStatusChipConfig => {
  const hasAudio = Boolean(chapterAudio.audio_path)
  return {
    label: hasAudio
      ? t('audiobook.chapterAudioResultUtils.audioGenerated')
      : t('audiobook.chapterAudioResultUtils.audioNotGenerated'),
    backgroundColor: hasAudio ? audiobookColors.brandSoft : audiobookColors.neutralChipStrong,
    color: hasAudio ? audiobookColors.brandDark : audiobookColors.neutralText,
  }
}

export const formatChapterAudioButtonLabel = (
  chapterAudio: Pick<ChapterAudio, 'chapter_id'>,
  chapter: Pick<Chapter, 'chapter_number'> | null | undefined,
  t: TranslateFn,
): string =>
  chapter
    ? t('audiobook.chapterAudioResultUtils.chapterNumberLabel', { number: chapter.chapter_number })
    : t('audiobook.chapterAudioResultUtils.chapterIdLabel', { id: chapterAudio.chapter_id })

export const formatResumeCheckpointChipLabel = (
  checkpoint: GenerationCheckpoint | null | undefined,
  t: TranslateFn,
): string => {
  if (checkpoint && checkpoint.total_segments > 0) {
    return t('audiobook.chapterAudioResultUtils.checkpointLabel', {
      done: checkpoint.completed_segments,
      total: checkpoint.total_segments,
    })
  }
  return t('audiobook.chapterAudioResultUtils.checkpointResumable')
}
