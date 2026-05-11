export * from './runPageDiagnosticHelpers'
export * from './runPageConfigHelpers'
export * from './runPagePropsBuilders'
export * from './runPageAccessors'
export * from './runPageDataTransforms'
export * from './runPageLibraryHelpers'
export * from './runPageHistoryHelpers'
export * from './runPageFormatUtils'

import type {
  DreamweaverAssetPlanItem,
  DreamweaverRunPreflight,
  DreamweaverRunSnapshot,
  DreamweaverShotFrame,
  DreamweaverShotSnapshot,
  RunResult,
} from '@/types/dreamweaver'
import { buildResultFromRunSnapshot, mergeRunResult } from '@/utils/dreamweaver'
import { asObject, toDreamweaverShotSnapshots, toDreamweaverShotFrames } from './runPageDataTransforms'
import { getShotAssets, getShotId, getResultVideoClipPath, getShotFrameCandidateUris, getShotFramePath } from './runPageAccessors'

export function resolveWaitingKind(stage: string | null, state: string | null): string {
  return (stage || state || '').toString().toLowerCase()
}

export function resolveWaitingState(params: {
  status: string | null
  stage: string | null
  state: string | null
  waitingScriptApprovalStage: string
  waitingApprovalStage: string
  waitingVideoConfirmationStage: string
}): { waiting: boolean; isRunning: boolean } {
  const statusLower = (params.status || '').toString().toLowerCase()
  const waitingKind = resolveWaitingKind(params.stage, params.state)
  const waiting =
    statusLower === 'waiting' ||
    waitingKind === params.waitingScriptApprovalStage ||
    waitingKind === params.waitingApprovalStage ||
    waitingKind === params.waitingVideoConfirmationStage
  const isRunning = statusLower === 'running' || statusLower === 'queued'
  return { waiting, isRunning }
}

export function resolveTaskStateKind(state: string | null): 'waiting' | 'done' | 'failed' | 'running' {
  if (!state) return 'running'
  const upper = state.toUpperCase()
  if (upper.startsWith('WAITING')) return 'waiting'
  if (upper === 'DONE') return 'done'
  if (upper === 'FAILED') return 'failed'
  return 'running'
}

export function resolveCanResumeFromScript(params: {
  currentRunId: string | null
  scriptLoading: boolean
  resumeLoading: boolean
  scriptDirty: boolean
  scriptRequiresReview: boolean
  scriptApproved: boolean
}): boolean {
  return (
    Boolean(params.currentRunId) &&
    !params.scriptLoading &&
    !params.resumeLoading &&
    !params.scriptDirty &&
    (!params.scriptRequiresReview || params.scriptApproved)
  )
}

export function resolveCanResumeFromLibrary(params: {
  currentRunId: string | null
  libraryLoading: boolean
  resumeLoading: boolean
  libraryApproved: boolean
  promptReviewReady: boolean
}): boolean {
  return (
    Boolean(params.currentRunId) &&
    !params.libraryLoading &&
    !params.resumeLoading &&
    params.libraryApproved &&
    params.promptReviewReady
  )
}

export function parsePromptedIds(raw: string | null): string[] {
  if (raw == null) return []
  return raw
    .split(/[\s,，;；\n]+/g)
    .map((s) => s.trim())
    .filter((s) => s)
}

export function parsePromptedCameraIndices(raw: string | null): number[] {
  const ids = parsePromptedIds(raw)
    .map((s) => Number(s))
    .filter((n) => Number.isFinite(n))
    .map((n) => Math.trunc(n))
  return ids.filter((n, idx, arr) => arr.indexOf(n) === idx)
}

export const PENDING_STAGE_HINTS: Record<number, string> = {
  0: '剧本预览：当前为运行中阶段，进入"剧本待审核"后可加载/编辑/通过。',
  1: '分镜预览：将展示镜头数量与分镜阶段信息（后续可升级为镜头列表/分镜卡）。',
  2: '素材预览：素材库在生成后可在此加载并逐项审核。',
  3: '镜头预览：关键帧/中间帧/片段生成将逐步更新计数与产物路径。',
  4: '合成预览：合成视频与质检结果将在后续阶段产出。',
}

