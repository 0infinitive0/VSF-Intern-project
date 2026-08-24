import { Banner } from '../../ui/banner'

interface HotelTabNearbyProps {
  nearbyAttractions: unknown
  nearbyEssentials: unknown
}

function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <div style={{ fontSize: 12.5, color: 'var(--t4)' }}>Không có dữ liệu.</div>
  }
  return (
    <pre
      style={{
        fontSize: 11.5,
        lineHeight: 1.5,
        background: 'var(--fill)',
        borderRadius: 10,
        padding: 12,
        overflowX: 'auto',
        margin: 0,
      }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

/** hotel-tab-nearby.tsx -- B3's "Lân cận" tab (phase-09-hotel-edit.md, L38).
 * Read-only: `nearby_attractions`/`nearby_essentials` are JSONB with a
 * different shape per source (Agoda vs. Booking, per database_schema.sql's
 * own comment on these columns) -- editing them safely needs a
 * source-aware form this phase doesn't build. Rendered as raw JSON so an
 * admin can still see what's there. */
export function HotelTabNearby({ nearbyAttractions, nearbyEssentials }: HotelTabNearbyProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Banner tone="info">
        Chỉ đọc — cấu trúc dữ liệu khác nhau giữa Agoda và Booking, chỉnh sửa chưa được hỗ trợ ở đây.
      </Banner>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span className="field-label">Địa điểm lân cận (nearby_attractions)</span>
        <JsonBlock value={nearbyAttractions} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span className="field-label">Tiện ích xung quanh (nearby_essentials)</span>
        <JsonBlock value={nearbyEssentials} />
      </div>
    </div>
  )
}
