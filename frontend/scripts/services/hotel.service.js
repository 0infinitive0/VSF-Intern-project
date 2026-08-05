// Hotel data access — the only place Root Logic reads hotel data from.
// Synchronous today (reads window.VOTA.MockData; see README "Current
// Project Status" for why this stays mock-only for now). When a real
// backend exists, each function's body is the only thing that changes,
// e.g. getHotels() becomes `return window.VOTA.Api.http.get('/hotels')`
// (and Root Logic's constructor read moves to an async load — see
// BACKEND_INTEGRATION.md for that one flagged exception).
window.VOTA = window.VOTA || {};
window.VOTA.Services = window.VOTA.Services || {};

window.VOTA.Services.hotel = {
  // Future: GET /api/hotels (or POST /api/hotels/search with filters).
  getHotels() {
    return window.VOTA.MockData.hotels;
  },

  // The "AI đang tìm khách sạn phù hợp..." progress-step copy shown while
  // the hotel search animation runs. Future: could ship as part of the
  // search response, or stay static UI copy — left as a service function
  // either way so Root Logic doesn't care which.
  getSearchLabels() {
    return window.VOTA.MockData.searchLabels;
  },
};
