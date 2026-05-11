import type {
  DreamweaverDiagnosticShot,
  DreamweaverDiagnosticShotFrames,
  DreamweaverRunPreflight,
  DreamweaverSmartDispatchTrace,
  DreamweaverVideoProviderShotTrace,
  DreamweaverVideoProviderTrace,
  RunResult,
} from '@/types/dreamweaver'
import { asObject, toStringArray } from './runPageDataTransforms'
import { getResultVideoClipMeta } from './runPageAccessors'

export type ShotDiagnosticAccordionState = {
  shotId: string
  frames: DreamweaverDiagnosticShotFrames | null
  sb: Record<string, unknown> | null
  desc: string
  duration: number | null
  shotAutoQC: Record<string, unknown> | null
  shotAutoQCPass: boolean | null
  shotAutoQCScore: number | null
  shotProviderTrace: DreamweaverVideoProviderShotTrace | null
  videoClip: unknown
  hasVideoClip: boolean
}

export function resolveShotDiagnosticAccordionState(
  shot: DreamweaverDiagnosticShot,
  diagnosticResult: unknown,
  providerTraceByShotId: Map<string, DreamweaverVideoProviderShotTrace>,
): ShotDiagnosticAccordionState {
  const diagRecord = asObject(diagnosticResult)
  const shotId = String(shot.shot_id || '').trim()
  const frames = shot.frames || null
  const sb = shot.storyboard || null
  const desc = typeof sb?.desc === 'string' ? sb.desc : ''
  const duration =
    typeof sb?.duration_s === 'number' ? Number(sb.duration_s) : typeof sb?.duration_s === 'string' ? Number(sb.duration_s) : null
  const autoqcShots = asObject(asObject(diagRecord?.autoqc)?.shots)
  const shotAutoQC = asObject(autoqcShots?.[shotId])
  const shotAutoQCPass = shotAutoQC ? Boolean(shotAutoQC.pass) : null
  const shotAutoQCScore =
    typeof asObject(shotAutoQC?.scores)?.overall === 'number' ? Number(asObject(shotAutoQC?.scores)?.overall) : null
  const shotProviderTrace = providerTraceByShotId.get(shotId) || null

  return {
    shotId,
    frames,
    sb,
    desc,
    duration,
    shotAutoQC,
    shotAutoQCPass,
    shotAutoQCScore,
    shotProviderTrace,
    videoClip: shot.video_clip,
    hasVideoClip: Boolean(shot.video_clip),
  }
}

export interface VideoDiagnostics {
  clipCount: number
  viaSummary: string
  fallbackCount: number
  errorCount: number
}

export function computeVideoDiagnostics(videoClips: unknown[]): VideoDiagnostics {
  const viaSet = new Set<string>()
  let fallbackCount = 0
  let errorCount = 0
  for (const clip of videoClips) {
    const meta = getResultVideoClipMeta(clip)
    const via = typeof meta?.via === 'string' ? String(meta.via).trim() : ''
    if (via) viaSet.add(via)
    if (via.includes('fallback')) fallbackCount += 1
    const err = typeof meta?.error === 'string' ? String(meta.error).trim() : ''
    if (err) errorCount += 1
  }
  return { clipCount: videoClips.length, viaSummary: Array.from(viaSet).join(', '), fallbackCount, errorCount }
}

export type SnapshotCameraDiagnostics = {
  generation: Record<string, unknown> | null
  cameraTree: unknown[] | null
  cameraStates: unknown[] | null
  cameraScenes: unknown[] | null
  sceneUris: string[]
  mode: string | null
}

export function computeSnapshotCameraDiagnostics(runtimeConfig: Record<string, unknown> | null): SnapshotCameraDiagnostics {
  const generation = asObject(runtimeConfig?.camera_tree_generation)
  const cameraTree = Array.isArray(runtimeConfig?.camera_tree) ? runtimeConfig.camera_tree : null
  const cameraStates = Array.isArray(runtimeConfig?.camera_states) ? runtimeConfig.camera_states : null
  const cameraScenes = Array.isArray(runtimeConfig?.camera_scenes) ? runtimeConfig.camera_scenes : null
  const sceneUris = (cameraScenes || [])
    .map((item) => {
      const record = asObject(item)
      return typeof record?.scene_uri === 'string' ? String(record.scene_uri || '').trim() : ''
    })
    .filter((item): item is string => Boolean(item))
  const mode = typeof generation?.mode === 'string' ? String(generation.mode) : null
  return { generation, cameraTree, cameraStates, cameraScenes, sceneUris, mode }
}

