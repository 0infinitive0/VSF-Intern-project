// Dev-only static file server — zero dependencies (Node's built-in http/fs only).
//
// Why this exists: the app is a set of `.dc.html` "Design Component" files loaded by
// support.js via `fetch()` (dc-import / x-import). Browsers block `fetch()` against
// `file://` URLs, so the project must be served over http:// during development.
// This is NOT a production server — it is only meant for local preview while building.
//
// Usage: node server.js   (or `npm run dev`)
// Then open the URL it prints.

const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const PORT = Number(process.env.PORT) || 5173;
const DEFAULT_FILE = "V-OTA Planner.dc.html";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".mjs": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".md": "text/markdown; charset=utf-8",
};
// Every *.dc.html file must be served as html so the runtime's fetch() gets raw markup.
function mimeFor(filePath) {
  if (filePath.toLowerCase().endsWith(".dc.html")) return MIME[".html"];
  return MIME[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}

const server = http.createServer((req, res) => {
  let reqPath = decodeURIComponent(req.url.split("?")[0]);
  if (reqPath === "/") reqPath = "/" + DEFAULT_FILE;

  // Prevent path traversal outside the project root.
  const filePath = path.normalize(path.join(ROOT, reqPath));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Not found: " + reqPath);
      return;
    }
    res.writeHead(200, { "Content-Type": mimeFor(filePath) });
    res.end(data);
  });
});

server.listen(PORT, () => {
  const url = `http://localhost:${PORT}/${encodeURIComponent(DEFAULT_FILE)}`;
  console.log(`V-OTA dev server running.`);
  console.log(`Open: ${url}`);
});
