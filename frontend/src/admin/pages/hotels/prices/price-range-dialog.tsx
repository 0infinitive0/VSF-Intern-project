import { useEffect, useState } from 'react'
import type { RangeRow } from '../../../api/hotels-client'
import { dateRange } from '../../../lib/expand-dates'
import { Button } from '../../../ui/button'
import { Input } from '../../../ui/input'
import { Modal } from '../../../ui/modal'
import { Switch } from '../../../ui/switch'

interface PriceRangeDialogProps {
  open: boolean
  /** `null` = "+ Thêm khoảng ngày" (blank form); a range = "Sửa" (prefilled). */
  editingRange: RangeRow | null
  /** Currency for a brand-new range (no `editingRange` to read one from). */
  defaultCurrency: string
  todayIso: string
  saving: boolean
  onClose: () => void
  onSubmit: (dates: string[], price: string, soldOut: boolean, currency: string) => void
}

/** to-exclusive -> last included night. */
function lastNightInclusive(rangeTo: string): string {
  const d = new Date(rangeTo + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

export function PriceRangeDialog({ open, editingRange, defaultCurrency, todayIso, saving, onClose, onSubmit }: PriceRangeDialogProps) {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [price, setPrice] = useState('')
  const [soldOut, setSoldOut] = useState(false)

  useEffect(() => {
    if (!open) return
    if (editingRange) {
      setFrom(editingRange.from)
      setTo(lastNightInclusive(editingRange.to))
      setPrice(String(Math.trunc(Number(editingRange.price))))
      setSoldOut(editingRange.sold_out)
    } else {
      setFrom('')
      setTo('')
      setPrice('')
      setSoldOut(false)
    }
  }, [open, editingRange])

  if (!open) return null

  const dates = from && to && to >= from ? dateRange(from, to) : []
  const currency = editingRange?.currency ?? defaultCurrency
  const canSubmit = dates.length > 0 && price.trim().length > 0 && !saving

  return (
    <Modal open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: 20, minWidth: 360 }}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>{editingRange ? 'Sửa khoảng ngày' : 'Thêm khoảng ngày'}</div>

        <div style={{ display: 'flex', gap: 10 }}>
          <Input
            label="Từ ngày"
            type="date"
            value={from}
            min={todayIso}
            disabled={!!editingRange}
            onChange={(e) => setFrom(e.target.value)}
          />
          <Input label="Đến ngày" type="date" value={to} min={from || todayIso} onChange={(e) => setTo(e.target.value)} />
        </div>

        <Input label="Giá mỗi đêm" inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value.replace(/[^\d]/g, ''))} placeholder="1500000" />

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Switch checked={soldOut} onChange={setSoldOut} label="Đánh dấu hết phòng" />
          <span className="field-label">Đánh dấu hết phòng</span>
        </div>

        {dates.length > 0 && <div className="price-set-panel__note">Ghi đè giá đang có của {dates.length} đêm. Các đơn đã đặt trước giữ nguyên giá cũ.</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Huỷ
          </Button>
          <Button variant="primary" disabled={!canSubmit} onClick={() => onSubmit(dates, price, soldOut, currency)}>
            {saving ? 'Đang lưu…' : 'Lưu'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
