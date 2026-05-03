import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Typography,
} from '@mui/material'

import { STAGE_STATUS_LABELS } from './constants'
import { audiobookColors } from './audiobookTheme'
import type {
  StageConfig,
  StageInfo,
} from './types'

export interface StageMetricsDialogData {
  stage: StageConfig
  info: StageInfo
}

interface StageMetricsDialogProps {
  open: boolean
  data: StageMetricsDialogData | null
  onClose: () => void
}

const StageMetricsDialog = ({
  open,
  data,
  onClose,
}: StageMetricsDialogProps) => (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="md"
    fullWidth
  >
    <DialogTitle>
      {data ? `阶段结果：${data.stage.name}` : '阶段结果'}
    </DialogTitle>
    <DialogContent dividers>
      {!data ? (
        <Typography variant="body2" color="text.secondary">
          暂无阶段数据
        </Typography>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            状态：{STAGE_STATUS_LABELS[data.info.status]}
          </Typography>
          {data.info.message && (
            <Typography variant="body2">提示：{data.info.message}</Typography>
          )}
          {data.info.start_time && (
            <Typography variant="body2" color="text.secondary">
              开始时间：{data.info.start_time}
            </Typography>
          )}
          {data.info.end_time && (
            <Typography variant="body2" color="text.secondary">
              结束时间：{data.info.end_time}
            </Typography>
          )}
          {data.info.error_message && (
            <Alert severity="error">{data.info.error_message}</Alert>
          )}
          <Paper
            variant="outlined"
            sx={{ p: 1, backgroundColor: audiobookColors.surfaceSubtle }}
          >
            <Box
              component="pre"
              sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}
            >
              {JSON.stringify(data.info.metrics, null, 2)}
            </Box>
          </Paper>
        </Box>
      )}
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose}>关闭</Button>
    </DialogActions>
  </Dialog>
)

export default StageMetricsDialog
