import { useEffect, useRef, useState } from 'react'
import { deleteRoomPrices, getRoomPrices, setRoomPrices, type RangeRow, type RoomPricesResponse } from '../../../api/hotels-client'
import { PageHeader } from '../../../layout/page-header'
import { Banner } from '../../../ui/banner'
import { Button } from '../../../ui/button'
import { Tabs } from '../../../ui/tabs'
import { PriceCalendar } from './price-calendar'
import { PriceRangeDialog } from './price-range-dialog'
import { PriceRangeTable } from './price-range-table'
import { PriceSetPanel } from './price-set-panel'

interface RoomPricesPageProps {
  hotelId: string
  roomId: string
  navigate: (to: string) => void
}

type LoadState = { status: 'loading' } | { status: 'error'; detail: string } | { status: 'ok' }

/** Local calendar date, not UTC -- `toISOString()` reads the UTC clock, so
 * anywhere east of UTC (Asia/Ho_Chi_Minh is UTC+7) it still reports
 * yesterday's date for the first few hours after local midnight, letting an
 * already-elapsed night stay selectable as "today". */
function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function monthStartFrom(anchor: string): string {
  return `${anchor.slice(0, 7)}-01`
}

function shiftMonth(monthStart: string, delta: number): string {
  const [y, m] = monthStart.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1 + delta, 1))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-01`
}

function monthEndExclusive(monthStart: string): string {
  return shiftMonth(monthStart, 1)
}

function monthLabel(monthStart: string): string {
  const [y, m] = monthStart.split('-').map(Number)
  return `Tháng ${m} · ${y}`
}

/**
 * room-prices-page.tsx — B6 (phase-11-room-prices.md). Both view modes
 * (Lịch tháng / Bảng khoảng ngày) render the SAME GET response for the
 * displayed month -- `ranges[]` is already merged server-side (module's own
 * docstring: same algorithm regardless of which view renders it), so
 * switching tabs never re-fetches or re-derives anything, just changes
 * which component reads the already-loaded `nights`/`ranges`.
 *
 * Never shows anything embedding-related (success criterion in the plan):
 * `room_prices` has no `embedding` column, unlike B3/B5's RAG-field dialogs.
 */
export function RoomPricesPage({ hotelId, roomId, navigate }: RoomPricesPageProps) {
  const today = todayIso()
  const [month, setMonth] = useState(() => monthStartFrom(today))
  const [viewMode, setViewMode] = useState<'calendar' | 'range'>('calendar')
  const [data, setData] = useState<RoomPricesResponse | null>(null)
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })

  const [selectedDates, setSelectedDates] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [justSavedDates, setJustSavedDates] = useState<Set<string>>(new Set())

  const [rangeDialogOpen, setRangeDialogOpen] = useState(false)
  const [editingRange, setEditingRange] = useState<RangeRow | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // Tracks the latest `month` synchronously (updated every render, ahead of
  // any effect) so an in-flight `reload()`'s `.then` can tell whether it's
  // still the newest request -- comparing against the `month` captured in
  // its own closure would always read that same render's value and never
  // detect staleness.
  const latestMonthRef = useRef(month)
  latestMonthRef.current = month

  function reload() {
    setLoadState({ status: 'loading' })
    const requestedMonth = month
    getRoomPrices(roomId, requestedMonth, monthEndExclusive(requestedMonth)).then((result) => {
      if (requestedMonth !== latestMonthRef.current) return
      if (result.ok) {
        setData(result.data)
        setLoadState({ status: 'ok' })
      } else {
        setLoadState({ status: 'error', detail: result.detail })
      }
    })
  }

  useEffect(() => {
    reload()
    setSelectedDates(new Set())
    setJustSavedDates(new Set())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, month])

  async function applyPrices(dates: string[], price: string, soldOut: boolean, currency?: string) {
    if (!data) return
    setSaving(true)
    setSaveError(null)
    const result = await setRoomPrices(roomId, { dates, price, currency: currency ?? data.currency, sold_out: soldOut })
    setSaving(false)
    if (!result.ok) {
      setSaveError(result.detail)
      return
    }
    setSelectedDates(new Set())
    setJustSavedDates(new Set(dates))
    setRangeDialogOpen(false)
    setEditingRange(null)
    reload()
  }

  async function handleDeleteRange(range: RangeRow) {
    setDeleteError(null)
    const result = await deleteRoomPrices(roomId, range.from, range.to)
    if (!result.ok) {
      setDeleteError(result.detail)
      return
    }
    reload()
  }

  if (loadState.status === 'loading' && !data) {
    return <div style={{ flex: 1, padding: 28 }} />
  }

  if (loadState.status === 'error' || !data) {
    return (
      <div style={{ flex: 1, padding: 28 }}>
        <Banner tone="err">{loadState.status === 'error' ? loadState.detail : 'Không tải được giá phòng.'}</Banner>
      </div>
    )
  }

  const missingCount = new Set(data.nights.map((n) => n.date)).size
  const daysInThisMonth = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)).getUTCDate()
  const nightsMissingPrice = daysInThisMonth - missingCount

  return (
    <>
      <PageHeader
        breadcrumb={`Quản trị · Khách sạn · ${data.hotel_name} · Phòng · ${data.room_name}`}
        title={`Giá phòng theo ngày · ${data.room_name}`}
        action={
          <Button variant="secondary" size="sm" onClick={() => navigate(`/admin/hotels/${hotelId}`)}>
            ‹ Quay lại phòng
          </Button>
        }
      />

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '14px 28px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {!data.is_manual && (
            <Banner tone="warn">
              Giá của khách sạn này do pipeline OTA quản lý — chạy lại pipeline sẽ ghi đè giá bạn vừa nhập.
            </Banner>
          )}
          {saveError && <Banner tone="err">{saveError}</Banner>}
          {deleteError && <Banner tone="err">{deleteError}</Banner>}

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Button variant="ghost" size="sm" onClick={() => setMonth((m) => shiftMonth(m, -1))}>
                ‹
              </Button>
              <div style={{ fontWeight: 600, minWidth: 120, textAlign: 'center' }}>{monthLabel(month)}</div>
              <Button variant="ghost" size="sm" onClick={() => setMonth((m) => shiftMonth(m, 1))}>
                ›
              </Button>
            </div>
            <Tabs
              items={[
                { key: 'calendar', label: 'Lịch tháng' },
                { key: 'range', label: 'Bảng khoảng ngày' },
              ]}
              activeKey={viewMode}
              onChange={(key) => setViewMode(key as 'calendar' | 'range')}
            />
          </div>

          {nightsMissingPrice > 0 && (
            <div style={{ fontSize: 11.5, color: 'var(--warn-ink)' }}>
              {nightsMissingPrice} đêm trong tháng chưa có giá — khách không đặt được các đêm này.
            </div>
          )}
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 22, display: 'flex', gap: 16 }}>
          {viewMode === 'calendar' ? (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <PriceCalendar monthStart={month} nights={data.nights} selectedDates={selectedDates} onSelectionChange={setSelectedDates} todayIso={today} />
              </div>
              {selectedDates.size > 0 && (
                <div style={{ width: 300, flex: 'none' }}>
                  <PriceSetPanel
                    selectedDates={[...selectedDates]}
                    nights={data.nights}
                    currency={data.currency}
                    saving={saving}
                    todayIso={today}
                    onCancel={() => setSelectedDates(new Set())}
                    onApply={applyPrices}
                  />
                </div>
              )}
            </>
          ) : (
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: 600 }}>Bảng giá theo khoảng ngày</div>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    setEditingRange(null)
                    setRangeDialogOpen(true)
                  }}
                >
                  + Thêm khoảng ngày
                </Button>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <PriceRangeTable
                  ranges={data.ranges}
                  nights={data.nights}
                  justSavedDates={justSavedDates}
                  onEdit={(range) => {
                    setEditingRange(range)
                    setRangeDialogOpen(true)
                  }}
                  onDelete={handleDeleteRange}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <PriceRangeDialog
        open={rangeDialogOpen}
        editingRange={editingRange}
        defaultCurrency={data.currency}
        todayIso={today}
        saving={saving}
        onClose={() => {
          setRangeDialogOpen(false)
          setEditingRange(null)
        }}
        onSubmit={applyPrices}
      />
    </>
  )
}
