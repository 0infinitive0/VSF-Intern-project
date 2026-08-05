// Destination data access — trip-destination options, interest tags, and
// landmark reference points. Synchronous today, same rationale as
// hotel.service.js.
window.VOTA = window.VOTA || {};
window.VOTA.Services = window.VOTA.Services || {};

window.VOTA.Services.destination = {
  // Future: GET /api/destinations — the destination-picker chip list.
  getDestinationOptions() {
    return window.VOTA.MockData.dests;
  },

  // Future: GET /api/destinations/{id}/interests (or a static reference
  // endpoint) — the interest-picker chip list.
  getInterestOptions() {
    return window.VOTA.MockData.interests;
  },

  // Points of interest used both for hotel-to-landmark distance display
  // and for map markers. Future: GET /api/destinations/{id}/landmarks.
  getLandmarks() {
    return window.VOTA.MockData.landmarks;
  },
};