export function extractResultPlanText(result: Record<string, unknown> | null): string {
  const plan = result?.plan
  if (!plan || typeof plan !== 'object') return ''
  const text = (plan as { text?: unknown }).text
  return typeof text === 'string' ? text : ''
}

export function extractResultVideoClipPaths(videoClips: unknown[]): string[] {
  return videoClips.map((clip) => getResultVideoClipPath(clip)).filter(Boolean)
}

export function collectCandidateFrameUris(keyframes: unknown, midframes: unknown): string[] {
  const uris: string[] = []
  const pushFromFrames = (frames: DreamweaverShotFrame[]) => {
    for (const frame of frames) {
      uris.push(...getShotFrameCandidateUris(frame))
    }
  }
  pushFromFrames(toDreamweaverShotFrames(keyframes))
  pushFromFrames(toDreamweaverShotFrames(midframes))
  return Array.from(new Set(uris))
}

export function collectShotFramePaths(frames: unknown): string[] {
  return toDreamweaverShotFrames(frames).map((frame) => getShotFramePath(frame)).filter(Boolean)
}

export function resolveStreamingTexts(streamSnapshots: Record<string, unknown>): {
  planText: string
  scriptText: string
  profileText: string
  audioText: string
  storyboardText: string
  cameraTreeText: string
} {
  return {
    planText: String(streamSnapshots.plan || '').trim(),
    scriptText: String(streamSnapshots.script || streamSnapshots.scriptEnhance || '').trim(),
    profileText: String(streamSnapshots.characterProfiles || '').trim(),
    audioText: String(streamSnapshots.audioMarkers || '').trim(),
    storyboardText: String(streamSnapshots.storyboard || '').trim(),
    cameraTreeText: String(streamSnapshots.cameraTree || '').trim(),
  }
}

export type StreamSnapshots = {
  plan: string
  script: string
  scriptEnhance: string
  characterProfiles: string
  audioMarkers: string
  storyboard: string
  cameraTree: string
}

export function buildStreamSnapshots(streamTextByKey: Record<string, string>): StreamSnapshots {
  return {
    plan: streamTextByKey.plan || '',
    script: streamTextByKey.script || '',
    scriptEnhance: streamTextByKey.script_enhance || '',
    characterProfiles: streamTextByKey.character_profiles || '',
    audioMarkers: streamTextByKey.audio_markers || '',
    storyboard: streamTextByKey.storyboard || '',
    cameraTree: streamTextByKey.camera_tree || '',
  }
}

export function computeActiveStreamKeys(streamMetaByKey: Record<string, { stage?: string | null; done?: boolean }>): string[] {
  return Object.entries(streamMetaByKey)
    .filter(([, meta]) => meta && !meta.done)
    .map(([key]) => key)
}

export function resolveTaskStatusLabel(taskStatus: string | null): string | null {
  const value = (taskStatus || '').trim().toLowerCase()
  if (!value) return null
  if (value === 'queued') return '排队中'
  if (value === 'running') return '运行中'
  if (value === 'waiting') return '等待中'
  if (value === 'completed') return '已完成'
  if (value === 'failed') return '失败'
  return taskStatus
}

export function resolveTaskStatusColor(taskStatus: string | null): 'default' | 'info' | 'warning' | 'success' | 'error' {
  const value = (taskStatus || '').trim().toLowerCase()
  if (value === 'queued') return 'warning'
  if (value === 'waiting') return 'warning'
  if (value === 'running') return 'info'
  if (value === 'completed') return 'success'
  if (value === 'failed') return 'error'
  return 'default'
}

export type ScriptGenerationLike = {
  mode?: string | null
  model?: string | null
}

export function resolveScriptGenerationLabel(generation: ScriptGenerationLike | null): string | null {
  const mode = (generation?.mode || '').toString()
  const model = generation?.model ? String(generation.model) : ''
  if (!mode) return null
  if (mode === 'llm') return model ? `LLM（${model}）` : 'LLM'
  if (mode === 'rule_fallback') return '规则回退'
  if (mode === 'rule') return '规则'
  if (mode === 'manual') return '手动编辑'
  return mode
}

export function extractScriptGeneration(runtimeConfig: Record<string, unknown>): unknown {
  const generation = runtimeConfig?.script_generation
  return generation && typeof generation === 'object' && !Array.isArray(generation) ? generation : null
}

