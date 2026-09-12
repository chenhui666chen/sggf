import {
  Divider,
  Grid,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

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
}: ScriptReviewMetricSectionsProps) => {
  const { t } = useTranslation()
  return (
  <>
    <Divider textAlign="left">{t('audiobook.scriptReviewMetricSections.scriptQualityTitle')}</Divider>
    <Grid container spacing={1}>
      <Grid item xs={4}>
        <Typography variant="caption" color="text.secondary">
          {t('audiobook.scriptReviewMetricSections.naturalnessLabel')}
        </Typography>
        <Typography variant="subtitle2">{formatTenScale(scriptQuality.naturalness_score)}/10</Typography>
      </Grid>
      <Grid item xs={4}>
        <Typography variant="caption" color="text.secondary">
          {t('audiobook.scriptReviewMetricSections.clarityLabel')}
        </Typography>
        <Typography variant="subtitle2">{formatTenScale(scriptQuality.clarity_score)}/10</Typography>
      </Grid>
      <Grid item xs={4}>
        <Typography variant="caption" color="text.secondary">
          {t('audiobook.scriptReviewMetricSections.engagementLabel')}
        </Typography>
        <Typography variant="subtitle2">{formatTenScale(scriptQuality.engagement_score)}/10</Typography>
      </Grid>
    </Grid>
    <Typography variant="caption" color="text.secondary">
      {t('audiobook.scriptReviewMetricSections.segmentSummary', { total: scriptQuality.total_segments ?? '—' })}
      {typeof scriptQuality.average_segment_length === 'number'
        ? t('audiobook.scriptReviewMetricSections.charUnit', { count: formatOneDecimal(scriptQuality.average_segment_length) })
        : '—'}
    </Typography>

    <Divider textAlign="left">{t('audiobook.scriptReviewMetricSections.audioBalanceTitle')}</Divider>
    <List dense>
      <ListItem disableGutters>
        <ListItemText
          primary={t('audiobook.scriptReviewMetricSections.effectsDensityLabel')}
          secondary={
            audioBalance.sound_effects
              ? t('audiobook.scriptReviewMetricSections.effectsDensityValue', {
                  value: audioBalance.sound_effects,
                  rate: formatOneDecimal(audioBalance.effects_per_minute),
                })
              : '—'
          }
        />
      </ListItem>
      <ListItem disableGutters>
        <ListItemText
          primary={t('audiobook.scriptReviewMetricSections.musicCoverageLabel')}
          secondary={
            audioBalance.music
              ? t('audiobook.scriptReviewMetricSections.musicCoverageValue', {
                  value: audioBalance.music,
                  total: audioBalance.total_music_cues ?? 0,
                })
              : '—'
          }
        />
      </ListItem>
      <ListItem disableGutters>
        <ListItemText
          primary={t('audiobook.scriptReviewMetricSections.voiceDiffLabel')}
          secondary={audioBalance.voice_differentiation || '—'}
        />
      </ListItem>
      {(audioBalance.unresolved_effect_count ?? 0) > 0 && (
        <ListItem disableGutters>
          <ListItemText
            primary={t('audiobook.scriptReviewMetricSections.unresolvedEffectsLabel')}
            secondary={t('audiobook.scriptReviewMetricSections.unresolvedEffectsValue', {
              total: audioBalance.unresolved_effect_count,
              placeholder: audioBalance.placeholder_effect_count ?? 0,
              missing: audioBalance.missing_effect_file_count ?? 0,
            })}
          />
        </ListItem>
      )}
    </List>

    <Divider textAlign="left">{t('audiobook.scriptReviewMetricSections.pacingTitle')}</Divider>
    <List dense>
      <ListItem disableGutters>
        <ListItemText
          primary={t('audiobook.scriptReviewMetricSections.estimatedDurationLabel')}
          secondary={pacing.estimated_duration || '—'}
        />
      </ListItem>
      <ListItem disableGutters>
        <ListItemText
          primary={t('audiobook.scriptReviewMetricSections.avgSegmentDurationLabel')}
          secondary={pacing.average_segment_duration || '—'}
        />
      </ListItem>
      {pacing.pacing_issues?.length ? (
        pacing.pacing_issues.map((issue, idx) => (
          <ListItem key={idx} disableGutters>
            <ListItemText
              primaryTypographyProps={{ variant: 'body2' }}
              primary={t('audiobook.scriptReviewMetricSections.pacingIssueLabel', { index: idx + 1 })}
              secondary={issue}
            />
          </ListItem>
        ))
      ) : (
        <ListItem disableGutters>
          <ListItemText secondary={t('audiobook.scriptReviewMetricSections.pacingStable')} />
        </ListItem>
      )}
    </List>
  </>
  )
}

export default ScriptReviewMetricSections
