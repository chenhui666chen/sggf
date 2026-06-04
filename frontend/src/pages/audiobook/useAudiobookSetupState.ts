import { useState } from 'react'

import {
  DEFAULT_NARRATION_STYLE,
  type NarrationStyleId,
} from './narrationStyles'
import { createDefaultAudioFxConfig } from './projectAudioConfigUtils'
import { DEFAULT_TTS_MODEL } from './ttsModels'
import type {
  AudioFxConfig,
  AudioOutputFormat,
  TtsModel,
} from './types'

export const useAudiobookSetupState = () => {
  const [audioFxConfig, setAudioFxConfig] = useState<AudioFxConfig>(() => createDefaultAudioFxConfig())
  const [scriptOnlyMode, setScriptOnlyMode] = useState(false)
  const [ttsModel, setTtsModel] = useState<TtsModel>(DEFAULT_TTS_MODEL)
  const [narrationStyle, setNarrationStyle] = useState<NarrationStyleId>(DEFAULT_NARRATION_STYLE)
  const [narrationStylePrompt, setNarrationStylePrompt] = useState('')
  const [outputFormat, setOutputFormat] = useState<AudioOutputFormat>('mp3')
  const [generateSubtitle, setGenerateSubtitle] = useState(true)

  return {
    audioFxConfig,
    setAudioFxConfig,
    scriptOnlyMode,
    setScriptOnlyMode,
    ttsModel,
    setTtsModel,
    narrationStyle,
    setNarrationStyle,
    narrationStylePrompt,
    setNarrationStylePrompt,
    outputFormat,
    setOutputFormat,
    generateSubtitle,
    setGenerateSubtitle,
  }
}
