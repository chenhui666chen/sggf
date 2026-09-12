import type {
  StoryExpansionAnalysis,
} from '@/types/storyExpansion'
import type {
  StoryExpansionDialogFormState,
  StoryExpansionRequestControls,
} from '@/types/storyExpansionDialog'
import {
  getStoryExpansionValidationError,
  shouldConfirmStoryExpansionVolumeOverwrite,
  type StoryExpansionRequestPlan,
} from './storyExpansionPlanning'
import type { TFunction } from 'i18next'
import {
  createStoryExpansionRequestPayloadFromForm,
  createStoryExpansionRequestPlanFromForm,
  type StoryExpansionRequestContent,
} from './storyExpansionFormRequest'

export type StoryExpansionSubmitContent = StoryExpansionRequestContent

export interface StoryExpansionSubmitPreflightInput {
  content: StoryExpansionSubmitContent
  currentChapterCount: number
  currentCharacterCount: number
  form: StoryExpansionDialogFormState
}

export interface StoryExpansionSubmitPreflight {
  requestPlan: StoryExpansionRequestPlan
  validationError: string | null
  confirmDialogs: StoryExpansionConfirmDialogConfig[]
}

export interface StoryExpansionSubmitPayloadInput {
  projectId: number
  content: StoryExpansionSubmitContent
  currentChapterCount: number
  currentCharacterCount: number
  form: StoryExpansionDialogFormState
  requestControls: StoryExpansionRequestControls
  analysis: StoryExpansionAnalysis | null
  requestPlan?: StoryExpansionRequestPlan
}

export interface StoryExpansionConfirmDialogConfig {
  kind: 'volume_overwrite' | 'framework_reset' | 'framework_regenerate'
  title: string
  description: string
  detail: string
  confirmLabel: string
  cancelLabel: string
  message: string
}

export type StoryExpansionConfirmAction = (
  confirmDialog: StoryExpansionConfirmDialogConfig,
) => boolean | Promise<boolean>

function getStoryExpansionVolumeLabel(
  targetVolumeIndex: number | null | undefined,
  t?: TFunction,
): string {
  if (!Number.isFinite(targetVolumeIndex)) {
    return t ? t('storyExpansion.submission.volumeFallback') : '当前卷'
  }
  return t ? t('storyExpansion.submission.volumeLabel', { n: targetVolumeIndex }) : `第 ${targetVolumeIndex} 卷`
}

export function getStoryExpansionVolumeOverwriteConfirmMessage(
  targetVolumeIndex: number | null | undefined,
  t?: TFunction,
): string {
  return t
    ? t('storyExpansion.submission.overwriteMsg', { n: targetVolumeIndex })
    : `第${targetVolumeIndex}卷细纲已存在，重新协同生成将覆盖现有细纲。\n\n确认继续吗？`
}

export function getStoryExpansionFrameworkResetConfirmMessage(t?: TFunction): string {
  return t
    ? t('storyExpansion.submission.resetMsg')
    : '当前项目已存在长篇框架与卷细纲。\n\n继续使用“常规协同”补细化章节会清空旧框架状态，后续将以新的章节大纲为准。\n\n确认继续吗？'
}

export function getStoryExpansionFrameworkRegenerateConfirmMessage(t?: TFunction): string {
  return t
    ? t('storyExpansion.submission.regenerateMsg')
    : '当前项目已存在长篇框架与卷细纲。\n\n继续使用“长篇框架协同”重新生成后，会覆盖现有框架，并清空已展开卷的细纲。\n\n确认继续吗？'
}

export function getStoryExpansionVolumeOverwriteConfirmDialog(
  targetVolumeIndex: number | null | undefined,
  t?: TFunction,
): StoryExpansionConfirmDialogConfig {
  const volumeLabel = getStoryExpansionVolumeLabel(targetVolumeIndex, t)

  return {
    kind: 'volume_overwrite',
    title: t ? t('storyExpansion.submission.overwriteTitle') : '覆盖现有细纲',
    description: t
      ? t('storyExpansion.submission.overwriteDescription', { volume: volumeLabel })
      : `${volumeLabel}已存在细纲。重新协同生成会覆盖当前卷的现有内容。`,
    detail: t
      ? t('storyExpansion.submission.overwriteDetail', { volume: volumeLabel })
      : `确认后将按当前配置重新生成${volumeLabel}细纲，不影响其他卷。`,
    confirmLabel: t ? t('storyExpansion.submission.overwriteConfirm') : '继续覆盖',
    cancelLabel: t ? t('action.cancel') : '取消',
    message: getStoryExpansionVolumeOverwriteConfirmMessage(targetVolumeIndex, t),
  }
}

