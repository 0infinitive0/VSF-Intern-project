import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import RemoteImage from './remote-image'
import { useMountTransition } from '../lib/use-mount-transition'

const EXIT_MS = 220

/**
 * ImageLightbox — the full-size photo viewer behind every gallery thumbnail
 * (image-gallery.tsx owns the state and renders this).
 *
 * Portaled to document.body, and that is not optional: every caller sits
 * inside a `.glass-panel`, whose `backdrop-filter` makes it a containing
 * block for `position: fixed` descendants — a non-portaled overlay would be
 * clipped to the panel's own width instead of filling the viewport. Same
 * reason user-menu.tsx portals its profile modal; see its doc comment.
 *
 * Enter/exit runs through the shared useMountTransition rather than the
 * inlined double-rAF confirm-dialog.tsx hand-rolls, since this is exactly the
 * shape that hook documents: a parent that always renders it, driven by an
 * `open` prop.
 *
 * Sits at z-[80], one rung above BookingModal/BookingReceiptModal (z-[70]),
 * so a thumbnail opened from inside a modal still shows over it.
 *
 * The body scroll lock is the first in this codebase — no other dialog here
 * has one. It earns it: this overlay is the only one that captures arrow keys
 * for its own navigation, and letting the page underneath scroll away behind
 * a viewport-filling photo leaves the guest somewhere else entirely on close.
 */
