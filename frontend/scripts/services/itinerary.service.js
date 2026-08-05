// Itinerary data access — the generated day-by-day plan and its supporting
// copy. Synchronous today, same rationale as hotel.service.js.
window.VOTA = window.VOTA || {};
window.VOTA.Services = window.VOTA.Services || {};

window.VOTA.Services.itinerary = {
  // Future: GET /api/itinerary (or the response of POST /api/itinerary/generate).
  getDays() {
    return window.VOTA.MockData.days;
  },

  // Per-day extra start/end transit info (airport pickup, Bà Nà cable car,
  // ...) keyed by day number. Future: part of the same itinerary response.
  getDayHooks() {
    return window.VOTA.MockData.dayHooks;
  },

  // "Đang tối ưu tuyến đường..." progress-step copy shown while the
  // itinerary-optimization animation runs.
  getOptimizationLabels() {
    return window.VOTA.MockData.optLabels;
  },

  // "Đang xây dựng lịch trình theo từng ngày..." progress-step copy shown
  // during the initial itinerary-generation animation.
  getGenLabels() {
    return window.VOTA.MockData.genLabels;
  },
};
