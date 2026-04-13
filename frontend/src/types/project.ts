export interface Project {
  id: number
  display_no: number
  user_id: number
  title: string
  description?: string
  genre?: string
  sub_genre?: string
  planned_length_type?: string
  planned_chapters_min?: number
  planned_chapters_max?: number
  user_outline_plan?: string
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

export interface ProjectCreatePayload {
  title: string
  description?: string
  genre?: string
  sub_genre?: string
  planned_length_type?: string
  planned_chapters_min?: number
  planned_chapters_max?: number
  user_outline_plan?: string
}

export type ProjectUpdatePayload = Partial<ProjectCreatePayload> & Record<string, unknown>
