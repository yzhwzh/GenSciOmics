import { useState, useEffect, useRef, useCallback } from 'react'

interface Transform {
  x: number
  y: number
  scale: number
}

export default function ZoomableImage({
  src,
  alt,
  className,
}: {
  src: string
  alt: string
  className?: string
}) {
  const [zoomed, setZoomed] = useState(false)
  const [transform, setTransform] = useState<Transform>({ x: 0, y: 0, scale: 1 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 })
  const imgRef = useRef<HTMLImageElement>(null)

  // Reset transform when closing
  const close = useCallback(() => {
    setZoomed(false)
    setTransform({ x: 0, y: 0, scale: 1 })
  }, [])

  // Escape key
  useEffect(() => {
    if (!zoomed) return
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [zoomed, close])

  // Window-level mouse listeners for drag (survive mouse leaving image)
  useEffect(() => {
    if (!dragging) return
    const handleMove = (e: MouseEvent) => {
      setTransform(prev => ({
        ...prev,
        x: dragStart.current.tx + (e.clientX - dragStart.current.x),
        y: dragStart.current.ty + (e.clientY - dragStart.current.y),
      }))
    }
    const handleUp = () => setDragging(false)
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
  }, [dragging])

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    setDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y }
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    setTransform(prev => {
      const newScale = Math.max(0.5, Math.min(5, prev.scale + delta))
      // Zoom toward mouse position
      const rect = imgRef.current?.getBoundingClientRect()
      if (rect) {
        const mx = e.clientX - rect.left
        const my = e.clientY - rect.top
        const scaleRatio = newScale / prev.scale
        return {
          x: mx - scaleRatio * (mx - prev.x),
          y: my - scaleRatio * (my - prev.y),
          scale: newScale,
        }
      }
      return { ...prev, scale: newScale }
    })
  }

  const handleReset = (e: React.MouseEvent) => {
    e.stopPropagation()
    setTransform({ x: 0, y: 0, scale: 1 })
  }

  return (
    <>
      <img
        src={src}
        alt={alt}
        className={className}
        onDoubleClick={() => setZoomed(true)}
        style={{ cursor: 'zoom-in' }}
      />
      {zoomed && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-8"
          onClick={close}
        >
          <div
            className="relative w-[95vw] h-[95vh] flex items-center justify-center overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              ref={imgRef}
              src={src}
              alt={alt}
              draggable={false}
              style={{
                transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
                cursor: dragging ? 'grabbing' : 'grab',
                maxWidth: 'none',
                maxHeight: 'none',
                userSelect: 'none',
              }}
              onMouseDown={handleMouseDown}
              onWheel={handleWheel}
              onDoubleClick={handleReset}
            />
            <button
              onClick={close}
              className="absolute -top-3 -right-3 w-8 h-8 bg-surface rounded-full shadow-md flex items-center justify-center text-text-secondary hover:text-text-primary text-lg font-bold border border-border-light z-10"
            >
              &times;
            </button>
          </div>
        </div>
      )}
    </>
  )
}
