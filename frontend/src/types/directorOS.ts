// AI Director OS 前端类型定义（Phase 2/3/4 新功能的 UI 层数据结构）
// 与后端 payload 键一一对应

// ============================================================
// Shot Contract（Phase 2.3 Contract 引擎产出）
// ============================================================
export interface ShotContract {
  shot_id: string
  scene_id: string
  beat_id: string
  shot_size: 'LS' | 'FS' | 'MS' | 'CU' | 'ECU'
  shot_size_zh: string
  camera_angle: string
  camera_movement: string
  lighting: string
  duration_s: number
  action: string
  dialogue: Array<{ speaker: string; line: string; emotion?: string }>
  visual_anchor: string
  technique: string
  family: string
  dispatch_dc_ids: string[]
  shot_purpose: string
  keyframe_source: 't2i_direct' | 'i2v_trajectory'
  state_before: string
  state_after: string
  r_pre_eligible: boolean
  movement_model_lang: string
  movement_compliance: string
  lighting_compliance: string
  reference_image_required: boolean
  characters: string[]
  emotion: string
  lens?: string
}

// ============================================================
// AM-15 评价报告（Phase 2.5 产出，REVIEW 阶段挂 payload）
// ============================================================
export interface Am15Critique {
  schema: string
  verdict: 'pass' | 'fail_state' | 'fail_physical'
  failure_types: string[]
  cf_hits: Array<{
    failure_type: string
    cf_id: string
    title: string
    repair_model: string
  }>
  hybrid: {
    objective: {
      cheap: { status: string; checks: unknown[]; intercepted: number; intercept_rate?: number }
      transition_summaries: Array<{ verified: number; gaps: number; missing: number }>
    }
    subjective: { status: string; result?: Record<string, unknown> }
    arbitration: {
      objective_veto_triggered: boolean
      objective_veto_scope: string[]
      cross_shot_gaps: number
      rule: string
    }
  }
  personas: {
    status: string
    personas?: Array<{ id: string; profile: string; feedback?: Record<string, unknown> }>
    rule?: string
  }
  cross_shot: {
    story_consistency?: number | null
    action_completion?: number | null
    state_transition_gaps: number
  }
  repair_suggestions: string[]
  repair_dispatch: {
    verdict: string
    r_level_hint: string
    recalculate_state_transitions: boolean
  }
}

export interface Am15Report {
  status: 'ok' | 'disabled' | 'error'
  markdown?: string
  critique?: Am15Critique
  error?: string
}

// ============================================================
// State Engine（Phase 2.4 camera_states 升级）
// ============================================================
export interface StateEngineState {
  state_id: string
  shot_id: string
  start_state: string
  end_state: string
  transition_verified?: boolean
  transition_gap?: { prev_end_state: string; cur_start_state: string }
  state_before?: string
  state_after?: string
  scene_id?: string
  ff_desc?: string
  lf_desc?: string
}

export interface StateEngineTrack {
  cam_idx: number
  states: StateEngineState[]
  first_state_id: string
  transition_summary: {
    contract: string
    verified: number
    gaps: number
    missing: number
    total_transitions: number
  }
}

// ============================================================
// 修复知识层（Phase 2.5 R0-R6 路由）
// ============================================================
export interface RepairKnowledge {
  r_level: 'R0' | 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'R6'
  cf_hits: Array<{ cf_id: string; title: string; repair_model: string }>
  execution_dictionary: Record<string, string>
  edit_budget: {
    triggered: boolean
    reasons?: string[]
    budget?: { asset_max_rounds: number; shot_r3_max_rounds: number }
    forced_upgrade?: string
  }
  recalculate_state_transitions: boolean
  dual_perspective: string
}

// ============================================================
// 编排套件（Phase 2.6）
// ============================================================
export interface StageHandoff {
  stage: string
  status: 'pass' | 'fail'
  missing: string[]
  optional_missing: string[]
  mode: string
}

export interface CostLedgerEntry {
  asset_id: string
  model: string
  cost: number
  tokens: number
  seconds: number
  shot_id: string
  stage: string
  kind: string
}

export interface CostLedgerSummary {
  total_cost: number
  entries: number
  by_model: Record<string, number>
  by_shot: Record<string, number>
}

// ============================================================
// 合成双通道（Phase 2.7）
// ============================================================
export interface SynthesisChannels {
  baseline: { vcodec: string; crf: number; pix_fmt: string; movflags: string }
  ffmpeg: { artifact: string; verify: { status: string; checks?: Record<string, boolean> } }
  jianying?: {
    draft_dir: string
    draft_content: string
    report: string
    shots: number
    format: string
  } | { status: 'disabled' }
}

// ============================================================
// script_document（Phase 2.2 剧本引擎产出）
// ============================================================
export interface ScriptBeat {
  beat_id: string
  family: string
  type: string
  description: string
  action: string
  shot_purpose: string
  dialogue: Array<{ speaker: string; line: string; emotion?: string }>
  visual_anchor: string
  hook: boolean
  duration_hint_s: number
}

export interface ScriptScene {
  scene_id: string
  number: number
  title: string
  interior: string
  location: string
  time_of_day: string
  characters: string[]
  summary: string
  beats: ScriptBeat[]
}

export interface ScriptDocument {
  schema_version: string
  title: string
  logline: string
  synopsis: string
  hooks: { opening_hook: string; ending_hook: string; share_emotion: string }
  scenes: ScriptScene[]
  source: {
    chapter_ids: string[]
    source_sha256: string
    chapter_version: string
    provenance: Array<{
      source_resource_id: string
      source_version: string
      used_in: string
      reuse_mode: string
    }>
  }
}

export interface StoryGraphCharacter {
  name: string
  description: string
  importance: string
  personality_traits: string[]
  relationships: Array<{ with: string; relation: string }>
}

export interface StoryGraph {
  characters: StoryGraphCharacter[]
  timeline: Array<{ order: number; event: string; characters: string[] }>
  scenes: Array<{ location: string; summary: string }>
  props: Array<{ name: string; descriptor: string }>
}

// ============================================================
// 治理与知识中枢（Phase 3）
// ============================================================
export interface KnowledgeGovernanceSummary {
  verified: number
  pending: number
  deprecated: number
  stale: number
}

export interface RepairStats {
  total_repair_attempts: number
  success_count: number
  success_rate: number
}

export interface AuditStats {
  total_calls: number
  stages: string[]
  knowledge_ids_used: number
}

// ============================================================
// 商业化挂钩（Phase 4）
// ============================================================
export interface BrandLockInfo {
  brand_id: string
  snapshot_hash: string
  created_at: string
}

export interface BudgetStatus {
  project_total_cap: number
  accumulated: number
  blocked: boolean
}
