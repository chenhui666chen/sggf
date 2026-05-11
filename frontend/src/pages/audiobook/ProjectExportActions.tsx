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
    ? '暂无已完成章节，无法导出'
    : hasPendingExport
      ? '已有导出任务排队中'
      : '导出整本有声书'

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
            {hasPendingExport ? '导出排队中...' : '导出'}
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
            primary="整本 M4B"
            secondary={isM4bPending ? '导出排队中' : '适合整本收听和归档'}
          />
        </MenuItem>

        <MenuItem onClick={handleExportAudacity} disabled={!canExport || isAudacityPending}>
          <ListItemIcon>
            {isAudacityPending ? <CircularProgress size={18} /> : <DownloadIcon fontSize="small" />}
          </ListItemIcon>
          <ListItemText
            primary="Audacity ZIP"
            secondary={isAudacityPending ? '导出排队中' : '适合后期工程编辑'}
          />
        </MenuItem>
      </Menu>
    </>
  )
}

export default ProjectExportActions
