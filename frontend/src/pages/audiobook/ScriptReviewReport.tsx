import {
  Alert,
  Box,
  Chip,
  Divider,
  Grid,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'

import type { ScriptReviewDetail } from './types'
import {
  ISSUE_DISPLAY_LIMIT,
  categoryLabelMap,
  formatOneDecimal,
  formatTenScale,
  severityColorMap,
  severityLabelMap,
} from './utils'

interface ScriptReviewReportProps {
  review: ScriptReviewDetail | null
}

const ScriptReviewReport = ({ review }: ScriptReviewReportProps) => {
  if (!review) return null
  const scriptQuality = review.script_quality || {}
  const audioBalance = review.audio_balance || {}
  const pacing = review.pacing || {}
  const issues = review.issues || []
  const suggestions = review.revision_suggestions || []
  const extraIssues =
    (review.issues_count || issues.length || 0) > ISSUE_DISPLAY_LIMIT
      ? (review.issues_count || issues.length || 0) - ISSUE_DISPLAY_LIMIT
      : 0

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
          总体评分
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 70,
              height: 70,
              borderRadius: '50%',
              backgroundColor:
                (review.overall_score || 0) >= 8
                  ? 'rgba(76, 175, 80, 0.15)'
                  : (review.overall_score || 0) >= 6
                  ? 'rgba(255, 152, 0, 0.15)'
                  : 'rgba(244, 67, 54, 0.15)',
            }}
          >
            <Typography
              variant="h5"
              sx={{
                fontWeight: 600,
                color:
                  (review.overall_score || 0) >= 8
                    ? '#2e7d32'
                    : (review.overall_score || 0) >= 6
                    ? '#f57c00'
                    : '#c62828',
              }}
            >
              {typeof review.overall_score === 'number'
                ? review.overall_score.toFixed(1)
                : '—'}
            </Typography>
          </Box>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>
              等级：{review.overall_grade || 'N/A'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              问题数：{review.issues_count ?? issues.length ?? 0}
            </Typography>
          </Box>
        </Box>
        {suggestions.length > 0 && (
          <Alert severity="info" sx={{ mb: 1 }}>
            {suggestions[0]}
            {suggestions.length > 1 && (
              <Typography variant="caption" component="div">
                其余建议在下方详列
              </Typography>
            )}
          </Alert>
        )}
      </Box>

      <Divider textAlign="left">剧本质量</Divider>
      <Grid container spacing={1}>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">
            自然流畅度
          </Typography>
          <Typography variant="subtitle2">{formatTenScale(scriptQuality.naturalness_score)}/10</Typography>
        </Grid>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">
            信息清晰度
          </Typography>
          <Typography variant="subtitle2">{formatTenScale(scriptQuality.clarity_score)}/10</Typography>
        </Grid>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">
            听觉张力
          </Typography>
          <Typography variant="subtitle2">{formatTenScale(scriptQuality.engagement_score)}/10</Typography>
        </Grid>
      </Grid>
      <Typography variant="caption" color="text.secondary">
        片段数：{scriptQuality.total_segments ?? '—'} · 平均片段长度：
        {typeof scriptQuality.average_segment_length === 'number'
          ? `${formatOneDecimal(scriptQuality.average_segment_length)} 字`
          : '—'}
      </Typography>

      <Divider textAlign="left">音频平衡</Divider>
      <List dense>
        <ListItem disableGutters>
          <ListItemText
            primary="音效密度"
            secondary={
              audioBalance.sound_effects
                ? `${audioBalance.sound_effects}（≈ ${formatOneDecimal(audioBalance.effects_per_minute)} / 分钟）`
                : '—'
            }
          />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText
            primary="配乐覆盖"
            secondary={
              audioBalance.music
                ? `${audioBalance.music}（共 ${audioBalance.total_music_cues ?? 0} 个提示）`
                : '—'
            }
          />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText
            primary="角色音色区分"
            secondary={audioBalance.voice_differentiation || '—'}
          />
        </ListItem>
      </List>

      <Divider textAlign="left">节奏评估</Divider>
      <List dense>
        <ListItem disableGutters>
          <ListItemText
            primary="预计成品时长"
            secondary={pacing.estimated_duration || '—'}
          />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText
            primary="平均片段朗读时长"
            secondary={pacing.average_segment_duration || '—'}
          />
        </ListItem>
        {pacing.pacing_issues?.length ? (
          pacing.pacing_issues.map((issue, idx) => (
            <ListItem key={idx} disableGutters>
              <ListItemText
                primaryTypographyProps={{ variant: 'body2' }}
                primary={`节奏提示 ${idx + 1}`}
                secondary={issue}
              />
            </ListItem>
          ))
        ) : (
          <ListItem disableGutters>
            <ListItemText secondary="节奏稳定，未发现明显问题" />
          </ListItem>
        )}
      </List>

      <Divider textAlign="left">问题清单</Divider>
      {issues.length > 0 ? (
        <List dense>
          {issues.slice(0, ISSUE_DISPLAY_LIMIT).map((issue, idx) => {
            const severityKey = (issue.severity || '').toLowerCase()
            const color = severityColorMap[severityKey] || 'default'
            const categoryLabel = categoryLabelMap[(issue.category || '').toLowerCase()] || issue.category || '其他'
            const severityLabel = severityLabelMap[severityKey] || issue.severity || '未分级'
            return (
              <ListItem key={`${issue.location || idx}-${idx}`} alignItems="flex-start" sx={{ mb: 1 }}>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Chip label={severityLabel} size="small" color={color} />
                      <Chip label={categoryLabel} size="small" variant="outlined" />
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {issue.description || '未提供描述'}
                      </Typography>
                    </Box>
                  }
                  secondary={
                    issue.suggestion ? (
                      <Typography variant="body2" color="text.secondary">
                        建议：{issue.suggestion}
                      </Typography>
                    ) : undefined
                  }
                />
              </ListItem>
            )
          })}
        </List>
      ) : (
        <Typography variant="body2" color="text.secondary">
          未找到具体问题，整体表现稳定。
        </Typography>
      )}
      {extraIssues > 0 && (
        <Typography variant="caption" color="text.secondary">
          另有 {extraIssues} 条问题记录，可在导出报告或后台数据库中查看全部明细。
        </Typography>
      )}

      {suggestions.length > 1 && (
        <>
          <Divider textAlign="left">修订建议</Divider>
          <List dense>
            {suggestions.map((suggestion, idx) => (
              <ListItem key={idx} disableGutters>
                <ListItemText primary={`建议 ${idx + 1}`} secondary={suggestion} />
              </ListItem>
            ))}
          </List>
        </>
      )}
    </Box>
  )
}

export default ScriptReviewReport
