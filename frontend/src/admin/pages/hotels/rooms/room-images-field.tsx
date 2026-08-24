import { useRef, useState } from 'react'
import Lightbox from 'yet-another-react-lightbox'
import 'yet-another-react-lightbox/styles.css'
import { uploadRoomImage } from '../../../api/hotels-client'
import { Banner } from '../../../ui/banner'
import { Button } from '../../../ui/button'
import { Input } from '../../../ui/input'

interface RoomImagesFieldProps {
  images: string[]
  onChange: (next: string[]) => void
  /** null in "Thêm phòng" mode -- upload needs a real room id to namespace
   * the storage path (`POST /rooms/{room_id}/images/upload`), which doesn't
   * exist yet for a room being created. URL paste still works in both
   * modes; only the upload button is gated on this. */
  roomId: string | null
}

const MAX_IMAGES = 50

function isHttpUrl(value: string): boolean {
  return (value.startsWith('http://') || value.startsWith('https://')) && value.length <= 2048
}

/** room-images-field.tsx -- B5 drawer's `Ảnh phòng` field (phase-10-rooms.md,
 * L40). `rooms.images` is a `TEXT[]` of URLs -- most of them the crawler's,
 * but an admin can also add one either way: paste a URL directly, or upload
 * a file to the shared `hotel-images` Storage bucket via
 * `POST /rooms/{room_id}/images/upload` (rooms.py), same two-ways-in-one-array
 * contract as B3's Hình ảnh tab. Clicking a thumbnail opens a full-size
 * preview via `yet-another-react-lightbox` -- the only third-party UI
 * library in this admin portal (every other dialog is the hand-rolled
 * `.overlay`/`.modal` in admin.css), pulled in specifically because a real
 * "click to enlarge" needs viewport-filling layout + next/prev + keyboard
 * nav that `.modal`'s fixed 480px box doesn't give for free. */
export function RoomImagesField({ images, onChange, roomId }: RoomImagesFieldProps) {
  const [draftUrl, setDraftUrl] = useState('')
  const [urlError, setUrlError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const atLimit = images.length >= MAX_IMAGES

  function addUrl() {
    setUrlError(null)
    const url = draftUrl.trim()
    if (!url || images.includes(url)) return
    if (atLimit) {
      setUrlError(`Đã đạt tối đa ${MAX_IMAGES} ảnh.`)
      return
    }
    if (!isHttpUrl(url)) {
      setUrlError('URL phải bắt đầu bằng http:// hoặc https://.')
      return
    }
    onChange([...images, url])
    setDraftUrl('')
  }

  function removeUrl(url: string) {
    onChange(images.filter((existing) => existing !== url))
  }

  function moveUrl(index: number, direction: -1 | 1) {
    const target = index + direction
    if (target < 0 || target >= images.length) return
    const next = [...images]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }

  async function handleFileSelected(file: File) {
    if (!roomId) return
    setUploadError(null)
    if (atLimit) {
      setUploadError(`Đã đạt tối đa ${MAX_IMAGES} ảnh.`)
      return
    }
    setUploading(true)
    const result = await uploadRoomImage(roomId, file)
    setUploading(false)
    if (!result.ok) {
      setUploadError(result.detail)
      return
    }
    if (!images.includes(result.data.url)) onChange([...images, result.data.url])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <span className="field-label">Ảnh phòng</span>
      <Banner tone="info">
        {roomId
          ? 'Ảnh dưới 5MB, định dạng JPEG/PNG/WebP. Có thể tải file lên hoặc dán URL ảnh có sẵn.'
          : 'Lưu phòng trước để tải ảnh lên -- có thể dán URL ảnh có sẵn ngay bây giờ.'}
      </Banner>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) void handleFileSelected(file)
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={!roomId || uploading || atLimit}
          >
            {uploading ? 'Đang tải lên…' : '↑ Tải ảnh lên'}
          </Button>
        </div>
        {uploadError && <Banner tone="err">{uploadError}</Banner>}

        <div style={{ display: 'flex', gap: 8 }}>
          <Input
            placeholder="https://..."
            value={draftUrl}
            disabled={atLimit}
            onChange={(e) => setDraftUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addUrl()
              }
            }}
          />
          <Button variant="secondary" size="sm" onClick={addUrl} disabled={!draftUrl.trim() || atLimit}>
            + Thêm URL
          </Button>
        </div>
        {urlError && <span style={{ fontSize: 11.5, color: 'var(--err)' }}>{urlError}</span>}
      </div>

      {images.length === 0 ? (
        <div style={{ fontSize: 12.5, color: 'var(--t4)' }}>Chưa có ảnh nào.</div>
      ) : (
        // 2 columns, not 3 like B3's Hình ảnh tab -- that grid lives in a
        // 760px-wide card, this one lives in a 480px drawer (admin.css
        // `.drawer`).
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
          {images.map((url, index) => (
            <div key={url} style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
              <img
                src={url}
                alt=""
                style={{
                  width: '100%',
                  height: 96,
                  objectFit: 'cover',
                  borderRadius: 10,
                  border: '1px solid var(--stroke)',
                  cursor: 'zoom-in',
                }}
                onClick={() => setPreviewIndex(index)}
                onError={(e) => {
                  e.currentTarget.style.display = 'none'
                }}
              />
              <span
                style={{
                  fontSize: 11,
                  color: 'var(--t4)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {url}
              </span>
              <div style={{ display: 'flex', gap: 4 }}>
                <Button variant="ghost" size="sm" onClick={() => moveUrl(index, -1)} disabled={index === 0}>
                  ↑
                </Button>
                <Button variant="ghost" size="sm" onClick={() => moveUrl(index, 1)} disabled={index === images.length - 1}>
                  ↓
                </Button>
                <Button variant="ghost" size="sm" onClick={() => removeUrl(url)}>
                  Xoá
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Lightbox
        open={previewIndex !== null}
        index={previewIndex ?? 0}
        close={() => setPreviewIndex(null)}
        slides={images.map((url) => ({ src: url }))}
      />
    </div>
  )
}