export function resolveDiagnosticCameraDiagnostics(
  snapshotCameraDiagnostics: SnapshotCameraDiagnostics,
  diagnosticResult: RunResult | null,
): SnapshotCameraDiagnostics {
  const snapshotHasAny =
    Boolean(snapshotCameraDiagnostics.cameraTree && snapshotCameraDiagnostics.cameraTree.length) ||
    Boolean(snapshotCameraDiagnostics.cameraStates && snapshotCameraDiagnostics.cameraStates.length) ||
    Boolean(snapshotCameraDiagnostics.cameraScenes && snapshotCameraDiagnostics.cameraScenes.length) ||
    Boolean(snapshotCameraDiagnostics.generation)
  if (snapshotHasAny) return snapshotCameraDiagnostics

  const generation = asObject(diagnosticResult?.camera_tree_generation)
  const cameraTree = Array.isArray(diagnosticResult?.camera_tree) ? diagnosticResult.camera_tree : null
  const cameraStates = Array.isArray(diagnosticResult?.camera_states) ? diagnosticResult.camera_states : null
  const cameraScenes = Array.isArray(diagnosticResult?.camera_scenes) ? diagnosticResult.camera_scenes : null
  const sceneUris = (cameraScenes || [])
    .map((item) => {
      const record = asObject(item)
      return typeof record?.scene_uri === 'string' ? String(record.scene_uri || '').trim() : ''
    })
    .filter((item): item is string => Boolean(item))
  const mode = typeof generation?.mode === 'string' ? String(generation.mode) : null
  const resultHasAny = Boolean(generation) || Boolean(cameraTree && cameraTree.length) || Boolean(cameraStates && cameraStates.length) || Boolean(cameraScenes && cameraScenes.length)
  if (!resultHasAny) return snapshotCameraDiagnostics

  return { generation, cameraTree, cameraStates, cameraScenes, sceneUris, mode }
}

export function computeDiagnosticShots(diagnosticResult: RunResult | null): DreamweaverDiagnosticShot[] {
  if (!diagnosticResult) return []

  const map = new Map<string, DreamweaverDiagnosticShot>()
  const ensure = (shotId: string): DreamweaverDiagnosticShot | null => {
    const key = String(shotId || '').trim()
    if (!key) return null
    if (!map.has(key)) map.set(key, { shot_id: key })
    return map.get(key) || null
  }

  const storyboard = Array.isArray(diagnosticResult.storyboard) ? diagnosticResult.storyboard : []
  for (const item of storyboard) {
    const itemRecord = asObject(item)
    const shotId = String(itemRecord?.shot_id || '').trim()
    const node = ensure(shotId)
    if (!node) continue
    node.storyboard = itemRecord
  }

  const parseFrameUri = (uri: string) => {
    const name = String(uri || '').split(/[\\/]+/).pop() || ''
    if (name.endsWith('_head.png')) return { shot_id: name.slice(0, -'_head.png'.length), role: 'head' as const }
    if (name.endsWith('_tail.png')) return { shot_id: name.slice(0, -'_tail.png'.length), role: 'tail' as const }
    if (name.endsWith('_mid.png')) return { shot_id: name.slice(0, -'_mid.png'.length), role: 'mid' as const }
    return { shot_id: '', role: null }
  }

  const parseClipUri = (uri: string) => {
    const name = String(uri || '').split(/[\\/]+/).pop() || ''
    if (!name) return ''
    const parts = name.split('.')
    if (parts.length < 2) return ''
    return parts.slice(0, -1).join('.')
  }

  const keyframes = Array.isArray(diagnosticResult.keyframes) ? diagnosticResult.keyframes : []
  for (const frame of keyframes) {
    const frameRecord = asObject(frame)
    const uri = typeof frameRecord?.path === 'string' ? String(frameRecord.path || '').trim() : ''
    if (!uri) continue
    const parsed = parseFrameUri(uri)
    if (!parsed.shot_id || !parsed.role) continue
    const node = ensure(parsed.shot_id)
    if (!node) continue
    node.frames = node.frames || {}
    node.frames[parsed.role] = frameRecord
  }

  const midframes = Array.isArray(diagnosticResult.midframes) ? diagnosticResult.midframes : []
  for (const frame of midframes) {
    const frameRecord = asObject(frame)
    const uri = typeof frameRecord?.path === 'string' ? String(frameRecord.path || '').trim() : ''
    if (!uri) continue
    const parsed = parseFrameUri(uri)
    if (!parsed.shot_id) continue
    const node = ensure(parsed.shot_id)
    if (!node) continue
    node.frames = node.frames || {}
    node.frames.mid = frameRecord
  }

  const clips = Array.isArray(diagnosticResult.video_clips) ? diagnosticResult.video_clips : []
  for (const clip of clips) {
    const clipRecord = asObject(clip)
    const uri = typeof clipRecord?.path === 'string' ? String(clipRecord.path || '').trim() : ''
    if (!uri) continue
    const shotId = parseClipUri(uri)
    if (!shotId) continue
    const node = ensure(shotId)
    if (!node) continue
    node.video_clip = clipRecord
  }

  const ordered: DreamweaverDiagnosticShot[] = []
  const pushed = new Set<string>()
  for (const item of storyboard) {
    const shotId = String(asObject(item)?.shot_id || '').trim()
    if (!shotId || pushed.has(shotId)) continue
    const node = map.get(shotId)
    if (node) {
      ordered.push(node)
      pushed.add(shotId)
    }
  }
  const rest = Array.from(map.values()).filter((node) => !pushed.has(String(node.shot_id || '')))
  rest.sort((a, b) => String(a.shot_id || '').localeCompare(String(b.shot_id || ''), 'zh-CN'))
  ordered.push(...rest)
  return ordered
}

