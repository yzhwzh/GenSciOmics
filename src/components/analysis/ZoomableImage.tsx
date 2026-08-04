import { useState, useEffect } from 'react'

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

  useEffect(() => {
    if (!zoomed) return
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setZoomed(false) }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [zoomed])

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
          onClick={() => setZoomed(false)}
        >
          <div
            className="relative max-w-[95vw] max-h-[95vh] flex items-center justify-center"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={src}
              alt={alt}
              className="max-w-full max-h-full object-contain shadow-2xl rounded"
            />
            <button
              onClick={() => setZoomed(false)}
              className="absolute -top-3 -right-3 w-8 h-8 bg-surface rounded-full shadow-md flex items-center justify-center text-text-secondary hover:text-text-primary text-lg font-bold border border-border-light"
            >
              X
            </button>
          </div>
        </div>
      )}
    </>
  )
}
