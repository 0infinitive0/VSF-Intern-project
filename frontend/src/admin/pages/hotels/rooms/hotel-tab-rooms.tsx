import { useEffect, useState } from 'react'
import { listRoomFacilities, listRooms, type AmenityOption, type RoomRow } from '../../../api/hotels-client'
import { Banner } from '../../../ui/banner'
import { Button } from '../../../ui/button'
import { DataTable, type DataTableColumn } from '../../../ui/data-table'
import { Money } from '../../../ui/money'
import { Pagination } from '../../../ui/pagination'
import { RoomDrawer } from './room-drawer'
import { RoomReembedDialog } from './room-reembed-dialog'
import { RoomsEmpty } from './rooms-empty'
import { roomPricesPath } from '../../../lib/room-prices-path'

const PAGE_SIZE = 25

interface HotelTabRoomsProps {
  hotelId: string
  hotelName: string
  navigate: (to: string) => void
  /** Bumped by the parent whenever a room write should re-trigger the
   * hotel's own `room_count`/embedding-badge refresh (hotel-detail-page.tsx
   * re-fetches `GET /hotels/{id}` on this). */
  onRoomsChanged: () => void
}

/** hotel-tab-rooms.tsx -- B5 (phase-10-rooms.md), the `Phòng` tab inside B3.
 * Owns its own fetch (not lifted into hotel-detail-page.tsx's state) since
 * rooms are a different resource/lifecycle than the hotel-level tabs
 * (Cơ bản/Vị trí/...), each with its own save button and no cross-tab dirty
 * state to track. */
export function HotelTabRooms({ hotelId, hotelName, navigate, onRoomsChanged }: HotelTabRoomsProps) {
  const [rooms, setRooms] = useState<RoomRow[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [facilityCatalog, setFacilityCatalog] = useState<AmenityOption[]>([])
  const [page, setPage] = useState(1)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingRoom, setEditingRoom] = useState<RoomRow | null>(null)
  const [reembedOpen, setReembedOpen] = useState(false)
  const [ragFieldsChanged, setRagFieldsChanged] = useState<string[]>([])

  function reload() {
    listRooms(hotelId).then((result) => {
      if (result.ok) setRooms(result.data.items)
      else setLoadError(result.detail)
    })
  }

  useEffect(() => {
    setRooms(null)
    setLoadError(null)
    setPage(1)
    reload()
    listRoomFacilities().then((result) => {
      if (result.ok) setFacilityCatalog(result.data)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotelId])

  function openCreate() {
    setEditingRoom(null)
    setDrawerOpen(true)
  }

  function openEdit(room: RoomRow) {
    setEditingRoom(room)
    setDrawerOpen(true)
  }

  function handleSaved(changed: string[]) {
    setDrawerOpen(false)
    reload()
    onRoomsChanged()
    if (changed.length > 0) {
      setRagFieldsChanged(changed)
      setReembedOpen(true)
    }
  }

  function handleDeleted() {
    setDrawerOpen(false)
    setPage(1)
    reload()
    onRoomsChanged()
  }

  if (loadError) {
    return <Banner tone="err">{loadError}</Banner>
  }

  if (rooms === null) {
    return <div style={{ fontSize: 12.5, color: 'var(--t4)' }}>Đang tải…</div>
  }

  const viewSuggestions = Array.from(new Set(rooms.map((r) => r.view).filter((v): v is string => !!v))).sort()
  const pageRooms = rooms.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const columns: DataTableColumn<RoomRow>[] = [
    { key: 'name', header: 'TÊN PHÒNG', render: (row) => <span style={{ fontWeight: 600 }}>{row.name}</span> },
    { key: 'max_guests', header: 'SỨC CHỨA', render: (row) => (row.max_guests != null ? `${row.max_guests} khách` : '—') },
    { key: 'bed', header: 'GIƯỜNG', render: (row) => row.bed_description ?? '—' },
    { key: 'size', header: 'DIỆN TÍCH', render: (row) => (row.room_size_sqm != null ? `${row.room_size_sqm} m²` : '—') },
    { key: 'facilities', header: 'TIỆN NGHI', render: (row) => `${row.facility_count} tiện nghi` },
    {
      key: 'images',
      header: 'ẢNH',
      render: (row) =>
        row.image_count === 0 ? (
          <span style={{ color: 'var(--warn-ink)', fontWeight: 600 }}>Chưa có ảnh</span>
        ) : (
          <span style={{ color: 'var(--t2)' }}>{row.image_count} ảnh</span>
        ),
    },
    {
      key: 'price',
      header: 'GIÁ THẤP NHẤT',
      render: (row) =>
        row.lowest_price_30d != null ? (
          <Money value={Number(row.lowest_price_30d)} />
        ) : (
          <span style={{ color: 'var(--warn-ink)' }}>Chưa có giá</span>
        ),
    },
    {
      key: 'actions',
      header: 'THAO TÁC',
      align: 'right',
      render: (row) => (
        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <Button variant="secondary" size="sm" onClick={() => navigate(roomPricesPath(hotelId, row.id))}>
            Giá theo ngày
          </Button>
          <Button variant="secondary" size="sm" onClick={() => openEdit(row)}>
            Sửa
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button variant="primary" size="sm" onClick={openCreate}>
          + Thêm phòng
        </Button>
      </div>

      {rooms.length === 0 ? (
        <RoomsEmpty onAddRoom={openCreate} />
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <DataTable columns={columns} rows={pageRooms} rowKey={(row) => row.id} />
          </div>
          {rooms.length > PAGE_SIZE && <Pagination page={page} pageSize={PAGE_SIZE} total={rooms.length} onPageChange={setPage} />}
          <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>
            Giá thấp nhất tính trên bảng giá theo ngày trong 30 ngày tới.
          </div>
        </>
      )}

      <RoomDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        hotelId={hotelId}
        hotelName={hotelName}
        room={editingRoom}
        facilityCatalog={facilityCatalog}
        viewSuggestions={viewSuggestions}
        onSaved={handleSaved}
        onDeleted={handleDeleted}
      />

      <RoomReembedDialog open={reembedOpen} onClose={() => setReembedOpen(false)} hotelId={hotelId} ragFieldsChanged={ragFieldsChanged} />
    </div>
  )
}
