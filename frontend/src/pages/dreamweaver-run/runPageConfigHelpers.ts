import type { LibraryPayload } from '@/types/dreamweaver'
import {
  STYLE_PRESETS,
  STYLE_PRESET_LABELS,
  IMAGE_RATIOS,
  IMAGE_RATIOS_LABELS,
  IMAGE_RESOLUTIONS,
  IMAGE_RESOLUTIONS_LABELS,
} from '@/constants/dreamweaver'
import { DreamweaverModelOption, mapCatalogOptionToDreamweaverOption, resolvePreferredDreamweaverOption } from './runPageAccessors'
import { arrayLength } from './runPageDiagnosticHelpers'

export interface RestartMenuItemDef {
  key: string
  label: string
  stage: string
  isCustom?: boolean
}

export const RESTART_MENU_DEFS: RestartMenuItemDef[] = [
  { key: 'edit', label: '重新合成（EDIT）', stage: 'EDIT' },
  { key: 'video', label: '从镜头视频（VIDEO）重跑', stage: 'VIDEO' },
  { key: 'video-shots', label: '重跑指定镜头视频（VIDEO）…', stage: 'VIDEO', isCustom: true },
  { key: 'keyframes', label: '从关键帧（KEYFRAMES）重跑', stage: 'KEYFRAMES' },
  { key: 'keyframe-cameras', label: '重跑指定相机关键帧（KEYFRAMES）…', stage: 'KEYFRAMES', isCustom: true },
  { key: 'storyboard', label: '从分镜（STORYBOARD）重跑', stage: 'STORYBOARD' },
  { key: 'script', label: '从剧本（SCRIPT）重跑', stage: 'SCRIPT' },
]

export interface RestartMenuItem {
  key: string
  label: string
  onClick: () => void
  disabled: boolean
}

export function buildRestartMenuItems(params: {
  currentRunId: string | null
  running: boolean
  restartLoading: boolean
  requestRestartVideoShots: () => void
  requestRestartKeyframeCameras: () => void
  triggerRestartFromStage: (stage: string) => void
}): RestartMenuItem[] {
  const disabled = !params.currentRunId || params.running || params.restartLoading
  return RESTART_MENU_DEFS.map((def) => ({
    key: def.key,
    label: def.label,
    onClick: def.isCustom
      ? (def.key === 'video-shots' ? params.requestRestartVideoShots : params.requestRestartKeyframeCameras)
      : () => params.triggerRestartFromStage(def.stage),
    disabled,
  }))
}

export type DreamweaverRunConfig = {
  quality_mode: 'quality' | 'cost'
  qc_allow_fail: boolean
  smart_tuning: boolean
  ab_variant?: string
  video_require_confirmation: boolean
  prompt_review_required: boolean
  style_preset: string
  image_ratio: string
  image_resolution: string
  image_model: string
  video_model: string
  video_edit_model: string
  vision_model: string
  enable_video_edit: boolean
  enable_vision_review: boolean
  enable_safety_audit: boolean
  safety_fail_policy: 'warn' | 'block'
}

export function buildDreamweaverRunConfig(params: {
  highQuality: boolean
  qcAllowFail: boolean
  smartTuning: boolean
  abVariant: string
  videoRequireConfirmation: boolean
  promptReviewRequired: boolean
  stylePreset: string
  imageRatio: string
  imageResolution: string
  imageModel: string
  videoModel: string
  videoEditModel: string
  visionModel: string
  enableVideoEdit: boolean
  enableVisionReview: boolean
  enableSafetyAudit: boolean
  safetyFailPolicy: string
}): DreamweaverRunConfig {
  return {
    quality_mode: params.highQuality ? 'quality' : 'cost',
    qc_allow_fail: params.qcAllowFail,
    smart_tuning: params.smartTuning,
    ab_variant: params.abVariant.trim() ? params.abVariant.trim() : undefined,
    video_require_confirmation: params.videoRequireConfirmation,
    prompt_review_required: params.promptReviewRequired,
    style_preset: params.stylePreset,
    image_ratio: params.imageRatio,
    image_resolution: params.imageResolution,
    image_model: params.imageModel,
    video_model: params.videoModel,
    video_edit_model: params.videoEditModel,
    vision_model: params.visionModel,
    enable_video_edit: params.enableVideoEdit,
    enable_vision_review: params.enableVisionReview,
    enable_safety_audit: params.enableSafetyAudit,
    safety_fail_policy: params.safetyFailPolicy === 'block' ? 'block' : 'warn',
  }
}

export type GenerationConfigSource = {
  style_preset?: string | null
  quality_mode?: string | null
  qc_allow_fail?: boolean | null
  smart_tuning?: boolean | null
  video_require_confirmation?: boolean | null
  prompt_review_required?: boolean | null
  image_ratio?: string | null
  image_resolution?: string | null
  image_model?: string | null
  video_model?: string | null
  video_edit_model?: string | null
  vision_model?: string | null
  enable_video_edit?: boolean | null
  enable_vision_review?: boolean | null
  enable_safety_audit?: boolean | null
  safety_fail_policy?: 'warn' | 'block' | string | null
}

