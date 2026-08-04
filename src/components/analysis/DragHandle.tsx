import { useRef, useEffect } from 'react'

export default function DragHandle({
  onDrag,
  orientation = 'horizontal',
}: {
  onDrag: (delta: number) => void
  orientation?: 'horizontal' | 'vertical'
}) {
  const handleRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const startPos = useRef(0)

  useEffect(() => {
    const el = handleRef.current
    if (!el) return

    const onDown = (e: MouseEvent) => {
      dragging.current = true
      startPos.current = orientation === 'vertical' ? e.clientX : e.clientY
      document.body.style.cursor = orientation === 'vertical' ? 'col-resize' : 'row-resize'
      document.body.style.userSelect = 'none'
      e.preventDefault()
    }

    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const currentPos = orientation === 'vertical' ? e.clientX : e.clientY
      const delta = currentPos - startPos.current
      if (Math.abs(delta) > 2) {
        onDrag(delta)
        startPos.current = currentPos
      }
    }

    const onUp = () => {
      if (dragging.current) {
        dragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
    }

    el.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      el.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [onDrag, orientation])

  return (
    <div
      ref={handleRef}
      className={`shrink-0 transition-colors ${
        orientation === 'vertical'
          ? 'w-[5px] cursor-col-resize bg-gray-100 hover:bg-brand-light/40 active:bg-brand-light border-x border-border-light'
          : 'h-[5px] cursor-row-resize bg-gray-100 hover:bg-brand-light/40 active:bg-brand-light border-t border-b border-border-light'
      }`}
      title="Drag to resize"
    />
  )
}
