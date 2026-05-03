import {
  Menu,
  MenuItem,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'

import { audiobookColors } from './audiobookTheme'

interface ChapterActionsMenuProps {
  anchorEl: HTMLElement | null
  onClose: () => void
  onOpenDeleteDialog: () => void
}

const ChapterActionsMenu = ({
  anchorEl,
  onClose,
  onOpenDeleteDialog,
}: ChapterActionsMenuProps) => (
  <Menu
    anchorEl={anchorEl}
    open={Boolean(anchorEl)}
    onClose={onClose}
    anchorOrigin={{
      vertical: 'bottom',
      horizontal: 'right',
    }}
    transformOrigin={{
      vertical: 'top',
      horizontal: 'right',
    }}
  >
    <MenuItem onClick={onOpenDeleteDialog} sx={{ color: audiobookColors.dangerMain }}>
      <DeleteIcon fontSize="small" sx={{ mr: 1 }} />
      删除章节
    </MenuItem>
  </Menu>
)

export default ChapterActionsMenu