export function getStoryExpansionFrameworkResetConfirmDialog(t?: TFunction): StoryExpansionConfirmDialogConfig {
  return {
    kind: 'framework_reset',
    title: t ? t('storyExpansion.submission.resetTitle') : '重置长篇框架状态',
    description: t ? t('storyExpansion.submission.resetDescription') : '当前项目已存在长篇框架与卷细纲。继续使用“常规协同”补细化章节，会清空现有框架状态。',
    detail: t ? t('storyExpansion.submission.resetDetail') : '后续将以新的章节大纲为准，原有卷级细纲需要重新协同生成。',
    confirmLabel: t ? t('storyExpansion.submission.resetConfirm') : '继续重置',
    cancelLabel: t ? t('action.cancel') : '取消',
    message: getStoryExpansionFrameworkResetConfirmMessage(t),
  }
}

export function getStoryExpansionFrameworkRegenerateConfirmDialog(t?: TFunction): StoryExpansionConfirmDialogConfig {
  return {
    kind: 'framework_regenerate',
    title: t ? t('storyExpansion.submission.regenerateTitle') : '重新生成长篇框架',
    description: t ? t('storyExpansion.submission.regenerateDescription') : '当前项目已存在长篇框架与卷细纲。继续重新生成会覆盖现有框架，并清空已展开卷的细纲。',
    detail: t ? t('storyExpansion.submission.regenerateDetail') : '成功后将以新的分卷框架为准，原有单卷细化内容需要按新框架重新生成。',
    confirmLabel: t ? t('storyExpansion.submission.regenerateConfirm') : '继续重生成',
    cancelLabel: t ? t('action.cancel') : '取消',
    message: getStoryExpansionFrameworkRegenerateConfirmMessage(t),
  }
}

export function createStoryExpansionSubmitPreflight(
  input: StoryExpansionSubmitPreflightInput,
  t?: TFunction,
): StoryExpansionSubmitPreflight {
  const requestPlan = createStoryExpansionRequestPlanFromForm(input)

  const validationError = getStoryExpansionValidationError({
    expansionMode: input.form.expansionMode,
    currentChapterCount: input.currentChapterCount,
    currentCharacterCount: input.currentCharacterCount,
    targetChapterCount: input.form.targetChapterCount,
    targetCharacterCount: input.form.targetCharacterCount,
    totalVolumes: input.form.totalVolumes,
    totalChaptersMin: input.form.totalChaptersMin,
    totalChaptersMax: input.form.totalChaptersMax,
    frameworkMetadata: input.form.frameworkMetadata,
    targetVolumeIndex: input.form.targetVolumeIndex,
    volumeChaptersMin: input.form.volumeChaptersMin,
    volumeChaptersMax: input.form.volumeChaptersMax,
    hasStoryContext: Boolean(input.content.worldSetting && (input.content.plotOutline || input.content.characters)),
  })

  const requiresVolumeOverwriteConfirm = (
    requestPlan.isVolumeDetailMode
    && shouldConfirmStoryExpansionVolumeOverwrite(input.form.frameworkMetadata, input.form.targetVolumeIndex)
  )
  const requiresResetFrameworkConfirm = requestPlan.requiresEpicFrameworkReset
  const requiresFrameworkRegenerateConfirm = (
    input.form.expansionMode === 'epic_framework'
    && Boolean(input.form.frameworkMetadata?.has_framework)
  )

  const confirmDialogs: StoryExpansionConfirmDialogConfig[] = []

  if (requiresVolumeOverwriteConfirm) {
    confirmDialogs.push(getStoryExpansionVolumeOverwriteConfirmDialog(input.form.targetVolumeIndex, t))
  }

  if (requiresResetFrameworkConfirm) {
    confirmDialogs.push(getStoryExpansionFrameworkResetConfirmDialog(t))
  }

  if (requiresFrameworkRegenerateConfirm) {
    confirmDialogs.push(getStoryExpansionFrameworkRegenerateConfirmDialog(t))
  }

  return {
    requestPlan,
    validationError,
    confirmDialogs,
  }
}

export async function confirmStoryExpansionSubmitPreflight(
  preflight: Pick<
    StoryExpansionSubmitPreflight,
    'confirmDialogs'
  >,
  confirmAction: StoryExpansionConfirmAction,
): Promise<boolean> {
  for (const confirmDialog of preflight.confirmDialogs) {
    if (!await confirmAction(confirmDialog)) {
      return false
    }
  }

  return true
}

export function createStoryExpansionSubmitPayload(
  input: StoryExpansionSubmitPayloadInput,
): ReturnType<typeof createStoryExpansionRequestPayloadFromForm> {
  return createStoryExpansionRequestPayloadFromForm({
    ...input,
    preferAnalysis: true,
  })
}
