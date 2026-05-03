import {
  Divider,
  Grid,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'

import type { ScriptReviewDetail } from './types'
import {
  formatOneDecimal,
  formatTenScale,
} from './utils'

interface ScriptReviewMetricSectionsProps {
  scriptQuality: NonNullable<ScriptReviewDetail['script_quality']>
  audioBalance: NonNullable<ScriptReviewDetail['audio_balance']>
  pacing: NonNullable<ScriptReviewDetail['pacing']>
}

const ScriptReviewMetricSections = ({
  scriptQuality,
  audioBalance,
  pacing,
}: ScriptReviewMetricSectionsProps) => (
  <>
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
  </>
)

export default ScriptReviewMetricSections
