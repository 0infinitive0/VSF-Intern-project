/**
 * strings.js — every user-facing Vietnamese string in one place.
 * This is the i18n seam: a bilingual retrofit becomes a translation task, not a sweep.
 * No component should hardcode a string in JSX.
 */

export const S = {
  // Header
  appTitle: 'VSF Trip Planner',
  appSubtitle: 'Chat để lên kế hoạch chuyến đi — gợi ý khách sạn, lịch trình',

  // Composer
  composerPlaceholder: 'Nhập tin nhắn... (vd: Tôi muốn đi Đà Nẵng 3 ngày 2 người)',
  sendBtn: 'Gửi',
  newChatBtn: '+ Hội thoại mới',
  newChatConfirm: 'Bắt đầu hội thoại mới? Cuộc trò chuyện hiện tại sẽ bị xóa.',

  // Greetings / empty states
  greeting: 'Xin chào! Bạn muốn đi đâu, trong bao lâu, và đi cùng bao nhiêu người?',
  itineraryEmptyTitle: 'Lịch trình của bạn',
  itineraryEmptyBody: 'Lịch trình sẽ hiển thị ở đây sau khi bạn chọn khách sạn.',

  // Pending / spinner
  pendingDefault: 'Đang xử lý...',
  pendingSearchingHotels: 'Đang tìm khách sạn phù hợp...',
  pendingBuildingPlan: 'Đang lên lịch trình — thường mất 30–60 giây...',
  elapsedSuffix: 'giây',

  // Itinerary panel
  itineraryTitle: 'Lịch trình dự kiến',
  hotelLabel: 'Khách sạn',
  hotelStars: (n) => '★'.repeat(n),
  dayLabel: (n) => `Ngày ${n}`,
  adjustmentsLabel: 'Điều chỉnh',
  statusLabel: (s) => `Trạng thái: ${s}`,

  // Hotel card
  hotelRooms: 'Phòng gợi ý',
  hotelAverageNightly: (price, currency) => `${price} ${currency}/đêm`,
  hotelTotalStay: (nights, price, currency) => `Tổng ${nights} đêm: ${price} ${currency}`,
  hotelPickBtn: 'Chọn khách sạn này',

  // Errors
  errorPrefix: 'Lỗi: ',
  errorNetwork: (msg) => `Lỗi kết nối: ${msg}`,
  errorStage: 'SYSTEM ERROR',

  // Reset
  resetTitle: 'Tạo lại từ đầu',

  // Map panel (placeholder — no map integration yet)
  mapPlaceholderTitle: 'Bản đồ lộ trình',
  mapPlaceholderBody: 'Tính năng bản đồ đang được phát triển.',
}
