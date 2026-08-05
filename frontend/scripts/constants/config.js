// Static app config — plain global script (see README: dc-runtime logic
// scripts run via `new Function`, so they can only reach this through
// `window.VOTA.*`, not `import`). Loaded from the real document <head>,
// before the runtime boots, so Root Logic can read it synchronously in its
// constructor.
window.VOTA = window.VOTA || {};

window.VOTA.Config = {
  // Per-day route color (index 0 = Day 1, etc.) — map polylines, day
  // badges/timeline dots, and the itinerary legend all key off this.
  DAY_COLORS: ["#3A73DE", "#2A9187", "#C8802F", "#8E6BC4"],
  // Extended palette for per-leg (hop-to-hop) coloring, cycles independently
  // of DAY_COLORS so consecutive legs on the same day read distinctly.
  LEG_COLORS: ["#3A73DE", "#2A9187", "#C8802F", "#8E6BC4", "#C05E70", "#5E8F49"],
  // Dual-thumb budget slider bounds (VND, whole trip).
  BUDGET: { MIN: 500000, MAX: 50000000, STEP: 500000 },
};
