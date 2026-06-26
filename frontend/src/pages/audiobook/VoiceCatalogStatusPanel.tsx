import {
  Alert,
  Box,
  Button,
  Typography,
} from '@mui/material'

import CosyVoiceVoiceWorkbench from './CosyVoiceVoiceWorkbench'
import type { CosyVoiceWorkbench } from './CosyVoiceVoiceWorkbench'
import MimoVoiceAssetWorkbench from './MimoVoiceAssetWorkbench'
import StepAudioVoiceCloneWorkbench from './StepAudioVoiceCloneWorkbench'
import type {
  TtsModel,
  VoiceCatalogMeta,
  VoicePreset,
} from './types'

type VoiceCatalogNoticeSeverity = 'success' | 'warning' | 'info'

const MIMO_VOICE_CLONE_NOTICE = 'MiMo Voice Clone 不创建系统音色；audio.voice 必须传入 data:{MIME_TYPE};base64,$BASE64_AUDIO 样本。请在角色音色或调用参数中填入授权音频样本，样本 base64 不超过 10 MB。'
const MIMO_VOICE_DESIGN_NOTICE = 'MiMo Voice Design 不创建系统音色；请先在上方 MiMo 本地音色中填写 voice design prompt 并保存为可复用音色，再到角色音色下拉中选用。生成时后端会把该音色展开到 role=user，朗读文本仍放在 role=assistant。'

const STEPAUDIO_VOICE_CLONE_NOTICE = 'StepAudio 2.5 TTS 支持 Zero-shot 复刻试听；当前先保存本地参考样本和可选 file_id，正式自生成音色资产创建接口待官方合同确认后再接入。'

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
}: VoiceCatalogStatusPanelProps) => (
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
    {(ttsModel === 'mimo-v2.5-tts-voiceclone' || ttsModel === 'mimo-v2.5-tts-voicedesign') && (
      <MimoVoiceAssetWorkbench
        ttsModel={ttsModel}
        customVoicePresets={customVoicePresets}
        previewingVoiceId={customVoicePreviewingId}
        onPreviewCustomVoice={onPreviewCustomVoice}
        onChanged={onFetchVoiceCatalog}
      />
    )}
    {ttsModel === 'stepaudio-2.5-tts' && (
      <StepAudioVoiceCloneWorkbench
        customVoicePresets={customVoicePresets}
        previewingVoiceId={customVoicePreviewingId}
        onPreviewCustomVoice={onPreviewCustomVoice}
        onChanged={onFetchVoiceCatalog}
      />
    )}
    {ttsModel === 'mimo-v2.5-tts-voiceclone' && (
      <Alert severity="info" sx={{ mb: 1 }}>
        {MIMO_VOICE_CLONE_NOTICE}
      </Alert>
    )}
    {ttsModel === 'mimo-v2.5-tts-voicedesign' && (
      <Alert severity="info" sx={{ mb: 1 }}>
        {MIMO_VOICE_DESIGN_NOTICE}
      </Alert>
    )}
    {ttsModel === 'stepaudio-2.5-tts' && (
      <Alert severity="info" sx={{ mb: 1 }}>
        {STEPAUDIO_VOICE_CLONE_NOTICE}
      </Alert>
    )}
    {voiceError && (
      <Alert
        severity="warning"
        action={
          <Button size="small" onClick={onFetchVoiceCatalog} disabled={voiceLoading}>
            {voiceLoading ? '同步中...' : '重新同步'}
          </Button>
        }
        sx={{ mb: 1 }}
      >
        {voiceError}
      </Alert>
    )}
  </Box>
)

export default VoiceCatalogStatusPanel
