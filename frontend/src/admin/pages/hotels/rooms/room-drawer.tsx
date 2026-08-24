import { useEffect, useState } from 'react'
import {
  createRoom,
  deleteRoom,
  updateRoom,
  type AmenityOption,
  type CreateRoomRequest,
  type RoomRow,
  type UpdateRoomRequest,
} from '../../../api/hotels-client'
import { Banner } from '../../../ui/banner'
import { Button } from '../../../ui/button'
import { Drawer } from '../../../ui/drawer'
import { Input } from '../../../ui/input'
import { Modal } from '../../../ui/modal'
import { Select } from '../../../ui/select'
import { Textarea } from '../../../ui/textarea'
import { RagFieldLabel } from '../rag-field-label'
import { RoomImagesField } from './room-images-field'

interface RoomDrawerProps {
  open: boolean
  onClose: () => void
  hotelId: string
  hotelName: string
  /** null = "Thêm phòng" mode; a row = "Sửa phòng" mode. */
  room: RoomRow | null
  facilityCatalog: AmenityOption[]
  /** Distinct `view` values already used by this hotel's other rooms --
   * combobox suggestions for L41 (no global "DISTINCT view" endpoint exists
   * in the plan's API contract, so this reuses data the tab already
   * fetched instead of adding one). */
  viewSuggestions: string[]
  onSaved: (ragFieldsChanged: string[]) => void
  onDeleted: () => void
}

const MAX_GUEST_OPTIONS = Array.from({ length: 10 }, (_, i) => i + 1)

interface FormState {
  name: string
  maxGuests: number | null
  bedDescription: string
  roomSizeSqm: string
  view: string
  facilities: string[]
  images: string[]
}

function formFromRoom(room: RoomRow | null): FormState {
  if (!room) return { name: '', maxGuests: null, bedDescription: '', roomSizeSqm: '', view: '', facilities: [], images: [] }
  return {
    name: room.name,
    maxGuests: room.max_guests ?? null,
    bedDescription: room.bed_description ?? '',
    roomSizeSqm: room.room_size_sqm != null ? String(room.room_size_sqm) : '',
    view: room.view ?? '',
    facilities: room.room_facilities,
    images: room.images,
  }
}

/** room-drawer.tsx -- B5's `Thêm phòng`/`Sửa phòng` drawer (phase-10-rooms.md).
 * Unlike B3's tab-level unsaved-bar pattern, this submits directly on `Lưu
 * phòng` (same immediate-submit posture as hotel-create-page.tsx) -- a
 * per-room drawer has no reason to accumulate cross-tab dirty state. */
