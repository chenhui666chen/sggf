import { apiClient } from '../../services/api'
import type {
  AudioEngineMode,
  AudioFxConfig,
  Chapter,
  CharacterVoiceSetting,
  ProjectAudioConfig,
  TtsModel,
  VoicePreset,
} from './types'
import { normalizeSelectedChapterIds } from './sessionUtils'
import {
  buildBaseNarratorVoice,
  buildInitialProjectVoiceSettings,
  createDefaultAudioFxConfig,
  normalizeProjectAudioFxConfig,
  type ProjectCharacterSummary,
} from './projectAudioConfigUtils'

export interface AudiobookProjectSelectionData {
  chapters: Chapter[]
  selectedChapterIds: number[]
  characterVoices: CharacterVoiceSetting[]
  audioFxConfig: AudioFxConfig
  audioEngineMode: AudioEngineMode
}

const normalizeAudioEngineMode = (value: unknown): AudioEngineMode => (
  value === 'seed_scene' ? 'seed_scene' : 'legacy_stems'
)

export const loadAudiobookProjectSelectionData = async ({
  projectId,
  selectedChapterIds,
  ttsModel,
  voicePresets,
}: {
  projectId: number
  selectedChapterIds?: number[]
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
}): Promise<AudiobookProjectSelectionData> => {
  const chaptersRes = await apiClient.getChapters(projectId)
  const chaptersData: Chapter[] = Array.isArray(chaptersRes.data) ? chaptersRes.data : []
  const chapterIds = chaptersData.map((chapter) => chapter.id)

  try {
    const charactersRes = await apiClient.getCharacters(projectId)
    const charactersData: ProjectCharacterSummary[] = Array.isArray(charactersRes.data)
      ? charactersRes.data
      : []

    let projectAudioConfig: ProjectAudioConfig | null = null
    try {
      const audioConfigRes = await apiClient.getProjectAudioConfig(projectId, ttsModel)
      projectAudioConfig = audioConfigRes.data
    } catch {
      // 项目音频配置不是项目选择的硬依赖，失败时使用默认配置继续。
    }

    return {
      chapters: chaptersData,
      selectedChapterIds: normalizeSelectedChapterIds(selectedChapterIds, {
        allowedIds: chapterIds,
        fallbackIds: chapterIds.slice(0, 1),
      }),
      characterVoices: buildInitialProjectVoiceSettings({
        characters: charactersData,
        projectAudioConfig,
        ttsModel,
        voicePresets,
      }),
      audioFxConfig: normalizeProjectAudioFxConfig(projectAudioConfig?.audio_fx),
      audioEngineMode: normalizeAudioEngineMode(projectAudioConfig?.audio_engine_mode),
    }
  } catch {
    return {
      chapters: chaptersData,
      selectedChapterIds: normalizeSelectedChapterIds(selectedChapterIds, {
        allowedIds: chapterIds,
        fallbackIds: chapterIds.slice(0, 1),
      }),
      characterVoices: [buildBaseNarratorVoice(ttsModel, voicePresets)],
      audioFxConfig: createDefaultAudioFxConfig(),
      audioEngineMode: 'legacy_stems',
    }
  }
}