export default function ImageLightbox({
  images,
  index,
  open,
  onClose,
  onIndexChange,
  altFor,
  icon,
}: {
  images: string[]
  /** Which image is showing. Clamped by the caller; guarded here anyway so a
   * shrinking `images` array can never render an undefined src. */
  index: number
  open: boolean
  onClose: () => void
  onIndexChange: (next: number) => void
  altFor: (index: number) => string
  icon?: string
}) {
  const { t } = useTranslation()
  const { mounted, visible } = useMountTransition(open, EXIT_MS)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const touchStartX = useRef<number | null>(null)

  const count = images.length
  const safeIndex = count > 0 ? Math.min(Math.max(index, 0), count - 1) : 0

  const goTo = useCallback(
    (next: number) => {
      if (count === 0) return
      // Wraps both ways — at the last photo "next" returns to the first
      // rather than dead-ending on a disabled button.
      onIndexChange(((next % count) + count) % count)
    },
    [count, onIndexChange],
  )

  // Escape closes, arrows navigate. Bound to window (the established idiom in
  // confirm-dialog/booking-modal/user-menu) rather than to the overlay node,
  // so it works no matter what inside it holds focus.
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (count < 2) return
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        goTo(safeIndex - 1)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        goTo(safeIndex + 1)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, goTo, safeIndex, count])

  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  // Focus lands on the close button so Escape isn't the only way out for
  // keyboard users. Returning focus to whatever opened this is the caller's
  // job (image-gallery.tsx remembers the thumbnail) — from in here the
  // trigger is already gone by the time this unmounts.
  useEffect(() => {
    if (!open) return
    const frame = requestAnimationFrame(() => closeButtonRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [open])

  if (!mounted || count === 0) return null

  // The photo before, at and after the current one, all kept mounted and
  // stacked. Keying a single <img> on the URL instead made every navigation
  // remount it, so the guest watched RemoteImage's loading box flash between
  // photos; here the neighbour is already loaded and the swap is a pure
  // opacity/transform transition with nothing to wait for.
  //
  // The offset (-1/0/+1) is the layer's position, not `i - safeIndex`, so
  // wrapping from the last photo to the first still slides one step rather
  // than the whole width of the array. Current is written last: at one or two
  // photos the three roles collide on the same index, and the visible layer
  // has to win.
  const layerOffsets = new Map<number, number>()
  layerOffsets.set((safeIndex - 1 + count) % count, -1)
  layerOffsets.set((safeIndex + 1) % count, 1)
  layerOffsets.set(safeIndex, 0)
  const layers = [...layerOffsets.entries()].sort((a, b) => a[0] - b[0])

  const navButtonClass =
    'absolute top-1/2 -translate-y-1/2 w-11 h-11 rounded-full flex items-center justify-center ' +
    'text-white border border-white/20 cursor-pointer transition-all duration-200 ' +
    'hover:bg-white/25 active:scale-90'
  const navButtonStyle = { background: 'rgba(255,255,255,.14)', backdropFilter: 'blur(10px)' }

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex flex-col items-center justify-center p-4 sm:p-8"
      style={{
        background: 'rgba(8,12,20,.72)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        opacity: visible ? 1 : 0,
        transition: `opacity ${EXIT_MS}ms ease`,
      }}
      // Only a click that lands on the backdrop itself closes — the same
      // guard booking-modal.tsx uses, so dragging off the photo or releasing
      // over a control doesn't dismiss.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      onTouchStart={(e) => {
        touchStartX.current = e.touches[0]?.clientX ?? null
      }}
      onTouchEnd={(e) => {
        const start = touchStartX.current
        touchStartX.current = null
        if (start == null || count < 2) return
        const delta = (e.changedTouches[0]?.clientX ?? start) - start
        if (Math.abs(delta) < 48) return
        goTo(safeIndex + (delta < 0 ? 1 : -1))
      }}
      role="dialog"
      aria-modal="true"
      aria-label={altFor(safeIndex)}
    >
      <div
        className="relative flex items-center justify-center w-full"
        style={{
          maxWidth: 'min(1100px, 92vw)',
          opacity: visible ? 1 : 0,
          transform: visible ? 'none' : 'translateY(18px) scale(.98)',
          transition: `opacity ${EXIT_MS}ms ease, transform 320ms cubic-bezier(.22,1,.36,1)`,
        }}
      >
        <div className="relative w-full h-[78vh]">
          {layers.map(([i, offset]) => (
            <div
              // Keyed by index, not URL: the same photo can legitimately
              // appear twice in one array, and duplicate keys would collapse
              // two layers into one.
              key={i}
              className="absolute inset-0"
              // The outgoing layer keeps its own transition running while the
              // incoming one fades in over it, which is what makes this read
              // as a cross-fade rather than a blank-then-appear.
              style={{
                opacity: offset === 0 ? 1 : 0,
                transform: `translateX(${offset * 26}px)`,
                transition:
                  'opacity 280ms ease, transform 340ms cubic-bezier(.22,1,.36,1)',
                pointerEvents: offset === 0 ? undefined : 'none',
              }}
              aria-hidden={offset !== 0}
            >
              <RemoteImage
                src={images[i]}
                alt={offset === 0 ? altFor(i) : ''}
                icon={icon}
                fit="contain"
                className="w-full h-full rounded-[24px]"
              />
            </div>
          ))}
        </div>

        {count > 1 && (
          <>
            <button
              type="button"
              aria-label={t('lightboxPrev')}
              onClick={() => goTo(safeIndex - 1)}
              className={`${navButtonClass} left-3`}
              style={navButtonStyle}
            >
              <span className="material-symbols-outlined text-[22px]" aria-hidden="true">
                chevron_left
              </span>
            </button>
            <button
              type="button"
              aria-label={t('lightboxNext')}
              onClick={() => goTo(safeIndex + 1)}
              className={`${navButtonClass} right-3`}
              style={navButtonStyle}
            >
              <span className="material-symbols-outlined text-[22px]" aria-hidden="true">
                chevron_right
              </span>
            </button>
          </>
        )}

        <button
          ref={closeButtonRef}
          type="button"
          aria-label={t('lightboxClose')}
          onClick={onClose}
          className="absolute top-3 right-3 w-10 h-10 rounded-full flex items-center justify-center text-white border border-white/20 cursor-pointer transition-all duration-200 hover:bg-white/25 active:scale-90"
          style={navButtonStyle}
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
            close
          </span>
        </button>

        {count > 1 && (
          <div
            className="absolute top-3 left-3 px-3 py-1 rounded-full text-white text-[12px] font-[590] tabular-nums border border-white/20"
            style={navButtonStyle}
          >
            {t('lightboxCounter', { index: safeIndex + 1, total: count })}
          </div>
        )}
      </div>

      {count > 1 && (
        <div
          className="flex gap-2 mt-4 max-w-full overflow-x-auto custom-scrollbar px-1 pb-1"
          style={{
            opacity: visible ? 1 : 0,
            transition: `opacity ${EXIT_MS}ms ease`,
          }}
        >
          {images.map((url, i) => (
            <button
              key={url}
              type="button"
              aria-label={altFor(i)}
              aria-current={i === safeIndex}
              onClick={() => goTo(i)}
              className="flex-none w-[62px] h-[44px] rounded-[10px] overflow-hidden cursor-pointer transition-all duration-200 hover:opacity-100"
              style={{
                opacity: i === safeIndex ? 1 : 0.5,
                outline: i === safeIndex ? '2px solid var(--acc)' : '1px solid rgba(255,255,255,.25)',
                outlineOffset: i === safeIndex ? '1px' : '0',
              }}
            >
              <RemoteImage src={url} alt="" icon={icon} className="w-full h-full" />
            </button>
          ))}
        </div>
      )}
    </div>,
    document.body,
  )
}
