import type { ChangeEvent } from 'react'

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

interface CosyVoiceCloneVoicePanelProps {
  cloneName: string
  cloneUrl: string
  cloneLoading: boolean
  cloneUploading: boolean
  busy: boolean
  cloneError: string | null
  cloneSuccess: string | null
  onCloneNameChange: (value: string) => void
  onCloneUrlChange: (value: string) => void
  onCreateCloneVoice: () => void
  onOpenCloneRecordDialog: () => void
  onUploadCloneAudio: (event: ChangeEvent<HTMLInputElement>) => void
}

const CosyVoiceCloneVoicePanel = ({
  cloneName,
  cloneUrl,
  cloneLoading,
  cloneUploading,
  busy,
  cloneError,
  cloneSuccess,
  onCloneNameChange,
  onCloneUrlChange,
  onCreateCloneVoice,
  onOpenCloneRecordDialog,
  onUploadCloneAudio,
}: CosyVoiceCloneVoicePanelProps) => (
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
        声音复刻
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, lineHeight: 1.75 }}>
        上传或录制真实样本，填写临时 URL 后创建专属复刻音色。
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
        label="声音名称"
        value={cloneName}
        onChange={(event) => onCloneNameChange(event.target.value)}
        disabled={busy}
        sx={{ minWidth: 0 }}
      />
      <TextField
        size="small"
        fullWidth
        label="音频 URL"
        placeholder="http/https 或 oss://"
        value={cloneUrl}
        onChange={(event) => onCloneUrlChange(event.target.value)}
        disabled={busy}
        sx={{ minWidth: 0 }}
      />
      <Button
        fullWidth
        variant="contained"
        onClick={onCreateCloneVoice}
        disabled={busy || !cloneName.trim() || !cloneUrl.trim()}
        startIcon={cloneLoading ? <CircularProgress size={18} color="inherit" /> : undefined}
        sx={{ ...audiobookButtonSx.brandContained, minHeight: 40 }}
      >
        {cloneLoading ? '提交中...' : '开始复刻'}
      </Button>
    </Box>

    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
      <Button
        variant="outlined"
        onClick={onOpenCloneRecordDialog}
        disabled={busy}
        sx={audiobookButtonSx.neutralOutlined}
      >
        录音
      </Button>
      <Button
        variant="outlined"
        component="label"
        disabled={busy}
        startIcon={cloneUploading ? <CircularProgress size={16} color="inherit" /> : undefined}
        sx={audiobookButtonSx.brandOutlined}
      >
        {cloneUploading ? '上传中...' : '上传音频'}
        <input
          type="file"
          hidden
          accept="audio/*"
          onChange={onUploadCloneAudio}
        />
      </Button>
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 220, flex: '1 1 260px' }}>
        支持 http/https 或 oss://，临时 URL 有效期 48 小时。
      </Typography>
    </Box>

    {cloneError && (
      <Alert severity="warning">
        {cloneError}
      </Alert>
    )}
    {cloneSuccess && (
      <Alert severity="success">
        {cloneSuccess}
      </Alert>
    )}
  </Paper>
)

export default CosyVoiceCloneVoicePanel
