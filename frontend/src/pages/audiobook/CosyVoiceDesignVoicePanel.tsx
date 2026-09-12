import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  TextField,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import { audiobookButtonSx } from './audiobookTheme'

interface CosyVoiceDesignVoicePanelProps {
  designName: string
  designPrompt: string
  designLoading: boolean
  designPreviewAudioUrl: string
  designPreviewVoiceId: string
  busy: boolean
  designError: string | null
  designSuccess: string | null
  onDesignNameChange: (value: string) => void
  onDesignPromptChange: (value: string) => void
  onCreateDesignVoice: () => void
  onPreviewDesignVoice: () => void
}

const CosyVoiceDesignVoicePanel = ({
  designName,
  designPrompt,
  designLoading,
  designPreviewAudioUrl,
  designPreviewVoiceId,
  busy,
  designError,
  designSuccess,
  onDesignNameChange,
  onDesignPromptChange,
  onCreateDesignVoice,
  onPreviewDesignVoice,
}: CosyVoiceDesignVoicePanelProps) => {
  const { t } = useTranslation()
  const hasDesignPreviewTarget = Boolean(designPreviewAudioUrl.trim() || designPreviewVoiceId.trim())

  return (
    <Paper
      variant="outlined"
      sx={{
        p: { xs: 1.5, md: 2 },
        display: 'grid',
        gap: 1.5,
      }}
    >
      <Box sx={{ minWidth: 0, maxWidth: 720 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.25 }}>
          {t('audiobook.cosyVoiceDesignVoicePanel.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, lineHeight: 1.75 }}>
          {t('audiobook.cosyVoiceDesignVoicePanel.description')}
        </Typography>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) 120px' },
          gap: 1.25,
          alignItems: 'stretch',
          width: '100%',
          maxWidth: 740,
        }}
      >
        <TextField
          size="small"
          fullWidth
          label={t('audiobook.cosyVoiceDesignVoicePanel.nameLabel')}
          value={designName}
          onChange={(event) => onDesignNameChange(event.target.value)}
          disabled={busy}
          sx={{ minWidth: 0 }}
        />
        <Button
          fullWidth
          variant="contained"
          onClick={hasDesignPreviewTarget ? onPreviewDesignVoice : onCreateDesignVoice}
          disabled={
            busy
            || (
              !hasDesignPreviewTarget
              && (!designName.trim() || !designPrompt.trim())
            )
          }
          startIcon={designLoading ? <CircularProgress size={18} color="inherit" /> : undefined}
          sx={{ ...audiobookButtonSx.brandContained, minHeight: 40 }}
        >
          {designLoading ? t('audiobook.cosyVoiceDesignVoicePanel.designing') : hasDesignPreviewTarget ? t('audiobook.cosyVoiceDesignVoicePanel.preview') : t('audiobook.cosyVoiceDesignVoicePanel.startDesign')}
        </Button>
        <TextField
          size="small"
          fullWidth
          multiline
          minRows={3}
          maxRows={5}
          label={t('audiobook.cosyVoiceDesignVoicePanel.promptLabel')}
          placeholder={t('audiobook.cosyVoiceDesignVoicePanel.promptPlaceholder')}
          value={designPrompt}
          onChange={(event) => onDesignPromptChange(event.target.value)}
          disabled={busy}
          sx={{ gridColumn: '1 / -1', minWidth: 0 }}
        />
      </Box>

      {designError && (
        <Alert severity="warning">
          {designError}
        </Alert>
      )}
      {designSuccess && (
        <Alert severity="success">
          {designSuccess}
        </Alert>
      )}
    </Paper>
  )
}

export default CosyVoiceDesignVoicePanel
