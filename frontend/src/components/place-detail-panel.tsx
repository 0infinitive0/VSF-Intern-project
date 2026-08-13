import { useTranslation } from 'react-i18next'
import RemoteImage from './remote-image'
import { useAttractionDetail } from '../hooks/use-attraction-detail'
import { formatCurrency } from '../lib/format-currency'
import { stripSeconds } from '../lib/item-duration'
import { kindAccent } from '../lib/map-colors'
import type { Leg } from '../lib/leg'
import type { AttractionDetail } from '../types'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

const SECTION_EYEBROW =
  'text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted mb-[9px]'

/**
 * PlaceDetailPanel — the Place Detail Focus Mode surface (PlaceDetail.dc.html),
 * a real flex sibling of the workspace split view (itinerary | map | detail),
 * not a modal. Shares the chat/hotel glass surface (glass-panel).
 *
 * Data contract: the detail body comes only from `GET /attractions/{id}` via
 * useAttractionDetail (per-session cache); the hero badge's day number, the
 * context time, the kind accent and the travel-info block are NOT on that
 * endpoint — they are the timeline item's context, passed in by the caller.
 *
 * Sections deliberately absent (phase-09 §Place Detail Focus Mode / plan.md
 * "Phần chưa làm" #5-#7, #20): the "AI đề xuất vì…" block (match_reasons only
 * exist for hotels), top reviews (no review content in the DB), nearby places
 * (no neighbourhood relation), and facilities chips (attractions have no
 * amenities column).
 *
 * Ticket price keeps 0 and null distinct (phase-09): adult 0 → "Miễn phí";
 * null → the line is hidden entirely, never "0 ₫".
 */
