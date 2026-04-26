import type {
  UserAssetRecord,
  UserAssetRecordUpdatePayload,
} from '@/services/api'

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
): { payload?: UserAssetRecordUpdatePayload; validationError?: string } {
  const normalizedTitle = formData.title.trim()
  if (!normalizedTitle) {
    return { validationError: '资产标题不能为空' }
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
): UserAssetEditorDialogPresentation {
  const { submitting = false, hasAsset } = options

  return {
    dialogTitle: '编辑资产信息',
    titleLabel: '资产标题',
    descriptionLabel: '补充说明',
    tagsLabel: '标签',
    tagsPlaceholder: '可使用逗号、中文逗号、顿号或换行分隔',
    tagsHelperText: '最多保留 12 个标签，每个标签最多 30 个字符。',
    cancelLabel: '取消',
    saveLabel: '保存',
    savingLabel: '保存中...',
    saveDisabled: submitting || !hasAsset,
  }
}
