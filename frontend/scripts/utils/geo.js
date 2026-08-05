// Map/geometry helpers — pure functions, no `this`, no DOM, no Leaflet
// dependency (Leaflet only consumes their plain-number/array results).
window.VOTA = window.VOTA || {};
window.VOTA.Utils = window.VOTA.Utils || {};

window.VOTA.Utils.geo = {
  // Small deterministic string hash — used to vary review-card presentation
  // per item without needing stored random seeds.
  hash(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 9973;
    return h;
  },
  // Great-circle distance in km between {lat,lng} points (haversine).
  kmFrom(a, b) {
    const R = 6371, dLat = (b.lat - a.lat) * Math.PI / 180, dLng = (b.lng - a.lng) * Math.PI / 180;
    const la1 = a.lat * Math.PI / 180, la2 = b.lat * Math.PI / 180;
    const x = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
  },
  // Sampled points along a quadratic bezier curve bowed between [x,y] points
  // `a` and `b` — gives map routes their gentle arc instead of a straight line.
  curve(a, b) {
    const pts = [];
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const cx = mx - dy * 0.12, cy = my + dx * 0.12;
    for (let t = 0; t <= 1.0001; t += 0.05) {
      const u = 1 - t;
      pts.push([u * u * a[0] + 2 * u * t * cx + t * t * b[0], u * u * a[1] + 2 * u * t * cy + t * t * b[1]]);
    }
    return pts;
  },
};
