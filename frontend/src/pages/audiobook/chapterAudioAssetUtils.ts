import type {
  AudiobookProjectDetail,
  Chapter,
  ChapterAudio,
  Project,
} from './types'
import { buildAudiobookChapterAssetUuid } from './utils'

export interface AudiobookChapterAudioAssetMetadata {
  audiobook_project_id: number
  chapter_id: number
  chapter_audio_id: number
  project_id: number | null
  project_title: string | null
  chapter_title: string | null
  chapter_number: number | null
  filename: string
  audio_path: string | null
}

export interface AudiobookChapterAudioAssetDescriptor {
  assetUuid: string
  title: string
  projectId: number | null
  metadata: AudiobookChapterAudioAssetMetadata
}

const normalizePositiveNumber = (value: unknown): number | null => {
  const numericValue = Number(value)
  return Number.isFinite(numericValue) && numericValue > 0 ? numericValue : null
}

const normalizeOptionalText = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

export const buildAudiobookChapterAudioAssetDescriptor = ({
  audiobookProject,
  chapterAudio,
  chapters,
  selectedProject,
  routeProjectId,
  filename,
}: {
  audiobookProject: Pick<AudiobookProjectDetail, 'id' | 'project_id'>
  chapterAudio: Pick<ChapterAudio, 'id' | 'chapter_id' | 'chapter_number' | 'audio_path'>
  chapters: readonly Pick<Chapter, 'id' | 'chapter_number' | 'title'>[]
  selectedProject?: Pick<Project, 'id' | 'title'> | null
  routeProjectId?: number | null
  filename: string
}): AudiobookChapterAudioAssetDescriptor => {
  const chapter = chapters.find((item) => item.id === chapterAudio.chapter_id)
  const projectId = normalizePositiveNumber(selectedProject?.id ?? audiobookProject.project_id ?? routeProjectId)
  const projectTitle = normalizeOptionalText(selectedProject?.title)
  const chapterNumber = normalizePositiveNumber(chapter?.chapter_number ?? chapterAudio.chapter_number)
  const chapterTitle = normalizeOptionalText(chapter?.title)
  const title = chapterNumber
    ? `第${chapterNumber}章${chapterTitle ? ` - ${chapterTitle}` : ''} 有声书音频`
    : `${chapterTitle || `章节 ${chapterAudio.chapter_id}`} 有声书音频`

  const metadata: AudiobookChapterAudioAssetMetadata = {
    audiobook_project_id: audiobookProject.id,
    chapter_id: chapterAudio.chapter_id,
    chapter_audio_id: chapterAudio.id,
    project_id: projectId,
    project_title: projectTitle,
    chapter_title: chapterTitle,
    chapter_number: chapterNumber,
    filename,
    audio_path: normalizeOptionalText(chapterAudio.audio_path),
  }

  return {
    assetUuid: buildAudiobookChapterAssetUuid(audiobookProject.id, chapterAudio.chapter_id),
    title,
    projectId,
    metadata,
  }
}
