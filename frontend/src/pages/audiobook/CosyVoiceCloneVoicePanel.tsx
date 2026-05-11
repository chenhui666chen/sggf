import type { ChangeEvent } from 'react'

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Grid,
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
  <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
      声音复刻
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
      支持 http/https 或 oss:// 临时 URL（有效期 48 小时）；系统会自动生成合规 prefix，并用你的“命名”在列表中展示。
    </Typography>
    <Grid container spacing={1}>
      <Grid item xs={12} md={4}>
        <TextField
          size="small"
          fullWidth
          label="声音名称"
          value={cloneName}
          onChange={(event) => onCloneNameChange(event.target.value)}
          disabled={busy}
        />
      </Grid>
      <Grid item xs={12} md={6}>
        <TextField
          size="small"
          fullWidth
          label="音频 URL（http/https 或 oss://）"
          value={cloneUrl}
          onChange={(event) => onCloneUrlChange(event.target.value)}
          disabled={busy}
        />
      </Grid>
      <Grid item xs={12} md={2}>
        <Button
          fullWidth
          variant="contained"
          onClick={onCreateCloneVoice}
          disabled={busy || !cloneName.trim() || !cloneUrl.trim()}
          startIcon={cloneLoading ? <CircularProgress size={18} color="inherit" /> : undefined}
          sx={{ ...audiobookButtonSx.brandContained, height: '100%' }}
        >
          {cloneLoading ? '提交中...' : '开始复刻'}
        </Button>
      </Grid>
      <Grid item xs={12}>
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
            {cloneUploading ? '上传中...' : '上传音频获取临时URL'}
            <input
              type="file"
              hidden
              accept="audio/*"
              onChange={onUploadCloneAudio}
            />
          </Button>
          <Typography variant="caption" color="text.secondary">
            录音或上传都会生成临时 URL（oss://），有效期 48 小时。点击“录音”可查看示例文本，也可以随机朗读其他内容。
          </Typography>
        </Box>
      </Grid>
    </Grid>
    {cloneError && (
      <Alert severity="warning" sx={{ mt: 1 }}>
        {cloneError}
      </Alert>
    )}
    {cloneSuccess && (
      <Alert severity="success" sx={{ mt: 1 }}>
        {cloneSuccess}
      </Alert>
    )}
  </Paper>
)

export default CosyVoiceCloneVoicePanel
