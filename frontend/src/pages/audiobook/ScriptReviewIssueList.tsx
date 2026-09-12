import {
  Box,
  Chip,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

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
}: ScriptReviewIssueListProps) => {
  const { t } = useTranslation()
  return (
  <>
    <Divider textAlign="left">{t('audiobook.scriptReviewIssueList.title')}</Divider>
    {issues.length > 0 ? (
      <List dense>
        {issues.slice(0, ISSUE_DISPLAY_LIMIT).map((issue, idx) => {
          const display = getReviewIssueDisplay(issue, t)
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
                    {display.dimensionLabel && (
                      <Chip label={display.dimensionLabel} size="small" variant="outlined" color="info" />
                    )}
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {display.description}
                    </Typography>
                  </Box>
                }
                secondary={
                  display.suggestion ? (
                    <Typography variant="body2" color="text.secondary">
                      {t('audiobook.scriptReviewIssueList.suggestionPrefix', { value: display.suggestion })}
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
        {t('audiobook.scriptReviewIssueList.noIssues')}
      </Typography>
    )}
    {extraIssues > 0 && (
      <Typography variant="caption" color="text.secondary">
        {t('audiobook.scriptReviewIssueList.extraIssuesHint', { total: extraIssues })}
      </Typography>
    )}
  </>
  )
}

export default ScriptReviewIssueList
