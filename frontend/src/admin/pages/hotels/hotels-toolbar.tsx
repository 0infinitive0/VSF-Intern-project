import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import type { EmbeddingFilter, SourceFilter } from '../../api/hotels-client'

interface HotelsToolbarProps {
  q: string
  onQChange: (q: string) => void
  source: SourceFilter
  onSourceChange: (source: SourceFilter) => void
  isActive: boolean | undefined
  onIsActiveChange: (isActive: boolean | undefined) => void
  embedding: EmbeddingFilter
  onEmbeddingChange: (embedding: EmbeddingFilter) => void
  shownCount: number
  totalCount: number
}

export function HotelsToolbar({
  q,
  onQChange,
  source,
  onSourceChange,
  isActive,
  onIsActiveChange,
  embedding,
  onEmbeddingChange,
  shownCount,
  totalCount,
}: HotelsToolbarProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, minWidth: 220, maxWidth: 320 }}>
        <Input placeholder="⌕ Tên khách sạn hoặc thành phố…" value={q} onChange={(e) => onQChange(e.target.value)} />
      </div>

      <Select value={source} onChange={(e) => onSourceChange(e.target.value as SourceFilter)} style={{ width: 240 }}>
        <option value="all">Nguồn dữ liệu: Tất cả</option>
        <option value="manual">Nguồn dữ liệu: Tự nhập</option>
        <option value="pipeline">Nguồn dữ liệu: Từ pipeline</option>
      </Select>

      <Select
        value={isActive === undefined ? 'all' : String(isActive)}
        onChange={(e) => onIsActiveChange(e.target.value === 'all' ? undefined : e.target.value === 'true')}
        style={{ width: 210 }}
      >
        <option value="all">Đang bán: Tất cả</option>
        <option value="true">Đang bán: Đang bán</option>
        <option value="false">Đang bán: Ngừng bán</option>
      </Select>

      <Select value={embedding} onChange={(e) => onEmbeddingChange(e.target.value as EmbeddingFilter)} style={{ width: 220 }}>
        <option value="all">Embedding: Tất cả</option>
        <option value="embedded">Embedding: Đã embed</option>
        <option value="missing">Embedding: Chưa embed</option>
      </Select>

      <div style={{ flex: 1 }} />

      <span className="tabular-nums" style={{ fontSize: 12.5, color: 'var(--t3)', whiteSpace: 'nowrap' }}>
        Hiển thị {shownCount} / {totalCount} khách sạn
      </span>
    </div>
  )
}