export type GenerationConfigSetters = {
  setStylePreset: (v: string) => void
  setHighQuality: (v: boolean) => void
  setQcAllowFail: (v: boolean) => void
  setSmartTuning: (v: boolean) => void
  setVideoRequireConfirmation: (v: boolean) => void
  setPromptReviewRequired: (v: boolean) => void
  setImageRatio: (v: string) => void
  setImageResolution: (v: string) => void
  setImageModel: (v: string) => void
  setVideoModel: (v: string) => void
  setVideoEditModel: (v: string) => void
  setVisionModel: (v: string) => void
  setEnableVideoEdit: (v: boolean) => void
  setEnableVisionReview: (v: boolean) => void
  setEnableSafetyAudit: (v: boolean) => void
  setSafetyFailPolicy: (v: 'warn' | 'block') => void
}

export function applyGenerationConfig(source: GenerationConfigSource, setters: GenerationConfigSetters): void {
  if (source.style_preset) setters.setStylePreset(source.style_preset)
  if (source.quality_mode) setters.setHighQuality(source.quality_mode === 'quality')
  if (typeof source.qc_allow_fail === 'boolean') setters.setQcAllowFail(source.qc_allow_fail)
  if (typeof source.smart_tuning === 'boolean') setters.setSmartTuning(source.smart_tuning)
  if (typeof source.video_require_confirmation === 'boolean') setters.setVideoRequireConfirmation(source.video_require_confirmation)
  if (typeof source.prompt_review_required === 'boolean') setters.setPromptReviewRequired(source.prompt_review_required)
  if (source.image_ratio) setters.setImageRatio(source.image_ratio)
  if (source.image_resolution) setters.setImageResolution(source.image_resolution)
  if (source.image_model) setters.setImageModel(source.image_model)
  if (source.video_model) setters.setVideoModel(source.video_model)
  if (source.video_edit_model) setters.setVideoEditModel(source.video_edit_model)
  if (source.vision_model) setters.setVisionModel(source.vision_model)
  if (typeof source.enable_video_edit === 'boolean') setters.setEnableVideoEdit(source.enable_video_edit)
  if (typeof source.enable_vision_review === 'boolean') setters.setEnableVisionReview(source.enable_vision_review)
  if (typeof source.enable_safety_audit === 'boolean') setters.setEnableSafetyAudit(source.enable_safety_audit)
  if (source.safety_fail_policy === 'warn' || source.safety_fail_policy === 'block') {
    setters.setSafetyFailPolicy(source.safety_fail_policy)
  }
}

export function normalizeShotIds(shotIds: unknown): string[] {
  if (!Array.isArray(shotIds)) return []
  return shotIds
    .map((s) => String(s || '').trim())
    .filter((s) => s)
    .filter((s, idx, arr) => arr.indexOf(s) === idx)
    .slice(0, 200)
}

export function normalizeCameraIndices(camIdxs: unknown): number[] {
  if (!Array.isArray(camIdxs)) return []
  return camIdxs
    .map((n) => Number(n))
    .filter((n) => Number.isFinite(n))
    .map((n) => Math.trunc(n))
    .filter((n, idx, arr) => arr.indexOf(n) === idx)
    .slice(0, 200)
}

export function buildRestartPartialHint(normalizedShotIds: string[], normalizedCamIdxs: number[]): string {
  if (normalizedShotIds.length > 0) {
    return `\n\n镜头：${normalizedShotIds.slice(0, 6).join(', ')}${normalizedShotIds.length > 6 ? '…' : ''}\n（仅重跑这些镜头，其余镜头将复用历史产物；仍会重新合成下游成片）`
  }
  if (normalizedCamIdxs.length > 0) {
    return `\n\n相机：${normalizedCamIdxs.join(', ')}\n（仅重跑这些相机的镜头，其余镜头将复用历史产物；仍会重新合成下游成片）`
  }
  return ''
}

export function validateRestartParams(
  startStateRaw: string,
  normalizedShotIds: string[],
  normalizedCamIdxs: number[],
): { valid: boolean; error?: string } {
  if (normalizedShotIds.length > 0 && normalizedCamIdxs.length > 0) {
    return { valid: false, error: 'shot_id 与 cam_idx 不能同时使用' }
  }

  if (
    (normalizedShotIds.length > 0 || normalizedCamIdxs.length > 0) &&
    !['KEYFRAMES', 'MIDFRAMES', 'VIDEO'].includes(startStateRaw)
  ) {
    return { valid: false, error: '镜头/相机级局部重跑仅支持 KEYFRAMES/MIDFRAMES/VIDEO 阶段' }
  }

  return { valid: true }
}

