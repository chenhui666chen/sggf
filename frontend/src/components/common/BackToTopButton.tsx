import { useEffect, useState } from 'react'
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
  label = '回到顶部',
  bottom = 32,
  right = 24,
  color = 'primary',
  size = 'medium',
}: BackToTopButtonProps) {
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
      <Tooltip title={label}>
        <Fab
          aria-label={label}
          color={color}
          size={size}
          onClick={handleBackToTop}
          sx={{
            position: 'fixed',
            right,
            bottom,
            zIndex: 1300,
            boxShadow: '0 16px 36px rgba(15, 23, 42, 0.16)',
          }}
        >
          <KeyboardArrowUpIcon />
        </Fab>
      </Tooltip>
    </Fade>
  )
}
