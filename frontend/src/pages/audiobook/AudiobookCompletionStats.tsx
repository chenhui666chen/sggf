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

const buildCompletionStats = (audiobookProject: AudiobookProjectDetail) => {
  const total = audiobookProject.total_chapters || 0
  const completed = audiobookProject.completed_chapters || 0
  const failed = audiobookProject.failed_chapters || 0
  const completionRate = total > 0 ? ((completed / total) * 100).toFixed(1) : '0.0'
  const totalSizeMB = ((audiobookProject.total_size || 0) / (1024 * 1024)).toFixed(1)

  return [
    {
      label: '完成章节',
      value: `${completed}/${total}`,
      sub: failed > 0 ? `${failed} 章失败` : undefined,
      backgroundColor: audiobookColors.brandSoft,
      color: audiobookColors.brand,
      borderColor: audiobookColors.brand,
    },
    {
      label: '完成率',
      value: `${completionRate}%`,
      sub: undefined,
      backgroundColor: audiobookColors.successSoft,
      color: audiobookColors.success,
      borderColor: audiobookColors.successMain,
    },
    {
      label: '总时长(分钟)',
      value: ((audiobookProject.total_duration || 0) / 60).toFixed(1),
      sub: totalSizeMB !== '0.0' ? `${totalSizeMB} MB` : undefined,
      backgroundColor: audiobookColors.infoSoft,
      color: audiobookColors.primaryDark,
      borderColor: audiobookColors.primary,
    },
    {
      label: '总成本',
      value: `￥${(audiobookProject.total_cost || 0).toFixed(2)}`,
      sub: undefined,
      backgroundColor: '#fff3e0',
      color: '#e65100',
      borderColor: '#ff9800',
    },
  ]
}

const AudiobookCompletionStats = ({
  audiobookProject,
}: AudiobookCompletionStatsProps) => (
  <Grid container spacing={2} sx={{ mb: 3 }}>
    {buildCompletionStats(audiobookProject).map((item) => (
      <Grid key={item.label} item xs={12} sm={3}>
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
          {item.sub && (
            <Typography variant="caption" sx={{ opacity: 0.7 }}>
              {item.sub}
            </Typography>
          )}
        </Paper>
      </Grid>
    ))}
  </Grid>
)

export default AudiobookCompletionStats
