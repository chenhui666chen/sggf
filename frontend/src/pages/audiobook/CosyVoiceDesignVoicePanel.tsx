import {
  Alert,
  Button,
  CircularProgress,
  Grid,
  Paper,
  TextField,
  Typography,
} from '@mui/material'

import { audiobookButtonSx } from './audiobookTheme'

interface CosyVoiceDesignVoicePanelProps {
  designName: string
  designPrompt: string
  designPreviewText: string
  designLoading: boolean
  busy: boolean
  designError: string | null
  designSuccess: string | null
  onDesignNameChange: (value: string) => void
  onDesignPromptChange: (value: string) => void
  onDesignPreviewTextChange: (value: string) => void
  onCreateDesignVoice: () => void
}

const CosyVoiceDesignVoicePanel = ({
  designName,
  designPrompt,
  designPreviewText,
  designLoading,
  busy,
  designError,
  designSuccess,
  onDesignNameChange,
  onDesignPromptChange,
  onDesignPreviewTextChange,
  onCreateDesignVoice,
}: CosyVoiceDesignVoicePanelProps) => (
  <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
      声音设计
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
      用自然语言描述声线、年龄感、气质和情绪，再提供一段试听文本，即可生成新的设计音色。
    </Typography>
    <Grid container spacing={1}>
      <Grid item xs={12} md={4}>
        <TextField
          size="small"
          fullWidth
          label="设计名称"
          value={designName}
          onChange={(event) => onDesignNameChange(event.target.value)}
          disabled={busy}
        />
      </Grid>
      <Grid item xs={12} md={8}>
        <TextField
          size="small"
          fullWidth
          label="声音描述"
          placeholder="例如：青年女性，声线清透，带一点冷静与克制，适合悬疑旁白。"
          value={designPrompt}
          onChange={(event) => onDesignPromptChange(event.target.value)}
          disabled={busy}
        />
      </Grid>
      <Grid item xs={12} md={9}>
        <TextField
          size="small"
          fullWidth
          multiline
          minRows={2}
          label="试听文本"
          value={designPreviewText}
          onChange={(event) => onDesignPreviewTextChange(event.target.value)}
          disabled={busy}
        />
      </Grid>
      <Grid item xs={12} md={3}>
        <Button
          fullWidth
          variant="contained"
          onClick={onCreateDesignVoice}
          disabled={busy || !designName.trim() || !designPrompt.trim() || !designPreviewText.trim()}
          startIcon={designLoading ? <CircularProgress size={18} color="inherit" /> : undefined}
          sx={{ ...audiobookButtonSx.brandContained, height: '100%' }}
        >
          {designLoading ? '设计中...' : '开始设计'}
        </Button>
      </Grid>
    </Grid>
    {designError && (
      <Alert severity="warning" sx={{ mt: 1 }}>
        {designError}
      </Alert>
    )}
    {designSuccess && (
      <Alert severity="success" sx={{ mt: 1 }}>
        {designSuccess}
      </Alert>
    )}
  </Paper>
)

export default CosyVoiceDesignVoicePanel
