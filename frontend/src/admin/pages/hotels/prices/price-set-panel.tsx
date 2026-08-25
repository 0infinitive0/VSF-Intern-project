import { useState } from 'react'
import type { NightRow } from '../../../api/hotels-client'
import { filterWeekendsOnly, repeatFourWeeks } from '../../../lib/expand-dates'
import { Banner } from '../../../ui/banner'
import { Button } from '../../../ui/button'
import { DateText } from '../../../ui/date-text'
import { Input } from '../../../ui/input'
import { Select } from '../../../ui/select'
import { Switch } from '../../../ui/switch'

interface PriceSetPanelProps {
  selectedDates: string[]
  nights: NightRow[]
  currency: string
  saving: boolean
  todayIso: string
  onCancel: () => void
  onApply: (dates: string[], price: string, soldOut: boolean) => void
}

function formatVnd(value: number): string {
  return new Intl.NumberFormat('vi-VN').format(value)
}

/**
 * price-set-panel.tsx — B6's "Đặt giá cho N ngày đã chọn" panel
 * (phase-11-room-prices.md). `Chỉ T7 & CN` and `Lặp lại 4 tuần` are
 * independent toggles applied in that order (weekend filter first, so a
 * repeat only ever projects the already-weekend-filtered set forward) --
 * the button label always reflects the exact date count `expand-dates.ts`
 * would send, so there is never a surprise between what's shown and what
 * PUT actually writes.
 */
export function PriceSetPanel({ selectedDates, nights, currency, saving, todayIso, onCancel, onApply }: PriceSetPanelProps) {
  const [price, setPrice] = useState('')
  const [soldOut, setSoldOut] = useState(false)
  const [weekendOnly, setWeekendOnly] = useState(false)
  const [repeat4Weeks, setRepeat4Weeks] = useState(false)

  const sorted = [...selectedDates].sort()
  const from = sorted[0]
  const to = sorted[sorted.length - 1]

  const currentPrices = nights.filter((n) => selectedDates.includes(n.date)).map((n) => Number(n.price))
  const priceRangeText =
    currentPrices.length === 0
      ? null
      : Math.min(...currentPrices) === Math.max(...currentPrices)
        ? `${formatVnd(Math.min(...currentPrices))} ${currency === 'VND' ? '₫' : currency}`
        : `${formatVnd(Math.min(...currentPrices))} ${currency === 'VND' ? '₫' : currency} – ${formatVnd(Math.max(...currentPrices))} ${currency === 'VND' ? '₫' : currency}`

  let finalDates = weekendOnly ? filterWeekendsOnly(sorted) : sorted
  if (repeat4Weeks) finalDates = repeatFourWeeks(finalDates, todayIso)

  const priceValue = price.replace(/[^\d]/g, '')
  const canApply = priceValue.length > 0 && finalDates.length > 0 && !saving

  // `sold_out` is checked per-row, not per-night-freshest, at the search
  // and pricing layer -- an admin row with sold_out=true does not exclude
  // a night if an older OTA row for that same night is still sold_out=false
  // (place_details._average_price and match_hotels_with_rooms both filter
  // sold_out BEFORE picking the freshest row, not after). `row_count > 1`
  // is the signal already returned by GET for exactly this: more than one
  // room_prices row exists for that night, i.e. an OTA row likely still
  // coexists alongside whatever this write creates.
  const soldOutMayNotHide = soldOut && selectedDates.some((d) => (nights.find((n) => n.date === d)?.row_count ?? 0) > 1)

  return (
    <div className="price-set-panel">
      <div className="price-set-panel__title">Đặt giá cho {selectedDates.length} ngày đã chọn</div>
      <div className="price-set-panel__subtitle">
        {from === to ? (
          <DateText value={from} />
        ) : (
          <>
            <DateText value={from} /> – <DateText value={to} />
          </>
        )}
      </div>

      <Input
        label="Giá mỗi đêm"
        inputMode="numeric"
        value={priceValue ? formatVnd(Number(priceValue)) : ''}
        onChange={(e) => setPrice(e.target.value)}
        placeholder="1.500.000"
      />
      <Select label="Đơn vị tiền tệ" value={currency} disabled>
        <option value={currency}>{currency}</option>
      </Select>

      {priceRangeText && (
        <div className="price-set-panel__hint">Giá hiện tại của {selectedDates.length} ngày này: {priceRangeText}</div>
      )}

      <div className="price-set-panel__row">
        <Switch checked={soldOut} onChange={setSoldOut} label="Đánh dấu hết phòng" />
        <div>
          <div className="field-label">Đánh dấu hết phòng</div>
          <div className="price-set-panel__hint">Khách không đặt được các ngày này</div>
        </div>
      </div>

      {soldOutMayNotHide && (
        <Banner tone="warn">
          Một số ngày đã chọn có giá từ nguồn khác (pipeline OTA). Đánh dấu hết phòng ở đây chỉ ghi đè dòng của bạn — nếu
          dòng OTA cho ngày đó vẫn còn hiệu lực, khách vẫn có thể thấy phòng còn trống.
        </Banner>
      )}

      <div className="price-set-panel__extra">
        <div className="field-label">Áp dụng thêm cho</div>
        <div className="price-set-panel__toggles">
          <button
            type="button"
            className={weekendOnly ? 'amenity-chip amenity-chip--on' : 'amenity-chip'}
            onClick={() => setWeekendOnly((v) => !v)}
          >
            Chỉ T7 &amp; CN
          </button>
          <button
            type="button"
            className={repeat4Weeks ? 'amenity-chip amenity-chip--on' : 'amenity-chip'}
            onClick={() => setRepeat4Weeks((v) => !v)}
          >
            Lặp lại 4 tuần
          </button>
        </div>
      </div>

      <div className="price-set-panel__note">Ghi đè giá đang có của {finalDates.length} ngày. Các đơn đã đặt trước giữ nguyên giá cũ.</div>

      <div className="price-set-panel__actions">
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          Bỏ chọn
        </Button>
        <Button variant="primary" disabled={!canApply} onClick={() => onApply(finalDates, priceValue, soldOut)}>
          {saving ? 'Đang lưu…' : `Đặt giá ${finalDates.length} ngày`}
        </Button>
      </div>
    </div>
  )
}
