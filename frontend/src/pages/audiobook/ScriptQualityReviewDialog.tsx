import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Typography,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'

import ScriptReviewReport from './ScriptReviewReport'
import type { ScriptReviewDialogData } from './types'

interface ScriptQualityReviewDialogProps {
  open: boolean
  data: ScriptReviewDialogData | null
  selectedIssueIndex?: number | null
  selectedSegmentIndex?: number | null
  onClose: () => void
  onOpenScriptEditor?: (chapterId: number) => void | Promise<void>
  onSelectIssue?: (index: number | null) => void
  onSelectSegment?: (index: number | null) => void
}

const ScriptQualityReviewDialog = ({
  open,
  data,
  selectedIssueIndex = null,
  selectedSegmentIndex = null,
  onClose,
  onOpenScriptEditor,
  onSelectIssue,
  onSelectSegment,
}: ScriptQualityReviewDialogProps) => {
  const canOpenScriptEditor = Boolean(data?.chapterId && onOpenScriptEditor)
  const handleOpenScriptEditor = () => {
    if (!data?.chapterId || !onOpenScriptEditor) return
    onClose()
    void onOpenScriptEditor(data.chapterId)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>剧本质量评审</DialogTitle>
      <DialogContent dividers>
        {!data ? (
          <Typography variant="body2" color="text.secondary">
            暂无评审数据
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <ScriptReviewReport
              review={data.report}
              selectedIssueIndex={selectedIssueIndex}
              onSelectIssue={onSelectIssue}
            />

            <Divider />

            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                剧本片段预览（前 {data.segments.length} 段）
              </Typography>
              <Paper
                variant="outlined"
                sx={{ maxHeight: 400, overflow: 'auto', p: 1 }}
              >
                <List dense>
                  {data.segments.map((seg, index) => {
                    const segmentIndex = typeof seg.index === 'number' ? seg.index : index
                    const segmentType = seg.type === 'dialogue' ? '对白' : seg.type || '旁白'
                    const speaker = seg.speaker || seg.speaker_name || seg.character_name || '旁白'

                    return (
                      <ListItemButton
                        key={`${segmentIndex}-${speaker}`}
                        alignItems="flex-start"
                        selected={selectedSegmentIndex === segmentIndex}
                        onClick={() => onSelectSegment?.(
                          selectedSegmentIndex === segmentIndex ? null : segmentIndex,
                        )}
                        sx={{ mb: 0.5, borderRadius: 1 }}
                      >
                        <ListItemText
                          primary={
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              #{segmentIndex + 1} [{segmentType}] {speaker}
                            </Typography>
                          }
                          secondary={
                            <Typography variant="body2" color="text.secondary">
                              {seg.text || ''}
                            </Typography>
                          }
                        />
                      </ListItemButton>
                    )
                  })}
                </List>
              </Paper>
            </Box>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        {canOpenScriptEditor && (
          <Button startIcon={<EditIcon />} onClick={handleOpenScriptEditor}>
            打开剧本编辑器
          </Button>
        )}
        <Button onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  )
}

export default ScriptQualityReviewDialog
