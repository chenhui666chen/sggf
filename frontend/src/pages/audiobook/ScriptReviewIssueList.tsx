import {
  Box,
  Chip,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material'

import type { ScriptReviewIssue } from './types'
import { ISSUE_DISPLAY_LIMIT } from './utils'
import { getReviewIssueDisplay } from './scriptReviewReportUtils'

interface ScriptReviewIssueListProps {
  issues: ScriptReviewIssue[]
  extraIssues: number
  selectedIssueIndex?: number | null
  onSelectIssue?: (index: number | null) => void
}

const ScriptReviewIssueList = ({
  issues,
  extraIssues,
  selectedIssueIndex = null,
  onSelectIssue,
}: ScriptReviewIssueListProps) => (
  <>
    <Divider textAlign="left">问题清单</Divider>
    {issues.length > 0 ? (
      <List dense>
        {issues.slice(0, ISSUE_DISPLAY_LIMIT).map((issue, idx) => {
          const display = getReviewIssueDisplay(issue)
          return (
            <ListItemButton
              key={`${issue.location || idx}-${idx}`}
              alignItems="flex-start"
              selected={selectedIssueIndex === idx}
              onClick={() => onSelectIssue?.(selectedIssueIndex === idx ? null : idx)}
              sx={{ mb: 1, borderRadius: 1 }}
            >
              <ListItemText
                primary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                    <Chip label={display.severityLabel} size="small" color={display.color} />
                    <Chip label={display.categoryLabel} size="small" variant="outlined" />
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {display.description}
                    </Typography>
                  </Box>
                }
                secondary={
                  display.suggestion ? (
                    <Typography variant="body2" color="text.secondary">
                      建议：{display.suggestion}
                    </Typography>
                  ) : undefined
                }
              />
            </ListItemButton>
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
  </>
)

export default ScriptReviewIssueList
