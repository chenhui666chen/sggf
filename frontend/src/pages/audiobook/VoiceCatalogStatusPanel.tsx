import {
  Alert,
  Box,
  Button,
  Typography,
} from '@mui/material'

import CosyVoiceVoiceWorkbench from './CosyVoiceVoiceWorkbench'
import type { CosyVoiceWorkbench } from './CosyVoiceVoiceWorkbench'
import type {
  VoiceCatalogMeta,
} from './types'

type VoiceCatalogNoticeSeverity = 'success' | 'warning' | 'info'

interface VoiceCatalogStatusPanelProps {
  voiceCatalogMeta?: VoiceCatalogMeta | null
  voiceCatalogSummary: string
  voiceCatalogNotice: string
  voiceCatalogNoticeSeverity: VoiceCatalogNoticeSeverity
  showCustomVoiceWorkbench: boolean
  voiceError: string | null
  voiceLoading: boolean
  cosyVoiceWorkbench: CosyVoiceWorkbench
  onFetchVoiceCatalog: () => void
}

const VoiceCatalogStatusPanel = ({
  voiceCatalogMeta,
  voiceCatalogSummary,
  voiceCatalogNotice,
  voiceCatalogNoticeSeverity,
  showCustomVoiceWorkbench,
  voiceError,
  voiceLoading,
  cosyVoiceWorkbench,
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
    {showCustomVoiceWorkbench && (
      <CosyVoiceVoiceWorkbench {...cosyVoiceWorkbench} />
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
