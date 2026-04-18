import { stageToPreviewStep as stageToPreviewStepConstant } from '../constants/dreamweaver'
import type {
  DreamweaverLibraryPlanItem,
  DreamweaverRunPreflight,
  DreamweaverSmartDispatchTrace,
  DreamweaverVideoProviderShotTrace,
  DreamweaverVideoProviderTrace,
  LibraryAsset,
  LibraryPayload,
  PersistedDreamWeaverRun,
  RunResult,
} from '../types/dreamweaver'
import { characterViewLabel, parseLibraryRole } from './dreamweaverLibraryRole'

export const DREAMWEAVER_RUN_STORAGE_PREFIX = 'dreamweaver:lastRun:'
export const DREAMWEAVER_LEGACY_RUN_STORAGE_PREFIX = 'dreamweaver_run_'

function legacyDreamweaverRunStorageKey(projectId: number): string {
  return `${DREAMWEAVER_LEGACY_RUN_STORAGE_PREFIX}${projectId}`
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function toDreamweaverRunPreflight(value: unknown): DreamweaverRunPreflight | null {
  return asRecord(value) ? (value as DreamweaverRunPreflight) : null
}

function toDreamweaverVideoProviderTrace(value: unknown): DreamweaverVideoProviderTrace | null {
  return asRecord(value) ? (value as DreamweaverVideoProviderTrace) : null
}

function toDreamweaverSmartDispatchTrace(value: unknown): DreamweaverSmartDispatchTrace | null {
  return asRecord(value) ? (value as DreamweaverSmartDispatchTrace) : null
}

function readPersistedDreamWeaverRunByKey(key: string): PersistedDreamWeaverRun | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const obj = JSON.parse(raw) as PersistedDreamWeaverRun
    if (!obj || typeof obj !== 'object') return null
    if (typeof obj.run_id !== 'string' || !obj.run_id.trim()) return null
    return obj
  } catch {
    return null
  }
}

export function dreamweaverRunStorageKey(projectId: number): string {
  return `${DREAMWEAVER_RUN_STORAGE_PREFIX}${projectId}`
}

export function readPersistedDreamWeaverRun(projectId: number): PersistedDreamWeaverRun | null {
  return (
    readPersistedDreamWeaverRunByKey(dreamweaverRunStorageKey(projectId)) ||
    readPersistedDreamWeaverRunByKey(legacyDreamweaverRunStorageKey(projectId))
  )
}

export function writePersistedDreamWeaverRun(projectId: number, patch: Partial<PersistedDreamWeaverRun>): void {
  try {
    const prev = readPersistedDreamWeaverRun(projectId)
    const next: PersistedDreamWeaverRun = {
      project_id: projectId,
      run_id: String(patch.run_id ?? prev?.run_id ?? '').trim(),
      task_id: patch.task_id ?? prev?.task_id ?? null,
      status: patch.status ?? prev?.status ?? null,
      quality_mode: patch.quality_mode ?? prev?.quality_mode,
      qc_allow_fail: patch.qc_allow_fail ?? prev?.qc_allow_fail,
      smart_tuning: patch.smart_tuning ?? prev?.smart_tuning,
      video_require_confirmation: patch.video_require_confirmation ?? prev?.video_require_confirmation,
      prompt_review_required: patch.prompt_review_required ?? prev?.prompt_review_required,
      style_preset: patch.style_preset ?? prev?.style_preset,
      image_ratio: patch.image_ratio ?? prev?.image_ratio,
      image_resolution: patch.image_resolution ?? prev?.image_resolution,
      image_model: patch.image_model ?? prev?.image_model,
      video_model: patch.video_model ?? prev?.video_model,
      video_edit_model: patch.video_edit_model ?? prev?.video_edit_model,
      vision_model: patch.vision_model ?? prev?.vision_model,
      enable_video_edit: patch.enable_video_edit ?? prev?.enable_video_edit,
      enable_vision_review: patch.enable_vision_review ?? prev?.enable_vision_review,
      enable_safety_audit: patch.enable_safety_audit ?? prev?.enable_safety_audit,
      safety_fail_policy: patch.safety_fail_policy ?? prev?.safety_fail_policy,
      video_fps: patch.video_fps ?? prev?.video_fps,
      selected_chapter_ids: patch.selected_chapter_ids ?? prev?.selected_chapter_ids,
      updated_at: Date.now(),
    }
    if (!next.run_id) return
    localStorage.setItem(dreamweaverRunStorageKey(projectId), JSON.stringify(next))
    localStorage.removeItem(legacyDreamweaverRunStorageKey(projectId))
  } catch {
    // ignore
  }
}

