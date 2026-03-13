import { useState, useEffect, useCallback } from 'react'

export type DeviceType = 'mobile' | 'tablet' | 'desktop' | 'large'

export interface ResponsiveInfo {
  deviceType: DeviceType
  isMobile: boolean
  isTablet: boolean
  isDesktop: boolean
  isLarge: boolean
  width: number
  height: number
  orientation: 'portrait' | 'landscape'
}

const BREAKPOINTS = {
  mobile: 767,
  tablet: 1024,
  desktop: 1920,
}

export function useResponsive(): ResponsiveInfo {
  const getDeviceType = useCallback((width: number): DeviceType => {
    if (width <= BREAKPOINTS.mobile) return 'mobile'
    if (width <= BREAKPOINTS.tablet) return 'tablet'
    if (width < BREAKPOINTS.desktop) return 'desktop'
    return 'large'
  }, [])

  const getResponsiveInfo = useCallback((): ResponsiveInfo => {
    const width = window.innerWidth
    const height = window.innerHeight
    const deviceType = getDeviceType(width)

    return {
      deviceType,
      isMobile: deviceType === 'mobile',
      isTablet: deviceType === 'tablet',
      isDesktop: deviceType === 'desktop' || deviceType === 'large',
      isLarge: deviceType === 'large',
      width,
      height,
      orientation: width > height ? 'landscape' : 'portrait',
    }
  }, [getDeviceType])

  const [responsiveInfo, setResponsiveInfo] = useState<ResponsiveInfo>(getResponsiveInfo)

  useEffect(() => {
    const handleResize = () => {
      setResponsiveInfo(getResponsiveInfo())
    }

    window.addEventListener('resize', handleResize)
    
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [getResponsiveInfo])

  return responsiveInfo
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches
    }
    return false
  })

  useEffect(() => {
    const mediaQuery = window.matchMedia(query)
    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches)
    }

    mediaQuery.addEventListener('change', handler)
    setMatches(mediaQuery.matches)

    return () => {
      mediaQuery.removeEventListener('change', handler)
    }
  }, [query])

  return matches
}

export function useBreakpoint() {
  const isMobile = useMediaQuery(`(max-width: ${BREAKPOINTS.mobile}px)`)
  const isTablet = useMediaQuery(
    `(min-width: ${BREAKPOINTS.mobile + 1}px) and (max-width: ${BREAKPOINTS.tablet}px)`
  )
  const isDesktop = useMediaQuery(
    `(min-width: ${BREAKPOINTS.tablet + 1}px) and (max-width: ${BREAKPOINTS.desktop - 1}px)`
  )
  const isLarge = useMediaQuery(`(min-width: ${BREAKPOINTS.desktop}px)`)

  return {
    isMobile,
    isTablet,
    isDesktop,
    isLarge,
    current: isMobile ? 'mobile' : isTablet ? 'tablet' : isDesktop ? 'desktop' : 'large',
  }
}

export function useContainerWidth(containerRef: React.RefObject<HTMLElement>) {
  const [width, setWidth] = useState(0)

  useEffect(() => {
    if (!containerRef.current) return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        setWidth(entry.contentRect.width)
      }
    })

    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
    }
  }, [containerRef])

  return width
}
