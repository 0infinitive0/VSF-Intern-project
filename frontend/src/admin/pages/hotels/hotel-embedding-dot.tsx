import type { HotelRow } from '../../api/hotels-client'

interface HotelEmbeddingDotProps {
  embeddingState: HotelRow['embedding_state']
  roomCount: number
  roomsMissingEmbedding: number
  roomsStaleEmbedding?: number
}

/** hotel-embedding-dot.tsx — EMBEDDING column, 4 states (L23 mitigation:
 * both hotels.embedding and rooms.embedding affect search, so "embedded"
 * (green) only lights up when neither is missing anything). "stale" is the
 * fourth: the vector exists and the bot still finds the hotel, but a RAG
 * field was edited after that vector was built
 * (backend/scripts/migrations/20260827_add_embedding_stale.sql) — a distinct
 * signal from "Chưa embed", where the bot cannot find the hotel at all.
 * Tooltip is a native `title` -- no tooltip primitive exists in ui/ yet and
 * one dot per row doesn't justify adding one. */
export function HotelEmbeddingDot({
  embeddingState,
  roomCount,
  roomsMissingEmbedding,
  roomsStaleEmbedding = 0,
}: HotelEmbeddingDotProps) {
  if (embeddingState === 'embedded') {
    return (
      <span className="embedding-dot" title="Khách sạn đã embed">
        <span className="embedding-dot__mark embedding-dot__mark--ok" />
        <span className="embedding-dot__label embedding-dot__label--ok">Đã embed</span>
      </span>
    )
  }

  if (embeddingState === 'stale') {
    // Rooms-only staleness gets its own tooltip for the same reason
    // "partial" does: the hotel row itself is fine, so "nội dung khách sạn
    // đã đổi" would point the admin at the wrong record.
    const tooltip =
      roomsStaleEmbedding > 0
        ? `Đã có embedding nhưng nội dung đã thay đổi · ${roomsStaleEmbedding}/${roomCount} phòng cần chạy lại`
        : 'Đã có embedding nhưng nội dung khách sạn đã thay đổi sau lần embed cuối — bot vẫn trả lời theo nội dung cũ'
    return (
      <span className="embedding-dot" title={tooltip}>
        <span className="embedding-dot__mark embedding-dot__mark--stale" />
        <span className="embedding-dot__label embedding-dot__label--stale">Cần chạy lại embedding</span>
      </span>
    )
  }

  const label = embeddingState === 'partial' ? 'Thiếu embedding' : 'Chưa embed'
  const tooltip =
    embeddingState === 'partial'
      ? `Khách sạn đã embed · ${roomsMissingEmbedding}/${roomCount} phòng chưa embed`
      : 'Khách sạn chưa embed'

  return (
    <span className="embedding-dot" title={tooltip}>
      <span className="embedding-dot__mark embedding-dot__mark--warn" />
      <span className="embedding-dot__label embedding-dot__label--warn">{label}</span>
    </span>
  )
}
