export interface Project {
  id: number
  title: string
  description?: string
  genre?: string
}

export interface Chapter {
  id: number
  chapter_number: number
  title: string
}

export interface ChapterAudio {
  id: number
  chapter_id: number
  chapter_number?: number | null
  audio_path?: string | null
  script_status?: string | null
  has_script?: boolean
}

export type AudiobookTtsModel = string

export interface AudiobookProjectDetail {
  id: number
  total_chapters?: number
  completed_chapters?: number
  total_duration?: number
  chapter_audios?: ChapterAudio[]
}

export interface AudiobookProjectSummary {
  id: number
  status?: string
  created_at?: string
  updated_at?: string | null
  completed_chapters?: number
  total_chapters?: number
  total_duration?: number
  total_cost?: number
  chapter_audios?: ChapterAudio[]
}

export interface UserAudiobookProjectOverview {
  id: number
  project_id: number
  project_title?: string | null
  project_description?: string | null
  status?: string | null
  total_chapters?: number | null
  completed_chapters?: number | null
  failed_chapters?: number | null
  total_duration?: number | null
  total_cost?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DeletedAudiobookProject {
  id: number
  project_id: number
  project_title?: string | null
  status?: string | null
  total_chapters?: number | null
  completed_chapters?: number | null
  total_duration?: number | null
  deleted_at?: string | null
  created_at?: string | null
  audit_id?: number | null
  delete_reason?: string | null
  affected_chapters?: number | null
  affected_tasks?: number | null
  total_size?: number | null
  restored_at?: string | null
}

export interface MergedChapterAudioRef {
  audiobookProjectId: number
  chapterAudio: ChapterAudio
}

export interface BookColors {
  primary: string
  secondary: string
  accent: string
  text: string
}

export type ChapterAudioDeleteCandidate = ChapterAudio & {
  chapterTitle: string
  chapterNumber: number
}
