import type { LibraryAsset, RunResult } from '@/types/dreamweaver'

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

export function buildProtectedLibraryAssetUrl(assetId: number): string {
  return `protected://dreamweaver-library/${assetId}`
}

export function libraryAssetToCssAspectRatio(asset: LibraryAsset | null, fallback: string): string {
  const meta = asset?.meta || {}
  const width = Number((meta as Record<string, unknown>).width)
  const height = Number((meta as Record<string, unknown>).height)
  if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
    return `${width} / ${height}`
  }
  const ratio = typeof (meta as Record<string, unknown>).ratio === 'string' 
    ? String((meta as Record<string, unknown>).ratio).trim() 
    : ''
  if (ratio) return ratioToCssAspectRatio(ratio, fallback)
  return fallback
}

export function extractMergedVideoFromContract(contract: Record<string, unknown> | null): string | null {
  const anchorSets = contract?.anchor_sets_ref as Record<string, unknown> | undefined
  const mergedFromAnchor = anchorSets?.merged_video as Record<string, unknown> | undefined
  if (mergedFromAnchor && typeof mergedFromAnchor.uri === 'string') {
    return mergedFromAnchor.uri.trim()
  }

  const assets = Array.isArray(contract?.assets) ? contract.assets as unknown[] : []
  for (const item of assets) {
    const role = item && typeof item === 'object' ? String((item as Record<string, unknown>).role || '') : ''
    if (role !== 'merged_video') continue
    const uri = item && typeof item === 'object' ? (item as Record<string, unknown>).uri as string | null : null
    if (typeof uri === 'string' && uri.trim()) return uri.trim()
  }
  return null
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
  }
}

export function formatPath(value: unknown): string | null {
  if (!value || typeof value !== 'string') return null
  const parts = value.split(/[\\/]+/).filter(Boolean)
  return parts.slice(-2).join('/')
}

export function formatPaths(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const formatted = value.map(formatPath).filter(Boolean)
  return formatted.length ? formatted.join('  ') : null
}

const DREAMWEAVER_RUN_STORAGE_PREFIX = 'dreamweaver:lastRun:'

export function dreamweaverRunStorageKey(projectId: number): string {
  return `${DREAMWEAVER_RUN_STORAGE_PREFIX}${projectId}`
}

export function readPersistedDreamWeaverRun(projectId: number): Record<string, unknown> | null {
  try {
    const raw = localStorage.getItem(dreamweaverRunStorageKey(projectId))
    if (!raw) return null
    const obj = JSON.parse(raw) as Record<string, unknown>
    if (!obj || typeof obj !== 'object') return null
    if (typeof obj.run_id !== 'string' || !String(obj.run_id).trim()) return null
    return obj
  } catch {
    return null
  }
}

export function writePersistedDreamWeaverRun(projectId: number, patch: Record<string, unknown>): void {
  try {
    const prev = readPersistedDreamWeaverRun(projectId)
    const next: Record<string, unknown> = {
      project_id: projectId,
      run_id: String(patch.run_id ?? prev?.run_id ?? '').trim(),
      task_id: patch.task_id ?? prev?.task_id ?? null,
      status: patch.status ?? prev?.status ?? null,
      updated_at: Date.now(),
      ...patch,
    }
    if (!next.run_id) return
    localStorage.setItem(dreamweaverRunStorageKey(projectId), JSON.stringify(next))
  } catch {
    // ignore
  }
}

export function clearPersistedDreamWeaverRun(projectId: number): void {
  try {
    localStorage.removeItem(dreamweaverRunStorageKey(projectId))
  } catch {
    // ignore
  }
}