export function extractCharacterProfiles(runtimeConfig: Record<string, unknown>): unknown[] {
  const profiles = runtimeConfig?.character_profiles
  return Array.isArray(profiles) ? profiles : []
}

export function extractAudioMarkers(runtimeConfig: Record<string, unknown>): unknown[] {
  const markers = runtimeConfig?.audio_markers
  return Array.isArray(markers) ? markers : []
}

export function shouldTreatRunNotFoundAsPending(taskIdValue?: string | null, statusValue?: string | null): boolean {
  const status = String(statusValue || '').trim().toLowerCase()
  if (status === 'queued' || status === 'running' || status === 'waiting') return true
  return Boolean(taskIdValue)
}

export function extractSnapshotPlanText(runtimeConfig: Record<string, unknown> | null): string {
  const plan = asObject(runtimeConfig?.plan)
  if (typeof plan?.text === 'string') return String(plan.text)
  if (typeof runtimeConfig?.plan_text === 'string' && runtimeConfig.plan_text.trim()) return runtimeConfig.plan_text.trim()
  return ''
}

export function extractSnapshotScriptText(runtimeConfig: Record<string, unknown> | null): string {
  return typeof runtimeConfig?.script_text === 'string' ? runtimeConfig.script_text : ''
}

export function extractSnapshotScriptApproved(runtimeConfig: Record<string, unknown> | null): boolean {
  const review = asObject(runtimeConfig?.script_review)
  return Boolean(review?.approved)
}

export function extractSnapshotAssetSummary(shots: DreamweaverShotSnapshot[]): {
  keyframes: string[]
  midframes: string[]
  videoClips: Array<{ path: string; meta: Record<string, unknown> }>
} {
  const keyframes: string[] = []
  const midframes: string[] = []
  const videoClips: Array<{ path: string; meta: Record<string, unknown> }> = []
  for (const shot of shots) {
    const assets = getShotAssets(shot)
    for (const asset of assets) {
      const role = String(asset.role || '')
      const uri = asset.uri
      if (typeof uri !== 'string' || !uri.trim()) continue
      const meta = asObject(asset.meta) || {}
      if (role === 'head_frame' || role === 'tail_frame') keyframes.push(uri)
      else if (role === 'mid_frame') midframes.push(uri)
      else if (role === 'video_clip') videoClips.push({ path: uri, meta })
    }
  }
  return { keyframes, midframes, videoClips }
}

export function computeAssetPlanSummary(items: DreamweaverAssetPlanItem[]): {
  total: number
  done: number
  planned: number
  images: number
  videos: number
} {
  let done = 0
  let planned = 0
  let images = 0
  let videos = 0
  for (const item of items) {
    if (item.kind === 'video') videos += 1
    else images += 1
    if (item.status === 'done' || item.uri) done += 1
    else planned += 1
  }
  return { total: items.length, done, planned, images, videos }
}

export function extractSnapshotShots(snapshot: DreamweaverRunSnapshot | null): DreamweaverShotSnapshot[] {
  const episodes = snapshot?.contract?.episodes
  if (!Array.isArray(episodes)) return []
  const shots: DreamweaverShotSnapshot[] = []
  for (const ep of episodes) {
    if (!ep || typeof ep !== 'object' || Array.isArray(ep)) continue
    const epShots = (ep as Record<string, unknown>).shots
    shots.push(...toDreamweaverShotSnapshots(epShots))
  }
  return shots
}

export type SafetyBlockedShot = {
  shotId: string
  shotIndex?: number
  roles: string[]
  errorSample: string
}

