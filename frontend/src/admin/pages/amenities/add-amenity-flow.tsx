import { useState } from 'react'
import { checkDuplicateAmenities, draftAmenities, type AmenityCatalogRow, type FlaggedName } from '../../api/amenity-catalog-client'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Drawer } from '../../ui/drawer'
import { Modal } from '../../ui/modal'
import { Textarea } from '../../ui/textarea'

interface AddAmenityFlowProps {
  open: boolean
  onClose: () => void
  scope: 'hotel' | 'room'
  onDrafted: (items: AmenityCatalogRow[]) => void
}

type Step = { kind: 'names' } | { kind: 'pick'; parsed: string[]; exact: FlaggedName[]; flagged: FlaggedName[]; acknowledged: Set<string> }

/** One row in Bước 1.5's pick list. `tone="exact"` (score >=0.85) reads
 * visibly stronger than `tone="flagged"` (0.55-0.85, --warn) -- err-toned
 * badge and border -- since it's the higher-confidence warning, even though
 * both are equally overridable (an admin who's certain it's not a duplicate
 * confirms either the same way, via "Tạo mới"). */
function MatchRow({
  match,
  tone,
  acknowledged,
  onToggle,
}: {
  match: FlaggedName
  tone: 'exact' | 'flagged'
  acknowledged: boolean
  onToggle: (next: boolean) => void
}) {
  const background = tone === 'exact' ? 'var(--err-soft)' : 'var(--warn-soft)'
  const accent = tone === 'exact' ? 'var(--err)' : 'var(--warn-ink)'
  return (
    <div
      style={{
        border: `1px solid ${tone === 'exact' ? 'var(--err)' : 'var(--stroke)'}`,
        background,
        borderRadius: 12,
        padding: '10px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 10.5,
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: 999,
              background: accent,
              color: 'var(--btn-fg)',
              whiteSpace: 'nowrap',
            }}
          >
            Trùng {Math.round(match.score * 100)}%
          </span>
          <div style={{ fontSize: 13, fontWeight: 600 }}>&quot;{match.name}&quot;</div>
        </div>
        <div style={{ fontSize: 11.5, color: accent, marginTop: 2 }}>Giống &quot;{match.closest.label_vi}&quot; đã có trong danh mục</div>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        <button type="button" className={acknowledged ? 'btn btn--secondary btn--sm' : 'btn btn--primary btn--sm'} onClick={() => onToggle(false)}>
          Bỏ qua
        </button>
        <button type="button" className={acknowledged ? 'btn btn--primary btn--sm' : 'btn btn--secondary btn--sm'} onClick={() => onToggle(true)}>
          Tạo mới
        </button>
      </div>
    </div>
  )
}

/** add-amenity-flow.tsx -- Bước 1 + Bước 1.5 of "+ Thêm tiện ích"
 * (phase-18-amenity-catalog.md): one free-text box, then a per-name
 * pick-and-choose dialog for anything scored 0.55-0.85 against the live
 * catalog (decision #8 -- not a batch-level yes/no). Bước 2 (the drafted
 * items' review list) is owned by the parent page via `onDrafted`, since it
 * is its own Drawer and this component never has both open at once. */
