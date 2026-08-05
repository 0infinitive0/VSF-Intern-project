// Mock "AI understanding" — pure text-analysis functions standing in for
// a real NLP/LLM call. This is the intended swap point once a real AI
// backend exists (see README/Current Project Status): a real
// implementation would replace detectLang/detectChange's regex heuristics
// with an actual model call but can keep the same signatures, so Root
// Logic and the chat UI would not need to change.
window.VOTA = window.VOTA || {};
window.VOTA.Services = window.VOTA.Services || {};

window.VOTA.Services.chat = {
  // Guess vi/en from free-typed text; falls back to the conversation's
  // current language when the text itself is not decisive.
  detectLang(txt, fallbackLang) {
    if (/[ăâêôơưđàáảãạằắẳẵặèéẻẽẹìíỉĩịòóỏõọồốổỗộùúủũụỳýỷỹỵ]/i.test(txt)) return 'vi';
    if (/\b(the|and|for|with|days?|nights?|people|hotel|budget|want|please|trip)\b/i.test(txt)) return 'en';
    return fallbackLang;
  },

  // Scan a free-typed chat message for which trip fields it seems to touch,
  // e.g. "đổi khách sạn khác" -> [{ f: 'Khách sạn', scope: 'itinerary' }].
  // Drives the "your request changed" pending-update prompt.
  detectChange(t) {
    const l = t.toLowerCase();
    const out = [];
    if (/ngân sách|budget|tiền|triệu|rẻ|tiết kiệm/.test(l)) out.push({ f: 'Ngân sách', scope: 'hotels' });
    if (/khách sạn|hotel|resort|homestay/.test(l)) out.push({ f: 'Khách sạn', scope: 'itinerary' });
    if (/điểm đến|đổi.*(huế|đà lạt|nha trang|phú quốc)|đi (huế|đà lạt|nha trang|phú quốc)/.test(l)) out.push({ f: 'Điểm đến', scope: 'both' });
    if (/thêm.*ngày|bớt.*ngày|ngày đi|ngày về|dời|lùi/.test(l)) out.push({ f: 'Thời gian', scope: 'itinerary' });
    if (/thêm người|\d+ người|số người|gia đình|trẻ/.test(l)) out.push({ f: 'Số người', scope: 'both' });
    if (/sở thích|ẩm thực|biển|trekking|chụp ảnh|cà phê|mua sắm|di sản|di chuyển/.test(l)) out.push({ f: 'Sở thích', scope: 'places' });
    return out;
  },

  // Which parts of the trip a given change "scope" affects — shown as the
  // bullet list under "Sẽ ảnh hưởng" in the pending-update card. Returned
  // labels are VI keys; the caller translates via tx()/EN content map.
  affectedOf(scope) {
    if (scope === 'hotels') return ['Đề xuất khách sạn', 'Chi phí lưu trú'];
    if (scope === 'both') return ['Đề xuất khách sạn', 'Lịch trình 4 ngày', 'Lộ trình trên bản đồ'];
    if (scope === 'places') return ['Các điểm tham quan gợi ý'];
    return ['Lịch trình 4 ngày', 'Lộ trình trên bản đồ'];
  },
};