export function RoomDrawer({ open, onClose, hotelId, hotelName, room, facilityCatalog, viewSuggestions, onSaved, onDeleted }: RoomDrawerProps) {
  const [form, setForm] = useState<FormState>(() => formFromRoom(room))
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<{ detail: string; count?: number } | null>(null)

  useEffect(() => {
    if (open) {
      setForm(formFromRoom(room))
      setSaveError(null)
      setDeleteError(null)
    }
  }, [open, room])

  if (!open) return null

  const isEdit = room !== null
  const facilitiesById = new Map(facilityCatalog.map((entry) => [entry.id, entry]))

  function toggleFacility(id: string) {
    setForm((prev) => ({
      ...prev,
      facilities: prev.facilities.includes(id) ? prev.facilities.filter((f) => f !== id) : [...prev.facilities, id],
    }))
  }

  async function handleSave() {
    setSaveError(null)
    if (form.name.trim() === '') {
      setSaveError('Tên phòng là bắt buộc.')
      return
    }
    setSaving(true)
    const sizeValue = form.roomSizeSqm.trim() === '' ? null : Number(form.roomSizeSqm)
    const shared = {
      name: form.name.trim(),
      max_guests: form.maxGuests,
      bed_description: form.bedDescription.trim() || null,
      room_size_sqm: sizeValue,
      view: form.view.trim() || null,
      room_facilities: form.facilities,
      images: form.images,
    }

    if (isEdit) {
      const body: UpdateRoomRequest = shared
      const result = await updateRoom(room.id, body)
      setSaving(false)
      if (!result.ok) {
        setSaveError(result.detail)
        return
      }
      onSaved(result.data.rag_fields_changed)
    } else {
      const body: CreateRoomRequest = shared
      const result = await createRoom(hotelId, body)
      setSaving(false)
      if (!result.ok) {
        setSaveError(result.detail)
        return
      }
      // A freshly created room has never been embedded -- always surface the
      // re-embed dialog, same as B2's "mới tạo, chưa embed" contract.
      onSaved(['name'])
    }
  }

  async function handleDelete() {
    if (!room) return
    setDeleting(true)
    setDeleteError(null)
    const result = await deleteRoom(room.id)
    setDeleting(false)
    if (!result.ok) {
      setDeleteConfirmOpen(false)
      setDeleteError({ detail: result.detail, count: result.count })
      return
    }
    onDeleted()
  }

  return (
    <Drawer open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{isEdit ? 'Sửa phòng' : 'Thêm phòng'}</div>
            <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>
              {isEdit ? `${room.name} · ${hotelName}` : hotelName}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Đóng">
            ✕
          </Button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {saveError && <Banner tone="err">{saveError}</Banner>}
          {deleteError && (
            <Banner tone="err">
              {deleteError.count
                ? `Phòng đang có ${deleteError.count} lượt đặt (kể cả đã huỷ) nên không thể xoá. Hãy đặt giá "Hết phòng" cho mọi ngày ở mục Giá theo ngày thay vì xoá.`
                : deleteError.detail}
            </Banner>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <label htmlFor="room-name" className="field-label">
                Tên phòng
              </label>
              <RagFieldLabel />
            </div>
            <Input id="room-name" value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} />
          </div>

          <Select
            id="room-max-guests"
            label="Sức chứa tối đa"
            title="Agoda chỉ tính người lớn, Booking tính tổng khách -- hai nguồn khác ngữ nghĩa, không so sánh trực tiếp liên-nguồn."
            value={form.maxGuests ?? ''}
            onChange={(e) => setForm((prev) => ({ ...prev, maxGuests: e.target.value ? Number(e.target.value) : null }))}
          >
            <option value="">Chưa chọn</option>
            {MAX_GUEST_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>

          <Input
            id="room-size"
            label="Diện tích (m²)"
            type="number"
            min={0}
            value={form.roomSizeSqm}
            onChange={(e) => setForm((prev) => ({ ...prev, roomSizeSqm: e.target.value }))}
          />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <label htmlFor="room-bed" className="field-label">
                Mô tả giường
              </label>
              <RagFieldLabel />
            </div>
            <Textarea
              id="room-bed"
              rows={2}
              value={form.bedDescription}
              onChange={(e) => setForm((prev) => ({ ...prev, bedDescription: e.target.value }))}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <label htmlFor="room-view" className="field-label">
                Hướng nhìn
              </label>
              <RagFieldLabel />
            </div>
            <Input
              id="room-view"
              list="room-view-suggestions"
              value={form.view}
              onChange={(e) => setForm((prev) => ({ ...prev, view: e.target.value }))}
            />
            <datalist id="room-view-suggestions">
              {viewSuggestions.map((v) => (
                <option key={v} value={v} />
              ))}
            </datalist>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="field-label">Tiện nghi phòng</span>
              <RagFieldLabel />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {facilityCatalog.map((entry) => {
                const isOn = form.facilities.includes(entry.id)
                return (
                  <button
                    key={entry.id}
                    type="button"
                    className={isOn ? 'amenity-chip amenity-chip--on' : 'amenity-chip'}
                    onClick={() => toggleFacility(entry.id)}
                  >
                    {isOn ? `✓ ${entry.label_vi}` : entry.label_vi}
                  </button>
                )
              })}
              {form.facilities
                .filter((id) => !facilitiesById.has(id))
                .map((id) => (
                  <button key={id} type="button" className="amenity-chip amenity-chip--on" onClick={() => toggleFacility(id)}>
                    ✓ {id}
                  </button>
                ))}
            </div>
          </div>

          <RoomImagesField
            images={form.images}
            onChange={(next) => setForm((prev) => ({ ...prev, images: next }))}
            roomId={room?.id ?? null}
          />

          {isEdit && (
            <div style={{ borderTop: '1px solid var(--stroke)', paddingTop: 12 }}>
              <Button variant="danger" size="sm" onClick={() => setDeleteConfirmOpen(true)}>
                Xoá phòng
              </Button>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', borderTop: '1px solid var(--stroke)', paddingTop: 12 }}>
          <Button variant="secondary" size="sm" onClick={onClose} disabled={saving}>
            Huỷ
          </Button>
          <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Đang lưu…' : 'Lưu phòng'}
          </Button>
        </div>
      </div>

      <Modal open={deleteConfirmOpen} onClose={() => setDeleteConfirmOpen(false)}>
        <div style={{ fontSize: 15, fontWeight: 600 }}>Xoá {room?.name}?</div>
        <div style={{ fontSize: 13, color: 'var(--t3)' }}>Hành động này không thể hoàn tác.</div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="secondary" size="sm" onClick={() => setDeleteConfirmOpen(false)} disabled={deleting}>
            Huỷ
          </Button>
          <Button variant="danger" size="sm" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Đang xoá…' : 'Xoá phòng'}
          </Button>
        </div>
      </Modal>
    </Drawer>
  )
}