export function computeSafetyBlockedShots(shots: DreamweaverShotSnapshot[]): SafetyBlockedShot[] {
  const results: SafetyBlockedShot[] = []
  const pattern = /datainspectionfailed|inappropriate content|content check failed/i
  for (const shot of shots) {
    const shotId = getShotId(shot)
    if (!shotId) continue
    const roles = new Set<string>()
    let errorSample = ''
    const assets = getShotAssets(shot)
    for (const asset of assets) {
      const meta = asset.meta && typeof asset.meta === 'object' && !Array.isArray(asset.meta) ? asset.meta : {}
      const safetyError = typeof meta.safety_error === 'string' ? meta.safety_error : ''
      const errorText = typeof meta.error === 'string' ? meta.error : ''
      const messageText = typeof meta.message === 'string' ? meta.message : ''
      const combined = [safetyError, errorText, messageText].filter((v) => v && v.trim()).join(' | ')
      const isBlocked = Boolean(meta.safety_blocked) || (combined && pattern.test(combined))
      if (!isBlocked) continue
      const role = String(asset.role || '').trim()
      if (role) roles.add(role)
      if (!errorSample && combined) errorSample = combined
    }
    if (!roles.size) continue
    results.push({
      shotId,
      shotIndex: typeof shot.shot_index === 'number' ? shot.shot_index : undefined,
      roles: Array.from(roles),
      errorSample,
    })
  }
  return results
}

export function buildSnapshotShotById(shots: DreamweaverShotSnapshot[]): Map<string, DreamweaverShotSnapshot> {
  const map = new Map<string, DreamweaverShotSnapshot>()
  for (const shot of shots) {
    const id = getShotId(shot)
    if (!id) continue
    map.set(id, shot)
  }
  return map
}

export function computeSnapshotAssetCount(shots: DreamweaverShotSnapshot[]): number {
  return shots.reduce((acc, shot) => acc + getShotAssets(shot).length, 0)
}

export type SnapshotCompletedResult = {
  result: RunResult | null
  preflight: DreamweaverRunPreflight | null
}

export function buildSnapshotCompletedResult(
  data: DreamweaverRunSnapshot,
  runId: string,
): SnapshotCompletedResult {
  const nextResult = buildResultFromRunSnapshot(data, runId)
  return {
    result: nextResult,
    preflight: nextResult?.preflight || null,
  }
}

export type PlanItemWithId = { id: string; status?: string; uri?: string | null }

export function mergePlanItems<T extends PlanItemWithId>(prev: T[], incoming: T[]): T[] {
  const map = new Map(prev.map((item) => [item.id, item]))
  for (const item of incoming) {
    const existing = map.get(item.id)
    if (existing) {
      map.set(item.id, {
        ...existing,
        ...item,
        status: existing.status === 'done' ? 'done' : item.status,
        uri: existing.uri || item.uri,
      })
    } else {
      map.set(item.id, item)
    }
  }
  return Array.from(map.values())
}

export function resolveAssetKind(kindRaw: string, role: string): 'image' | 'video' {
  const lower = kindRaw.toLowerCase()
  if (lower === 'video') return 'video'
  if (lower === 'image') return 'image'
  if (role === 'video_clip' || role === 'merged_video') return 'video'
  return 'image'
}

export type SnapshotStatusFields = {
  status: string
  statusLower: string
  stage: string | null
  state: string | null
  progress: number
}

export function extractSnapshotStatusFields(data: { status?: unknown; stage?: unknown; state?: unknown; progress?: unknown } | null): SnapshotStatusFields {
  const status = String(data?.status || '').trim()
  return {
    status,
    statusLower: status.toLowerCase(),
    stage: data?.stage != null ? String(data.stage) : null,
    state: data?.state != null ? String(data.state) : null,
    progress: typeof data?.progress === 'number' ? (data.progress as number) : 0,
  }
}

export type AssetReadyPayload = {
  assetId: string
  uri: string
  role: string
  kind: 'image' | 'video'
  shotId: string | null
}

export function extractAssetReadyPayload(payload: Record<string, unknown>): AssetReadyPayload | null {
  const assetId = typeof payload.id === 'string' ? String(payload.id || '').trim() : ''
  if (!assetId) return null
  const uri = typeof payload.uri === 'string' ? String(payload.uri || '').trim() : ''
  const role = typeof payload.role === 'string' ? String(payload.role || '').trim() : ''
  const kindRaw = typeof payload.kind === 'string' ? String(payload.kind || '').trim() : ''
  const kind = resolveAssetKind(kindRaw, role)
  const shotId = payload.shot_id != null ? String(payload.shot_id) : null
  return { assetId, uri, role, kind, shotId }
}

export type TextStreamUpdate = {
  textUpdater: ((prev: Record<string, string>) => Record<string, string>) | null
  metaUpdater: ((prev: Record<string, { stage?: string | null; done?: boolean }>) => Record<string, { stage?: string | null; done?: boolean }>) | null
  handled: boolean
}

