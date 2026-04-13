import { useRef, useEffect, useState } from 'react'

interface UseLazyImageOptions {
  src: string
  placeholder?: string
  rootMargin?: string
  threshold?: number
}

interface UseLazyImageReturn {
  imageSrc: string
  imageRef: React.RefObject<HTMLImageElement>
  isLoaded: boolean
  isError: boolean
  isLoading: boolean
}

export function useLazyImage(options: UseLazyImageOptions): UseLazyImageReturn {
  const { src, placeholder = '', rootMargin = '200px', threshold = 0.1 } = options
  const imageRef = useRef<HTMLImageElement>(null)
  const [isLoaded, setIsLoaded] = useState(false)
  const [isError, setIsError] = useState(false)
  const [isInView, setIsInView] = useState(false)

  const isLoading = isInView && !isLoaded && !isError
  const imageSrc = isInView ? src : placeholder

  useEffect(() => {
    const img = imageRef.current
    if (!img) return

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsInView(true)
            observer.unobserve(entry.target)
          }
        })
      },
      { rootMargin, threshold }
    )

    observer.observe(img)

    return () => {
      observer.disconnect()
    }
  }, [rootMargin, threshold])

  useEffect(() => {
    if (!isInView || !src) return

    const img = new Image()
    img.src = src

    img.onload = () => {
      setIsLoaded(true)
      setIsError(false)
    }

    img.onerror = () => {
      setIsError(true)
      setIsLoaded(false)
    }

    return () => {
      img.onload = null
      img.onerror = null
    }
  }, [isInView, src])

  return {
    imageSrc,
    imageRef,
    isLoaded,
    isError,
    isLoading,
  }
}

interface LazyImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
  placeholder?: string
  rootMargin?: string
  threshold?: number
  fallback?: React.ReactNode
  onLoad?: () => void
  onError?: () => void
}

export function LazyImage({
  src,
  placeholder = '',
  rootMargin = '200px',
  threshold = 0.1,
  fallback,
  onLoad,
  onError,
  ...props
}: LazyImageProps) {
  const { imageSrc, imageRef, isLoaded, isError, isLoading } = useLazyImage({
    src,
    placeholder,
    rootMargin,
    threshold,
  })

  useEffect(() => {
    if (isLoaded && onLoad) {
      onLoad()
    }
  }, [isLoaded, onLoad])

  useEffect(() => {
    if (isError && onError) {
      onError()
    }
  }, [isError, onError])

  if (isError && fallback) {
    return <>{fallback}</>
  }

  return (
    <img
      ref={imageRef}
      src={imageSrc}
      data-loaded={isLoaded}
      data-loading={isLoading}
      data-error={isError}
      {...props}
    />
  )
}
