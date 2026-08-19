import type { ScriptSegment } from './types'

/**
 * 场景编辑器细编草稿（P1 透明化）：用户可编辑的台词与声音设计字段。
 * 声音设计编辑写 simple 字段，交由后端 ScriptSegment 转换进渲染提示词。
 */
export interface SegmentDetailDraft {
  text?: string
  instruct_scene?: string
  performance_notes?: string
  /** 伴随音效，每行一条描述 */
  sound_effects?: string
  music_cue?: string
}

/** 回显音效列表：sound_effects_simple 优先，detail 对象回退取 name。 */
export const segmentSoundEffectsDraftValue = (segment: ScriptSegment): string => {
  const simple = segment.sound_effects_simple
  if (Array.isArray(simple) && simple.length > 0) {
    return simple.join('\n')
  }
  const details = segment.sound_effects ?? []
  return details
    .map((item) => (typeof item === 'string' ? item : String(item?.name ?? '')))
    .filter((name) => name.trim() !== '')
    .join('\n')
}

/** 回显配乐风格：music_cue_simple 优先，detail 回退取 style。 */
export const segmentMusicCueDraftValue = (segment: ScriptSegment): string => {
  const simple = segment.music_cue_simple
  if (simple) {
    return simple
  }
  const cue = segment.music_cue
  if (typeof cue === 'string') {
    return cue
  }
  return String(cue?.style ?? '')
}

export const parseSoundEffectLines = (value: string): string[] => (
  value.split('\n').map((line) => line.trim()).filter((line) => line !== '')
)

/** 音色编辑表单行（P2：JSON 手写改结构化表单；音色库选择携带参考音频字段）。 */
export interface VoiceCharacterDraft {
  character_name: string
  voice_id: string
  /** 仅接受后端 voice_reference_resolver 白名单值：user_private / public_pool */
  reference_source: string
  /** 以下音色库参考字段可选：手工输入音色 ID 时无需携带 */
  reference_audio_url?: string
  voice_reference_asset_id?: string
  voice_pool_publication_id?: string
}

export const EMPTY_VOICE_CHARACTER_DRAFT: VoiceCharacterDraft = {
  character_name: '',
  voice_id: '',
  reference_source: '',
  reference_audio_url: '',
  voice_reference_asset_id: '',
  voice_pool_publication_id: '',
}

/** 安全取字符串字段（兼容省略新字段的旧式行）。 */
const asString = (value: unknown): string => (typeof value === 'string' ? value : '')

/** 序列化为 voice_binding 保存接口的 characters 数组，丢弃完全空行。 */
export const serializeVoiceCharacters = (
  rows: VoiceCharacterDraft[],
): Array<Record<string, string>> => rows
  .filter((row) => row.character_name.trim() !== '' || row.voice_id.trim() !== '')
  .map((row) => {
    const entry: Record<string, string> = {
      character_name: row.character_name.trim(),
      voice_id: row.voice_id.trim(),
    }
    if (row.reference_source.trim() !== '') {
      entry.reference_source = row.reference_source.trim()
    }
    // 音色库选择需携带参考音频/资产字段，否则渲染端无法解析所选音色
    const referenceAudioUrl = asString(row.reference_audio_url).trim()
    if (referenceAudioUrl !== '') {
      entry.reference_audio_url = referenceAudioUrl
    }
    const voiceReferenceAssetId = asString(row.voice_reference_asset_id).trim()
    if (voiceReferenceAssetId !== '') {
      entry.voice_reference_asset_id = voiceReferenceAssetId
    }
    const voicePoolPublicationId = asString(row.voice_pool_publication_id).trim()
    if (voicePoolPublicationId !== '') {
      entry.voice_pool_publication_id = voicePoolPublicationId
    }
    return entry
  })

/** voice_binding_current 回显投影（后端 SceneEditorDocument）。 */
export interface VoiceBindingEcho {
  tts_model?: string | null
  characters?: Array<Record<string, unknown>>
}

/**
 * 把当前生效的 voice_binding 回显解析为表单草稿；
 * 无绑定时回退单空行，让用户从空白起步而不是面对无提示的空表单。
 */
export const voiceBindingDraftFromEcho = (
  echo: VoiceBindingEcho | null | undefined,
): { ttsModel: string; rows: VoiceCharacterDraft[] } => {
  const characters = Array.isArray(echo?.characters) ? echo?.characters ?? [] : []
  const rows = characters.map((character): VoiceCharacterDraft => ({
    character_name: asString(character?.character_name),
    voice_id: asString(character?.voice_id),
    reference_source: asString(character?.reference_source),
    reference_audio_url: asString(character?.reference_audio_url),
    voice_reference_asset_id: asString(character?.voice_reference_asset_id),
    voice_pool_publication_id: asString(character?.voice_pool_publication_id),
  }))
  return {
    ttsModel: asString(echo?.tts_model),
    rows: rows.length > 0 ? rows : [{ ...EMPTY_VOICE_CHARACTER_DRAFT }],
  }
}

/**
 * 把草稿合并进片段（仅覆盖用户编辑过的字段，未编辑返回原引用）。
 * 音效/配乐编辑后清空精品对象字段，由 ScriptSegment.__post_init__
 * 从 sound_effects_simple / music_cue_simple 自动转换。
 */
export const applySegmentDetailDraft = (
  segment: ScriptSegment,
  draft?: SegmentDetailDraft,
): ScriptSegment => {
  if (!draft) {
    return segment
  }
  const next: ScriptSegment = {
    ...segment,
    text: draft.text ?? segment.text ?? '',
    instruct_scene: draft.instruct_scene ?? segment.instruct_scene ?? '',
    performance_notes: draft.performance_notes ?? segment.performance_notes ?? '',
  }
  if (draft.sound_effects !== undefined) {
    next.sound_effects = []
    next.sound_effects_simple = parseSoundEffectLines(draft.sound_effects)
  }
  if (draft.music_cue !== undefined) {
    next.music_cue = null
    next.music_cue_simple = draft.music_cue
  }
  return next
}
