/**
 * strings.js — every user-facing Vietnamese string in one place.
 * This is the i18n seam: a bilingual retrofit becomes a translation task, not a sweep.
 * No component should hardcode a string in JSX.
 */

export const S = {
  // Top nav — English by design: these are the brand wordmark and inert nav-tab
  // labels, not part of the Vietnamese user-facing conversation flow below.
  navBrand: 'V-OTA AI',
  navExplorer: 'Explorer',
  navTrips: 'Trips',
  navConcierge: 'Concierge',

  // Chat panel header
  chatPanelTitle: 'AI Assistant',
  chatPanelMoreHint: 'Tùy chọn (chưa hỗ trợ)',
  chatPanelExpandHint: 'Toàn màn hình (chưa hỗ trợ)',

  // Composer
  composerPlaceholder: 'Nhập tin nhắn...',
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
  hotelStars: (n: number) => '★'.repeat(n),
  dayLabel: (n: number) => `Ngày ${n}`,
  adjustmentsLabel: 'Điều chỉnh',
  statusLabel: (s: string) => `Trạng thái: ${s}`,
  itineraryTabLabel: 'Lịch trình',
  ideasTabLabel: 'Gợi ý',
  bookingsTabLabel: 'Đặt chỗ',
  addDayLabel: 'Thêm ngày (chưa hỗ trợ)',
  guestsAdultsSuffix: 'người lớn',

  // Activity kind badges — the 7 real ItemKind values
  // (src/services/trip_edit_planner.py:31), never a guessed default.
  kindBreakfast: 'Ăn sáng',
  kindLunch: 'Ăn trưa',
  kindDinner: 'Ăn tối',
  kindCoffee: 'Cà phê',
  kindAttraction: 'Tham quan',
  kindRest: 'Nghỉ ngơi',
  kindEvening: 'Buổi tối',

  // Trip parameters card
  tripParamsTitle: 'Thông số chuyến đi',
  tripParamsDatesLabel: 'Ngày đi',
  tripParamsGuestsLabel: 'Số khách',
  tripParamsAdultsSuffix: 'người lớn',

  // Trip Parameters Intake Form — fixed Vietnamese chip options. These mirror the
  // backend closed sets (source of truth — if a label changes there, update here):
  //   src/services/trip_intake.py:30-64 (_PREFERENCE_LABELS / _COMPANION_LABELS /
  //     _PACE_LABELS / _DAY_RHYTHM_LABELS)
  //   src/services/hotel_selection.py:509-531 (_BUDGET_QUESTION labels, exposed via
  //     budget_option_labels())
  intakeDestinationLabel: 'Điểm đến',
  intakeDestinationPlaceholder: 'Chọn điểm đến',
  intakeDatesLabel: 'Ngày đi & thời lượng',
  intakeStartDateLabel: 'Ngày bắt đầu',
  intakeEndDateLabel: 'Ngày kết thúc',
  intakeDatePlaceholder: 'dd/mm/yyyy',
  intakeGuestsLabel: 'Số khách',
  intakeBudgetLabel: 'Ngân sách khách sạn',
  intakeOtherOptionsLabel: 'Tùy chọn khác',
  intakePreferencesLabel: 'Sở thích du lịch',
  intakeCompanionsLabel: 'Đi cùng',
  intakePaceLabel: 'Nhịp độ',
  intakeDayRhythmLabel: 'Nhịp sinh hoạt',
  intakeNotesLabel: 'Nhu cầu khác',
  intakeNotesPlaceholder: 'Ví dụ: cần phòng view biển, ăn chay...',
  intakeNotesCounter: (n: number) => `${n}/1000`,
  intakeSubmit: 'Gửi thông tin',
  intakeRequiredHint: 'Điểm đến, ngày đi và số khách là bắt buộc',
  intakePreferenceOptions: [
    'biển',
    'văn hóa',
    'ẩm thực',
    'thiên nhiên',
    'lịch sử',
    'mua sắm',
    'cuộc sống về đêm',
    'trẻ em',
    'cổ điển',
    'cảnh đô thị',
  ],
  intakeCompanionOptions: [
    'đi một mình',
    'đi cùng gia đình',
    'đi cùng người yêu hoặc vợ chồng',
    'đi cùng bạn bè',
    'có người lớn tuổi trong đoàn',
  ],
  intakePaceOptions: ['dày đặc', 'vừa phải', 'thư thái'],
  intakeDayRhythmOptions: ['bắt đầu sớm', 'về khuya'],

  // Hotel card
  hotelRooms: 'Phòng gợi ý',
  hotelAverageNightly: (price: string, currency: string) => `${price} ${currency}/đêm`,
  hotelTotalStay: (nights: number, price: string, currency: string) =>
    `Tổng ${nights} đêm: ${price} ${currency}`,
  hotelPickBtn: 'Chọn khách sạn này',

  // Errors
  errorPrefix: 'Lỗi: ',
  errorNetwork: (msg: string) => `Lỗi kết nối: ${msg}`,
  errorStage: 'SYSTEM ERROR',

  // Reset
  resetTitle: 'Tạo lại từ đầu',

  // Map panel (placeholder — no map integration yet)
  mapPlaceholderTitle: 'Bản đồ lộ trình',
  mapPlaceholderBody: 'Tính năng bản đồ đang được phát triển.',
  mapControlDisabledHint: 'Tính năng bản đồ đang được phát triển',
  mapFilterAttractions: 'Tham quan',
  mapFilterProperties: 'Khách sạn',
  mapFilterFood: 'Ẩm thực',
  mapFilterShopping: 'Mua sắm',
  mapSearchPlaceholder: 'Tìm khu vực...',
}