export function AddAmenityFlow({ open, onClose, scope, onDrafted }: AddAmenityFlowProps) {
  const [text, setText] = useState('')
  const [step, setStep] = useState<Step>({ kind: 'names' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setText('')
    setStep({ kind: 'names' })
    setSubmitting(false)
    setError(null)
  }

  function handleClose() {
    reset()
    onClose()
  }

  async function submitDraft(names: string[], acknowledge: string[]) {
    setSubmitting(true)
    setError(null)
    const result = await draftAmenities({ names, scope, acknowledge })
    setSubmitting(false)
    if (!result.ok) {
      setError(result.detail)
      return
    }
    if (result.data.items.length === 0) {
      // Every name resolved to an exact match (always skipped, no override)
      // or a flagged match the admin didn't acknowledge -- nothing was
      // created. Say so instead of silently opening an empty review drawer.
      setError('Không có tiện ích nào được tạo — tất cả tên đã trùng với mục có sẵn.')
      return
    }
    onDrafted(result.data.items)
    reset()
    onClose()
  }

  async function handleNamesContinue() {
    if (text.trim() === '') return
    setSubmitting(true)
    setError(null)
    const result = await checkDuplicateAmenities({ text, scope })
    setSubmitting(false)
    if (!result.ok) {
      setError(result.detail)
      return
    }
    if (result.data.exact.length > 0 || result.data.flagged.length > 0) {
      setStep({ kind: 'pick', parsed: result.data.parsed, exact: result.data.exact, flagged: result.data.flagged, acknowledged: new Set() })
      return
    }
    await submitDraft(result.data.parsed, [])
  }

  if (!open) return null

  if (step.kind === 'pick') {
    const clearNames = step.parsed.filter((name) => !step.flagged.some((f) => f.name === name) && !step.exact.some((f) => f.name === name))
    return (
      <Modal open={open} onClose={handleClose}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {step.parsed.length} tên bạn nhập, {step.exact.length + step.flagged.length} tên có thể đã có
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>Chọn từng tên: giữ mục đã có trong danh mục, hoặc vẫn tạo tên mới.</div>
          </div>

          {error && <Banner tone="err">{error}</Banner>}

          {step.exact.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {step.exact.map((match) => (
                <MatchRow
                  key={match.name}
                  match={match}
                  tone="exact"
                  acknowledged={step.acknowledged.has(match.name)}
                  onToggle={(next) =>
                    setStep((prev) => {
                      if (prev.kind !== 'pick') return prev
                      const acknowledged = new Set(prev.acknowledged)
                      if (next) acknowledged.add(match.name)
                      else acknowledged.delete(match.name)
                      return { ...prev, acknowledged }
                    })
                  }
                />
              ))}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {step.flagged.map((match) => (
              <MatchRow
                key={match.name}
                match={match}
                tone="flagged"
                acknowledged={step.acknowledged.has(match.name)}
                onToggle={(next) =>
                  setStep((prev) => {
                    if (prev.kind !== 'pick') return prev
                    const acknowledged = new Set(prev.acknowledged)
                    if (next) acknowledged.add(match.name)
                    else acknowledged.delete(match.name)
                    return { ...prev, acknowledged }
                  })
                }
              />
            ))}
          </div>

          {clearNames.length > 0 && (
            <div style={{ fontSize: 12, color: 'var(--t2)', background: 'var(--fill)', borderRadius: 10, padding: '10px 12px' }}>
              {clearNames.length} tên còn lại — {clearNames.map((n) => `"${n}"`).join(', ')} — không giống mục nào đã có, sẽ được tạo bình thường.
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button variant="secondary" size="sm" onClick={handleClose} disabled={submitting}>
              Huỷ
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={submitting}
              onClick={() => submitDraft(step.parsed, Array.from(step.acknowledged))}
            >
              {submitting ? 'Đang tạo…' : 'Tiếp tục'}
            </Button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Drawer open={open} onClose={handleClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Thêm tiện ích</div>
            <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>Bước 1 / 2 · AI sẽ tự điền phần còn lại</div>
          </div>
          <Button variant="ghost" size="sm" onClick={handleClose} aria-label="Đóng">
            ✕
          </Button>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {error && <Banner tone="err">{error}</Banner>}
          <Textarea
            label="Tên tiện ích"
            rows={5}
            placeholder="Xông hơi, Bồn sục, Phòng gym 24/7"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <span style={{ fontSize: 11.5, color: 'var(--t3)', lineHeight: 1.5 }}>
            Tiếng Việt hoặc tiếng Anh, một hoặc nhiều tên cùng lúc — cách nhau bằng dấu phẩy hoặc xuống dòng. Không cần điền nhóm, phạm vi hay từ khoá; AI
            sẽ đề xuất ở bước sau để bạn duyệt.
          </span>
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', borderTop: '1px solid var(--stroke)', paddingTop: 12 }}>
          <Button variant="secondary" size="sm" onClick={handleClose} disabled={submitting}>
            Huỷ
          </Button>
          <Button variant="primary" size="sm" onClick={handleNamesContinue} disabled={submitting || text.trim() === ''}>
            {submitting ? 'Đang kiểm tra…' : 'Tiếp tục'}
          </Button>
        </div>
      </div>
    </Drawer>
  )
}
