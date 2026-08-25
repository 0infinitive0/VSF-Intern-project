import { useState } from 'react'
import { approveAmenity, deleteAmenity, updateAmenity, type AmenityCatalogRow } from '../../api/amenity-catalog-client'
import { categoryLabel } from '../../lib/amenity-categories'
import { Banner } from '../../ui/banner'
import { AmenityFormFields, formFromRow, type AmenityFormState } from './amenity-form-fields'

interface AmenityDraftCardProps {
  row: AmenityCatalogRow
  parentOptions: AmenityCatalogRow[]
  onApproved: (id: string) => void
  onRejected: (id: string) => void
  disabled: boolean
}

function scopeLabel(scope: AmenityCatalogRow['scope']): string {
  return scope === 'room' ? 'Phòng' : scope === 'both' ? 'Khách sạn · Phòng' : 'Khách sạn'
}

function diff(row: AmenityCatalogRow, form: AmenityFormState) {
  const body: Record<string, unknown> = {}
  if (form.labelVi !== row.label_vi) body.label_vi = form.labelVi
  if (form.labelEn !== row.label_en) body.label_en = form.labelEn
  if (form.scope !== row.scope) body.scope = form.scope
  if (form.category !== row.category) body.category = form.category
  if (JSON.stringify([...form.keywords].sort()) !== JSON.stringify([...row.match_keywords].sort())) body.match_keywords = form.keywords
  const nextParentId = form.parentId || null
  if (nextParentId !== (row.parent_id ?? null)) body.parent_id = nextParentId
  return body
}

/** amenity-draft-card.tsx -- one AI-drafted row in Bước 2's review list
 * (phase-18-amenity-catalog.md). Collapsed by default; "Sửa các trường"
 * expands into the same AmenityFormFields the edit drawer uses. "Duyệt"
 * saves any pending edits first (PATCH), then approves -- admin never
 * duyệt's a field they just changed without it actually landing. */
export function AmenityDraftCard({ row, parentOptions, onApproved, onRejected, disabled }: AmenityDraftCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [form, setForm] = useState<AmenityFormState>(() => formFromRow(row))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleApprove() {
    setBusy(true)
    setError(null)
    const body = diff(row, form)
    if (Object.keys(body).length > 0) {
      const updateResult = await updateAmenity(row.id, body)
      if (!updateResult.ok) {
        setBusy(false)
        setError(updateResult.detail)
        return
      }
    }
    const approveResult = await approveAmenity(row.id)
    setBusy(false)
    if (!approveResult.ok) {
      setError(approveResult.detail)
      return
    }
    onApproved(row.id)
  }

  async function handleReject() {
    setBusy(true)
    setError(null)
    const result = await deleteAmenity(row.id)
    setBusy(false)
    if (!result.ok) {
      setError(result.detail)
      return
    }
    onRejected(row.id)
  }

  const isBusy = busy || disabled

  return (
    <div className={expanded ? 'card amenity-draft-card amenity-draft-card--expanded' : 'card amenity-draft-card'} style={{ padding: expanded ? '14px 16px' : '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{row.label_vi}</div>
          <div style={{ fontSize: 11, color: 'var(--t4)' }}>
            {row.label_en} · {categoryLabel(row.category)} · {scopeLabel(row.scope)} · ID: {row.id}
          </div>
        </div>
        <button type="button" className="btn btn--secondary btn--sm" onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Thu gọn' : 'Sửa các trường'}
        </button>
      </div>

      {error && <Banner tone="err">{error}</Banner>}

      {expanded && <AmenityFormFields value={form} onChange={setForm} parentOptions={parentOptions.filter((o) => o.id !== row.id)} />}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn--danger btn--sm" disabled={isBusy} onClick={handleReject}>
          Từ chối
        </button>
        <button type="button" className="btn btn--primary btn--sm" disabled={isBusy} onClick={handleApprove}>
          Duyệt
        </button>
      </div>
    </div>
  )
}
