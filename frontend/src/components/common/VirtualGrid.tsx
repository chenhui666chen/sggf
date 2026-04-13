import { useRef, useMemo } from 'react'
import { useVirtualizer, type Virtualizer } from '@tanstack/react-virtual'

interface UseVirtualGridOptions {
  itemCount: number
  columns: number
  itemHeight: number
  gap?: number
  overscan?: number
}

interface UseVirtualGridReturn {
  virtualizer: Virtualizer<HTMLDivElement, Element>
  virtualItems: ReturnType<Virtualizer<HTMLDivElement, Element>['getVirtualItems']>
  totalHeight: number
  gridRef: React.RefObject<HTMLDivElement>
}

export function useVirtualGrid(options: UseVirtualGridOptions): UseVirtualGridReturn {
  const { itemCount, columns, itemHeight, gap = 16, overscan = 5 } = options
  const gridRef = useRef<HTMLDivElement>(null)

  const rows = useMemo(() => {
    return Math.ceil(itemCount / columns)
  }, [itemCount, columns])

  const rowHeight = useMemo(() => {
    return itemHeight + gap
  }, [itemHeight, gap])

  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => gridRef.current,
    estimateSize: () => rowHeight,
    overscan,
  })

  const virtualItems = virtualizer.getVirtualItems()

  return {
    virtualizer,
    virtualItems,
    totalHeight: virtualizer.getTotalSize(),
    gridRef,
  }
}

interface VirtualGridProps<T> {
  items: T[]
  columns: number
  itemWidth: number
  itemHeight: number
  gap?: number
  overscan?: number
  renderItem: (item: T, index: number) => React.ReactNode
  className?: string
  style?: React.CSSProperties
}

export function VirtualGrid<T>({
  items,
  columns,
  itemWidth,
  itemHeight,
  gap = 16,
  overscan = 5,
  renderItem,
  className,
  style,
}: VirtualGridProps<T>) {
  const { virtualItems, totalHeight, gridRef } = useVirtualGrid({
    itemCount: items.length,
    columns,
    itemHeight,
    gap,
    overscan,
  })

  return (
    <div
      ref={gridRef}
      className={className}
      style={{
        height: '100%',
        overflow: 'auto',
        ...style,
      }}
    >
      <div
        style={{
          height: `${totalHeight}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualItems.map((virtualRow) => {
          const startIndex = virtualRow.index * columns
          const endIndex = Math.min(startIndex + columns, items.length)
          const rowItems = items.slice(startIndex, endIndex)

          return (
            <div
              key={virtualRow.key}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
                display: 'flex',
                gap: `${gap}px`,
                paddingLeft: `${gap}px`,
              }}
            >
              {rowItems.map((item, colIndex) => {
                const globalIndex = startIndex + colIndex
                return (
                  <div
                    key={globalIndex}
                    style={{
                      width: `${itemWidth}px`,
                      height: `${itemHeight}px`,
                      flexShrink: 0,
                    }}
                  >
                    {renderItem(item, globalIndex)}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}
