// The one small "store" in this project: theme + language persistence.
//
// Why only these two: dc-import's props flow one-way (parent -> child) with
// callbacks going back up, which already covers every other piece of state
// here (chat/hotel/itinerary selections all live in Root and get passed
// down — see README). Theme and language are different: they're read
// *before* Root even mounts (the constructor needs the saved value for
// initial state) and written to by a DOM side effect
// (document.body.setAttribute), so they're genuinely state used outside the
// component tree, not just app state. That's the actual justification for
// singling these two out rather than building a general Redux-style store
// for everything (see the plan's rationale for why a bigger store was
// judged over-engineering for this app).
window.VOTA = window.VOTA || {};
window.VOTA.Store = window.VOTA.Store || {};

window.VOTA.Store.app = {
  getTheme() {
    try { return localStorage.getItem('vota-theme') || 'light'; } catch (e) { return 'light'; }
  },
  setTheme(t) {
    try { localStorage.setItem('vota-theme', t); } catch (e) {}
  },
  getLang() {
    try { return localStorage.getItem('vota-lang') || 'vi'; } catch (e) { return 'vi'; }
  },
  setLang(l) {
    try { localStorage.setItem('vota-lang', l); } catch (e) {}
  },
};
