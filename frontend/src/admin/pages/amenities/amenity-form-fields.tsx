import { useState } from 'react'
import { AMENITY_CATEGORY_ORDER, categoryLabel } from '../../lib/amenity-categories'
import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import type { AmenityCatalogRow } from '../../api/amenity-catalog-client'
import { AmenityParentPicker } from './amenity-parent-picker'

export interface AmenityFormState {
  labelVi: string
  labelEn: string
  scope: 'hotel' | 'room' | 'both'
  category: string
  keywords: string[]
  parentId: string
}

export function formFromRow(row: AmenityCatalogRow): AmenityFormState {
  return {
    labelVi: row.label_vi,
    labelEn: row.label_en,
    scope: row.scope,
    category: row.category,
    keywords: row.match_keywords,
    parentId: row.parent_id ?? '',
  }
}

interface AmenityFormFieldsProps {
  value: AmenityFormState
  onChange: (next: AmenityFormState) => void
  /** Scope the "Danh mục cha" search runs against -- the active tab
   * ('hotel'/'room'), not `value.scope` (which can be 'both' -- not a
   * value the list endpoint's scope filter accepts). */
  scope: 'hotel' | 'room'
  /** Excluded from "Danh mục cha" results (edit mode) so admin can't
   * hand-pick a self-reference; the multi-hop cycle check still happens
   * server-side (G4). */
  excludeId?: string
  idPreview?: string
}

/** amenity-form-fields.tsx -- shared between amenity-edit-drawer.tsx (Sửa on
 * an approved row) and amenity-draft-card.tsx's expanded state (Bước 2's "Sửa
 * các trường") -- same 5 fields, same validation shape, one form to keep in
 * sync (phase-18-amenity-catalog.md). `Phạm vi` uses <Select> rather than a
 * 3-way segmented control: no segmented primitive exists in ui/ yet and one
 * dropdown doesn't justify adding one (plan's "không sáng tác thành phần
 * mới" rule) -- a documented deviation from the design canvas's mockup. */
export function AmenityFormFields({ value, onChange, scope, excludeId, idPreview }: AmenityFormFieldsProps) {
  const [keywordDraft, setKeywordDraft] = useState('')

  function addKeyword() {
    const cleaned = keywordDraft.trim().toLowerCase()
    if (!cleaned || value.keywords.includes(cleaned) || value.keywords.length >= 8) {
      setKeywordDraft('')
      return
    }
    onChange({ ...value, keywords: [...value.keywords, cleaned] })
    setKeywordDraft('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 10 }}>
        <div style={{ flex: 1 }}>
          <Input label="Tên tiếng Việt" value={value.labelVi} onChange={(e) => onChange({ ...value, labelVi: e.target.value })} />
        </div>
        <div style={{ flex: 1 }}>
          <Input label="Tên tiếng Anh" value={value.labelEn} onChange={(e) => onChange({ ...value, labelEn: e.target.value })} />
        </div>
      </div>
      {idPreview && <span style={{ fontSize: 11, color: 'var(--t4)', fontFamily: 'ui-monospace, monospace' }}>ID: {idPreview}</span>}

      <Select label="Phạm vi" value={value.scope} onChange={(e) => onChange({ ...value, scope: e.target.value as AmenityFormState['scope'] })}>
        <option value="hotel">Khách sạn</option>
        <option value="room">Phòng</option>
        <option value="both">Cả hai</option>
      </Select>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Select label="Nhóm" value={value.category} onChange={(e) => onChange({ ...value, category: e.target.value })}>
          {AMENITY_CATEGORY_ORDER.map((c) => (
            <option key={c} value={c}>
              {categoryLabel(c)}
            </option>
          ))}
        </Select>
        <span style={{ fontSize: 10.5, color: 'var(--t4)' }}>14 nhóm cố định từ cơ sở dữ liệu</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <span className="field-label">Từ khoá liên quan</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {value.keywords.map((keyword) => (
            <button
              key={keyword}
              type="button"
              className="amenity-chip amenity-chip--on"
              onClick={() => onChange({ ...value, keywords: value.keywords.filter((k) => k !== keyword) })}
            >
              {keyword} ✕
            </button>
          ))}
        </div>
        {value.keywords.length < 8 && (
          <div style={{ display: 'flex', gap: 8 }}>
            <Input
              placeholder="Thêm từ khoá…"
              value={keywordDraft}
              onChange={(e) => setKeywordDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addKeyword()
                }
              }}
              maxLength={80}
            />
          </div>
        )}
      </div>

      <AmenityParentPicker value={value.parentId} onChange={(parentId) => onChange({ ...value, parentId })} scope={scope} excludeId={excludeId} />
    </div>
  )
}
