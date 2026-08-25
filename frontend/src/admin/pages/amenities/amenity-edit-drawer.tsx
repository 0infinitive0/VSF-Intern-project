import { useEffect, useState } from 'react'
import { updateAmenity, type AmenityCatalogRow, type UpdateAmenityRequest } from '../../api/amenity-catalog-client'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Drawer } from '../../ui/drawer'
import { AmenityFormFields, formFromRow, type AmenityFormState } from './amenity-form-fields'

interface AmenityEditDrawerProps {
  open: boolean
  onClose: () => void
  row: AmenityCatalogRow | null
  parentOptions: AmenityCatalogRow[]
  onSaved: () => void
}

function diff(row: AmenityCatalogRow, form: AmenityFormState): UpdateAmenityRequest {
  const body: UpdateAmenityRequest = {}
  if (form.labelVi !== row.label_vi) body.label_vi = form.labelVi
  if (form.labelEn !== row.label_en) body.label_en = form.labelEn
  if (form.scope !== row.scope) body.scope = form.scope
  if (form.category !== row.category) body.category = form.category
  if (JSON.stringify([...form.keywords].sort()) !== JSON.stringify([...row.match_keywords].sort())) body.match_keywords = form.keywords
  const nextParentId = form.parentId || null
  if (nextParentId !== (row.parent_id ?? null)) body.parent_id = nextParentId
  return body
}

/** amenity-edit-drawer.tsx -- "Sửa" on an already-approved row
 * (phase-18-amenity-catalog.md). Submits directly on "Lưu", same immediate-
 * submit posture as room-drawer.tsx -- no unsaved-bar state for a single
 * catalog row. `id`/`is_approved`/`retired_at` are never part of the form:
 * the backend PATCH endpoint doesn't accept them either (G3/G9). */
export function AmenityEditDrawer({ open, onClose, row, parentOptions, onSaved }: AmenityEditDrawerProps) {
  const [form, setForm] = useState<AmenityFormState | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open && row) {
      setForm(formFromRow(row))
      setError(null)
    }
  }, [open, row])

  if (!open || !row || !form) return null

  async function handleSave() {
    if (!row || !form) return
    if (form.labelVi.trim() === '' || form.labelEn.trim() === '') {
      setError('Tên tiếng Việt và tiếng Anh là bắt buộc.')
      return
    }
    const body = diff(row, form)
    if (Object.keys(body).length === 0) {
      onClose()
      return
    }
    setSaving(true)
    setError(null)
    const result = await updateAmenity(row.id, body)
    setSaving(false)
    if (!result.ok) {
      setError(result.detail)
      return
    }
    onSaved()
  }

  return (
    <Drawer open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Sửa tiện ích</div>
            <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>{row.label_vi}</div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Đóng">
            ✕
          </Button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {error && <Banner tone="err">{error}</Banner>}
          <AmenityFormFields value={form} onChange={setForm} parentOptions={parentOptions.filter((o) => o.id !== row.id)} idPreview={row.id} />
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', borderTop: '1px solid var(--stroke)', paddingTop: 12 }}>
          <Button variant="secondary" size="sm" onClick={onClose} disabled={saving}>
            Huỷ
          </Button>
          <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Đang lưu…' : 'Lưu'}
          </Button>
        </div>
      </div>
    </Drawer>
  )
}
