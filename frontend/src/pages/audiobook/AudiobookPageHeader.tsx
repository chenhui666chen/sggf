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
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
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
      <Tooltip title={t('audiobook.audiobookPageHeader.backTooltip')}>
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
            {t('audiobook.audiobookPageHeader.productName')}
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            sx={{ display: { xs: 'none', sm: 'block' } }}
          >
            {t('audiobook.audiobookPageHeader.productTagline')}
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
          {t('audiobook.audiobookPageHeader.createProject')}
        </Button>

        {hasSelectedProject && (
          <Tooltip title={t('audiobook.audiobookPageHeader.historyTooltip')}>
            <Button
              variant="outlined"
              startIcon={<HistoryIcon />}
              onClick={onOpenHistory}
              color="primary"
            >
              {t('audiobook.audiobookPageHeader.history')}
            </Button>
          </Tooltip>
        )}
      </Box>

      <Box sx={{ display: { xs: 'flex', sm: 'none' }, flexShrink: 0 }}>
        <Tooltip title={t('audiobook.audiobookPageHeader.moreActions')}>
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
            <ListItemText primary={t('audiobook.audiobookPageHeader.createProject')} />
          </MenuItem>

          {hasSelectedProject && (
            <MenuItem onClick={handleOpenHistory}>
              <ListItemIcon>
                <HistoryIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText primary={t('audiobook.audiobookPageHeader.history')} />
            </MenuItem>
          )}
        </Menu>
      </Box>
    </Box>
  )
}

export default AudiobookPageHeader