export function clearPersistedDreamWeaverRun(projectId: number): void {
  try {
    localStorage.removeItem(dreamweaverRunStorageKey(projectId))
    localStorage.removeItem(legacyDreamweaverRunStorageKey(projectId))
  } catch {
    // ignore
  }
}

export function stageToPreviewStep(stage: string | null | undefined): number {
  return stageToPreviewStepConstant(stage)
}

export function ratioToCssAspectRatio(value: string | null | undefined, fallback = '16 / 9'): string {
  const raw = String(value ?? '').trim()
  if (!raw) return fallback
  const match = raw.match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/)
  if (!match) return fallback
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return fallback
  return `${width} / ${height}`
}

export function ratioIsPortrait(value: string | null | undefined): boolean {
  const raw = String(value ?? '').trim()
  if (!raw) return false
  const match = raw.match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/)
  if (!match) return false
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return false
  return height > width
}

export function isPlaceholderEntityName(value: unknown): boolean {
  const text = String(value ?? '').trim()
  if (!text) return true
  const lowered = text.toLowerCase()
  if (lowered === 'unknown' || lowered === 'n/a' || lowered === 'na') return true
  if (lowered.startsWith('lib_character_portrait')) return true
  if (lowered.startsWith('lib_scene_card:')) return true
  if (lowered.startsWith('lib_prop_card:')) return true
  return false
}

export function buildProtectedMergedVideoUrl(runId: string): string {
  return `protected://dreamweaver-run-merged/${encodeURIComponent(runId)}`
}

export function buildLibraryPlanItemsFromPayload(data: LibraryPayload | null | undefined): DreamweaverLibraryPlanItem[] {
  if (!data || typeof data !== 'object') return []

  const assets = Array.isArray(data.assets) ? data.assets : []
  const assetsByRole = new Map<string, LibraryAsset>()
  for (const asset of assets) {
    const role = String(asset?.role || '').trim()
    if (!role) continue
    assetsByRole.set(role, asset)
  }

  const entityNameByKey = new Map<string, string>()
  const spec = asRecord(data.spec) || {}
  const sections: Array<{ key: string; entityType: 'character' | 'scene' | 'prop' }> = [
    { key: 'characters', entityType: 'character' },
    { key: 'scenes', entityType: 'scene' },
    { key: 'props', entityType: 'prop' },
  ]
  for (const section of sections) {
    const items = Array.isArray(spec[section.key]) ? (spec[section.key] as unknown[]) : []
    for (const item of items) {
      const itemRecord = asRecord(item)
      if (!itemRecord) continue
      const entityId = Number.parseInt(String(itemRecord.entity_id ?? ''), 10)
      if (!Number.isFinite(entityId) || entityId <= 0) continue
      const name = String(itemRecord.name || '').trim()
      if (!name) continue
      entityNameByKey.set(`${section.entityType}:${entityId}`, name)
    }
  }

  const review = asRecord(data.review) || {}
  const requiredRolesRaw = Array.isArray(review.required_roles) ? (review.required_roles as unknown[]) : []
  const requiredRoles = requiredRolesRaw
    .map((raw) => String(raw || '').trim())
    .filter((role) => role)

  const orderedRoles = requiredRoles.length
    ? requiredRoles
    : Array.from(assetsByRole.keys()).sort((a, b) => a.localeCompare(b, 'zh-CN'))

  const seen = new Set<string>()
  const items: DreamweaverLibraryPlanItem[] = []
  for (const role of orderedRoles) {
    if (seen.has(role)) continue
    seen.add(role)
    const parsed = parseLibraryRole(role)
    const asset = assetsByRole.get(role) || null
    const entityType = parsed.entityType === 'unknown' ? null : parsed.entityType
    const entityId = typeof parsed.entityId === 'number' && parsed.entityId > 0 ? parsed.entityId : null
    const nameFromSpec = entityType && entityId ? entityNameByKey.get(`${entityType}:${entityId}`) || '' : ''
    const nameFromAsset = String(asset?.meta?.entity_name || '').trim()
    const entityName = nameFromSpec || (!isPlaceholderEntityName(nameFromAsset) ? nameFromAsset : '') || null
    const hasUri = Boolean(asset && String(asset.uri || '').trim())
    const status: DreamweaverLibraryPlanItem['status'] = hasUri ? 'done' : 'planned'
    const viewLabel = parsed.entityType === 'character' && parsed.view ? characterViewLabel(parsed.view, 'short') : ''
    const baseLabel = entityName || role
    const label = viewLabel && !baseLabel.includes(viewLabel) ? `${baseLabel} ${viewLabel}` : baseLabel

    items.push({
      id: role,
      role,
      entity_type: entityType,
      entity_id: entityId,
      entity_name: entityName,
      label,
      view: parsed.entityType === 'character' ? parsed.view || null : null,
      status,
      kind: 'image',
      uri: hasUri ? String(asset!.uri || '').trim() : null,
      asset_id: asset?.id ?? null,
      approved: typeof asset?.meta?.approved === 'boolean' ? Boolean(asset.meta?.approved) : null,
    })
  }
  return items
}

