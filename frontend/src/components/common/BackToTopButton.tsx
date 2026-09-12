import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp'
import {
  Fade,
  Fab,
  Tooltip,
  type FabProps,
} from '@mui/material'

export interface BackToTopButtonProps {
  threshold?: number
  label?: string
  bottom?: number | string
  right?: number | string
  color?: FabProps['color']
  size?: FabProps['size']
}

export default function BackToTopButton({
  threshold = 360,
  label,
  bottom = 32,
  right = 24,
  color = 'primary',
  size = 'medium',
}: BackToTopButtonProps) {
  const { t } = useTranslation()
  const resolvedLabel = label ?? t('backToTop.label')
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const handleScroll = () => {
      const scrollTop =
        window.scrollY ||
        document.documentElement.scrollTop ||
        document.body.scrollTop ||
        0
      setVisible(scrollTop > threshold)
    }

    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })

    return () => {
      window.removeEventListener('scroll', handleScroll)
    }
  }, [threshold])

  const handleBackToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: 'smooth',
    })
  }

  return (
    <Fade in={visible}>
      <Tooltip title={resolvedLabel}>
        <Fab
          aria-label={resolvedLabel}
          color={color}
          size={size}
          onClick={handleBackToTop}
          sx={{
            position: 'fixed',
            right,
            bottom,
            zIndex: 1300,
            boxShadow: 16, // 16-24 档 = shadow4（theme.shadows 表）
          }}
        >
          <KeyboardArrowUpIcon />
        </Fab>
      </Tooltip>
    </Fade>
  )
}
