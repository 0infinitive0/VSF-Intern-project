import { useRef, useState } from 'react'
import { uploadHotelImage } from '../../api/hotels-client'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'

interface HotelTabImagesProps {
  hotelId: string
  images: string[]
  onChange: (next: string[]) => void
}

const MAX_IMAGES = 50

function isHttpUrl(value: string): boolean {
  return (value.startsWith('http://') || value.startsWith('https://')) && value.length <= 2048
}

/** hotel-tab-images.tsx -- B3's "Hình ảnh" tab (phase-09-hotel-edit.md,
 * L38). `images` is a flat URL array on `hotels` -- no direct DB write here;
 * this only edits the local array, saved through the ordinary tab-level
 * PATCH like every other field. A pasted URL is added straight to the
 * array; an uploaded file goes to the `hotel-images` Storage bucket first
 * (upload_hotel_image, backend/src/api/admin/hotels.py) and the public URL
 * it returns is added the same way -- one array, two ways to add to it. */
export function HotelTabImages({ hotelId, images, onChange }: HotelTabImagesProps) {
  const [draftUrl, setDraftUrl] = useState('')
  const [urlError, setUrlError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
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

  async function handleFileSelected(file: File) {
    setUploadError(null)
    if (atLimit) {
      setUploadError(`Đã đạt tối đa ${MAX_IMAGES} ảnh.`)
      return
    }
    setUploading(true)
    const result = await uploadHotelImage(hotelId, file)
    setUploading(false)
    if (!result.ok) {
      setUploadError(result.detail)
      return
    }
    if (!images.includes(result.data.url)) onChange([...images, result.data.url])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Banner tone="info">Ảnh dưới 5MB, định dạng JPEG/PNG/WebP. Có thể tải file lên hoặc dán URL ảnh có sẵn.</Banner>

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
          <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()} disabled={uploading || atLimit}>
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
        // minmax(0, 1fr), not 1fr: a bare `1fr` track still won't shrink
        // below its content's intrinsic width (grid's `min-width: auto`
        // default), so the long Storage/OTA URL below forced every column
        // -- and the whole card -- wider than its container instead of
        // ellipsizing.
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
          {images.map((url) => (
            <div key={url} style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
              <img
                src={url}
                alt=""
                style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 10, border: '1px solid var(--stroke)' }}
                onError={(e) => {
                  e.currentTarget.style.display = 'none'
                }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--t4)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                    minWidth: 0,
                  }}
                >
                  {url}
                </span>
                <Button variant="ghost" size="sm" onClick={() => removeUrl(url)}>
                  Xoá
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