export function extractMergedVideoFromContract(contract: unknown): string | null {
  const contractRecord = asRecord(contract)
  if (!contractRecord) return null

  const anchorSets = asRecord(contractRecord.anchor_sets_ref)
  const mergedFromAnchor = asRecord(anchorSets?.merged_video)
  const uriFromAnchor = mergedFromAnchor?.uri
  if (typeof uriFromAnchor === 'string' && uriFromAnchor.trim()) return uriFromAnchor.trim()

  const assets = Array.isArray(contractRecord.assets) ? (contractRecord.assets as unknown[]) : []
  for (const item of assets) {
    const itemRecord = asRecord(item)
    if (!itemRecord) continue
    const role = String(itemRecord.role || '').trim()
    if (role !== 'merged_video') continue
    const uri = itemRecord.uri
    if (typeof uri === 'string' && uri.trim()) return uri.trim()
  }
  return null
}

export function buildResultFromRunSnapshot(data: unknown, fallbackRunId: string): RunResult | null {
  const dataRecord = asRecord(data)
  const contract = asRecord(dataRecord?.contract)
  if (!contract) return null

  const runtimeCfg = asRecord(contract.runtime_config) || {}
  const chapterIds = Array.isArray(runtimeCfg.chapter_ids) ? (runtimeCfg.chapter_ids as unknown[]) : []
  let plan: Record<string, unknown> | undefined =
    asRecord(runtimeCfg.plan) ||
    (typeof runtimeCfg.plan_text === 'string' && runtimeCfg.plan_text.trim()
      ? { text: runtimeCfg.plan_text.trim() }
      : undefined)

  if (!plan) {
    const scriptText = typeof runtimeCfg.script_text === 'string' ? runtimeCfg.script_text : ''
    if (scriptText.trim()) {
      const lines = scriptText.split(/\r?\n/)
      const start = lines.findIndex((line) => line.trim() === '## 概要')
      if (start >= 0) {
        const picked: string[] = []
        for (const line of lines.slice(start + 1)) {
          const value = line.trim()
          if (!value) continue
          if (value.startsWith('## ')) break
          if (value.startsWith('-')) {
            picked.push(value)
            if (picked.length >= 6) break
          }
        }
        if (picked.length) plan = { text: picked.join('\n') }
      }
      if (!plan) plan = { text: scriptText.trim().slice(0, 280) }
    }
  }

  const storyboard: unknown[] = []
  const keyframes: unknown[] = []
  const midframes: unknown[] = []
  const videoClips: unknown[] = []

  const episodes = Array.isArray(contract.episodes) ? (contract.episodes as unknown[]) : []
  for (const episode of episodes) {
    const episodeRecord = asRecord(episode)
    const shots = Array.isArray(episodeRecord?.shots) ? (episodeRecord.shots as unknown[]) : []
    for (const shot of shots) {
      const shotRecord = asRecord(shot)
      if (!shotRecord) continue
      const shotSchemaV2 = asRecord(shotRecord.shot_schema_v2) || {}
      storyboard.push({
        scene_id: shotRecord.scene_id,
        shot_id: shotRecord.shot_key,
        desc: shotRecord.desc,
        duration_s: shotRecord.duration_s,
        cam_idx: shotSchemaV2.cam_idx,
        visual_desc: shotSchemaV2.visual_desc,
        ff_desc: shotSchemaV2.ff_desc,
        lf_desc: shotSchemaV2.lf_desc,
        motion_desc: shotSchemaV2.motion_desc,
        audio_desc: shotSchemaV2.audio_desc,
        ff_vis_char_ids: shotSchemaV2.ff_vis_char_ids,
        lf_vis_char_ids: shotSchemaV2.lf_vis_char_ids,
        head_frame: shotRecord.head_frame,
        tail_frame: shotRecord.tail_frame,
      })

      const assets = Array.isArray(shotRecord.assets) ? (shotRecord.assets as unknown[]) : []
      for (const asset of assets) {
        const assetRecord = asRecord(asset)
        if (!assetRecord) continue
        const role = String(assetRecord.role || '').trim()
        const uri = assetRecord.uri
        if (typeof uri !== 'string' || !uri.trim()) continue
        const meta = asRecord(assetRecord.meta) || {}

        if (role === 'head_frame' || role === 'tail_frame') {
          keyframes.push({ path: uri, ratio: meta.ratio, spec: meta.spec, meta })
        } else if (role === 'mid_frame') {
          midframes.push({ path: uri, ratio: meta.ratio, spec: meta.spec, meta })
        } else if (role === 'video_clip') {
          videoClips.push({ path: uri, duration: meta.duration, head: meta.head, mid: meta.mid, tail: meta.tail, meta })
        }
      }
    }
  }

  const runId =
    typeof dataRecord?.run_id === 'string' && dataRecord.run_id.trim() ? dataRecord.run_id.trim() : fallbackRunId
  const state = typeof dataRecord?.state === 'string' && dataRecord.state.trim() ? dataRecord.state.trim() : 'DONE'
  const stage = dataRecord?.stage != null ? String(dataRecord.stage) : null
  const progress = typeof dataRecord?.progress === 'number' ? dataRecord.progress : null
  const preflight = toDreamweaverRunPreflight(dataRecord?.preflight) || toDreamweaverRunPreflight(runtimeCfg.preflight)
  const videoProviderTrace =
    toDreamweaverVideoProviderTrace(dataRecord?.video_provider_trace) ||
    toDreamweaverVideoProviderTrace(runtimeCfg.video_provider_trace)
  const smartDispatchTrace =
    toDreamweaverSmartDispatchTrace(dataRecord?.smart_dispatch_trace) ||
    toDreamweaverSmartDispatchTrace(runtimeCfg.smart_dispatch_trace)
  const audit = asRecord(dataRecord?.audit) || asRecord(runtimeCfg.audit)
  const qcWarning = asRecord(dataRecord?.qc_warning) || asRecord(runtimeCfg.qc_warning)
  const autoqc = asRecord(contract.autoqc) || asRecord(dataRecord?.autoqc) || asRecord(runtimeCfg.autoqc)

  return {
    run_id: runId,
    state,
    stage,
    progress,
    artifacts: null,
    source_chapter_count: chapterIds.length,
    plan,
    storyboard: storyboard.length ? storyboard : undefined,
    camera_tree_generation: asRecord(runtimeCfg.camera_tree_generation) ?? null,
    camera_tree: Array.isArray(runtimeCfg.camera_tree) ? (runtimeCfg.camera_tree as unknown[]) : null,
    camera_states: Array.isArray(runtimeCfg.camera_states) ? (runtimeCfg.camera_states as unknown[]) : null,
    camera_scenes: Array.isArray(runtimeCfg.camera_scenes) ? (runtimeCfg.camera_scenes as unknown[]) : null,
    keyframes: keyframes.length ? keyframes : undefined,
    midframes: midframes.length ? midframes : undefined,
    video_clips: videoClips.length ? videoClips : undefined,
    merged_video: extractMergedVideoFromContract(contract),
    audit: audit ?? undefined,
    autoqc: autoqc ?? undefined,
    qc_warning: qcWarning ?? undefined,
    preflight,
    video_provider_trace: videoProviderTrace,
    smart_dispatch_trace: smartDispatchTrace,
  }
}