export interface ShotDiagnosticCopyPayload {
  shot_id: string
  storyboard: Record<string, unknown> | null
  frames: { head?: unknown; tail?: unknown; mid?: unknown }
  video_clip: unknown
  provider_trace: unknown
  autoqc: unknown
}

export function buildShotDiagnosticCopyPayload(params: {
  shotId: string
  sb: Record<string, unknown> | null
  frames: { head?: unknown; tail?: unknown; mid?: unknown }
  videoClip: unknown
  shotProviderTrace: unknown
  shotAutoQC: unknown
}): ShotDiagnosticCopyPayload {
  return {
    shot_id: params.shotId,
    storyboard: params.sb,
    frames: params.frames,
    video_clip: params.videoClip || null,
    provider_trace: params.shotProviderTrace,
    autoqc: params.shotAutoQC,
  }
}

export function hasDiagnosticCopyData(params: {
  diagnosticResult: unknown
  diagnosticPreflight: unknown
  diagnosticProviderTrace: unknown
  diagnosticSmartDispatchTrace: unknown
}): boolean {
  return Boolean(params.diagnosticResult || params.diagnosticPreflight || params.diagnosticProviderTrace || params.diagnosticSmartDispatchTrace)
}

export function hasCameraDiagnosticsData(d: {
  cameraTree: unknown
  cameraStates: unknown
  cameraScenes: unknown
  generation: unknown
}): boolean {
  return Boolean(d.cameraTree || d.cameraStates || d.cameraScenes || d.generation)
}

export function resolveCameraCounts(d: {
  cameraTree: unknown
  cameraScenes: unknown
}): { cameraCount: number | null; sceneCount: number | null } {
  return {
    cameraCount: Array.isArray(d.cameraTree) ? d.cameraTree.length : null,
    sceneCount: Array.isArray(d.cameraScenes) ? d.cameraScenes.length : null,
  }
}

export interface DebugInfoPayload {
  selectedProjectId: string | number | null
  selectedChapterIds: number[]
  qualityMode: string
  stylePreset: string
  imageRatio: string
  imageResolution: string
  running: boolean
  task: {
    taskId: string | null
    status: string | null
    queue: string | null
    runId: string | null
    progress: number | null
    state: string | null
    stage: string | null
    artifacts: unknown
  }
  error: string | null
  preflight: unknown
  video_provider_trace: unknown
  result: unknown
}

