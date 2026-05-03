import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Typography,
} from '@mui/material'

import type {
  EditorConflictDiffPreview,
  EditorConflictSegmentDiffPreview,
} from './types'
import { audiobookColors } from './audiobookTheme'

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
}: ScriptEditorConflictNoticeProps) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
    <Alert
      severity="warning"
      action={(
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Button size="small" color="inherit" onClick={onApplyIncomingDraft}>
            载入对方草稿
          </Button>
          <Button size="small" color="inherit" onClick={onKeepLocalDraft}>
            保留本页草稿
          </Button>
        </Box>
      )}
    >
      检测到另一个标签页刚刚更新了同一章节的未保存草稿
      {timeLabel ? `（${timeLabel}）` : ''}。
      你可以先查看字段级差异，再决定载入对方草稿，或继续保留当前标签页的内容。
    </Alert>

    {preview && (
      <Paper
        variant="outlined"
        sx={{
          p: 1.5,
          borderColor: 'warning.light',
          backgroundColor: audiobookColors.warningFaint,
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
            字段级差异预览
          </Typography>
          <Typography variant="caption" color="text.secondary">
            顶层 {preview.fieldDiffs.length} 项 · 片段 {preview.segmentDiffs.length} 个
          </Typography>
        </Box>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            <Typography variant="caption" color="text.secondary">
              顶层状态
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
                    {fieldDiff.label}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div">
                    当前：{fieldDiff.currentValue}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div">
                    对方：{fieldDiff.incomingValue}
                  </Typography>
                </Box>
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">
                顶层字段无差异，当前冲突主要集中在片段内容。
              </Typography>
            )}
          </Box>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            <Typography variant="caption" color="text.secondary">
              片段差异
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
                        片段 #{segmentDiff.index + 1} · {segmentDiff.speaker}
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
                            ? '对方新增'
                            : segmentDiff.changeType === 'removed'
                              ? '对方已删除'
                              : '字段变更'
                        }
                      />
                      {segmentDiff.fieldDiffs.slice(0, 4).map((fieldDiff) => (
                        <Chip
                          key={`${segmentDiff.index}-${fieldDiff.key}`}
                          size="small"
                          label={fieldDiff.label}
                          variant="outlined"
                        />
                      ))}
                      {segmentDiff.fieldDiffs.length > 4 && (
                        <Typography variant="caption" color="text.secondary">
                          等 {segmentDiff.fieldDiffs.length} 项
                        </Typography>
                      )}
                    </Box>

                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                      {visibleFieldDiffs.map((fieldDiff) => (
                        <Box key={`${segmentDiff.index}-${fieldDiff.key}-detail`}>
                          <Typography variant="caption" sx={{ fontWeight: 600 }}>
                            {fieldDiff.label}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" component="div">
                            当前：{fieldDiff.currentValue}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" component="div">
                            对方：{fieldDiff.incomingValue}
                          </Typography>
                        </Box>
                      ))}
                      {hiddenFieldDiffCount > 0 && (
                        <Typography variant="caption" color="text.secondary">
                          其余 {hiddenFieldDiffCount} 个字段差异已折叠。
                        </Typography>
                      )}
                    </Box>
                  </Box>
                )
              })
            ) : (
              <Typography variant="body2" color="text.secondary">
                片段内容无差异，当前冲突主要集中在顶层状态。
              </Typography>
            )}
            {hiddenSegmentDiffCount > 0 && (
              <Typography variant="caption" color="text.secondary">
                其余 {hiddenSegmentDiffCount} 个片段差异已折叠，避免在确认前把弹窗拉得过长。
              </Typography>
            )}
          </Box>
        </Box>
      </Paper>
    )}
  </Box>
)

export default ScriptEditorConflictNotice
