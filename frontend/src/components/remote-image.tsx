import { useEffect, useState } from 'react'

/**
 * RemoteImage — the shared image box with an honest fallback chain (Phase 8;
 * Phase 9 reuses it for place photos). Hotel/room image URLs are external and
 * can 404 or be null, so every slot renders exactly one of three states:
 *
 *   loading      → a plain, static bg-fill box — same neutral tone as the
 *                  error state below, deliberately with NO animation. Used
 *                  to be the shared shimmer-block utility (a moving-gradient
 *                  sweep), dropped on request alongside `vSheen` (below):
 *                  both read as the same "vệt sáng chạy" (running light
 *                  streak) on a photo once an image is slow to load, even
 *                  though they're two different mechanisms. shimmer-block
 *                  itself is untouched — skeleton-card.tsx still uses it for
 *                  whole-card generating-stage placeholders, a different,
 *                  design-matched pattern this doesn't affect.
 *   error / null → neutral Material icon centred in the same box — the
 *                  placeholder pattern hotel-option-card.tsx had pre-Phase-8,
 *                  promoted to shared so no screen hand-rolls its own fallback
 *   success      → the image, object-cover, with a descriptive alt
 *
 * The design also runs an infinite `vSheen` light-sweep over its LOADED photo
 * boxes; dropped here on request across every caller (no `sheen` prop anymore).
 */
export default function RemoteImage({
  src,
  alt,
  className = '',
  icon = 'hotel',
  fit = 'cover',
}: {
  src?: string | null
  alt: string
  className?: string
  icon?: string
  /** `cover` (default) fills the box and crops — right for every thumbnail
   * here, where the box shape is fixed and the photo is decorative. `contain`
   * is for the one place cropping is wrong: image-lightbox.tsx, where the
   * whole point is seeing the photo entire. Kept as a prop rather than a raw
   * <img> in the lightbox so it still gets the loading/error fallback chain
   * above. */
  fit?: 'cover' | 'contain'
}) {
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>(src ? 'loading' : 'error')

  useEffect(() => {
    setStatus(src ? 'loading' : 'error')
  }, [src])

  if (status === 'error') {
    return (
      <div
        className={`bg-fill flex items-center justify-center ${className}`}
        role="img"
        aria-label={alt}
      >
        <span className="material-symbols-outlined text-on-surface-faint" aria-hidden="true">
          {icon}
        </span>
      </div>
    )
  }

  return (
    <div className={`relative overflow-hidden ${className}`}>
      {status === 'loading' && <div className="bg-fill absolute inset-0" aria-hidden="true" />}
      <img
        src={src ?? undefined}
        alt={alt}
        className={`w-full h-full ${fit === 'contain' ? 'object-contain' : 'object-cover'}`}
        loading="lazy"
        onLoad={() => setStatus('ok')}
        onError={() => setStatus('error')}
      />
    </div>
  )
}
