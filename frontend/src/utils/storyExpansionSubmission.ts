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
  requiresVolumeOverwriteConfirm: boolean
  volumeOverwriteConfirmMessage: string
  requiresResetFrameworkConfirm: boolean
  resetFrameworkConfirmMessage: string
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

export type StoryExpansionConfirmAction = (message: string) => boolean

export function getStoryExpansionVolumeOverwriteConfirmMessage(
  targetVolumeIndex: number | null | undefined,
): string {
  return `第${targetVolumeIndex}卷细纲已存在，重新协同生成将覆盖现有细纲。\n\n确认继续吗？`
}

export function getStoryExpansionFrameworkResetConfirmMessage(): string {
  return '当前项目已存在长篇框架与卷细纲。\n\n继续使用“常规协同”补细化章节会清空旧框架状态，后续将以新的章节大纲为准。\n\n确认继续吗？'
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

  return {
    requestPlan,
    validationError,
    requiresVolumeOverwriteConfirm,
    volumeOverwriteConfirmMessage: requiresVolumeOverwriteConfirm
      ? getStoryExpansionVolumeOverwriteConfirmMessage(input.form.targetVolumeIndex)
      : '',
    requiresResetFrameworkConfirm,
    resetFrameworkConfirmMessage: requiresResetFrameworkConfirm
      ? getStoryExpansionFrameworkResetConfirmMessage()
      : '',
  }
}

export function confirmStoryExpansionSubmitPreflight(
  preflight: Pick<
    StoryExpansionSubmitPreflight,
    | 'requiresVolumeOverwriteConfirm'
    | 'volumeOverwriteConfirmMessage'
    | 'requiresResetFrameworkConfirm'
    | 'resetFrameworkConfirmMessage'
  >,
  confirmAction: StoryExpansionConfirmAction,
): boolean {
  if (
    preflight.requiresVolumeOverwriteConfirm
    && !confirmAction(preflight.volumeOverwriteConfirmMessage)
  ) {
    return false
  }

  if (
    preflight.requiresResetFrameworkConfirm
    && !confirmAction(preflight.resetFrameworkConfirmMessage)
  ) {
    return false
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
