import {
  Divider,
  Menu,
  MenuItem,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import ReplayIcon from '@mui/icons-material/Replay'

import { audiobookColorRoles } from './audiobookTheme'

interface ChapterActionsMenuProps {
  anchorEl: HTMLElement | null
  canRegenerate: boolean
  onClose: () => void
  onRegenerate: () => void
  onOpenDeleteDialog: () => void
}

const ChapterActionsMenu = ({
  anchorEl,
  canRegenerate,
  onClose,
  onRegenerate,
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
    {canRegenerate && (
      <MenuItem onClick={onRegenerate}>
        <ReplayIcon fontSize="small" sx={{ mr: 1 }} />
        重新生成
      </MenuItem>
    )}
    {canRegenerate && <Divider />}
    <MenuItem onClick={onOpenDeleteDialog} sx={{ color: audiobookColorRoles.destructiveAction.main }}>
      <DeleteIcon fontSize="small" sx={{ mr: 1 }} />
      删除章节
    </MenuItem>
  </Menu>
)

export default ChapterActionsMenu
