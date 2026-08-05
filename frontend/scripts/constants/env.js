// Single non-hard-coded place for environment-ish config (API base URL,
// version, ...). Real `.env` / Vite `import.meta.env` injection doesn't
// apply here — these dc-script files are plain global scripts loaded via
// <script src> with no bundler pass over them (Vite only serves files for
// local preview, see README "Running it locally"). If this project ever
// adopts a real build step, this is the file that becomes
// `import.meta.env.VITE_API_URL` etc. — everything downstream (http-client.js)
// already reads through `window.VOTA.Env`, not a literal string, so that
// swap wouldn't touch any other file.
window.VOTA = window.VOTA || {};

window.VOTA.Env = {
  API_BASE_URL: 'http://localhost:5000/api',
};
