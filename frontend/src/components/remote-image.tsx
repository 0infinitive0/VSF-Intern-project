import { useEffect, useState } from 'react'

/**
 * RemoteImage — the shared image box with an honest fallback chain (Phase 8;
 * Phase 9 reuses it for place photos). Hotel/room image URLs are external and
 * can 404 or be null, so every slot renders exactly one of three states:
 *
 *   loading      → shimmer block (the project's shimmer-block utility)
 *   error / null → neutral Material icon centred in the same box — the
 *                  placeholder pattern hotel-option-card.tsx had pre-Phase-8,
 *                  promoted to shared so no screen hand-rolls its own fallback
 *   success      → the image, object-cover, with a descriptive alt
 *
 * The design runs an infinite `vSheen` light-sweep over its photo boxes;
 * dropped here on request across every caller (no `sheen` prop anymore).
 */
export default function RemoteImage({
  src,
  alt,
  className = '',
  icon = 'hotel',
}: {
  src?: string | null
  alt: string
  className?: string
  icon?: string
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
      {status === 'loading' && <div className="shimmer-block absolute inset-0" aria-hidden="true" />}
      <img
        src={src ?? undefined}
        alt={alt}
        className="w-full h-full object-cover"
        loading="lazy"
        onLoad={() => setStatus('ok')}
        onError={() => setStatus('error')}
      />
    </div>
  )
}
