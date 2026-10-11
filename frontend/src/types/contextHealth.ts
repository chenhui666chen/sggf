// 上下文预算观测类型，与后端 ContextObservation 字段一一对应（阶段 A 只读）。

export type ContextRequestKind =
  | 'plan'
  | 'plan_retry'
  | 'content'
  | 'content_retry'
  | 'segment'
  | 'regeneration'
  | 'iteration_plan'
  | 'revision'
  | 'review'
  | 'fallback'
  | 'expansion'
  | 'final_validation'

export interface ContextSectionStat {
  section_id: string
  source_field: string
  layer: string
  raw_chars: number
  raw_tokens: number
  final_chars: number
  final_tokens: number
  trim_method: string
}

export interface ContextObservation {
  project_id: number
  chapter_number: number
  request_kind: ContextRequestKind
  model_id: string
  model_context_limit: number
  safe_input_budget: number
  sections: ContextSectionStat[]
  total_input_tokens: number
  remaining_budget: number
  context_payload_bytes: number
  prompt_request_bytes: number
  db_rows_read: number
  db_columns_read: number
  rag_hits: number
  rag_summary_cache_hits: number
  cache_lookup_performed: boolean
  cache_lookup_status: string
  online_llm_calls: number
  logical_step_count: number
  request_status: string
  error_type: string
  // 输出验收状态（与 request_status 解耦）：not_checked / accepted / rejected
  output_status: string
  // 输出被拒原因（仅 output_status=rejected 有意义）
  output_reject_reason: string
  retry_attempted: boolean
  retry_status: string
  fallback_to_previous_output: boolean
  durations_ms: Record<string, number>
  conflict_status: string
  blocking_conflict_count: number
  warning_conflict_count: number
  outline_status: string
  volume_matched: boolean
  task_id: string
  request_id: string
  created_at: string
}

export interface ContextHealthResponse {
  project_id: number
  latest: ContextObservation | null
  observations: ContextObservation[]
}
