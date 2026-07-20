import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosResponse } from 'axios'

import { apiClient } from '../../../services/api'
import { loadAudiobookProjectSelectionData } from '../projectSelectionLoader'

vi.mock('../../../services/api', () => ({
  apiClient: {
    getChapters: vi.fn(),
    getCharacters: vi.fn(),
    getProjectAudioConfig: vi.fn(),
  },
}))

const mockedApiClient = vi.mocked(apiClient)

const apiResponse = <TData,>(data: TData): AxiosResponse<TData> => ({
  data,
  status: 200,
  statusText: 'OK',
  headers: {},
  config: {} as AxiosResponse<TData>['config'],
})

describe('audiobook project selection loader', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads chapters, selected ids, saved voices, and audio fx config', async () => {
    mockedApiClient.getChapters.mockResolvedValue(
      apiResponse([
        { id: 1, chapter_number: 1, title: 'Chapter 1', content: 'Text 1' },
        { id: 2, chapter_number: 2, title: 'Chapter 2', content: 'Text 2' },
      ]),
    )
    mockedApiClient.getCharacters.mockResolvedValue(
      apiResponse([
        { id: 7, name: 'Hero', gender: 'male', role: 'lead' },
        { id: 8, name: 'Friend' },
      ]),
    )
    mockedApiClient.getProjectAudioConfig.mockResolvedValue(
      apiResponse({
        characters: [
          {
            character_id: 0,
            name: 'Narrator',
            voice_id: 'narrator-saved',
            volume: 65,
            speed: 0.95,
            pitch: 45,
          },
          {
            character_id: 7,
            name: 'Hero',
            voice_id: 'hero-saved',
            volume: 58,
            speed: 1.1,
            pitch: 52,
          },
        ],
        audio_fx: {
          enable_sound_effects: false,
          enable_music: true,
          sound_effect_density: 'high',
          music_density: 'low',
        },
      }),
    )

    const data = await loadAudiobookProjectSelectionData({
      projectId: 12,
      selectedChapterIds: [2, 99],
      ttsModel: 'cosyvoice-v3.5-plus',
      voicePresets: [
        { id: 'fallback-voice' },
        { id: 'narrator-saved' },
        { id: 'hero-saved' },
      ],
    })

    expect(mockedApiClient.getChapters).toHaveBeenCalledWith(12)
    expect(mockedApiClient.getCharacters).toHaveBeenCalledWith(12)
    expect(mockedApiClient.getProjectAudioConfig).toHaveBeenCalledWith(
      12,
      'cosyvoice-v3.5-plus',
    )
    expect(data.selectedChapterIds).toEqual([2])
    expect(data.audioFxConfig).toMatchObject({
      enable_sound_effects: false,
      enable_music: true,
      sound_effect_density: 'high',
      music_density: 'low',
    })
    expect(data.characterVoices).toMatchObject([
      {
        characterId: 0,
        voiceId: 'narrator-saved',
        volume: 65,
        speed: 0.95,
        pitch: 45,
      },
      {
        characterId: 7,
        name: 'Hero',
        voiceId: 'hero-saved',
        volume: 58,
        speed: 1.1,
        pitch: 52,
      },
      {
        characterId: 8,
        name: 'Friend',
        voiceId: '',
        volume: 50,
        speed: 1,
        pitch: 50,
      },
    ])
  })

  it('keeps chapter and character data when project audio config fails', async () => {
    mockedApiClient.getChapters.mockResolvedValue(
      apiResponse([
        { id: 3, chapter_number: 1, title: 'Only Chapter', content: 'Text' },
      ]),
    )
    mockedApiClient.getCharacters.mockResolvedValue(apiResponse([{ id: 9, name: 'Lead' }]))
    mockedApiClient.getProjectAudioConfig.mockRejectedValue(new Error('config failed'))

    const data = await loadAudiobookProjectSelectionData({
      projectId: 13,
      selectedChapterIds: [],
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
    })

    expect(data.selectedChapterIds).toEqual([3])
    expect(data.audioFxConfig).toMatchObject({
      enable_sound_effects: true,
      enable_music: true,
      sound_effect_density: 'medium',
      music_density: 'medium',
    })
    expect(data.characterVoices).toMatchObject([
      { characterId: 0, voiceId: 'Neil' },
      { characterId: 9, name: 'Lead', voiceId: '' },
    ])
  })

  it('selects only the first chapter for a fresh project session', async () => {
    mockedApiClient.getChapters.mockResolvedValue(
      apiResponse([
        { id: 21, chapter_number: 1, title: 'Chapter 1', content: 'Text 1' },
        { id: 22, chapter_number: 2, title: 'Chapter 2', content: 'Text 2' },
      ]),
    )
    mockedApiClient.getCharacters.mockResolvedValue(apiResponse([]))
    mockedApiClient.getProjectAudioConfig.mockResolvedValue(
      apiResponse({ characters: [], audio_fx: null }),
    )

    const data = await loadAudiobookProjectSelectionData({
      projectId: 20,
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
    })

    expect(data.selectedChapterIds).toEqual([21])
  })

  it('falls back to narrator voice and default audio fx when characters fail', async () => {
    mockedApiClient.getChapters.mockResolvedValue(
      apiResponse([
        { id: 4, chapter_number: 1, title: 'Chapter 1', content: 'Text 1' },
        { id: 5, chapter_number: 2, title: 'Chapter 2', content: 'Text 2' },
      ]),
    )
    mockedApiClient.getCharacters.mockRejectedValue(new Error('characters failed'))

    const data = await loadAudiobookProjectSelectionData({
      projectId: 14,
      selectedChapterIds: [5],
      ttsModel: 'cosyvoice-v3.5-plus',
      voicePresets: [{ id: 'cosy-narrator' }],
    })

    expect(mockedApiClient.getProjectAudioConfig).not.toHaveBeenCalled()
    expect(data.chapters).toHaveLength(2)
    expect(data.selectedChapterIds).toEqual([5])
    expect(data.audioFxConfig).toMatchObject({
      enable_sound_effects: true,
      enable_music: true,
      sound_effect_density: 'medium',
      music_density: 'medium',
    })
    expect(data.characterVoices).toMatchObject([
      { characterId: 0, voiceId: 'cosy-narrator' },
    ])
  })

  it('rejects when chapters cannot be loaded', async () => {
    const error = new Error('chapters failed')
    mockedApiClient.getChapters.mockRejectedValue(error)

    await expect(loadAudiobookProjectSelectionData({
      projectId: 15,
      selectedChapterIds: [1],
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
    })).rejects.toThrow('chapters failed')

    expect(mockedApiClient.getCharacters).not.toHaveBeenCalled()
    expect(mockedApiClient.getProjectAudioConfig).not.toHaveBeenCalled()
  })
})
