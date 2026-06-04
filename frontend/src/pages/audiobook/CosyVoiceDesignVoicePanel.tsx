import {
  Alert,
  Box,
  Button,
  CircularProgress,
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
        声音设计
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, lineHeight: 1.75 }}>
        用文字描述声线、年龄感和情绪，再提供试听文本生成设计音色。
      </Typography>
    </Box>

    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 220px) minmax(0, 360px) 120px' },
        gap: 1.25,
        alignItems: 'stretch',
        width: '100%',
        maxWidth: 740,
      }}
    >
      <TextField
        size="small"
        fullWidth
        label="设计名称"
        value={designName}
        onChange={(event) => onDesignNameChange(event.target.value)}
        disabled={busy}
        sx={{ minWidth: 0 }}
      />
      <TextField
        size="small"
        fullWidth
        label="声音描述"
        placeholder="如：沉稳的中年男性播报员，语速平稳，富有磁性。"
        value={designPrompt}
        onChange={(event) => onDesignPromptChange(event.target.value)}
        disabled={busy}
        sx={{ minWidth: 0 }}
      />
      <Button
        fullWidth
        variant="contained"
        onClick={onCreateDesignVoice}
        disabled={busy || !designName.trim() || !designPrompt.trim() || !designPreviewText.trim()}
        startIcon={designLoading ? <CircularProgress size={18} color="inherit" /> : undefined}
        sx={{ ...audiobookButtonSx.brandContained, minHeight: 40 }}
      >
        {designLoading ? '设计中...' : '开始设计'}
      </Button>
    </Box>

    <TextField
      size="small"
      fullWidth
      multiline
      minRows={2}
      maxRows={4}
      label="试听文本"
      value={designPreviewText}
      onChange={(event) => onDesignPreviewTextChange(event.target.value)}
      disabled={busy}
      sx={{ width: '100%', maxWidth: 740 }}
    />

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

export default CosyVoiceDesignVoicePanel
