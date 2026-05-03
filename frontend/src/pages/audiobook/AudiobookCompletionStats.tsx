import {
  Grid,
  Paper,
  Typography,
} from '@mui/material'

import { audiobookColors } from './audiobookTheme'
import type { AudiobookProjectDetail } from './types'

interface AudiobookCompletionStatsProps {
  audiobookProject: AudiobookProjectDetail
}

const buildCompletionStats = (audiobookProject: AudiobookProjectDetail) => [
  {
    label: '完成章节',
    value: audiobookProject.completed_chapters,
    backgroundColor: audiobookColors.brandSoft,
    color: audiobookColors.brand,
    borderColor: audiobookColors.brand,
  },
  {
    label: '总时长(分钟)',
    value: ((audiobookProject.total_duration || 0) / 60).toFixed(1),
    backgroundColor: audiobookColors.successSoft,
    color: audiobookColors.success,
    borderColor: audiobookColors.successMain,
  },
  {
    label: '总成本',
    value: `￥${(audiobookProject.total_cost || 0).toFixed(2)}`,
    backgroundColor: audiobookColors.infoSoft,
    color: audiobookColors.primaryDark,
    borderColor: audiobookColors.primary,
  },
]

const AudiobookCompletionStats = ({
  audiobookProject,
}: AudiobookCompletionStatsProps) => (
  <Grid container spacing={2} sx={{ mb: 3 }}>
    {buildCompletionStats(audiobookProject).map((item) => (
      <Grid key={item.label} item xs={12} sm={4}>
        <Paper
          sx={{
            p: 3,
            textAlign: 'center',
            backgroundColor: item.backgroundColor,
            color: item.color,
            border: '1px solid',
            borderColor: item.borderColor,
            boxShadow: 'none',
          }}
        >
          <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
            {item.value}
          </Typography>
          <Typography variant="body2" sx={{ opacity: 0.9 }}>
            {item.label}
          </Typography>
        </Paper>
      </Grid>
    ))}
  </Grid>
)

export default AudiobookCompletionStats
