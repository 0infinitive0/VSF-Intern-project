import { useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { formatCurrency } from '../lib/format-currency'
import { hotelPriceBounds, PRICE_SLIDER_STEP, roundedPriceSliderBounds, type HotelSortOrder } from '../lib/hotel-filters'
import type { ActivePreferencePayload, HotelOption } from '../types'

export default function HotelFilterBar({
  hotels, apiPriceMin, apiPriceMax, amenityOptions, minPrice, maxPrice, minStars, preferenceLoading, sortOrder,
  onMinPriceChange, onMaxPriceChange, onMinStarsChange, onPreferenceToggle, onSortOrderChange, onClear,
}: {
  hotels: HotelOption[]
  apiPriceMin: number | null
  apiPriceMax: number | null
  amenityOptions: ActivePreferencePayload[]
  minPrice: number | null
  maxPrice: number | null
  minStars: number | null
  preferenceLoading: boolean
  sortOrder: HotelSortOrder
  onMinPriceChange: (value: number | null) => void
  onMaxPriceChange: (value: number | null) => void
  onMinStarsChange: (value: number | null) => void
  onPreferenceToggle: (id: string, active: boolean) => void
  onSortOrderChange: (value: HotelSortOrder) => void
  onClear: () => void
}) {
  const { t, i18n } = useTranslation()
  const preferenceListRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startScroll: number } | null>(null)
  const didDragRef = useRef(false)
  const [isSortMenuOpen, setIsSortMenuOpen] = useState(false)
  const priceBounds = useMemo(() => hotelPriceBounds(hotels, apiPriceMin, apiPriceMax), [apiPriceMax, apiPriceMin, hotels])
  const sliderBounds = priceBounds ? roundedPriceSliderBounds(priceBounds) : null
  const filtersActive = minPrice != null || maxPrice != null || minStars != null || sortOrder !== 'match'
  const selectedMinPrice = sliderBounds ? minPrice ?? sliderBounds.min : null
  const selectedMaxPrice = sliderBounds ? maxPrice ?? sliderBounds.max : null
  const priceRangeStyle = sliderBounds
    ? {
        '--range-low': `${((selectedMinPrice! - sliderBounds.min) / (sliderBounds.max - sliderBounds.min || 1)) * 100}%`,
        '--range-high': `${((selectedMaxPrice! - sliderBounds.min) / (sliderBounds.max - sliderBounds.min || 1)) * 100}%`,
      } as CSSProperties
    : undefined

  function startPreferenceDrag(event: PointerEvent<HTMLDivElement>) {
    didDragRef.current = false
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startScroll: event.currentTarget.scrollLeft }
  }

  function dragPreferences(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const delta = event.clientX - drag.startX
    if (Math.abs(delta) > 3) didDragRef.current = true
    event.currentTarget.scrollLeft = drag.startScroll - delta
  }

  function stopPreferenceDrag(event: PointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return
    dragRef.current = null
  }

  const sortOptions: { value: HotelSortOrder; label: string }[] = [
    { value: 'match', label: t('hotelFiltersSortMatch') },
    { value: 'priceAsc', label: t('hotelFiltersSortPriceAsc') },
    { value: 'priceDesc', label: t('hotelFiltersSortPriceDesc') },
  ]
  const selectedSortLabel = sortOptions.find((option) => option.value === sortOrder)?.label ?? sortOptions[0].label

  return (
    <section className="glass-card p-3.5" aria-label={t('hotelFiltersLabel')}>
      <div className="flex items-center gap-2 mb-2.5">
        <div className="text-[10px] font-semibold tracking-[0.1em] uppercase text-on-surface-muted">{t('hotelFiltersLabel')}</div>
        {filtersActive && <button type="button" onClick={onClear} className="ml-auto px-2 py-1 rounded-full text-[11px] text-on-surface-variant hover:text-on-surface hover:bg-fill transition-colors">{t('hotelFiltersClear')}</button>}
      </div>
      {sliderBounds && <div className="mb-3" role="group" aria-label={t('hotelFiltersMaxPrice')}>
        <div className="flex justify-between gap-3 text-[11px] text-on-surface-variant">
          <label htmlFor="hotel-min-price">{t('hotelFiltersPriceRange')}</label>
          <output htmlFor="hotel-min-price hotel-max-price">{t('hotelFiltersPriceRangeValue', { min: formatCurrency(selectedMinPrice!, i18n.language), max: formatCurrency(selectedMaxPrice!, i18n.language) })}</output>
        </div>
        <div className="hotel-price-range mt-1.5" style={priceRangeStyle}>
          <input
            id="hotel-min-price"
            aria-label={t('hotelFiltersMinPrice')}
            type="range"
            min={sliderBounds.min}
            max={sliderBounds.max}
            step={PRICE_SLIDER_STEP}
            value={selectedMinPrice!}
            disabled={sliderBounds.min === sliderBounds.max}
            onChange={(event) => {
              const value = Number(event.target.value)
              onMinPriceChange(value <= sliderBounds.min ? null : Math.min(value, selectedMaxPrice!))
            }}
          />
          <input
            id="hotel-max-price"
            aria-label={t('hotelFiltersMaxPrice')}
            type="range"
            min={sliderBounds.min}
            max={sliderBounds.max}
            step={PRICE_SLIDER_STEP}
            value={selectedMaxPrice!}
            disabled={sliderBounds.min === sliderBounds.max}
            onChange={(event) => {
              const value = Number(event.target.value)
              onMaxPriceChange(value >= sliderBounds.max ? null : Math.max(value, selectedMinPrice!))
            }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-on-surface-muted"><span>{formatCurrency(sliderBounds.min, i18n.language)}</span><span>{formatCurrency(sliderBounds.max, i18n.language)}</span></div>
      </div>}
      <div className="flex flex-wrap items-center justify-center gap-2" role="group" aria-label={t('hotelFiltersLabel')}>
        {/* One shared bg-fill container (no nested pill-in-a-pill) — same
            segmented-control language as intake-people-stepper.tsx: the
            selected segment gets a soft raised bg-glass-3 chip + shadow,
            never a solid dark fill, so it doesn't read as a separate block
            sitting next to the small star icons. Both controls in this row
            share one rendered height (34px: the star group's own 28px chips
            + its 3px top/bottom padding, matched by the sort button's
            explicit h-[34px] rather than the plain h-7 it had before —
            those two heights don't naturally agree since only one of the
            two sits inside a padded track) so the text chip and the round
            star buttons line up evenly, and both use the app's real design
            tokens instead of literal hex — the old #2C5FC9/white didn't
            adapt to dark theme (a plain white dropdown surface in dark
            mode). Star fill is one glyph (★) at two opacities rather than
            swapping ★/☆, so all 5 render at identical metrics — mixing the
            two glyphs from a fallback symbol font is what read as uneven. */}
        <div className="flex items-center gap-0.5 rounded-[13px] bg-fill p-[3px]" role="radiogroup" aria-label={t('hotelFiltersMinStars')}>
          <button
            type="button"
            role="radio"
            aria-checked={minStars == null}
            onClick={() => onMinStarsChange(null)}
            className={`h-7 shrink-0 whitespace-nowrap rounded-[10px] px-3 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
              minStars == null
                ? 'bg-glass-3 text-on-surface font-[600] shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6),0_0_0_1px_var(--edge),inset_0_1px_0_var(--gloss)]'
                : 'text-on-surface-variant font-normal hover:text-on-surface'
            }`}
          >
            {t('hotelFiltersAnyRating')}
          </button>
          {[1, 2, 3, 4, 5].map((stars) => (
            <button
              key={stars}
              type="button"
              role="radio"
              aria-checked={minStars === stars}
              aria-label={t('hotelFiltersStarsAndUp', { stars })}
              title={t('hotelFiltersStarsAndUp', { stars })}
              onClick={() => onMinStarsChange(stars)}
              className="grid size-7 shrink-0 place-items-center rounded-[10px] text-[15px] leading-none transition-colors hover:bg-glass-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <span aria-hidden="true" className={minStars != null && stars <= minStars ? 'text-warning' : 'text-on-surface-faint'}>★</span>
            </button>
          ))}
        </div>
        <div className="relative" onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setIsSortMenuOpen(false)
        }}>
          <button
            id="hotel-sort-order"
            type="button"
            aria-haspopup="listbox"
            aria-expanded={isSortMenuOpen}
            onClick={() => setIsSortMenuOpen((open) => !open)}
            className="flex h-[34px] min-w-44 items-center justify-between gap-2.5 rounded-full border border-stroke bg-glass-2 px-3.5 text-[11px] font-[530] text-on-surface transition-colors hover:bg-glass-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <span className="truncate">{selectedSortLabel}</span>
            {/* Material Symbols instead of the raw "⌄" glyph — that character
                doesn't sit centered in its own em-box in most fonts, so
                items-center alone couldn't line it up with the text next to
                it. The icon font (used the same way everywhere else in this
                app) is drawn centered in its box by design. */}
            <span
              className={`material-symbols-outlined shrink-0 text-[16px] text-on-surface-muted transition-transform ${isSortMenuOpen ? 'rotate-180' : ''}`}
              aria-hidden="true"
            >
              expand_more
            </span>
          </button>
          {/* glass-panel's own background (--g1, 60% opacity — meant for large
              surfaces like the chat/header panel, with plenty of blur behind
              them) read as too see-through for a small floating menu with
              arbitrary page content behind it. Inline style to override just
              the background (wins over the utility class at equal
              specificity, same as sidebar-rail.tsx's borderRight) up to
              --g3 (92%), the same "elevated surface" tier hotel-card.tsx
              already uses for hover/selected — keeps the blur/border/shadow
              from glass-panel, only the opacity changes. */}
          {isSortMenuOpen && <div role="listbox" aria-label={t('hotelFiltersSort')} className="glass-panel absolute left-0 z-20 mt-1.5 min-w-full overflow-hidden rounded-[16px] p-1.5" style={{ background: 'var(--g3)' }}>
            {sortOptions.map((option) => {
              const selected = option.value === sortOrder
              return <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onSortOrderChange(option.value)
                  setIsSortMenuOpen(false)
                }}
                // hover:bg-glass-3 used to be invisible here — the panel
                // itself sits at --g3 (see the style={{background}} above),
                // the top of the g0-g3 glass scale, so "hover one tier up"
                // had nowhere left to go and just matched the panel. A soft
                // accent tint reads clearly regardless of the panel's own tier.
                className={`flex w-full items-center rounded-[12px] px-3 py-2 text-left text-[12px] font-[450] transition-colors ${selected ? 'bg-button text-on-button' : 'text-on-surface hover:bg-primary-soft'}`}
              >
                {option.label}
              </button>
            })}
          </div>}
        </div>
      </div>
      {amenityOptions.length > 0 && <div
        ref={preferenceListRef}
        className="hotel-preference-scroll mt-2 flex gap-2 overflow-x-auto pb-1"
        role="group"
        aria-label={t('hotelFiltersPreferences')}
        onPointerDown={startPreferenceDrag}
        onPointerMove={dragPreferences}
        onPointerUp={stopPreferenceDrag}
        onPointerCancel={stopPreferenceDrag}
        onClickCapture={(event) => {
          if (!didDragRef.current) return
          event.preventDefault()
          event.stopPropagation()
          didDragRef.current = false
        }}
      >
        {amenityOptions.map(({ id, label, active, polarity }) => {
          const stateText = active ? 'Đang áp dụng, nhấn để tắt' : 'Đã tắt, nhấn để áp dụng lại'
          const exclusion = polarity === 'exclude'
          return <button key={`${id}-${polarity}`} type="button" disabled={preferenceLoading} aria-pressed={active} aria-label={`${label}: ${stateText}`} onClick={() => onPreferenceToggle(id, !active)} className={`shrink-0 rounded-full border px-3 py-2 text-[12px] transition-colors disabled:cursor-wait disabled:opacity-60 ${!active ? 'border-dashed border-fill2 bg-glass-2 text-on-surface-muted' : exclusion ? 'border-danger/50 bg-danger/10 text-danger' : 'border-primary bg-primary text-on-primary shadow-sm'}`}>{exclusion ? '− ' : !active ? '○ ' : ''}{label}</button>
        })}
      </div>}
    </section>
  )
}
