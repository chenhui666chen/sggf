export const IMAGE_EDIT_REQUIREMENT_ERROR = '图像编辑模式下请填写“修改要求”（基于参考原图需要修改的内容）'

export interface DreamweaverLibraryRegeneratePayload {
  role: string
  prompt?: string
  run_id?: string
  style_preset?: string
  image_ratio?: string
  prefer_image_edit?: boolean
  prefer_view_chain_edit_base?: boolean
}

export interface BuildLibraryRegeneratePayloadOptions {
  role: string
  prompt: string
  imageEditActive: boolean
  imageEditAutoCleared: boolean
  promptDirty: boolean
  forceImageEdit: boolean
  preferImageEdit: boolean
  hasImageBase: boolean
  forceViewChainEditBase: boolean
  runId?: string
  stylePreset?: string
  imageRatio?: string
}

export interface BuildLibraryRegeneratePayloadResult {
  error: string | null
  payload: DreamweaverLibraryRegeneratePayload
}

export function buildLibraryRegeneratePayload(
  options: BuildLibraryRegeneratePayloadOptions,
): BuildLibraryRegeneratePayloadResult {
  const role = String(options.role || '').trim()
  const promptText = String(options.prompt || '').trim()
  const runId = String(options.runId || '').trim()
  const stylePreset = String(options.stylePreset || '').trim()
  const imageRatio = String(options.imageRatio || '').trim()

  const payload: DreamweaverLibraryRegeneratePayload = { role }

  if (options.imageEditActive && options.imageEditAutoCleared && !promptText) {
    return { error: IMAGE_EDIT_REQUIREMENT_ERROR, payload }
  }

  const shouldSendPrompt = options.imageEditActive ? true : Boolean(options.promptDirty && promptText)
  if (shouldSendPrompt) payload.prompt = promptText

  if (runId) payload.run_id = runId
  if (stylePreset) payload.style_preset = stylePreset
  if (imageRatio) payload.image_ratio = imageRatio

  const preferImageEdit = Boolean(options.forceImageEdit || (options.preferImageEdit && options.hasImageBase))
  if (preferImageEdit) payload.prefer_image_edit = true
  if (options.forceViewChainEditBase) payload.prefer_view_chain_edit_base = true

  return { error: null, payload }
}

