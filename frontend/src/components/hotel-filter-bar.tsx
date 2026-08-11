import { useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { formatCurrency } from '../lib/format-currency'
import { hotelPriceBounds, PRICE_SLIDER_STEP, roundedPriceSliderBounds, type HotelSortOrder } from '../lib/hotel-filters'
import type { HotelOption, PreferencePayload } from '../types'

export default function HotelFilterBar({
  hotels, apiPriceMin, apiPriceMax, allPreferences, minPrice, maxPrice, minStars, preferenceIds, sortOrder,
  onMinPriceChange, onMaxPriceChange, onMinStarsChange, onPreferenceIdsChange, onSortOrderChange, onClear,
}: {
  hotels: HotelOption[]
  apiPriceMin: number | null
  apiPriceMax: number | null
  allPreferences: PreferencePayload[]
  minPrice: number | null
  maxPrice: number | null
  minStars: number | null
  preferenceIds: string[]
  sortOrder: HotelSortOrder
  onMinPriceChange: (value: number | null) => void
  onMaxPriceChange: (value: number | null) => void
  onMinStarsChange: (value: number | null) => void
  onPreferenceIdsChange: (value: string[]) => void
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
  const filtersActive = minPrice != null || maxPrice != null || minStars != null || preferenceIds.length > 0 || sortOrder !== 'match'
  const selectedMinPrice = sliderBounds ? minPrice ?? sliderBounds.min : null
  const selectedMaxPrice = sliderBounds ? maxPrice ?? sliderBounds.max : null
  const priceRangeStyle = sliderBounds
    ? {
        '--range-low': `${((selectedMinPrice! - sliderBounds.min) / (sliderBounds.max - sliderBounds.min || 1)) * 100}%`,
        '--range-high': `${((selectedMaxPrice! - sliderBounds.min) / (sliderBounds.max - sliderBounds.min || 1)) * 100}%`,
      } as CSSProperties
    : undefined

  function togglePreference(preferenceId: string) {
    onPreferenceIdsChange(preferenceIds.includes(preferenceId) ? preferenceIds.filter((id) => id !== preferenceId) : [...preferenceIds, preferenceId])
  }

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
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('hotelFiltersLabel')}>
        <div className="flex items-center rounded-full border border-fill2 bg-glass-2 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]" role="radiogroup" aria-label={t('hotelFiltersMinStars')}>
          <button
            type="button"
            role="radio"
            aria-checked={minStars == null}
            onClick={() => onMinStarsChange(null)}
            className={`rounded-full px-2.5 py-1.5 text-[11px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2C5FC9] ${minStars == null ? 'bg-[#2C5FC9] text-white shadow-sm' : 'text-on-surface-variant hover:bg-white/70 hover:text-[#2C5FC9]'}`}
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
              className="grid size-7 place-items-center rounded-full text-[17px] leading-none transition-colors hover:bg-[#2C5FC9]/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2C5FC9]"
            >
              <span aria-hidden="true" className={minStars != null && stars <= minStars ? 'text-[#D3812A]' : 'text-on-surface-muted'}>{minStars != null && stars <= minStars ? '★' : '☆'}</span>
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
            className="flex min-w-44 items-center justify-between gap-3 rounded-full border border-fill2 bg-glass-2 px-3.5 py-2 text-[12px] font-medium text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] transition-colors hover:border-[#2C5FC9]/40 hover:bg-white/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2C5FC9]"
          >
            <span>{selectedSortLabel}</span>
            <span aria-hidden="true" className={`text-[#2C5FC9] transition-transform ${isSortMenuOpen ? 'rotate-180' : ''}`}>⌄</span>
          </button>
          {isSortMenuOpen && <div role="listbox" aria-label={t('hotelFiltersSort')} className="absolute left-0 z-20 mt-1.5 min-w-full overflow-hidden rounded-2xl border border-[#2C5FC9]/20 bg-white/95 p-1.5 shadow-[0_14px_32px_rgba(44,95,201,0.18)] backdrop-blur-xl">
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
                className={`flex w-full items-center rounded-xl px-3 py-2 text-left text-[12px] font-medium transition-colors ${selected ? 'bg-[#2C5FC9] text-white shadow-sm' : 'text-on-surface hover:bg-[#2C5FC9]/10 hover:text-[#2C5FC9]'}`}
              >
                {option.label}
              </button>
            })}
          </div>}
        </div>
      </div>
      {allPreferences.length > 0 && <div
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
        {allPreferences.map(({ id, label }) => {
          const active = preferenceIds.includes(id)
          return <button key={id} type="button" aria-pressed={active} onClick={() => togglePreference(id)} className={`shrink-0 rounded-full border px-3 py-2 text-[12px] transition-colors ${active ? 'border-[#2C5FC9] bg-[#2C5FC9] text-white shadow-sm' : 'border-fill2 bg-glass-2 text-on-surface-variant hover:text-on-surface'}`}>{label}</button>
        })}
      </div>}
    </section>
  )
}