export function buildDebugInfoPayload(params: Omit<DebugInfoPayload, 'qualityMode'> & { highQuality: boolean }): DebugInfoPayload {
  return {
    selectedProjectId: params.selectedProjectId,
    selectedChapterIds: params.selectedChapterIds,
    qualityMode: params.highQuality ? 'quality' : 'cost',
    stylePreset: params.stylePreset,
    imageRatio: params.imageRatio,
    imageResolution: params.imageResolution,
    running: params.running,
    task: params.task,
    error: params.error,
    preflight: params.preflight,
    video_provider_trace: params.video_provider_trace,
    result: params.result,
  }
}

export interface DiagnosticPayloadParams {
  currentRunId: string | null
  taskStatus: string | null
  taskState: string | null
  taskStage: string | null
  diagnosticPreflight: unknown
  diagnosticProviderTrace: unknown
  diagnosticSmartDispatchTrace: unknown
  snapshotRuntimeConfig: Record<string, unknown> | null
  cameraDiagnosticsGeneration: unknown
  cameraDiagnosticsCameraTree: unknown
  cameraDiagnosticsCameraStates: unknown
  cameraDiagnosticsCameraScenes: unknown
  diagnosticResult: unknown
}

export function buildRunDiagnosticPayload(params: DiagnosticPayloadParams): Record<string, unknown> {
  const dr = asObject(params.diagnosticResult)
  return {
    page: 'DreamWeaverRunDiagnostics',
    run_id: params.currentRunId,
    status: params.taskStatus,
    state: params.taskState,
    stage: params.taskStage,
    preflight: params.diagnosticPreflight,
    video_provider_trace: params.diagnosticProviderTrace,
    smart_dispatch_trace: params.diagnosticSmartDispatchTrace,
    runtime_config: params.snapshotRuntimeConfig,
    camera_tree_generation: params.cameraDiagnosticsGeneration || null,
    camera_tree: params.cameraDiagnosticsCameraTree || null,
    camera_states: params.cameraDiagnosticsCameraStates || null,
    camera_scenes: params.cameraDiagnosticsCameraScenes || null,
    autoqc: dr?.autoqc || null,
    storyboard: dr?.storyboard || null,
    keyframes: dr?.keyframes || null,
    midframes: dr?.midframes || null,
    video_clips: dr?.video_clips || null,
    merged_video: dr?.merged_video || null,
  }
}

export function buildCameraDiagnosticPayload(cameraDiagnostics: {
  generation: unknown
  cameraTree: unknown
  cameraStates: unknown
  cameraScenes: unknown
}): Record<string, unknown> {
  return {
    camera_tree_generation: cameraDiagnostics.generation || null,
    camera_tree: cameraDiagnostics.cameraTree || null,
    camera_states: cameraDiagnostics.cameraStates || null,
    camera_scenes: cameraDiagnostics.cameraScenes || null,
  }
}

export interface FeatureFlags {
  allowKlingOmni: boolean | null
  enableKlingVideoProvider: boolean | null
  allowSubjectBridge: boolean | null
}

export interface PreflightVideoConfig {
  providerMode: string | null
  selectorMode: string | null
  featureFlags: FeatureFlags
}

export function resolvePreflightVideoConfig(preflight: unknown): PreflightVideoConfig {
  const obj = (typeof preflight === 'object' && preflight !== null) ? preflight as Record<string, unknown> : {}
  const resolved = (obj.resolved_video_config || {}) as Record<string, unknown>
  const featureFlags: FeatureFlags = {
    allowKlingOmni: typeof resolved['allow_kling_omni'] === 'boolean' ? resolved['allow_kling_omni'] : null,
    enableKlingVideoProvider: typeof resolved['enable_kling_video_provider'] === 'boolean' ? resolved['enable_kling_video_provider'] : null,
    allowSubjectBridge: typeof resolved['allow_subject_bridge'] === 'boolean' ? resolved['allow_subject_bridge'] : null,
  }
  return {
    providerMode: typeof resolved['provider_mode'] === 'string' ? String(resolved['provider_mode']) : null,
    selectorMode: typeof resolved['selector_mode'] === 'string' ? String(resolved['selector_mode']) : null,
    featureFlags,
  }
}

