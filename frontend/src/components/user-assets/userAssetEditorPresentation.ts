import type { TFunction } from 'i18next'
import type {
  UserAssetRecord,
  UserAssetRecordUpdatePayload,
} from '@/services/api'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type UserAssetEditorFormData = {
  title: string
  description: string
  tagsText: string
}

export type UserAssetEditorDialogPresentation = {
  dialogTitle: string
  titleLabel: string
  descriptionLabel: string
  tagsLabel: string
  tagsPlaceholder: string
  tagsHelperText: string
  cancelLabel: string
  saveLabel: string
  savingLabel: string
  saveDisabled: boolean
}

export function getEmptyUserAssetEditorFormData(): UserAssetEditorFormData {
  return {
    title: '',
    description: '',
    tagsText: '',
  }
}

export function buildUserAssetEditorFormData(
  asset?: Pick<UserAssetRecord, 'title' | 'description' | 'tags'> | null,
): UserAssetEditorFormData {
  if (!asset) return getEmptyUserAssetEditorFormData()

  return {
    title: asset.title || '',
    description: asset.description || '',
    tagsText: asset.tags.join(', '),
  }
}

export function parseUserAssetEditorTagsInput(value: string): string[] {
  const parts = String(value || '')
    .split(/[\n,，、]+/)
    .map((item) => item.trim())
    .filter(Boolean)

  const nextTags: string[] = []
  const seen = new Set<string>()

  parts.forEach((tag) => {
    const normalized = tag.slice(0, 30)
    const key = normalized.toLowerCase()
    if (!normalized || seen.has(key) || nextTags.length >= 12) return
    seen.add(key)
    nextTags.push(normalized)
  })

  return nextTags
}

export function normalizeUserAssetEditorPayload(
  formData: UserAssetEditorFormData,
  t?: TFunction,
): { payload?: UserAssetRecordUpdatePayload; validationError?: string } {
  const translate = t ?? DEFAULT_TRANSLATE
  const normalizedTitle = formData.title.trim()
  if (!normalizedTitle) {
    return { validationError: translate('userAsset.editor.titleRequired') }
  }

  return {
    payload: {
      title: normalizedTitle,
      description: formData.description.trim() || null,
      tags: parseUserAssetEditorTagsInput(formData.tagsText),
    },
  }
}

type BuildUserAssetEditorDialogPresentationOptions = {
  submitting?: boolean
  hasAsset: boolean
}

export function buildUserAssetEditorDialogPresentation(
  options: BuildUserAssetEditorDialogPresentationOptions,
  t?: TFunction,
): UserAssetEditorDialogPresentation {
  const translate = t ?? DEFAULT_TRANSLATE
  const { submitting = false, hasAsset } = options

  return {
    dialogTitle: translate('userAsset.editor.dialogTitle'),
    titleLabel: translate('userAsset.editor.titleLabel'),
    descriptionLabel: translate('userAsset.editor.descriptionLabel'),
    tagsLabel: translate('userAsset.editor.tagsLabel'),
    tagsPlaceholder: translate('userAsset.editor.tagsPlaceholder'),
    tagsHelperText: translate('userAsset.editor.tagsHelperText'),
    cancelLabel: translate('userAsset.editor.cancel'),
    saveLabel: translate('userAsset.editor.save'),
    savingLabel: translate('userAsset.editor.saving'),
    saveDisabled: submitting || !hasAsset,
  }
}
