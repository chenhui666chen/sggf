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
  kind: 'volume_overwrite' | 'framework_reset'
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

function getStoryExpansionVolumeLabel(targetVolumeIndex: number | null | undefined): string {
  return Number.isFinite(targetVolumeIndex) ? `第 ${targetVolumeIndex} 卷` : '当前卷'
}

export function getStoryExpansionVolumeOverwriteConfirmMessage(
  targetVolumeIndex: number | null | undefined,
): string {
  return `第${targetVolumeIndex}卷细纲已存在，重新协同生成将覆盖现有细纲。\n\n确认继续吗？`
}

export function getStoryExpansionFrameworkResetConfirmMessage(): string {
  return '当前项目已存在长篇框架与卷细纲。\n\n继续使用“常规协同”补细化章节会清空旧框架状态，后续将以新的章节大纲为准。\n\n确认继续吗？'
}

export function getStoryExpansionVolumeOverwriteConfirmDialog(
  targetVolumeIndex: number | null | undefined,
): StoryExpansionConfirmDialogConfig {
  const volumeLabel = getStoryExpansionVolumeLabel(targetVolumeIndex)

  return {
    kind: 'volume_overwrite',
    title: '覆盖现有细纲',
    description: `${volumeLabel}已存在细纲。重新协同生成会覆盖当前卷的现有内容。`,
    detail: `确认后将按当前配置重新生成${volumeLabel}细纲，不影响其他卷。`,
    confirmLabel: '继续覆盖',
    cancelLabel: '取消',
    message: getStoryExpansionVolumeOverwriteConfirmMessage(targetVolumeIndex),
  }
}

export function getStoryExpansionFrameworkResetConfirmDialog(): StoryExpansionConfirmDialogConfig {
  return {
    kind: 'framework_reset',
    title: '重置长篇框架状态',
    description: '当前项目已存在长篇框架与卷细纲。继续使用“常规协同”补细化章节，会清空现有框架状态。',
    detail: '后续将以新的章节大纲为准，原有卷级细纲需要重新协同生成。',
    confirmLabel: '继续重置',
    cancelLabel: '取消',
    message: getStoryExpansionFrameworkResetConfirmMessage(),
  }
}

export function createStoryExpansionSubmitPreflight(
  input: StoryExpansionSubmitPreflightInput,
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

  const confirmDialogs: StoryExpansionConfirmDialogConfig[] = []

  if (requiresVolumeOverwriteConfirm) {
    confirmDialogs.push(getStoryExpansionVolumeOverwriteConfirmDialog(input.form.targetVolumeIndex))
  }

  if (requiresResetFrameworkConfirm) {
    confirmDialogs.push(getStoryExpansionFrameworkResetConfirmDialog())
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
