import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import type {
  EditorConflictDiffPreview,
  EditorConflictSegmentDiffPreview,
} from './types'
import { audiobookColorRoles, audiobookColors } from './audiobookTheme'

const EDITOR_CONFLICT_FIELD_DETAIL_LIMIT = 3

interface ScriptEditorConflictNoticeProps {
  timeLabel?: string | null
  preview?: EditorConflictDiffPreview | null
  visibleSegmentDiffs: EditorConflictSegmentDiffPreview[]
  hiddenSegmentDiffCount: number
  onApplyIncomingDraft?: () => void
  onKeepLocalDraft?: () => void
}

const ScriptEditorConflictNotice = ({
  timeLabel,
  preview,
  visibleSegmentDiffs,
  hiddenSegmentDiffCount,
  onApplyIncomingDraft,
  onKeepLocalDraft,
}: ScriptEditorConflictNoticeProps) => {
  const { t } = useTranslation()
  return (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
    <Alert
      severity="warning"
      action={(
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Button size="small" color="inherit" onClick={onApplyIncomingDraft}>
            {t('audiobook.scriptEditorConflictNotice.loadIncomingDraft')}
          </Button>
          <Button size="small" color="inherit" onClick={onKeepLocalDraft}>
            {t('audiobook.scriptEditorConflictNotice.keepLocalDraft')}
          </Button>
        </Box>
      )}
    >
      {t('audiobook.scriptEditorConflictNotice.alertTitle')}
      {timeLabel ? t('audiobook.scriptEditorConflictNotice.timeSuffix', { time: timeLabel }) : ''}。
      {t('audiobook.scriptEditorConflictNotice.alertHint')}
    </Alert>

    {preview && (
      <Paper
        variant="outlined"
        sx={{
          p: 1.5,
          borderColor: 'warning.light',
          backgroundColor: audiobookColorRoles.notice.warning.faintBg,
        }}
      >
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 1,
            flexWrap: 'wrap',
            mb: 1,
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {t('audiobook.scriptEditorConflictNotice.fieldDiffPreviewTitle')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('audiobook.scriptEditorConflictNotice.fieldDiffSummary', {
              fieldCount: preview.fieldDiffs.length,
              segmentCount: preview.segmentDiffs.length,
            })}
          </Typography>
        </Box>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            <Typography variant="caption" color="text.secondary">
              {t('audiobook.scriptEditorConflictNotice.topLevelStatus')}
            </Typography>
            {preview.fieldDiffs.length > 0 ? (
              preview.fieldDiffs.map((fieldDiff) => (
                <Box
                  key={fieldDiff.key}
                  sx={{
                    p: 1,
                    borderRadius: 1,
                    backgroundColor: audiobookColors.surfaceRaised,
                    border: `1px solid ${audiobookColors.surfaceBorder}`,
                  }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {fieldDiff.labelKey ? t(fieldDiff.labelKey) : fieldDiff.label}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div">
                    {t('audiobook.scriptEditorConflictNotice.currentValue', { value: fieldDiff.currentValue })}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div">
                    {t('audiobook.scriptEditorConflictNotice.incomingValue', { value: fieldDiff.incomingValue })}
                  </Typography>
                </Box>
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">
                {t('audiobook.scriptEditorConflictNotice.topLevelNoDiff')}
              </Typography>
            )}
          </Box>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            <Typography variant="caption" color="text.secondary">
              {t('audiobook.scriptEditorConflictNotice.segmentDiffsTitle')}
            </Typography>
            {visibleSegmentDiffs.length > 0 ? (
              visibleSegmentDiffs.map((segmentDiff) => {
                const visibleFieldDiffs = segmentDiff.fieldDiffs.slice(
                  0,
                  EDITOR_CONFLICT_FIELD_DETAIL_LIMIT,
                )
                const hiddenFieldDiffCount = Math.max(
                  0,
                  segmentDiff.fieldDiffs.length - visibleFieldDiffs.length,
                )

                return (
                  <Box
                    key={`${segmentDiff.index}-${segmentDiff.changeType}`}
                    sx={{
                      p: 1,
                      borderRadius: 1,
                      backgroundColor: audiobookColors.surfaceRaised,
                      border: `1px dashed ${audiobookColors.surfaceDashedBorder}`,
                    }}
                  >
                    <Box
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 0.75,
                        flexWrap: 'wrap',
                        mb: 0.75,
                      }}
                    >
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {t('audiobook.scriptEditorConflictNotice.segmentLabel', {
                          index: segmentDiff.index + 1,
                          speaker: segmentDiff.speaker,
                        })}
                      </Typography>
                      <Chip
                        size="small"
                        variant="outlined"
                        color={
                          segmentDiff.changeType === 'added'
                            ? 'success'
                            : segmentDiff.changeType === 'removed'
                              ? 'info'
                              : 'warning'
                        }
                        label={
                          segmentDiff.changeType === 'added'
                            ? t('audiobook.scriptEditorConflictNotice.changeAdded')
                            : segmentDiff.changeType === 'removed'
                              ? t('audiobook.scriptEditorConflictNotice.changeRemoved')
                              : t('audiobook.scriptEditorConflictNotice.changeModified')
                        }
                      />
                      {segmentDiff.fieldDiffs.slice(0, 4).map((fieldDiff) => (
                        <Chip
                          key={`${segmentDiff.index}-${fieldDiff.key}`}
                          size="small"
                          label={fieldDiff.labelKey ? t(fieldDiff.labelKey) : fieldDiff.label}
                          variant="outlined"
                        />
                      ))}
                      {segmentDiff.fieldDiffs.length > 4 && (
                        <Typography variant="caption" color="text.secondary">
                          {t('audiobook.scriptEditorConflictNotice.moreItems', { total: segmentDiff.fieldDiffs.length })}
                        </Typography>
                      )}
                    </Box>

                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                      {visibleFieldDiffs.map((fieldDiff) => (
                        <Box key={`${segmentDiff.index}-${fieldDiff.key}-detail`}>
                          <Typography variant="caption" sx={{ fontWeight: 600 }}>
                            {fieldDiff.labelKey ? t(fieldDiff.labelKey) : fieldDiff.label}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" component="div">
                            {t('audiobook.scriptEditorConflictNotice.currentValue', { value: fieldDiff.currentValue })}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" component="div">
                            {t('audiobook.scriptEditorConflictNotice.incomingValue', { value: fieldDiff.incomingValue })}
                          </Typography>
                        </Box>
                      ))}
                      {hiddenFieldDiffCount > 0 && (
                        <Typography variant="caption" color="text.secondary">
                          {t('audiobook.scriptEditorConflictNotice.hiddenFieldDiffs', { total: hiddenFieldDiffCount })}
                        </Typography>
                      )}
                    </Box>
                  </Box>
                )
              })
            ) : (
              <Typography variant="body2" color="text.secondary">
                {t('audiobook.scriptEditorConflictNotice.segmentNoDiff')}
              </Typography>
            )}
            {hiddenSegmentDiffCount > 0 && (
              <Typography variant="caption" color="text.secondary">
                {t('audiobook.scriptEditorConflictNotice.hiddenSegmentDiffs', { total: hiddenSegmentDiffCount })}
              </Typography>
            )}
          </Box>
        </Box>
      </Paper>
    )}
  </Box>
  )
}

export default ScriptEditorConflictNotice
