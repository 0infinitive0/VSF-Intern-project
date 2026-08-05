// Shared Leaflet bootstrap — the one piece of the two map integrations
// (hotels-screen map and trip-workspace map, in Root Logic's ensureHotelMap()/
// ensureMap()) that was byte-for-byte duplicated: create the map, add the
// OSM tile layer, add the zoom control. Everything past this point (markers,
// routes, hover-sync back into Root's own state) stays in Root — see
// README "Map duplication" note for why the rest wasn't unified further.
window.VOTA = window.VOTA || {};
window.VOTA.Services = window.VOTA.Services || {};

window.VOTA.Services.map = {
  createBaseMap(el, center, zoom, opts) {
    const L = window.L;
    const map = L.map(el, Object.assign({ zoomControl: false }, opts)).setView(center, zoom);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors',
    }).addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    return map;
  },

  // Real road geometry for one itinerary leg, via OSRM's public routing
  // API — a third-party map service, not our own backend, so it stays a
  // direct fetch() here rather than going through http-client.js (which is
  // reserved for our own /api/* backend). This is the one network call in
  // the app that isn't mocked; it's still routed through a service, not
  // called from Root, so the "no fetch() in a component" rule holds.
  // Resolves to a [lat,lng][] path, or null if the request fails (caller
  // falls back to a drawn curve).
  fetchRouteGeometry(a, b, mode) {
    const prof = mode === 'foot' ? 'foot' : 'driving';
    const url = 'https://router.project-osrm.org/route/v1/' + prof + '/' + a[1] + ',' + a[0] + ';' + b[1] + ',' + b[0] + '?overview=full&geometries=geojson';
    return fetch(url).then(r => r.json()).then(j => {
      const c = j && j.routes && j.routes[0] && j.routes[0].geometry && j.routes[0].geometry.coordinates;
      return c && c.length > 1 ? c.map(p => [p[1], p[0]]) : null;
    }).catch(() => null);
  },
};
