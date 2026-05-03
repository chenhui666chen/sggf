import {
  Alert,
  Snackbar,
} from '@mui/material'

import type { SnackbarState } from './hookTypes'

interface AudiobookSnackbarProps {
  snackbar: SnackbarState
  onClose: () => void
}

const AudiobookSnackbar = ({
  snackbar,
  onClose,
}: AudiobookSnackbarProps) => (
  <Snackbar
    open={snackbar.open}
    autoHideDuration={4000}
    onClose={onClose}
    anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
  >
    <Alert
      onClose={onClose}
      severity={snackbar.severity}
      sx={{ width: '100%' }}
    >
      {snackbar.message}
    </Alert>
  </Snackbar>
)

export default AudiobookSnackbar