export function resolveProviderTraceFeatureFlags(trace: { allow_kling_omni?: boolean | null; enable_kling_video_provider?: boolean | null; allow_subject_bridge?: boolean | null }): FeatureFlags {
  return {
    allowKlingOmni: trace.allow_kling_omni ?? null,
    enableKlingVideoProvider: trace.enable_kling_video_provider ?? null,
    allowSubjectBridge: trace.allow_subject_bridge ?? null,
  }
}

export function extractAttemptedModels(execution: unknown): string[] {
  const obj = (typeof execution === 'object' && execution !== null) ? execution as Record<string, unknown> : {}
  const raw = Array.isArray(obj.attempted_models) ? obj.attempted_models : []
  return raw
    .map((item) => String(item || '').trim())
    .filter((item): item is string => Boolean(item))
}

export interface SmartDispatchTraceDetails {
  routing: Record<string, unknown> | null
  execution: Record<string, unknown> | null
  prompt: Record<string, unknown> | null
  attemptedModels: string[]
}

export function resolveSmartDispatchTraceDetails(trace: unknown): SmartDispatchTraceDetails {
  const routing = asObject(trace != null && typeof trace === 'object' ? (trace as Record<string, unknown>).routing : undefined)
  const execution = asObject(trace != null && typeof trace === 'object' ? (trace as Record<string, unknown>).execution : undefined)
  const prompt = asObject(execution?.prompt)
  const attemptedModels = extractAttemptedModels(execution)
  return { routing, execution, prompt, attemptedModels }
}

export interface TelemetryStageEntry {
  stage: string
  totalS: number | null
  calls: number
  failure?: number
}

export interface TelemetryChipItem {
  key: string
  label: string
}

export function buildTelemetryStageEntries(entries: TelemetryStageEntry[]): TelemetryChipItem[] {
  return entries.map((item) => ({
    key: `tele:${item.stage}`,
    label: `${item.stage}: ${Number(item.totalS).toFixed(1)}s (${item.calls}${item.failure ? `, fail:${item.failure}` : ''})`,
  }))
}

export function buildTelemetryReworkChips(reworkByType: Record<string, unknown> | null | undefined): TelemetryChipItem[] {
  if (!reworkByType) return []
  return Object.entries(reworkByType).map(([key, value]) => ({
    key: `rework:${key}`,
    label: `rework.${key}: ${value}`,
  }))
}

export function buildTelemetryCounterChips(counters: Array<{ name: string; value: number | string }>): TelemetryChipItem[] {
  return counters.map((item) => ({
    key: `telemetry-counter:${item.name}`,
    label: `${item.name}: ${item.value}`,
  }))
}

export type TelemetrySummary = {
  startedAt: number | null
  finishedAt: number | null
  totalS: number | null
  terminalState: string | null
  reworkCount: number | null
  reworkByType: Record<string, unknown>
  stageEntries: Array<{ stage: string; totalS: number | null; calls: number; failure: number }>
}

export function computeTelemetrySummary(telemetry: Record<string, unknown> | null): TelemetrySummary | null {
  if (!telemetry) return null
  const startedAt = typeof telemetry.run_started_at === 'number' ? Number(telemetry.run_started_at) : null
  const finishedAt = typeof telemetry.run_finished_at === 'number' ? Number(telemetry.run_finished_at) : null
  const totalS = startedAt != null && finishedAt != null && finishedAt >= startedAt ? finishedAt - startedAt : null
  const terminalState = typeof telemetry.terminal_state === 'string' ? String(telemetry.terminal_state) : null
  const reworkCount = typeof telemetry.rework_count === 'number' ? Number(telemetry.rework_count) : null
  const reworkByType = asObject(telemetry.rework_by_type)
  const stagesRaw = asObject(telemetry.stages) || {}
  const stageOrder = ['init', 'script', 'storyboard', 'asset_library', 'keyframes', 'midframes', 'video', 'edit', 'review']
  const stageEntries = Object.entries(stagesRaw)
    .map(([stage, value]) => {
      const item = asObject(value) || {}
      const total = typeof item.total_s === 'number' ? Number(item.total_s) : null
      const calls = typeof item.calls === 'number' ? Number(item.calls) : 0
      const failure = typeof item.failure === 'number' ? Number(item.failure) : 0
      return { stage: String(stage), totalS: total, calls, failure }
    })
    .filter((it) => typeof it.totalS === 'number' && Number.isFinite(it.totalS) && it.totalS >= 0)
    .sort((a, b) => {
      const ia = stageOrder.indexOf(a.stage)
      const ib = stageOrder.indexOf(b.stage)
      if (ia === -1 && ib === -1) return a.stage.localeCompare(b.stage)
      if (ia === -1) return 1
      if (ib === -1) return -1
      return ia - ib
    })
  return { startedAt, finishedAt, totalS, terminalState, reworkCount, reworkByType: reworkByType || {}, stageEntries }
}

