import {
  Alert,
  Box,
  Button,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import CosyVoiceVoiceWorkbench from './CosyVoiceVoiceWorkbench'
import type { CosyVoiceWorkbench } from './CosyVoiceVoiceWorkbench'
import MimoVoiceAssetWorkbench from './MimoVoiceAssetWorkbench'
import MiniMaxVoiceCloneWorkbench from './MiniMaxVoiceCloneWorkbench'
import StepAudioVoiceCloneWorkbench from './StepAudioVoiceCloneWorkbench'
import type {
  TtsModel,
  VoiceCatalogMeta,
  VoicePreset,
} from './types'

type VoiceCatalogNoticeSeverity = 'success' | 'warning' | 'info'

const MIMO_VOICE_CLONE_NOTICE = 'audiobook.voiceCatalogStatusPanel.mimoCloneNotice'
const MIMO_VOICE_DESIGN_NOTICE = 'audiobook.voiceCatalogStatusPanel.mimoDesignNotice'

const STEPAUDIO_VOICE_CLONE_NOTICE = 'audiobook.voiceCatalogStatusPanel.stepAudioCloneNotice'

interface VoiceCatalogStatusPanelProps {
  ttsModel: TtsModel
  voiceCatalogMeta?: VoiceCatalogMeta | null
  voiceCatalogSummary: string
  voiceCatalogNotice: string
  voiceCatalogNoticeSeverity: VoiceCatalogNoticeSeverity
  showCustomVoiceWorkbench: boolean
  voiceError: string | null
  voiceLoading: boolean
  customVoicePresets: VoicePreset[]
  cosyVoiceWorkbench: CosyVoiceWorkbench
  customVoicePreviewingId: string | null
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onFetchVoiceCatalog: () => void
}

const VoiceCatalogStatusPanel = ({
  ttsModel,
  voiceCatalogMeta,
  voiceCatalogSummary,
  voiceCatalogNotice,
  voiceCatalogNoticeSeverity,
  showCustomVoiceWorkbench,
  voiceError,
  voiceLoading,
  customVoicePresets,
  cosyVoiceWorkbench,
  customVoicePreviewingId,
  onPreviewCustomVoice,
  onFetchVoiceCatalog,
}: VoiceCatalogStatusPanelProps) => {
  const { t } = useTranslation()
  return (
  <Box sx={{ flex: 1, minWidth: 260 }}>
    {voiceCatalogMeta && (
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {voiceCatalogSummary}
      </Typography>
    )}
    <Alert severity={voiceCatalogNoticeSeverity} sx={{ mb: 1 }}>
      {voiceCatalogNotice}
    </Alert>
    {showCustomVoiceWorkbench && ttsModel === 'cosyvoice-v3.5-plus' && (
      <CosyVoiceVoiceWorkbench {...cosyVoiceWorkbench} />
    )}
    {showCustomVoiceWorkbench && (
      ttsModel === 'minimax-speech-2.8-hd'
      || ttsModel === 'minimax-speech-2.8-turbo'
    ) && (
      <MiniMaxVoiceCloneWorkbench
        ttsModel={ttsModel}
        customVoicePresets={customVoicePresets}
        previewingVoiceId={customVoicePreviewingId}
        onPreviewCustomVoice={onPreviewCustomVoice}
        onChanged={onFetchVoiceCatalog}
      />
    )}
    {(ttsModel === 'mimo-v2.5-tts-voiceclone' || ttsModel === 'mimo-v2.5-tts-voicedesign') && (
      <MimoVoiceAssetWorkbench
        ttsModel={ttsModel}
        customVoicePresets={customVoicePresets}
        previewingVoiceId={customVoicePreviewingId}
        onPreviewCustomVoice={onPreviewCustomVoice}
        onChanged={onFetchVoiceCatalog}
      />
    )}
    {ttsModel === 'stepaudio-3-tts' && (
      <StepAudioVoiceCloneWorkbench
        customVoicePresets={customVoicePresets}
        previewingVoiceId={customVoicePreviewingId}
        onPreviewCustomVoice={onPreviewCustomVoice}
        onChanged={onFetchVoiceCatalog}
      />
    )}
    {ttsModel === 'mimo-v2.5-tts-voiceclone' && (
      <Alert severity="info" sx={{ mb: 1 }}>
        {t(MIMO_VOICE_CLONE_NOTICE)}
      </Alert>
    )}
    {ttsModel === 'mimo-v2.5-tts-voicedesign' && (
      <Alert severity="info" sx={{ mb: 1 }}>
        {t(MIMO_VOICE_DESIGN_NOTICE)}
      </Alert>
    )}
    {ttsModel === 'stepaudio-3-tts' && (
      <Alert severity="info" sx={{ mb: 1 }}>
        {t(STEPAUDIO_VOICE_CLONE_NOTICE)}
      </Alert>
    )}
    {voiceError && (
      <Alert
        severity="warning"
        action={
          <Button size="small" onClick={onFetchVoiceCatalog} disabled={voiceLoading}>
            {voiceLoading
              ? t('audiobook.voiceCatalogStatusPanel.syncing')
              : t('audiobook.voiceCatalogStatusPanel.resync')}
          </Button>
        }
        sx={{ mb: 1 }}
      >
        {voiceError}
      </Alert>
    )}
  </Box>
  )
}

export default VoiceCatalogStatusPanel
