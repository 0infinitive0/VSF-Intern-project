/** Shared by admin-app.tsx's route matcher and hotel-tab-rooms.tsx's `Giá
 * theo ngày` button (B6, phase-11-room-prices.md), so the two never drift
 * apart on the URL shape. */
export function roomPricesPath(hotelId: string, roomId: string): string {
  return `/admin/hotels/${hotelId}/rooms/${roomId}/prices`
}
