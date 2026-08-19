import { describe, expect, it } from 'vitest'

import {
  applySegmentDetailDraft,
  parseSoundEffectLines,
  segmentMusicCueDraftValue,
  segmentSoundEffectsDraftValue,
  serializeVoiceCharacters,
  voiceBindingDraftFromEcho,
} from '../sceneEditorDraftUtils'
import type { ScriptSegment } from '../types'

describe('sceneEditorDraftUtils', () => {
  it('prefers sound_effects_simple when deriving the sfx draft value', () => {
    const segment = {
      sound_effects_simple: ['金属碰撞', '脚步声'],
      sound_effects: [{ name: '旧音效', timing: 'during' }],
    } as ScriptSegment
    expect(segmentSoundEffectsDraftValue(segment)).toBe('金属碰撞\n脚步声')
  })

  it('falls back to sound_effects detail names or plain strings', () => {
    const detailSegment = {
      sound_effects: [
        { name: '雨声', timing: 'continuous' },
        '雷声',
        { name: '', timing: 'before' },
      ],
    } as unknown as ScriptSegment
    expect(segmentSoundEffectsDraftValue(detailSegment)).toBe('雨声\n雷声')

    expect(segmentSoundEffectsDraftValue({} as ScriptSegment)).toBe('')
  })

  it('prefers music_cue_simple and falls back to cue style', () => {
    expect(segmentMusicCueDraftValue({ music_cue_simple: '悬疑低频弦乐' } as ScriptSegment))
      .toBe('悬疑低频弦乐')
    expect(segmentMusicCueDraftValue({
      music_cue: { style: '紧张鼓点' },
    } as unknown as ScriptSegment)).toBe('紧张鼓点')
    expect(segmentMusicCueDraftValue({ music_cue: '弦乐渐强' } as ScriptSegment)).toBe('弦乐渐强')
    expect(segmentMusicCueDraftValue({} as ScriptSegment)).toBe('')
  })

  it('trims and drops empty sound effect lines', () => {
    expect(parseSoundEffectLines('  金属碰撞 \n\n雷声\n  ')).toEqual(['金属碰撞', '雷声'])
  })

  it('applies only edited fields and leaves untouched segments as-is', () => {
    const untouched = {
      segment_key: 'seg-a',
      text: '原文',
      sound_effects: [{ name: '雨声' }],
      music_cue: { style: '弦乐' },
    } as unknown as ScriptSegment
    expect(applySegmentDetailDraft(untouched)).toBe(untouched)

    const applied = applySegmentDetailDraft(untouched, { text: '新台词' })
    expect(applied.text).toBe('新台词')
    // 只改台词：声音设计字段原样保留
    expect(applied.sound_effects).toBe(untouched.sound_effects)
    expect(applied.music_cue).toBe(untouched.music_cue)
  })

  it('rewrites sfx edits through simple fields so backend converts them', () => {
    const segment = {
      segment_key: 'seg-b',
      text: '台词',
      sound_effects: [{ name: '旧音效', timing: 'during' }],
      sound_effects_simple: [],
    } as unknown as ScriptSegment
    const applied = applySegmentDetailDraft(segment, { sound_effects: '金属碰撞\n\n脚步声' })
    // 精品对象清空，交给 ScriptSegment.__post_init__ 从 simple 转换
    expect(applied.sound_effects).toEqual([])
    expect(applied.sound_effects_simple).toEqual(['金属碰撞', '脚步声'])
  })

  it('rewrites music edits through music_cue_simple', () => {
    const segment = {
      segment_key: 'seg-c',
      music_cue: { style: '旧配乐' },
      music_cue_simple: '',
    } as unknown as ScriptSegment
    const applied = applySegmentDetailDraft(segment, { music_cue: '紧张的鼓点渐强' })
    expect(applied.music_cue).toBeNull()
    expect(applied.music_cue_simple).toBe('紧张的鼓点渐强')
  })

  it('applies scene and performance notes when edited', () => {
    const segment = {
      segment_key: 'seg-d',
      instruct_scene: '旧宅走廊',
      performance_notes: '低声',
    } as ScriptSegment
    const applied = applySegmentDetailDraft(segment, {
      instruct_scene: '宫廷大殿',
      performance_notes: '压着嗓子说',
    })
    expect(applied.instruct_scene).toBe('宫廷大殿')
    expect(applied.performance_notes).toBe('压着嗓子说')
  })

  it('serializes voice character form rows, dropping fully empty rows', () => {
    expect(serializeVoiceCharacters([
      { character_name: '林晚', voice_id: 'voice_xxx', reference_source: 'public_pool' },
      { character_name: '', voice_id: '', reference_source: '' },
      { character_name: '旁白', voice_id: 'voice_yyy', reference_source: '' },
    ])).toEqual([
      { character_name: '林晚', voice_id: 'voice_xxx', reference_source: 'public_pool' },
      { character_name: '旁白', voice_id: 'voice_yyy' },
    ])
  })

  it('serializes voice pool reference fields so the resolver can locate audio', () => {
    // 音色池选择需携带 reference_audio_url 等字段，否则渲染端无法解析参考音频
    expect(serializeVoiceCharacters([
      {
        character_name: '林晚',
        voice_id: 'voice_pool:pub-1',
        reference_source: 'public_pool',
        reference_audio_url: 'https://example.com/ref.mp3',
        voice_pool_publication_id: 'pub-1',
      },
      {
        character_name: '顾行舟',
        voice_id: 'clone-asset-1',
        reference_source: 'user_private',
        voice_reference_asset_id: 'asset-1',
      },
    ])).toEqual([
      {
        character_name: '林晚',
        voice_id: 'voice_pool:pub-1',
        reference_source: 'public_pool',
        reference_audio_url: 'https://example.com/ref.mp3',
        voice_pool_publication_id: 'pub-1',
      },
      {
        character_name: '顾行舟',
        voice_id: 'clone-asset-1',
        reference_source: 'user_private',
        voice_reference_asset_id: 'asset-1',
      },
    ])
  })

  it('builds voice binding draft rows from the current echo projection', () => {
    // 回显：打开音色编辑时能看到当前生效绑定，而不是空表单
    const { ttsModel, rows } = voiceBindingDraftFromEcho({
      tts_model: 'seed-tts-2.0-expressive',
      characters: [
        {
          character_name: '林晚',
          voice_id: 'voice_pool:pub-1',
          reference_source: 'public_pool',
          reference_audio_url: 'https://example.com/ref.mp3',
        },
      ],
    })
    expect(ttsModel).toBe('seed-tts-2.0-expressive')
    expect(rows).toEqual([
      {
        character_name: '林晚',
        voice_id: 'voice_pool:pub-1',
        reference_source: 'public_pool',
        reference_audio_url: 'https://example.com/ref.mp3',
        voice_reference_asset_id: '',
        voice_pool_publication_id: '',
      },
    ])
  })

  it('falls back to a single empty row when no voice binding exists yet', () => {
    const { ttsModel, rows } = voiceBindingDraftFromEcho(null)
    expect(ttsModel).toBe('')
    expect(rows).toEqual([
      {
        character_name: '',
        voice_id: '',
        reference_source: '',
        reference_audio_url: '',
        voice_reference_asset_id: '',
        voice_pool_publication_id: '',
      },
    ])
  })
})