export function mergeRunResult(prev: RunResult | null, next: RunResult | null): RunResult | null {
  if (!prev) return next
  if (!next) return prev
  return {
    ...prev,
    ...next,
    plan: next.plan ?? prev.plan,
    storyboard: next.storyboard ?? prev.storyboard,
    camera_tree_generation: next.camera_tree_generation ?? prev.camera_tree_generation,
    camera_tree: next.camera_tree ?? prev.camera_tree,
    camera_states: next.camera_states ?? prev.camera_states,
    camera_scenes: next.camera_scenes ?? prev.camera_scenes,
    keyframes: next.keyframes ?? prev.keyframes,
    midframes: next.midframes ?? prev.midframes,
    video_clips: next.video_clips ?? prev.video_clips,
    merged_video: next.merged_video ?? prev.merged_video,
    audit: next.audit ?? prev.audit,
    autoqc: next.autoqc ?? prev.autoqc,
    qc_warning: next.qc_warning ?? prev.qc_warning,
    preflight: next.preflight ?? prev.preflight,
    video_provider_trace: next.video_provider_trace ?? prev.video_provider_trace,
    smart_dispatch_trace: next.smart_dispatch_trace ?? prev.smart_dispatch_trace,
  }
}

export function resolveDreamweaverDiagnosticPreflight(
  result: Pick<RunResult, 'preflight'> | null | undefined,
  snapshotRuntimeConfig: unknown,
  runPreflight: DreamweaverRunPreflight | null | undefined,
): DreamweaverRunPreflight | null {
  return (
    toDreamweaverRunPreflight(result?.preflight) ||
    toDreamweaverRunPreflight(asRecord(snapshotRuntimeConfig)?.preflight) ||
    toDreamweaverRunPreflight(runPreflight)
  )
}

