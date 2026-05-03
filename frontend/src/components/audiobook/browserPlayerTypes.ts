export interface BrowserPlayerSegment {
  text?: string
  type?: string
  character?: string
  start_time?: number
  end_time?: number
}

export interface BrowserPlayerChapter {
  chapter_id: number
  chapter_number?: number
  chapter_title?: string
  audio_url: string
  duration?: number
  has_subtitle?: boolean
  subtitle_url?: string | null
  audacity_labels_url?: string | null
  segments?: BrowserPlayerSegment[]
}

export interface BrowserPlayerProjectData {
  project_id: number
  project_title: string
  chapters: BrowserPlayerChapter[]
  total_duration: number
}
