import { useState } from 'react'
import {
  Box,
  Button,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import HistoryIcon from '@mui/icons-material/History'
import MoreVertIcon from '@mui/icons-material/MoreVert'

import { audiobookColors } from './audiobookTheme'

interface AudiobookPageHeaderProps {
  hasSelectedProject: boolean
  onBack: () => void
  onCreateProject: () => void
  onOpenHistory: () => void
}

const AudiobookPageHeader = ({
  hasSelectedProject,
  onBack,
  onCreateProject,
  onOpenHistory,
}: AudiobookPageHeaderProps) => {
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const menuOpen = Boolean(menuAnchor)

  const closeMenu = () => {
    setMenuAnchor(null)
  }

  const handleCreateProject = () => {
    closeMenu()
    onCreateProject()
  }

  const handleOpenHistory = () => {
    closeMenu()
    onOpenHistory()
  }

  return (
    <Box
      sx={{
        p: { xs: 1.5, sm: 2 },
        display: 'flex',
        alignItems: 'center',
        gap: { xs: 1, sm: 2 },
        backgroundColor: audiobookColors.surfacePaper,
        backdropFilter: 'blur(10px)',
        boxShadow: audiobookColors.shadowSoft,
      }}
    >
      <Tooltip title="返回">
        <IconButton onClick={onBack} edge="start">
          <ArrowBackIcon />
        </IconButton>
      </Tooltip>

      <Box sx={{ minWidth: 0, flex: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
        <HeadphonesIcon sx={{ flexShrink: 0, fontSize: { xs: 28, sm: 32 }, color: 'primary.main' }} />
        <Box sx={{ minWidth: 0 }}>
          <Typography
            variant="h5"
            noWrap
            sx={{ fontWeight: 700, fontSize: { xs: '1.15rem', sm: '1.5rem' } }}
          >
            耳畔星河
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            sx={{ display: { xs: 'none', sm: 'block' } }}
          >
            有声小说生成工具
          </Typography>
        </Box>
      </Box>

      <Box sx={{ display: { xs: 'none', sm: 'flex' }, alignItems: 'center', gap: 1, flexShrink: 0 }}>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={onCreateProject}
          color="primary"
        >
          新建项目
        </Button>

        {hasSelectedProject && (
          <Tooltip title="查看历史生成记录">
            <Button
              variant="outlined"
              startIcon={<HistoryIcon />}
              onClick={onOpenHistory}
              color="primary"
            >
              历史记录
            </Button>
          </Tooltip>
        )}
      </Box>

      <Box sx={{ display: { xs: 'flex', sm: 'none' }, flexShrink: 0 }}>
        <Tooltip title="更多操作">
          <IconButton
            onClick={(event) => setMenuAnchor(event.currentTarget)}
            aria-haspopup="menu"
            aria-expanded={menuOpen ? 'true' : undefined}
          >
            <MoreVertIcon />
          </IconButton>
        </Tooltip>

        <Menu
          anchorEl={menuAnchor}
          open={menuOpen}
          onClose={closeMenu}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        >
          <MenuItem onClick={handleCreateProject}>
            <ListItemIcon>
              <AddIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="新建项目" />
          </MenuItem>

          {hasSelectedProject && (
            <MenuItem onClick={handleOpenHistory}>
              <ListItemIcon>
                <HistoryIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText primary="历史记录" />
            </MenuItem>
          )}
        </Menu>
      </Box>
    </Box>
  )
}

export default AudiobookPageHeader