export function resolveDreamweaverDiagnosticProviderTrace(
  result: Pick<RunResult, 'video_provider_trace'> | null | undefined,
  snapshotRuntimeConfig: unknown,
): DreamweaverVideoProviderTrace | null {
  return (
    toDreamweaverVideoProviderTrace(result?.video_provider_trace) ||
    toDreamweaverVideoProviderTrace(asRecord(snapshotRuntimeConfig)?.video_provider_trace)
  )
}

export function resolveDreamweaverDiagnosticSmartDispatchTrace(
  result: Pick<RunResult, 'smart_dispatch_trace'> | null | undefined,
  snapshotRuntimeConfig: unknown,
): DreamweaverSmartDispatchTrace | null {
  return (
    toDreamweaverSmartDispatchTrace(result?.smart_dispatch_trace) ||
    toDreamweaverSmartDispatchTrace(asRecord(snapshotRuntimeConfig)?.smart_dispatch_trace)
  )
}

export function indexDreamweaverProviderTraceByShotId(
  trace: DreamweaverVideoProviderTrace | null | undefined,
): Map<string, DreamweaverVideoProviderShotTrace> {
  const map = new Map<string, DreamweaverVideoProviderShotTrace>()
  const shots = Array.isArray(trace?.shots) ? trace.shots : []
  for (const item of shots) {
    const shotId = String(item?.shot_id || '').trim()
    if (!shotId) continue
    map.set(shotId, item)
  }
  return map
}

export interface DreamweaverProviderTraceSummary {
  totalShots: number
  recommendedKling: number
  appliedKling: number
  shadowed: number
}

export function summarizeDreamweaverProviderTrace(
  trace: DreamweaverVideoProviderTrace | null | undefined,
): DreamweaverProviderTraceSummary | null {
  if (!trace) return null
  const shots = Array.isArray(trace.shots) ? trace.shots : []
  let recommendedKling = 0
  let appliedKling = 0
  let shadowed = 0

  for (const item of shots) {
    if (String(item?.recommended_provider || '').trim().toLowerCase() === 'kling') {
      recommendedKling += 1
    }
    if (String(item?.applied_provider || '').trim().toLowerCase() === 'kling') {
      appliedKling += 1
    }
    if (item?.shadowed) {
      shadowed += 1
    }
  }

  return {
    totalShots: shots.length,
    recommendedKling,
    appliedKling,
    shadowed,
  }
}

