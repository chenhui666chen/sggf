import { Snackbar, Alert, Slide, type SlideProps } from '@mui/material'
import type { CollectFeedback } from '@/types/dreamweaver'

interface ToastNotificationProps {
  feedback: CollectFeedback | null
  onClose: () => void
  duration?: number
}

function SlideTransition(props: SlideProps) {
  return <Slide {...props} direction="up" />
}

export function ToastNotification({
  feedback,
  onClose,
  duration = 5000,
}: ToastNotificationProps) {
  return (
    <Snackbar
      open={feedback !== null}
      autoHideDuration={duration}
      onClose={onClose}
      TransitionComponent={SlideTransition}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
    >
      {feedback ? (
        <Alert
          severity={feedback.type}
          onClose={onClose}
          variant="filled"
          sx={{ width: '100%', maxWidth: 400 }}
        >
          {feedback.text}
        </Alert>
      ) : undefined}
    </Snackbar>
  )
}

interface ToastContainerProps {
  toasts: Array<CollectFeedback & { id: string }>
  onRemove: (id: string) => void
  maxVisible?: number
}

export function ToastContainer({
  toasts,
  onRemove,
  maxVisible = 3,
}: ToastContainerProps) {
  const visibleToasts = toasts.slice(-maxVisible)

  return (
    <>
      {visibleToasts.map((toast, index) => (
        <Snackbar
          key={toast.id}
          open
          autoHideDuration={5000}
          onClose={() => onRemove(toast.id)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
          sx={{ bottom: `${24 + index * 60}px` }}
        >
          <Alert
            severity={toast.type}
            onClose={() => onRemove(toast.id)}
            variant="filled"
            sx={{ width: '100%', maxWidth: 400 }}
          >
            {toast.text}
          </Alert>
        </Snackbar>
      ))}
    </>
  )
}