export function computeTelemetryCounters(telemetry: Record<string, unknown> | null): Array<{ name: string; value: number }> {
  const raw = asObject(telemetry?.counters)
  if (!raw) return []
  const entries: { name: string; value: number }[] = []
  for (const [name, value] of Object.entries(raw)) {
    const key = String(name || '').trim()
    if (!key) continue
    if (typeof value === 'number' && Number.isFinite(value)) {
      entries.push({ name: key, value: Number(value) })
    } else if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) entries.push({ name: key, value: parsed })
    }
    if (entries.length >= 200) break
  }
  const valueByName = new Map(entries.map((it) => [it.name, it.value]))
  const vlmTotalCalls =
    Number(valueByName.get('vlm_text_prefilter_calls') || 0) +
    Number(valueByName.get('vlm_rewrite_t2i_calls') || 0) +
    Number(valueByName.get('vlm_edit_prompt_calls') || 0) +
    Number(valueByName.get('vlm_analyze_image_calls') || 0) +
    Number(valueByName.get('vlm_semantic_selector_calls') || 0)
  if (vlmTotalCalls > 0 && !valueByName.has('vlm_total_calls')) entries.push({ name: 'vlm_total_calls', value: vlmTotalCalls })
  const preferredOrder = [
    'vlm_total_calls',
    'vlm_text_prefilter_calls',
    'vlm_rewrite_t2i_calls',
    'vlm_edit_prompt_calls',
    'vlm_analyze_image_calls',
    'vlm_analyze_image_images',
    'vlm_semantic_selector_calls',
    'vlm_semantic_selector_images',
    'vlm_edit_prompt_calls_head',
    'vlm_edit_prompt_calls_tail',
    'vlm_edit_prompt_calls_mid',
    'vlm_edit_prompt_images',
    'vlm_rewrite_t2i_ref_images',
    'semantic_retrieval_queries',
    'semantic_retrieval_hits',
    't2i_generate_calls',
    't2i_cache_hits',
    't2i_cache_misses',
    'image_edit_generate_calls',
    'image_edit_cache_hits',
    'image_edit_cache_misses',
    'multiperson_fusion_attempts',
    'multiperson_fusion_success',
    'multiperson_fusion_failed',
    'multiperson_fusion_skipped',
    'multiperson_fusion_steps',
  ]
  const rank = new Map(preferredOrder.map((k, idx) => [k, idx]))
  entries.sort((a, b) => {
    const ra = rank.has(a.name) ? Number(rank.get(a.name)) : preferredOrder.length
    const rb = rank.has(b.name) ? Number(rank.get(b.name)) : preferredOrder.length
    if (ra !== rb) return ra - rb
    if (a.name === b.name) return 0
    return a.name.localeCompare(b.name)
  })
  return entries
}

export type ComputeSafetyAuditAlertStateParams = {
  result: unknown
  snapshotRuntimeConfig: Record<string, unknown>
  runSnapshot: unknown
  taskStatus: string | null
  error: string | null
  currentRunId: string | null
  running: boolean
}

export type SafetyAuditAlertState = {
  show: boolean
  canApprove: boolean
  summary: string
  categories: string[]
}

