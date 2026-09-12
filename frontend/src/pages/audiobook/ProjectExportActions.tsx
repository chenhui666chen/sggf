import { useState } from 'react'
import {
  Button,
  CircularProgress,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import { useTranslation } from 'react-i18next'

import { audiobookButtonSx } from './audiobookTheme'

interface ProjectExportActionsProps {
  hasChapterAudios: boolean
  completedChapters?: number | null
  exportingProjectM4b: boolean
  exportingProjectAudacity: boolean
  hasActiveM4bExportTask: boolean
  hasActiveAudacityExportTask: boolean
  onExportProjectM4b: () => void
  onExportProjectAudacity: () => void
}

const ProjectExportActions = ({
  hasChapterAudios,
  completedChapters,
  exportingProjectM4b,
  exportingProjectAudacity,
  hasActiveM4bExportTask,
  hasActiveAudacityExportTask,
  onExportProjectM4b,
  onExportProjectAudacity,
}: ProjectExportActionsProps) => {
  const { t } = useTranslation()
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)

  if (!hasChapterAudios) {
    return null
  }

  const canExport = Boolean(completedChapters)
  const isM4bPending = exportingProjectM4b || hasActiveM4bExportTask
  const isAudacityPending = exportingProjectAudacity || hasActiveAudacityExportTask
  const hasPendingExport = isM4bPending || isAudacityPending
  const menuOpen = Boolean(menuAnchor)
  const exportTooltipTitle = !canExport
    ? t('audiobook.projectExportActions.noCompletedChapters')
    : hasPendingExport
      ? t('audiobook.projectExportActions.exportTaskQueued')
      : t('audiobook.projectExportActions.exportWholeBook')

  const closeMenu = () => {
    setMenuAnchor(null)
  }

  const handleExportM4b = () => {
    closeMenu()
    if (!canExport || isM4bPending) {
      return
    }
    onExportProjectM4b()
  }

  const handleExportAudacity = () => {
    closeMenu()
    if (!canExport || isAudacityPending) {
      return
    }
    onExportProjectAudacity()
  }

  return (
    <>
      <Tooltip title={exportTooltipTitle}>
        <span>
          <Button
            variant="contained"
            startIcon={hasPendingExport ? <CircularProgress size={18} color="inherit" /> : <DownloadIcon />}
            endIcon={<KeyboardArrowDownIcon />}
            onClick={(event) => setMenuAnchor(event.currentTarget)}
            disabled={!canExport}
            aria-haspopup="menu"
            aria-expanded={menuOpen ? 'true' : undefined}
            sx={audiobookButtonSx.brandContained}
          >
            {hasPendingExport
              ? t('audiobook.projectExportActions.exportQueueing')
              : t('audiobook.projectExportActions.export')}
          </Button>
        </span>
      </Tooltip>

      <Menu
        anchorEl={menuAnchor}
        open={menuOpen}
        onClose={closeMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { minWidth: 220 } } }}
      >
        <MenuItem onClick={handleExportM4b} disabled={!canExport || isM4bPending}>
          <ListItemIcon>
            {isM4bPending ? <CircularProgress size={18} /> : <DownloadIcon fontSize="small" />}
          </ListItemIcon>
          <ListItemText
            primary={t('audiobook.projectExportActions.m4bItem')}
            secondary={
              isM4bPending
                ? t('audiobook.projectExportActions.exportQueueing')
                : t('audiobook.projectExportActions.m4bItemHint')
            }
          />
        </MenuItem>

        <MenuItem onClick={handleExportAudacity} disabled={!canExport || isAudacityPending}>
          <ListItemIcon>
            {isAudacityPending ? <CircularProgress size={18} /> : <DownloadIcon fontSize="small" />}
          </ListItemIcon>
          <ListItemText
            primary={t('audiobook.projectExportActions.audacityItem')}
            secondary={
              isAudacityPending
                ? t('audiobook.projectExportActions.exportQueueing')
                : t('audiobook.projectExportActions.audacityItemHint')
            }
          />
        </MenuItem>
      </Menu>
    </>
  )
}

export default ProjectExportActions
