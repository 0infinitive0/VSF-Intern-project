import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ImageLightbox from './image-lightbox'
import RemoteImage from './remote-image'

/**
 * ImageGallery — the thumbnail grid every photo list in the guest app now
 * renders, plus the click-to-enlarge behaviour behind it.
 *
 * Replaces four near-identical hand-rolled grids (hotel-detail-panel,
 * hotel-stay-panel, place-detail-panel, room-card) that differed only in
 * column count, thumb height and fallback icon — same `vFade` stagger, same
 * RemoteImage, same markup otherwise. Folding them together is what makes the
 * lightbox one change instead of four.
 *
 * `maxThumbs` caps what the grid SHOWS, never what the lightbox can reach:
 * the callers were already slicing to 3-4 while holding longer arrays, so the
 * extra photos existed but were unreachable and unannounced. Now the last
 * visible thumb carries a "+N" badge and opening any thumb pages through the
 * whole array.
 */
export default function ImageGallery({
  images,
  altFor,
  thumbClassName,
  columns,
  maxThumbs,
  icon,
  className = '',
}: {
  images: string[]
  altFor: (index: number) => string
  /** Sizing/rounding for each thumb, e.g. `h-[80px] rounded-[16px]`. */
  thumbClassName: string
  columns: 3 | 4
  /** How many thumbs to render. Omit to show every image. */
  maxThumbs?: number
  icon?: string
  className?: string
}) {
  const { t } = useTranslation()
  const [openIndex, setOpenIndex] = useState<number | null>(null)
  // The thumb that opened the lightbox, so focus can go back where it was
  // instead of to the top of the document when the overlay unmounts.
  const lastTriggerRef = useRef<HTMLButtonElement | null>(null)

  if (images.length === 0) return null

  const shown = maxThumbs != null ? images.slice(0, maxThumbs) : images
  const hiddenCount = images.length - shown.length
  // Tailwind scans for whole class names, so these can't be built by
  // interpolating `columns` into the string.
  const gridCols = columns === 3 ? 'grid-cols-3' : 'grid-cols-4'

  return (
    <>
      <div className={`grid ${gridCols} gap-[9px] ${className}`}>
        {shown.map((url, i) => {
          const isLastShown = i === shown.length - 1
          const showsMoreBadge = isLastShown && hiddenCount > 0
          return (
            <button
              key={url}
              type="button"
              // stopPropagation because RoomCard's whole card is a click
              // target that expands/collapses it — without this, enlarging a
              // photo would also collapse the card out from under the
              // lightbox. Harmless everywhere else, and the same idiom that
              // file already uses for its quantity stepper.
              onClick={(e) => {
                e.stopPropagation()
                lastTriggerRef.current = e.currentTarget
                setOpenIndex(i)
              }}
              aria-label={showsMoreBadge ? t('galleryMoreLabel', { count: hiddenCount }) : altFor(i)}
              className={`relative block w-full cursor-zoom-in overflow-hidden transition-transform duration-200 hover:scale-[1.03] active:scale-[0.98] ${thumbClassName}`}
              style={{ animation: `vFade .5s ${i * 90}ms ease both` }}
            >
              <RemoteImage
                src={url}
                alt={showsMoreBadge ? '' : altFor(i)}
                icon={icon}
                className="w-full h-full"
              />
              {showsMoreBadge && (
                <span
                  className="absolute inset-0 flex items-center justify-center text-white text-[15px] font-[650] tracking-[-0.2px]"
                  style={{ background: 'rgba(8,12,20,.52)' }}
                  aria-hidden="true"
                >
                  +{hiddenCount}
                </span>
              )}
            </button>
          )
        })}
      </div>

      <ImageLightbox
        images={images}
        index={openIndex ?? 0}
        open={openIndex !== null}
        onIndexChange={setOpenIndex}
        onClose={() => {
          setOpenIndex(null)
          lastTriggerRef.current?.focus()
        }}
        altFor={altFor}
        icon={icon}
      />
    </>
  )
}