export function resolveConfigRunDisabled(params: {
  running: boolean
  lockedGenerationConfigLoading: boolean
  selectedProjectId: number | null
  selectedChapterIdsLength: number
}): boolean {
  return params.running || params.lockedGenerationConfigLoading || !params.selectedProjectId || params.selectedChapterIdsLength === 0
}

export function isRestartDisabled(currentRunId: string | null, running: boolean, restartLoading: boolean): boolean {
  return !currentRunId || running || restartLoading
}

export function isLibraryActionDisabled(selectedProjectId: number | null, libraryLoading: boolean): boolean {
  return !selectedProjectId || libraryLoading
}

export interface SelectOption {
  value: string
  label: string
}

export function mapEnumToOptions(enumObj: Record<string, string>, labels: Record<string, string>): SelectOption[] {
  return Object.values(enumObj).map((optionValue) => ({
    value: optionValue,
    label: labels[optionValue] || optionValue,
  }))
}

export const STYLE_PRESET_OPTIONS = mapEnumToOptions(STYLE_PRESETS, STYLE_PRESET_LABELS)
export const IMAGE_RATIO_OPTIONS = mapEnumToOptions(IMAGE_RATIOS, IMAGE_RATIOS_LABELS)
export const IMAGE_RESOLUTION_OPTIONS = mapEnumToOptions(IMAGE_RESOLUTIONS, IMAGE_RESOLUTIONS_LABELS)

export function buildConfigDialogSubtitle(
  projectTitle: string | undefined,
  projectId: number | null,
  selectedChapterCount: number,
  totalChapterCount: number,
): string {
  const title = projectTitle || (projectId ? `项目 #${projectId}` : '请选择项目')
  const chapterSuffix = totalChapterCount > 0 ? ` · 已选 ${selectedChapterCount}/${totalChapterCount} 章` : ''
  return title + chapterSuffix
}

export function resolveModelOptions(
  catalogGroup: { model_id: string; label: string }[] | undefined,
  fallback: DreamweaverModelOption[],
): DreamweaverModelOption[] {
  return catalogGroup?.map(mapCatalogOptionToDreamweaverOption) || fallback
}

export function applyModelOptionSync(
  currentValue: string,
  options: DreamweaverModelOption[],
  defaultModelId: string,
): string | null {
  if (!shouldUpdateModelOption(currentValue, options)) return null
  return resolveDefaultModelValue(options, defaultModelId)
}

export function shouldUpdateModelOption(currentValue: string, options: Array<{ value: string }>): boolean {
  return !options.some((option) => option.value === currentValue)
}

export function resolveDefaultModelValue(
  options: DreamweaverModelOption[],
  defaultId: string,
): string {
  return resolvePreferredDreamweaverOption(options, defaultId)?.value || defaultId
}

export function resolveLibraryPromptReviewMessage(
  libraryApproved: boolean,
  promptReviewReady: boolean,
  promptReviewRequiredSnapshot: boolean,
): string {
  return libraryApproved
    ? promptReviewReady
      ? '素材库已通过，提示词已确认：可继续生成进入镜头阶段。'
      : '素材库已通过，但提示词待确认：请先完成提示词审核。'
    : promptReviewRequiredSnapshot
      ? '素材库待审核：通过后还需确认提示词，才能继续生成。'
      : '素材库待审核：通过后可继续生成。'
}

export type PendingLibraryControlsProps = {
  loadDisabled: boolean
  approveDisabled: boolean
  resumeDisabled: boolean
  resumeLoading: boolean
}

export function buildPendingLibraryControlsProps(params: {
  selectedProjectId: number | null
  libraryLoading: boolean
  canResumeFromLibrary: boolean
  resumeLoading: boolean
}): PendingLibraryControlsProps {
  return {
    loadDisabled: isLibraryActionDisabled(params.selectedProjectId, params.libraryLoading),
    approveDisabled: isLibraryActionDisabled(params.selectedProjectId, params.libraryLoading),
    resumeDisabled: !params.canResumeFromLibrary,
    resumeLoading: params.resumeLoading,
  }
}

export type PendingLibraryRuntimeStatusProps = {
  libraryError: string | null
  libraryLoading: boolean
  missingCount: number
  unapprovedCount: number
  hasReview: boolean
}

export function buildPendingLibraryRuntimeStatusProps(params: {
  libraryError: string | null
  libraryLoading: boolean
  library: LibraryPayload | null
}): PendingLibraryRuntimeStatusProps {
  return {
    libraryError: params.libraryError,
    libraryLoading: params.libraryLoading,
    missingCount: arrayLength(params.library?.review?.missing_roles, 0) ?? 0,
    unapprovedCount: arrayLength(params.library?.review?.unapproved_roles, 0) ?? 0,
    hasReview: Boolean(params.library?.review),
  }
}

export function resolvePendingLibraryNoticeSeverity(libraryApproved: boolean, promptReviewReady: boolean, isReadyView: boolean): 'success' | 'warning' | 'info' {
  if (libraryApproved && promptReviewReady) return 'success'
  if (isReadyView) return 'info'
  return 'warning'
}