export default function PlaceDetailPanel({
  placeId,
  name,
  kind,
  dayNumber,
  startTime,
  routeLeg,
  onClose,
}: {
  placeId: string
  name: string
  kind?: string | null
  dayNumber: number
  startTime: string | null
  routeLeg: Leg
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const { detail, status } = useAttractionDetail(placeId)
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language), { maximumFractionDigits: 1 })

  const displayName = detail?.name ?? name
  const heroSrc = detail?.images?.[0]
  const accent = kindAccent(kind)
  const kindLabel = kind
    ? t(`kind${kind[0]?.toUpperCase() ?? ''}${kind.slice(1)}`, { defaultValue: kind })
    : ''
  // Day + time come from the timeline item, never from the detail endpoint —
  // null start_time → only "Ngày N", no invented hour (phase-09).
  const dayContext = startTime
    ? `${t('dayLabel', { n: dayNumber })} · ${stripSeconds(startTime)}`
    : t('dayLabel', { n: dayNumber })

  // Adult and child fares are reported independently — 0 → "Miễn phí" for
  // that fare, null → that fare is hidden. A known child fare must never be
  // dropped just because the adult fare happens to be free (review finding
  // M1), and an unknown adult fare must never be inferred as free from the
  // child fare alone — that would invent a number the backend never sent.
  function ticketValue(d: AttractionDetail): string | null {
    const a = d.ticket_price_adult
    const c = d.ticket_price_child
    const parts: string[] = []
    // Both fares showing at once needs a label — two bare currency amounts
    // otherwise read as one ambiguous number (review finding M1).
    const bothShown = a != null && c != null
    if (a != null) {
      const value = a === 0 ? t('placeTicketFree') : formatCurrency(a, i18n.language)
      parts.push(bothShown ? `${t('placeTicketAdult')} ${value}` : value)
    }
    if (c != null) {
      const value = c === 0 ? t('placeTicketFree') : formatCurrency(c, i18n.language)
      parts.push(bothShown ? `${t('placeTicketChild')} ${value}` : value)
    }
    return parts.length > 0 ? parts.join(' · ') : null
  }

  function buildFacts(d: AttractionDetail): { label: string; value: string }[] {
    const cells: { label: string; value: string }[] = []
    if (d.category) cells.push({ label: t('placeFactCategory'), value: d.category })
    if (d.opening_time || d.closing_time) {
      cells.push({
        label: t('placeFactHours'),
        value: [d.opening_time, d.closing_time].filter((x): x is string => Boolean(x)).join(' – '),
      })
    }
    if (d.estimated_duration_minutes != null) {
      cells.push({
        label: t('placeFactDuration'),
        value: t('placeFactDurationValue', { mins: numFmt.format(d.estimated_duration_minutes) }),
      })
    }
    const ticket = ticketValue(d)
    if (ticket) cells.push({ label: t('placeFactTicket'), value: ticket })
    return cells
  }

  const facts = detail ? buildFacts(detail) : []

  // Travel-info row: the leg INTO this item, i.e. the previous item's
  // route_to_next (phase-09). First-of-day and route-null/crow-fly hide the
  // whole row — never empty cells.
  function buildRouteCells(): { label: string; value: string }[] {
    if (routeLeg.kind === 'route') {
      const cells: { label: string; value: string }[] = []
      if (routeLeg.profile) {
        const vehicle = t(`routeProfile.${routeLeg.profile}`, { defaultValue: '' })
        if (vehicle) cells.push({ label: t('placeRouteVehicle'), value: vehicle })
      }
      cells.push({ label: t('placeRouteDistance'), value: t('legDistanceKm', { km: numFmt.format(routeLeg.distanceKm) }) })
      cells.push({ label: t('placeRouteDuration'), value: t('legDurationMins', { mins: numFmt.format(routeLeg.durationMins) }) })
      return cells
    }
    if (routeLeg.kind === 'same-place') {
      return [{ label: t('placeRouteNote'), value: t('legSamePlace') }]
    }
    return []
  }

  const routeCells = buildRouteCells()

  if (status === 'error') {
    return (
      <div className="flex-none w-[430px] max-w-full min-w-0 animate-[vRise_0.6s_cubic-bezier(0.22,1,0.36,1)_both]">
        <div className="glass-panel h-full rounded-[26px] flex flex-col items-center justify-center gap-3 p-8 text-center">
          <span className="material-symbols-outlined text-4xl text-on-surface-faint" aria-hidden="true">
            attractions
          </span>
          <div className="text-sm text-on-surface-variant max-w-[260px]">{t('placeDetailNoInfo')}</div>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-[13px] border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] cursor-pointer hover:bg-glass-3"
          >
            {t('placeDetailCloseLabel')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-none w-[430px] max-w-full min-w-0 animate-[vRise_0.6s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="glass-panel relative h-full overflow-y-auto custom-scrollbar rounded-[26px]">
        {/* Hero — 250px, vHero reveal, bottom fade, close ✕ */}
        <div className="relative h-[250px] overflow-hidden animate-[vHero_0.9s_cubic-bezier(0.22,1,0.36,1)_both]">
          <RemoteImage
            src={heroSrc}
            alt={t('placeImgAlt', { name: displayName })}
            className="absolute inset-0"
            icon="attractions"
          />
          <div
            className="absolute inset-x-0 bottom-0 h-[120px] pointer-events-none"
            style={{ background: 'linear-gradient(to top, var(--g3), transparent)' }}
            aria-hidden="true"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label={t('placeDetailCloseLabel')}
            className="absolute top-4 right-4 w-[34px] h-[34px] rounded-full border border-edge text-on-surface text-[14px] cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92]"
            style={{
              background: 'var(--g3)',
              backdropFilter: 'blur(18px)',
              WebkitBackdropFilter: 'blur(18px)',
              boxShadow: '0 10px 24px -10px rgb(var(--shadow-rgb) / 0.5)',
            }}
          >
            ✕
          </button>
          <div className="absolute left-5 bottom-4 right-[70px]">
            <div className="flex items-center gap-2 mb-1.5">
              {kindLabel && (
                <div
                  className="text-[10px] font-[590] tracking-[0.1em] uppercase text-on-primary px-[9px] py-[3px] rounded-full"
                  style={{ background: accent }}
                >
                  {kindLabel}
                </div>
              )}
              <div className="text-[11px] font-[530] text-on-surface-variant px-[9px] py-[3px] rounded-full bg-glass-3">
                {dayContext}
              </div>
            </div>
            <div className="text-[26px] font-[590] tracking-[-0.9px] leading-[1.1] text-on-surface">
              {displayName}
            </div>
          </div>
        </div>

        <div className="px-5 pt-[18px] pb-[22px] flex flex-col gap-4">
          {/* Info row — rating + review count, then real facts. No divider when
              either side is empty. */}
          {(detail?.rating != null || facts.length > 0) && (
            <div className="flex items-center gap-4 flex-wrap">
              {detail?.rating != null && (
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[19px] font-[590] tracking-[-0.5px] text-on-surface">
                    {numFmt.format(detail.rating)}
                  </span>
                  {detail.review_count != null && (
                    <span className="text-[11px] font-[450] text-on-surface-muted">
                      {t('placeReviewCount', { count: numFmt.format(detail.review_count) })}
                    </span>
                  )}
                </div>
              )}
              {detail?.rating != null && facts.length > 0 && (
                <div className="w-px h-[22px] bg-stroke" aria-hidden="true" />
              )}
              {facts.map((f) => (
                <div key={f.label}>
                  <div className={SECTION_EYEBROW + ' mb-[3px]'}>{f.label}</div>
                  <div className="text-[13px] font-[530] tracking-[-0.12px] text-on-surface">{f.value}</div>
                </div>
              ))}
            </div>
          )}

          {detail?.description && (
            <div className="text-[14px] leading-[1.6] tracking-[-0.08px] text-on-surface-variant text-pretty">
              {detail.description}
            </div>
          )}

          {/* Travel-info cells — only when a real route (or same-place) exists */}
          {routeCells.length > 0 && (
            <div className="flex gap-[10px]">
              {routeCells.map((r) => (
                <div key={r.label} className="flex-1 p-[12px] px-[13px] rounded-[18px] bg-glass-2 border border-edge">
                  <div className={SECTION_EYEBROW + ' mb-[3px]'}>{r.label}</div>
                  <div className="text-[15px] font-[590] tracking-[-0.3px] text-on-surface">{r.value}</div>
                </div>
              ))}
            </div>
          )}

          {/* Gallery — up to all images, 3-col grid, vFade stagger */}
          {detail?.images && detail.images.length > 0 && (
            <div>
              <div className={SECTION_EYEBROW}>{t('placeGallery')}</div>
              <div className="grid grid-cols-3 gap-[9px]">
                {detail.images.map((url, i) => (
                  <div key={url} style={{ animation: `vFade .5s ${i * 90}ms ease both` }}>
                    <RemoteImage
                      src={url}
                      alt={t('placeImgAlt', { name: displayName })}
                      className="h-[92px] rounded-[16px]"
                      icon="attractions"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
