import { useTranslation } from 'react-i18next'
import type { CSSProperties } from 'react'
import type { MapStyleKind } from '../hooks/use-mapbox-map'

// Same circular glass icon-button formula as HotelDetailPanel/PlaceDetailPanel's
// close ✕ — no new visual vocabulary introduced for map chrome.
const BUTTON_CLASS =
  'w-[34px] h-[34px] rounded-full border border-edge text-on-surface flex items-center justify-center cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92]'
const BUTTON_STYLE: CSSProperties = {
  background: 'var(--g3)',
  backdropFilter: 'blur(18px)',
  WebkitBackdropFilter: 'blur(18px)',
  boxShadow: '0 10px 24px -10px rgb(var(--shadow-rgb) / 0.5)',
}

function ControlButton({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label} className={BUTTON_CLASS} style={BUTTON_STYLE}>
      <span className="material-symbols-outlined text-[17px]" aria-hidden="true">
        {icon}
      </span>
    </button>
  )
}

/**
 * MapControls — minimal floating glass button column (Phase 10.5 §12): zoom
 * in/out, fit route, current location (only rendered when the browser
 * exposes geolocation — `onLocate` is left undefined otherwise, never a
 * fabricated "you are here"), and a map/satellite style toggle. All the
 * imperative work (map.zoomIn(), fitBounds, flyTo) lives in MapView, which
 * owns `mapRef` — this component is purely presentational.
 */
export default function MapControls({
  onZoomIn,
  onZoomOut,
  onFitRoute,
  onLocate,
  styleKind,
  onToggleStyle,
  showSuggested,
  onToggleSuggested,
  className,
}: {
  onZoomIn: () => void
  onZoomOut: () => void
  onFitRoute: () => void
  /** Absent (not just a no-op) when `'geolocation' in navigator` is false. */
  onLocate?: () => void
  styleKind: MapStyleKind
  onToggleStyle: () => void
  /** Current visibility of the chatbot-suggested place pins. Absent (not
   * just a no-op) when there is nothing to toggle this turn — same
   * conditional-render convention as `onLocate`. */
  showSuggested?: boolean
  onToggleSuggested?: () => void
  className?: string
}) {
  const { t } = useTranslation()

  return (
    <div className={`flex flex-col gap-2 ${className ?? ''}`}>
      <ControlButton icon="zoom_in" label={t('mapZoomIn')} onClick={onZoomIn} />
      <ControlButton icon="zoom_out" label={t('mapZoomOut')} onClick={onZoomOut} />
      <ControlButton icon="fit_screen" label={t('mapFitRoute')} onClick={onFitRoute} />
      {onLocate && <ControlButton icon="my_location" label={t('mapMyLocation')} onClick={onLocate} />}
      {/* Label/icon show the mode you'll switch TO, matching ThemeToggle's convention. */}
      <ControlButton
        icon={styleKind === 'satellite' ? 'map' : 'satellite_alt'}
        label={styleKind === 'satellite' ? t('mapShowStreets') : t('mapShowSatellite')}
        onClick={onToggleStyle}
      />
      {onToggleSuggested && (
        <ControlButton
          icon={showSuggested ? 'visibility_off' : 'visibility'}
          label={showSuggested ? t('mapHideSuggested') : t('mapShowSuggested')}
          onClick={onToggleSuggested}
        />
      )}
    </div>
  )
}
