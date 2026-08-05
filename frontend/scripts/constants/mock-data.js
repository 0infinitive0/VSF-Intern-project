// Mock data — stands in for a real backend (see README: no backend/DB yet,
// see "Current Project Status"). This is the ONE place that should change
// once real hotel/itinerary/history APIs exist; everything else reads it
// through window.VOTA.MockData or the services in scripts/services/.
window.VOTA = window.VOTA || {};

window.VOTA.MockData = {
  hotels: [
    { id: 'h1', name: 'Sóng Xanh Boutique', area: 'Mỹ Khê, Ngũ Hành Sơn', stars: 4, rate: 8.9, reviews: 1284, price: '3,2tr', total: '9,6tr ₫ / 3 đêm', center: '2,4 km', view: 'biển',
      amen: ['Hồ bơi vô cực', 'Bãi biển riêng', 'Ăn sáng buffet', 'Đưa đón sân bay'], match: 96, lat: 16.0561, lng: 108.2452,
      why: ['Vừa đúng 39% ngân sách dành cho lưu trú', 'Đi bộ 4 phút ra biển Mỹ Khê', 'Nằm giữa trục Đà Nẵng – Hội An, tiết kiệm 18 km/ngày', 'Điểm đánh giá cao nhất trong tầm giá'] },
    { id: 'h2', name: 'An Nhiên Riverside', area: 'Bờ tây sông Hàn, Hải Châu', stars: 4, rate: 8.6, reviews: 976, price: '2,4tr', total: '7,2tr ₫ / 3 đêm', center: '0,6 km', view: 'sông Hàn',
      amen: ['Rooftop bar', 'Gym 24h', 'Ăn sáng buffet', 'Thuê xe máy'], match: 91, lat: 16.0673, lng: 108.2233,
      why: ['Rẻ hơn 2,4tr so với ngân sách dự kiến', 'Sát chợ Hàn và Cầu Rồng — đi bộ được buổi tối', 'Thuận tiện cho ngày đi Bà Nà', 'Phòng hướng sông, phù hợp cặp đôi'] },
    { id: 'h3', name: 'Lữ Khách Suites', area: 'Thạch Thang, Hải Châu', stars: 3, rate: 8.2, reviews: 612, price: '1,1tr', total: '3,3tr ₫ / 3 đêm', center: '1,2 km', view: 'thành phố',
      amen: ['Bếp chung', 'Ăn sáng nhẹ', 'Sân thượng', 'Giặt sấy'], match: 84, lat: 16.0625, lng: 108.2140,
      why: ['Tiết kiệm 6,3tr để dồn cho ăn uống và tour', 'Gần các quán ăn địa phương', 'Nhân viên hỗ trợ đặt tour tốt', 'Xa biển hơn — cần taxi 10 phút'] },
    { id: 'h4', name: 'Bãi Rạng Cliff Resort', area: 'Bán đảo Sơn Trà', stars: 5, rate: 9.2, reviews: 438, price: '6,8tr', total: '20,4tr ₫ / 3 đêm', center: '9,8 km', view: 'vịnh',
      amen: ['Villa riêng', 'Spa', '2 nhà hàng', 'Xe điện nội khu'], match: 71, lat: 16.1128, lng: 108.2724,
      why: ['Vượt 83% ngân sách lưu trú của bạn', 'Riêng tư và view vịnh đẹp nhất danh sách', 'Cách trung tâm 25 phút xe', 'Không thuận cho ngày đi Hội An'] }
  ],

  landmarks: [
    { name: 'Cầu Rồng', lat: 16.0614, lng: 108.2270 },
    { name: 'Biển Mỹ Khê', lat: 16.0587, lng: 108.2470 },
    { name: 'Phố cổ Hội An', lat: 15.8770, lng: 108.3268 },
    { name: 'Sân bay Đà Nẵng', lat: 16.0439, lng: 108.1994 }
  ],

  dayHooks: {
    2: { st: '07:00', sl: 'Đi bộ · 0,4 km · 5 phút', et: '19:40', el: 'Taxi · 3,4 km · 11 phút' },
    3: { st: '06:40', sl: 'Ô tô · 28,6 km · 55 phút', et: '20:40', el: 'Taxi · 2,8 km · 9 phút' },
    4: { st: '08:00', sl: 'Ô tô · 15,2 km · 24 phút' }
  },

  convos: [
    { id: 'c1', title: 'Đà Nẵng – Hội An 4N3Đ', date: 'Hôm nay', status: 'Draft' },
    { id: 'c2', title: 'Đà Nẵng – Bà Nà 3N2Đ', date: '28/07/2026', status: 'Completed', snap: { phase: 'workspace', hotel: 'h2', tab: 'overview' } },
    { id: 'c3', title: 'Hội An nghỉ dưỡng 5N4Đ', date: '19/07/2026', status: 'Draft', snap: { phase: 'hotels', hotel: null, tab: 'overview' } },
    { id: 'c4', title: 'Đà Nẵng gia đình 4N3Đ', date: '02/07/2026', status: 'Completed', snap: { phase: 'workspace', hotel: 'h4', tab: 'day2' } }
  ],

  convoChat: {
    c2: [['ai', 'Chuyến này bạn muốn tập trung vào Bà Nà và nghỉ dưỡng đúng không?'], ['user', 'Đúng, 3 ngày 2 đêm, 2 người, 18 triệu'], ['ai', 'Mình đã chốt An Nhiên Riverside và dựng lịch trình 3 ngày quanh khách sạn này.']],
    c3: [['ai', 'Bạn muốn nghỉ dưỡng ở Hội An 5 ngày, ngân sách 40 triệu — mình đã tìm được vài khách sạn.'], ['user', 'Cho mình xem thêm chỗ gần biển An Bàng'], ['ai', 'Đây là danh sách đề xuất, bạn chọn giúp mình một khách sạn để dựng lịch trình nhé.']],
    c4: [['ai', 'Chuyến gia đình 4 người, có trẻ nhỏ nên mình ưu tiên di chuyển ngắn.'], ['user', 'Ok, chọn resort có hồ bơi'], ['ai', 'Mình đã dùng Bãi Rạng Cliff Resort làm điểm đi và về mỗi ngày.']]
  },

  searchLabels: ['Phân tích điểm đến', 'Phân tích ngân sách', 'Tìm khách sạn phù hợp', 'Đánh giá vị trí', 'Tính khoảng cách tới các điểm tham quan', 'Chuẩn bị đề xuất'],
  optLabels: ['Đang lựa chọn điểm tham quan', 'Đang tính khoảng cách', 'Đang tối ưu tuyến đường', 'Đang xây dựng lịch trình theo từng ngày'],

  days: [
    { n: 1, label: 'N1', title: 'Ngày 1 · Chạm Đà Nẵng', sub: '12/09 · 18,4 km · sông Hàn về đêm', items: [
      { id: 'd1a', time: '13:40', kind: 'Di chuyển', name: 'Sân bay Đà Nẵng (DAD)', note: 'Đón xe riêng đã đặt trước tại cửa ga đến.', meta: '30 phút · 320k ₫', lat: 16.0439, lng: 108.1994, leg: 'Ô tô riêng · 6,4 km · 14 phút' },
      { id: 'd1b', time: '14:30', kind: 'Khách sạn', name: 'Sóng Xanh Boutique, Mỹ Khê', note: 'Nhận phòng đôi hướng biển, nghỉ ngơi 1 tiếng.', meta: '3 đêm · 9,6tr ₫', lat: 16.0561, lng: 108.2452, leg: 'Đi bộ · 0,3 km · 4 phút' },
      { id: 'd1c', time: '16:30', kind: 'Tham quan', name: 'Bãi biển Mỹ Khê', note: 'Tắm biển chiều, nước êm nhất trong khung 16–18h.', meta: '1,5 giờ · miễn phí', lat: 16.0587, lng: 108.2470, leg: 'Taxi · 3,1 km · 10 phút' },
      { id: 'd1d', time: '18:30', kind: 'Ăn uống', name: 'Bánh xèo – nem lụi Bà Dưỡng', note: 'Quán trong hẻm, đông sau 19h — nên đến sớm.', meta: '1 giờ · 260k ₫/2 người', lat: 16.0470, lng: 108.2210, leg: 'Taxi · 2,2 km · 8 phút' },
      { id: 'd1e', time: '20:30', kind: 'Tham quan', name: 'Cầu Rồng & bờ tây sông Hàn', note: 'Cuối tuần rồng phun lửa lúc 21h — đứng phía bờ đông.', meta: '1 giờ · miễn phí', lat: 16.0614, lng: 108.2270, leg: null }
    ]},
    { n: 2, label: 'N2', title: 'Ngày 2 · Sơn Trà & biển', sub: '13/09 · 31,2 km · nhiều điểm ngắm cảnh', items: [
      { id: 'd2a', time: '07:30', kind: 'Ăn uống', name: 'Mì Quảng sáng gần khách sạn', note: 'Bữa sáng nhanh trước khi lên bán đảo.', meta: '45 phút · 120k ₫', lat: 16.0552, lng: 108.2418, leg: 'Ô tô · 9,8 km · 22 phút' },
      { id: 'd2b', time: '08:45', kind: 'Tham quan', name: 'Chùa Linh Ứng – Bãi Bụt', note: 'Tượng Quan Âm 67m, view toàn vịnh Đà Nẵng.', meta: '1,5 giờ · miễn phí', lat: 16.1000, lng: 108.2777, leg: 'Ô tô · 4,6 km · 15 phút' },
      { id: 'd2c', time: '10:45', kind: 'Tham quan', name: 'Đỉnh Bàn Cờ', note: 'Đường dốc — đi ô tô, tránh xe máy nếu trời mưa.', meta: '1 giờ · miễn phí', lat: 16.1183, lng: 108.2900, leg: 'Ô tô · 12,4 km · 28 phút' },
      { id: 'd2d', time: '12:30', kind: 'Ăn uống', name: 'Hải sản Bãi Rạng', note: 'Ăn trưa sát biển, gọi ghẹ và mực một nắng.', meta: '1,5 giờ · 620k ₫', lat: 16.1128, lng: 108.2724, leg: 'Ô tô · 11,9 km · 26 phút' },
      { id: 'd2e', time: '16:00', kind: 'Tham quan', name: 'Công viên APEC & bờ sông', note: 'Chiều mát dạo bộ, cà phê tầng thượng ngắm cầu.', meta: '2 giờ · 180k ₫', lat: 16.0619, lng: 108.2231, leg: null }
    ]},
    { n: 3, label: 'N3', title: 'Ngày 3 · Bà Nà & núi mây', sub: '14/09 · 62,0 km · trọn ngày trên núi', items: [
      { id: 'd3a', time: '07:00', kind: 'Di chuyển', name: 'Khởi hành đi Bà Nà', note: 'Đi sớm để lên cáp treo trước 9h, tránh đông.', meta: '1 giờ · 450k ₫', lat: 16.0561, lng: 108.2452, leg: 'Ô tô · 28,6 km · 55 phút' },
      { id: 'd3b', time: '08:30', kind: 'Tham quan', name: 'Cầu Vàng, Bà Nà Hills', note: 'Chụp ảnh trước 10h khi mây chưa dày và ít người.', meta: '2 giờ · vé 900k ₫/người', lat: 15.9950, lng: 107.9963, leg: 'Đi bộ · 0,6 km · 10 phút' },
      { id: 'd3c', time: '12:00', kind: 'Ăn uống', name: 'Buffet Làng Pháp', note: 'Đã gồm trong vé combo, nên ăn trước 12:30.', meta: '1 giờ · đã bao gồm', lat: 15.9958, lng: 107.9945, leg: 'Đi bộ · 0,4 km · 7 phút' },
      { id: 'd3d', time: '14:00', kind: 'Tham quan', name: 'Vườn hoa Le Jardin & hầm rượu', note: 'Khu vực mát, ít khách vào đầu giờ chiều.', meta: '1,5 giờ · đã bao gồm', lat: 15.9971, lng: 107.9978, leg: 'Cáp treo + ô tô · 29,1 km · 1 giờ' },
      { id: 'd3e', time: '18:30', kind: 'Ăn uống', name: 'Lẩu nấm & cơm niêu, Hải Châu', note: 'Bữa tối nhẹ sau ngày dài leo núi.', meta: '1,5 giờ · 480k ₫', lat: 16.0662, lng: 108.2172, leg: null }
    ]},
    { n: 4, label: 'N4', title: 'Ngày 4 · Hội An', sub: '15/09 · 46,8 km · phố cổ lên đèn', items: [
      { id: 'd4a', time: '08:30', kind: 'Tham quan', name: 'Ngũ Hành Sơn', note: 'Đi thang máy lên, xuống bằng bậc đá phía động Huyền Không.', meta: '2 giờ · vé 40k ₫/người', lat: 16.0035, lng: 108.2632, leg: 'Ô tô · 15,2 km · 24 phút' },
      { id: 'd4b', time: '11:00', kind: 'Tham quan', name: 'Rừng dừa Bảy Mẫu, Cẩm Thanh', note: 'Thuyền thúng 30 phút — chọn suất trưa ít khách đoàn.', meta: '1,5 giờ · 350k ₫', lat: 15.8843, lng: 108.3676, leg: 'Ô tô · 5,1 km · 13 phút' },
      { id: 'd4c', time: '13:00', kind: 'Ăn uống', name: 'Cao lầu & bánh mì phố cổ', note: 'Ăn trưa muộn rồi nghỉ trong quán cà phê ven sông.', meta: '1,5 giờ · 240k ₫', lat: 15.8785, lng: 108.3280, leg: 'Đi bộ · 0,4 km · 6 phút' },
      { id: 'd4d', time: '16:00', kind: 'Tham quan', name: 'Phố cổ Hội An & Chùa Cầu', note: 'Vé tham quan 5 điểm; đèn lồng bật khoảng 18h.', meta: '3 giờ · vé 120k ₫/người', lat: 15.8770, lng: 108.3268, leg: 'Ô tô · 26,1 km · 45 phút' },
      { id: 'd4e', time: '21:00', kind: 'Di chuyển', name: 'Về sân bay Đà Nẵng', note: 'Chuyến bay 23:20 — có mặt trước 22:20.', meta: '45 phút · 420k ₫', lat: 16.0439, lng: 108.1994, leg: null }
    ]}
  ],

  dests: ['Đà Nẵng – Hội An', 'Hà Nội – Ninh Bình', 'Đà Lạt', 'Phú Quốc', 'Huế', 'Nha Trang', 'Hà Giang', 'Quy Nhơn'],
  interests: ['Ẩm thực đường phố', 'Biển & bãi tắm', 'Văn hoá – di sản', 'Chụp ảnh', 'Cà phê chill', 'Trekking nhẹ', 'Mua sắm', 'Đời sống về đêm'],
  genLabels: ['Phân tích sở thích & ngân sách', 'Chọn khách sạn phù hợp', 'Ghép 12 điểm đến vào 4 ngày', 'Tối ưu lộ trình & thời gian di chuyển']
};
