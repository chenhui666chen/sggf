import type {
  DreamweaverShotAsset,
  DreamweaverShotFrame,
  DreamweaverShotSchemaMeta,
  DreamweaverShotSnapshot,
  DreamweaverVideoClipJob,
  DreamweaverRunSnapshot,
} from '@/types/dreamweaver'
import { asObject } from './runPageDataTransforms'

export type DreamweaverModelOption = {
  value: string
  label: string
}

export function getShotAssets(shot: DreamweaverShotSnapshot | null | undefined): DreamweaverShotAsset[] {
  return Array.isArray(shot?.assets) ? shot.assets : []
}

export function getShotId(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(shot?.shot_key || shot?.shot_id || '').trim()
}

export function getShotDesc(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(shot?.desc || '').trim()
}

export function getShotFramePrompt(frame: DreamweaverShotFrame | null | undefined): string {
  return String(frame?.prompt || '').trim()
}

export function getShotFramePath(frame: DreamweaverShotFrame | null | undefined): string {
  return String(frame?.path || '').trim()
}

export function getShotFrameCandidateUris(frame: DreamweaverShotFrame | null | undefined): string[] {
  const candidates = asObject(frame?.meta)?.candidates
  if (!Array.isArray(candidates)) return []
  return candidates
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function getShotSchemaMeta(shot: DreamweaverShotSnapshot | null | undefined): DreamweaverShotSchemaMeta | null {
  const meta = shot?.shot_schema_v2?.meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  return meta
}

export function getShotVideoPromptOverride(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(getShotSchemaMeta(shot)?.video_prompt_override || '').trim()
}

export function getShotVideoPromptGenerated(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(getShotSchemaMeta(shot)?.video_prompt_generated || '').trim()
}

export function getResultVideoClipPath(clip: unknown): string {
  const path = asObject(clip)?.path
  return typeof path === 'string' ? path.trim() : ''
}

export function getResultVideoClipMeta(clip: unknown): Record<string, unknown> | null {
  return asObject(asObject(clip)?.meta)
}

export function getDiagnosticStoryboardPrompt(
  storyboard: Record<string, unknown> | null | undefined,
  frameKey: 'head_frame' | 'tail_frame',
): string {
  const framePrompt = asObject(storyboard?.[frameKey])?.prompt
  if (typeof framePrompt === 'string' && framePrompt.trim()) return framePrompt.trim()
  const visualDesc = storyboard?.visual_desc
  if (typeof visualDesc === 'string' && visualDesc.trim()) return visualDesc.trim()
  const desc = storyboard?.desc
  return typeof desc === 'string' ? desc.trim() : ''
}

export function withRunSnapshotVideoJobs(
  snapshot: DreamweaverRunSnapshot | null,
  jobs: DreamweaverVideoClipJob[],
): DreamweaverRunSnapshot | null {
  if (!snapshot) return snapshot
  const contract = asObject(snapshot.contract) || {}
  const runtimeConfig = asObject(contract.runtime_config) || {}
  return {
    ...snapshot,
    contract: {
      ...contract,
      runtime_config: {
        ...runtimeConfig,
        video_clip_jobs: jobs,
      },
    },
  }
}

export function getThrownErrorResponse(error: unknown): Record<string, unknown> | null {
  return asObject(asObject(error)?.response)
}

export function getThrownErrorStatus(error: unknown): number | null {
  const status = getThrownErrorResponse(error)?.status
  return typeof status === 'number' ? Number(status) : null
}

export function getThrownErrorMessage(error: unknown): string {
  const message = asObject(error)?.message
  return typeof message === 'string' ? message : ''
}

export function isNotFoundError(error: unknown): boolean {
  return getThrownErrorStatus(error) === 404
}

export function isTimeoutErrorLike(error: unknown): boolean {
  return getThrownErrorMessage(error).toLowerCase().includes('timeout')
}

export function isNetworkErrorLike(error: unknown): boolean {
  return !getThrownErrorResponse(error)
}

export function mapCatalogOptionToDreamweaverOption(option: { model_id: string; label: string }): DreamweaverModelOption {
  return {
    value: option.model_id,
    label: option.label,
  }
}

export function resolvePreferredDreamweaverOption(
  options: DreamweaverModelOption[],
  preferredModelId: string,
): DreamweaverModelOption | null {
  return options.find((option) => option.value === preferredModelId) || options[0] || null
}
