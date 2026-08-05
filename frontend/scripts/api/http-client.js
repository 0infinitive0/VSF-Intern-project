// Shared HTTP client — the one place a real network call to *our* backend
// would go through (as opposed to the third-party map/tile calls, which
// stay in map.service.js). Nothing calls this yet: there is no real backend
// (see "Current Project Status"), so every scripts/services/*.js function
// still returns mock data directly. This exists so that swapping a service
// from mock to real is "call http.get(...) instead of returning the mock
// array", not "invent an HTTP layer from scratch".
window.VOTA = window.VOTA || {};
window.VOTA.Api = window.VOTA.Api || {};

(function () {
  const DEFAULT_TIMEOUT_MS = 10000;
  let authToken = null;

  // Call once a real login flow exists; every request below will then carry
  // `Authorization: Bearer <token>`. Unused today — no auth UI in the app.
  function setAuthToken(token) {
    authToken = token || null;
  }

  function authHeader() {
    return authToken ? { Authorization: 'Bearer ' + authToken } : {};
  }

  async function request(method, path, body, opts) {
    const options = opts || {};
    const base = (window.VOTA.Env && window.VOTA.Env.API_BASE_URL) || '';
    const url = /^https?:\/\//.test(path) ? path : base + path;

    const controller = new AbortController();
    const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    let res;
    try {
      res = await fetch(url, {
        method,
        headers: Object.assign(
          { 'Content-Type': 'application/json' },
          authHeader(),
          options.headers
        ),
        body: body != null ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      throw { status: 0, message: err.name === 'AbortError' ? 'Request timed out' : String(err.message || err) };
    } finally {
      clearTimeout(timer);
    }

    let data = null;
    try { data = await res.json(); } catch (e) { /* empty/non-JSON body is fine */ }

    if (!res.ok) {
      throw { status: res.status, message: (data && data.message) || res.statusText, data };
    }
    return data;
  }

  window.VOTA.Api.http = {
    setAuthToken,
    get: (path, opts) => request('GET', path, null, opts),
    post: (path, body, opts) => request('POST', path, body, opts),
    put: (path, body, opts) => request('PUT', path, body, opts),
    del: (path, opts) => request('DELETE', path, null, opts),
  };
})();