export function computeSafetyAuditAlertState(params: ComputeSafetyAuditAlertStateParams): SafetyAuditAlertState {
  const { result, snapshotRuntimeConfig, runSnapshot: runSnapshotRaw, taskStatus, error, currentRunId, running } = params
  const runSnapshot = asObject(runSnapshotRaw)
  const resultAudit = asObject((result as Record<string, unknown>)?.audit)
  const snapshotAudit = asObject(snapshotRuntimeConfig.audit)
  const audit = resultAudit || snapshotAudit
  const safetyAudit = asObject(audit?.safety_audit)
  const snapshotReworkReason = asObject(snapshotRuntimeConfig.rework_reason)
  const reworkReason = snapshotReworkReason
  const reworkType = String(reworkReason?.type || '').trim().toLowerCase()
  const snapshotStatus = String(runSnapshot?.status || taskStatus || '').trim().toLowerCase()
  const errorTypeCandidates = [runSnapshot?.error_type, snapshotRuntimeConfig.error_type]
    .map((item) => String(item || '').trim())
    .filter(Boolean)
  const manualOverride = Boolean(safetyAudit?.manual_override)
  const blocked = Boolean(safetyAudit?.blocked)
  const safetyBlocked =
    (!manualOverride && blocked) ||
    (!manualOverride && reworkType === 'safety_audit_failed') ||
    (!manualOverride && errorTypeCandidates.includes('SafetyAuditFailed'))
  const summary =
    String(safetyAudit?.summary || '').trim() ||
    String(runSnapshot?.error_message || '').trim() ||
    String(error || '').trim() ||
    '成片命中安全审核阻断，当前 run 已停止。'
  const categories = toStringArray(safetyAudit?.categories)
  return {
    show: safetyBlocked,
    canApprove: Boolean(currentRunId) && snapshotStatus === 'failed' && safetyBlocked && !running,
    summary,
    categories,
  }
}

export type DiagnosticDialogProps = {
  runId: string | null
  state: string | null
  stage: string | null
  hasRunId: boolean
  hasDiagnosticResult: boolean
  error: string | null
  loading: boolean
  shotCount: number
  keyframeCount: number | null
  midframeCount: number | null
  videoClipCount: number | null
  refreshLabel: string
  refreshDisabled: boolean
  copyDisabled: boolean
}

export function buildDiagnosticDialogProps(params: {
  currentRunId: string | null
  diagnosticResult: RunResult | null
  diagnosticActionError: string | null
  diagnosticActionLoading: boolean
  diagnosticShots: DreamweaverDiagnosticShot[]
  persistedRunId: string | null
  runSnapshotLoading: boolean
  diagnosticPreflight: DreamweaverRunPreflight | null
  diagnosticProviderTrace: DreamweaverVideoProviderTrace | null
  diagnosticSmartDispatchTrace: DreamweaverSmartDispatchTrace | null
}): DiagnosticDialogProps {
  const { diagnosticResult } = params
  return {
    runId: params.currentRunId,
    state: diagnosticResult?.state || null,
    stage: diagnosticResult?.stage || null,
    hasRunId: Boolean(params.currentRunId),
    hasDiagnosticResult: Boolean(diagnosticResult),
    error: params.diagnosticActionError,
    loading: params.diagnosticActionLoading,
    shotCount: params.diagnosticShots.length,
    keyframeCount: arrayLength(diagnosticResult?.keyframes),
    midframeCount: arrayLength(diagnosticResult?.midframes),
    videoClipCount: arrayLength(diagnosticResult?.video_clips),
    refreshLabel: params.runSnapshotLoading ? '刷新中...' : '刷新运行快照',
    refreshDisabled: isSnapshotRefreshDisabled(params.persistedRunId, params.runSnapshotLoading),
    copyDisabled: !hasDiagnosticCopyData({
      diagnosticResult,
      diagnosticPreflight: params.diagnosticPreflight,
      diagnosticProviderTrace: params.diagnosticProviderTrace,
      diagnosticSmartDispatchTrace: params.diagnosticSmartDispatchTrace,
    }),
  }
}

export function arrayLength(value: unknown, fallback: number | null = null): number | null {
  return Array.isArray(value) ? value.length : fallback
}

export function isSnapshotRefreshDisabled(persistedRunId: string | null, runSnapshotLoading: boolean): boolean {
  return !persistedRunId || runSnapshotLoading
}