export function resolveTextStreamUpdate(
  eventType: string,
  payload: Record<string, unknown>,
  stage: string | null,
): TextStreamUpdate {
  if (eventType !== 'text_stream_start' && eventType !== 'text_stream_delta' && eventType !== 'text_stream_end') {
    return { textUpdater: null, metaUpdater: null, handled: false }
  }

  const streamKeyRaw = typeof payload.stream_key === 'string' ? String(payload.stream_key || '').trim() : ''
  const streamKey = streamKeyRaw || stage || 'default'

  if (eventType === 'text_stream_start') {
    return {
      textUpdater: (prev) => ({ ...prev, [streamKey]: '' }),
      metaUpdater: (prev) => ({ ...prev, [streamKey]: { stage, done: false } }),
      handled: true,
    }
  }

  if (eventType === 'text_stream_delta') {
    const chunk = typeof payload.chunk === 'string' ? String(payload.chunk || '') : ''
    const textUpdater = chunk
      ? (prev: Record<string, string>) => ({ ...prev, [streamKey]: (prev[streamKey] || '') + chunk })
      : null
    const metaUpdater = stage
      ? (prev: Record<string, { stage?: string | null; done?: boolean }>) => ({ ...prev, [streamKey]: { stage, done: prev[streamKey]?.done } })
      : null
    return { textUpdater, metaUpdater, handled: true }
  }

  if (eventType === 'text_stream_end') {
    return {
      textUpdater: null,
      metaUpdater: (prev) => ({ ...prev, [streamKey]: { stage, done: true } }),
      handled: true,
    }
  }

  return { textUpdater: null, metaUpdater: null, handled: false }
}

export type NotFoundRecovery = {
  handled: boolean
  pendingMessage: string | null
  shouldReset: boolean
}

export function resolveNotFoundRecovery(
  error: unknown,
  taskId: string | null,
  taskStatus: string | null,
  options: {
    isNotFoundError: (e: unknown) => boolean
    shouldTreatRunNotFoundAsPending: (taskId: string | null, status: string | null) => boolean
    pendingMessage: string
  },
): NotFoundRecovery {
  if (!options.isNotFoundError(error)) {
    return { handled: false, pendingMessage: null, shouldReset: false }
  }
  if (options.shouldTreatRunNotFoundAsPending(taskId, taskStatus)) {
    return { handled: true, pendingMessage: options.pendingMessage, shouldReset: false }
  }
  return { handled: true, pendingMessage: null, shouldReset: true }
}

export type LibraryPreviewEntry = {
  id: number
  url: string
  error: string
}

export type LibraryPreviewMaps = {
  previewMap: Record<number, string>
  previewErrorMap: Record<number, string>
}

export function collectLibraryPreviewMaps(entries: LibraryPreviewEntry[]): LibraryPreviewMaps {
  const previewMap: Record<number, string> = {}
  const previewErrorMap: Record<number, string> = {}
  for (const entry of entries) {
    if (entry.url) previewMap[entry.id] = entry.url
    if (entry.error) previewErrorMap[entry.id] = entry.error
  }
  return { previewMap, previewErrorMap }
}

export function extractMissingRoleSet(data: { review?: { missing_roles?: unknown } | null } | null): Set<string> {
  const missingRoles = Array.isArray(data?.review?.missing_roles) ? (data.review.missing_roles as string[]) : []
  return new Set(missingRoles.map((role) => String(role || '').trim()).filter(Boolean))
}

export function applySnapshotCompletedResult(
  data: DreamweaverRunSnapshot | null,
  runId: string,
  setters: {
    setResult: (updater: (prev: RunResult | null) => RunResult | null) => void
    setRunPreflight: (value: DreamweaverRunPreflight | null) => void
  },
): void {
  const statusLower = String(data?.status || '').trim().toLowerCase()
  if (statusLower !== 'completed' || !data) return
  const { result: nextResult, preflight } = buildSnapshotCompletedResult(data, runId)
  if (nextResult) {
    setters.setResult((prev) => mergeRunResult(prev, nextResult))
    if (preflight) {
      setters.setRunPreflight(preflight)
    }
  }
}