export interface DreamweaverSmartDispatchTraceSummary {
  stage: string | null
  strategy: string | null
  intentModality: string | null
  intentConfidence: number | null
  parseErrorCount: number
  selectedModel: string | null
  resolvedModel: string | null
  fallbackCount: number
  candidateCount: number
  attemptedCount: number
  phaseCount: number
  phaseStages: string[]
  promptChanged: boolean | null
  timedOut: boolean | null
}

export function summarizeDreamweaverSmartDispatchTrace(
  trace: DreamweaverSmartDispatchTrace | null | undefined,
): DreamweaverSmartDispatchTraceSummary | null {
  if (!trace) return null

  const routing = asRecord(trace.routing)
  const execution = asRecord(trace.execution)
  const intent = asRecord(trace.intent)
  const fallbackModels = Array.isArray(routing?.fallback_models) ? (routing?.fallback_models as unknown[]) : []
  const candidateScores = Array.isArray(routing?.candidate_scores) ? (routing?.candidate_scores as unknown[]) : []
  const attemptedModels = Array.isArray(execution?.attempted_models) ? (execution?.attempted_models as unknown[]) : []
  const parseErrors = Array.isArray(intent?.parse_errors) ? (intent?.parse_errors as unknown[]) : []
  const phases = Array.isArray(trace.phases) ? (trace.phases as unknown[]) : []
  const prompt = asRecord(execution?.prompt)
  const phaseStages = phases
    .map((item) => {
      const phase = asRecord(item)
      return typeof phase?.stage === 'string' && String(phase.stage).trim() ? String(phase.stage).trim() : ''
    })
    .filter((item): item is string => Boolean(item))

  return {
    stage: typeof trace.stage === 'string' && trace.stage.trim() ? trace.stage.trim() : null,
    strategy:
      typeof trace.strategy === 'string' && trace.strategy.trim()
        ? trace.strategy.trim()
        : typeof routing?.strategy === 'string' && String(routing.strategy).trim()
          ? String(routing.strategy).trim()
          : typeof execution?.strategy === 'string' && String(execution.strategy).trim()
            ? String(execution.strategy).trim()
            : null,
    intentModality: typeof intent?.modality === 'string' && String(intent.modality).trim() ? String(intent.modality).trim() : null,
    intentConfidence: typeof intent?.confidence === 'number' ? Number(intent.confidence) : null,
    parseErrorCount: parseErrors.length,
    selectedModel:
      typeof routing?.selected_model === 'string' && String(routing.selected_model).trim()
        ? String(routing.selected_model).trim()
        : null,
    resolvedModel:
      typeof execution?.resolved_model === 'string' && String(execution.resolved_model).trim()
        ? String(execution.resolved_model).trim()
        : null,
    fallbackCount: fallbackModels.filter((item) => typeof item === 'string' && String(item).trim()).length,
    candidateCount: candidateScores.length,
    attemptedCount: attemptedModels.filter((item) => typeof item === 'string' && String(item).trim()).length,
    phaseCount: phaseStages.length,
    phaseStages,
    promptChanged: typeof prompt?.prompt_changed === 'boolean' ? Boolean(prompt.prompt_changed) : null,
    timedOut: typeof execution?.timed_out === 'boolean' ? Boolean(execution.timed_out) : null,
  }
}

export function libraryAssetToCssAspectRatio(asset: LibraryAsset, fallback: string): string {
  const meta = asset?.meta || {}
  const width = Number((meta as Record<string, unknown>).width)
  const height = Number((meta as Record<string, unknown>).height)
  if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
    return `${width} / ${height}`
  }
  const ratio = typeof (meta as Record<string, unknown>).ratio === 'string' ? String((meta as Record<string, unknown>).ratio).trim() : ''
  if (ratio) return ratioToCssAspectRatio(ratio, fallback)
  return fallback
}
