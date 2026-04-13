import type {
  PersistedDreamWeaverRun,
  RunResult,
  LibraryPayload,
  LibraryAsset,
  DreamweaverLibraryPlanItem,
  CharacterView,
} from '../types/dreamweaver'

export const DREAMWEAVER_RUN_STORAGE_PREFIX = 'dreamweaver_run_'

export function dreamweaverRunStorageKey(projectId: number): string {
  return `${DREAMWEAVER_RUN_STORAGE_PREFIX}${projectId}`
}

export function readPersistedDreamWeaverRun(projectId: number): PersistedDreamWeaverRun | null {
  try {
    const raw = localStorage.getItem(dreamweaverRunStorageKey(projectId))
    if (!raw) return null
    const obj = JSON.parse(raw) as PersistedDreamWeaverRun
    if (!obj || typeof obj !== 'object') return null
    if (typeof obj.run_id !== 'string' || !obj.run_id.trim()) return null
    return obj
  } catch {
    return null
  }
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
      video_fps: patch.video_fps ?? prev?.video_fps,
      selected_chapter_ids: patch.selected_chapter_ids ?? prev?.selected_chapter_ids,
      updated_at: Date.now(),
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

export function stageToPreviewStep(stage: string | null | undefined): number {
  const value = (stage || '').trim().toLowerCase()
  if (!value) return 0
  if (value === 'init' || value === 'script' || value === 'waiting_script_approval') return 0
  if (value === 'storyboard') return 1
  if (value === 'asset_library' || value === 'waiting_approval') return 2
  if (value === 'keyframes' || value === 'midframes' || value === 'video' || value === 'waiting_video_confirmation') return 3
  if (value === 'edit' || value === 'review' || value === 'done' || value === 'rework' || value === 'failed') return 4
  return 0
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

export function characterViewLabel(view: CharacterView): string {
  const labels: Record<CharacterView, string> = {
    front: '正面',
    side: '侧面',
    back: '背面',
    half_front: '半身正面',
    half_3_4: '半身3-4',
    half_side: '半身侧面',
  }
  return labels[view] || view
}

export function parseLibraryRole(role: string): { entityType: 'character' | 'scene' | 'prop' | 'unknown'; entityId: number | null; view: CharacterView | null } {
  const raw = String(role || '').trim()
  if (!raw) return { entityType: 'unknown', entityId: null, view: null }

  if (raw.startsWith('lib_character_portrait_')) {
    const viewMap: Record<string, CharacterView> = {
      front: 'front',
      side: 'side',
      back: 'back',
      half_front: 'half_front',
      half_3_4: 'half_3_4',
      half_side: 'half_side',
    }
    const viewKey = raw.replace('lib_character_portrait_', '').toLowerCase()
    const view = viewMap[viewKey] || null
    return { entityType: 'character', entityId: null, view }
  }

  const sceneMatch = raw.match(/^lib_scene_card:(\d+)$/)
  if (sceneMatch) {
    const entityId = Number.parseInt(sceneMatch[1], 10)
    return { entityType: 'scene', entityId: Number.isFinite(entityId) && entityId > 0 ? entityId : null, view: null }
  }

  const propMatch = raw.match(/^lib_prop_card:(\d+)$/)
  if (propMatch) {
    const entityId = Number.parseInt(propMatch[1], 10)
    return { entityType: 'prop', entityId: Number.isFinite(entityId) && entityId > 0 ? entityId : null, view: null }
  }

  return { entityType: 'unknown', entityId: null, view: null }
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
  const spec = data.spec && typeof data.spec === 'object' ? data.spec : {}
  const sections: Array<{ key: string; entityType: 'character' | 'scene' | 'prop' }> = [
    { key: 'characters', entityType: 'character' },
    { key: 'scenes', entityType: 'scene' },
    { key: 'props', entityType: 'prop' },
  ]
  for (const section of sections) {
    const items = Array.isArray((spec as Record<string, unknown>)?.[section.key]) ? ((spec as Record<string, unknown>)[section.key] as unknown[]) : []
    for (const item of items) {
      if (!item || typeof item !== 'object') continue
      const entityId = Number.parseInt(String((item as Record<string, unknown>).entity_id ?? ''), 10)
      if (!Number.isFinite(entityId) || entityId <= 0) continue
      const name = String((item as Record<string, unknown>).name || '').trim()
      if (!name) continue
      entityNameByKey.set(`${section.entityType}:${entityId}`, name)
    }
  }

  const requiredRolesRaw = Array.isArray((data.review as Record<string, unknown>)?.required_roles)
    ? (((data.review as Record<string, unknown>).required_roles as unknown[]) ?? [])
    : []
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
    const viewLabel = parsed.entityType === 'character' && parsed.view ? characterViewLabel(parsed.view) : ''
    const baseLabel = entityName || role
    const label = viewLabel && !baseLabel.includes(viewLabel) ? `${baseLabel} ${viewLabel}` : baseLabel

    items.push({
      id: role,
      role,
      entity_type: entityType,
      entity_id: entityId,
      entity_name: entityName,
      label,
      view: parsed.entityType === 'character' && parsed.view ? parsed.view : null,
      status,
      kind: 'image',
      uri: hasUri ? String(asset!.uri || '').trim() : null,
      asset_id: asset?.id ?? null,
      approved: typeof asset?.meta?.approved === 'boolean' ? Boolean(asset?.meta?.approved) : null,
    })
  }
  return items
}

export function extractMergedVideoFromContract(contract: unknown): string | null {
  const anchorSets = (contract as Record<string, unknown>)?.anchor_sets_ref
  const mergedFromAnchor = (anchorSets as Record<string, unknown>)?.merged_video as Record<string, unknown> | undefined
  const uriFromAnchor = mergedFromAnchor?.uri
  if (typeof uriFromAnchor === 'string' && uriFromAnchor.trim()) return uriFromAnchor.trim()

  const assets = Array.isArray((contract as Record<string, unknown>)?.assets) ? (contract as Record<string, unknown>).assets as unknown[] : []
  for (const item of assets) {
    const role = item && typeof item === 'object' ? String((item as Record<string, unknown>).role || '') : ''
    if (role !== 'merged_video') continue
    const uri = item && typeof item === 'object' ? (item as Record<string, unknown>).uri as unknown : null
    if (typeof uri === 'string' && uri.trim()) return uri.trim()
  }
  return null
}

export function buildResultFromRunSnapshot(data: unknown, fallbackRunId: string): RunResult | null {
  const contract = (data as Record<string, unknown>)?.contract && typeof (data as Record<string, unknown>).contract === 'object' ? (data as Record<string, unknown>).contract as Record<string, unknown> : null
  if (!contract) return null

  const runtimeCfg = contract.runtime_config && typeof contract.runtime_config === 'object' ? contract.runtime_config as Record<string, unknown> : {}
  const chapterIds = Array.isArray(runtimeCfg.chapter_ids) ? runtimeCfg.chapter_ids as number[] : []
  let plan: Record<string, unknown> | undefined =
    runtimeCfg.plan && typeof runtimeCfg.plan === 'object'
      ? runtimeCfg.plan as Record<string, unknown>
      : typeof runtimeCfg.plan_text === 'string' && (runtimeCfg.plan_text as string).trim()
        ? { text: (runtimeCfg.plan_text as string).trim() }
        : undefined
  if (!plan) {
    const scriptText = typeof runtimeCfg.script_text === 'string' ? runtimeCfg.script_text as string : ''
    if (scriptText.trim()) {
      const lines = scriptText.split(/\r?\n/)
      const start = lines.findIndex((ln: string) => ln.trim() === '## 概要')
      if (start >= 0) {
        const picked: string[] = []
        for (const ln of lines.slice(start + 1)) {
          const s = ln.trim()
          if (!s) continue
          if (s.startsWith('## ')) break
          if (s.startsWith('-')) {
            picked.push(s)
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

  const episodes = Array.isArray(contract.episodes) ? contract.episodes as unknown[] : []
  for (const ep of episodes) {
    const shots = ep && typeof ep === 'object' && Array.isArray((ep as Record<string, unknown>).shots) ? (ep as Record<string, unknown>).shots as unknown[] : []
    for (const shot of shots) {
      const shotSchemaV2 = (shot as Record<string, unknown>)?.shot_schema_v2 && typeof (shot as Record<string, unknown>).shot_schema_v2 === 'object' ? (shot as Record<string, unknown>).shot_schema_v2 as Record<string, unknown> : {}
      storyboard.push({
        scene_id: (shot as Record<string, unknown>)?.scene_id,
        shot_id: (shot as Record<string, unknown>)?.shot_key,
        desc: (shot as Record<string, unknown>)?.desc,
        duration_s: (shot as Record<string, unknown>)?.duration_s,
        cam_idx: shotSchemaV2?.cam_idx,
        visual_desc: shotSchemaV2?.visual_desc,
        ff_desc: shotSchemaV2?.ff_desc,
        lf_desc: shotSchemaV2?.lf_desc,
        motion_desc: shotSchemaV2?.motion_desc,
        audio_desc: shotSchemaV2?.audio_desc,
        ff_vis_char_ids: shotSchemaV2?.ff_vis_char_ids,
        lf_vis_char_ids: shotSchemaV2?.lf_vis_char_ids,
        head_frame: (shot as Record<string, unknown>)?.head_frame,
        tail_frame: (shot as Record<string, unknown>)?.tail_frame,
      })

      const assets = Array.isArray((shot as Record<string, unknown>)?.assets) ? (shot as Record<string, unknown>).assets as unknown[] : []
      for (const asset of assets) {
        const role = asset && typeof asset === 'object' ? String((asset as Record<string, unknown>).role || '') : ''
        const uri = asset && typeof asset === 'object' ? (asset as Record<string, unknown>).uri as unknown : null
        if (typeof uri !== 'string' || !uri.trim()) continue
        const meta = asset && typeof asset === 'object' && (asset as Record<string, unknown>).meta && typeof (asset as Record<string, unknown>).meta === 'object' ? (asset as Record<string, unknown>).meta as Record<string, unknown> : {}

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

  const mergedVideo = extractMergedVideoFromContract(contract)
  const autoqc = contract.autoqc && typeof contract.autoqc === 'object' ? contract.autoqc as Record<string, unknown> : undefined

  const cameraTreeGeneration =
    runtimeCfg.camera_tree_generation && typeof runtimeCfg.camera_tree_generation === 'object'
      ? (runtimeCfg.camera_tree_generation as Record<string, unknown>)
      : undefined
  const cameraTree = Array.isArray(runtimeCfg.camera_tree) ? (runtimeCfg.camera_tree as unknown[]) : undefined
  const cameraStates = Array.isArray(runtimeCfg.camera_states) ? (runtimeCfg.camera_states as unknown[]) : undefined
  const cameraScenes = Array.isArray(runtimeCfg.camera_scenes) ? (runtimeCfg.camera_scenes as unknown[]) : undefined

  const runId = typeof (data as Record<string, unknown>)?.run_id === 'string' && ((data as Record<string, unknown>).run_id as string).trim() ? ((data as Record<string, unknown>).run_id as string).trim() : fallbackRunId
  const state = typeof (data as Record<string, unknown>)?.state === 'string' && ((data as Record<string, unknown>).state as string).trim() ? ((data as Record<string, unknown>).state as string).trim() : 'DONE'
  const stage = (data as Record<string, unknown>)?.stage != null ? String((data as Record<string, unknown>).stage) : null
  const progress = typeof (data as Record<string, unknown>)?.progress === 'number' ? (data as Record<string, unknown>).progress as number : null

  return {
    run_id: runId,
    state,
    stage,
    progress,
    artifacts: null,
    source_chapter_count: chapterIds.length,
    plan,
    storyboard: storyboard.length ? storyboard : undefined,
    camera_tree_generation: cameraTreeGeneration ?? null,
    camera_tree: cameraTree ?? null,
    camera_states: cameraStates ?? null,
    camera_scenes: cameraScenes ?? null,
    keyframes: keyframes.length ? keyframes : undefined,
    midframes: midframes.length ? midframes : undefined,
    video_clips: videoClips.length ? videoClips : undefined,
    merged_video: mergedVideo,
    autoqc,
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
