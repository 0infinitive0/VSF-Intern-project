import type { HotelRow } from '../../api/hotels-client'

interface HotelEmbeddingDotProps {
  embeddingState: HotelRow['embedding_state']
  roomCount: number
  roomsMissingEmbedding: number
}

/** hotel-embedding-dot.tsx — EMBEDDING column, 3 states (L23 mitigation:
 * both hotels.embedding and rooms.embedding affect search, so "embedded"
 * (green) only lights up when neither is missing anything). Tooltip is a
 * native `title` -- no tooltip primitive exists in ui/ yet and one dot per
 * row doesn't justify adding one. */
export function HotelEmbeddingDot({ embeddingState, roomCount, roomsMissingEmbedding }: HotelEmbeddingDotProps) {
  if (embeddingState === 'embedded') {
    return (
      <span className="embedding-dot" title="Khách sạn đã embed">
        <span className="embedding-dot__mark embedding-dot__mark--ok" />
        <span className="embedding-dot__label embedding-dot__label--ok">Đã embed</span>
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
